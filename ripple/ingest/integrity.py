"""시트 사이 정합 검사: 다른 시트 참조(없는 ID)·ID 중복·발주 관측끼리의 모순·공정 선후 순환.

문제는 그 행(시트·행·열)의 오류로 남기고, 지도는 오류가 하나도 없을 때만 만든다(build.py).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import date

from ripple.contracts.domain import (
    DIRECT_PERFORMER,
    PO_STATUS_ORDER,
    Precedence,
    StatusObservation,
    drawing_key,
)
from ripple.contracts.ingest import IssueCode, IssueSeverity

from .normalize import code_key
from .table_types import Issues, Record
from .template import DIRECT_LABEL, ENTERED_COLUMNS


def check_observations(
    observed: Mapping[str, list[tuple[Record, StatusObservation]]], orders: Mapping[str, Record], issues: Issues
) -> set[str]:
    """발주 관측끼리·확인된 진입일과의 모순을 '발주 관측' 행에서 짚는다(발주 계약 검사와 같은 규칙).

    문제가 있는 발주는 관측 없이 만들어 같은 문제를 발주 행으로 다시 알리지 않는다.
    """
    rank = PO_STATUS_ORDER.index
    troubled: set[str] = set()
    for po_id, items in observed.items():
        if _check_same_day(po_id, items, issues):
            troubled.add(po_id)
        timeline = sorted(items, key=lambda item: (item[1].observed_on, rank(item[1].status)))
        highest: tuple[Record, StatusObservation] | None = None
        for record, obs in timeline:
            if highest and rank(obs.status) < rank(highest[1].status) and obs.observed_on != highest[1].observed_on:
                troubled.add(po_id)
                issues.error(
                    IssueCode.INVALID_ROW,
                    f"발주 {po_id}의 상태 역행({highest[1].observed_on} {highest[1].status.value} → "
                    f"{obs.observed_on} {obs.status.value}, {highest[0].row}행 다음)",
                    record,
                    "상태",
                )
            if highest is None or rank(obs.status) >= rank(highest[1].status):
                highest = (record, obs)
        order = orders.get(po_id)
        if order is None:
            continue
        for stage, key in ENTERED_COLUMNS.items():
            entered = order.values.get(key)
            if not isinstance(entered, date):
                continue
            header = order.table.sheet.column(key).header
            for record, obs in items:
                reached = rank(stage) <= rank(obs.status)
                if (reached and entered > obs.observed_on) or (not reached and entered <= obs.observed_on):
                    troubled.add(po_id)
                    issues.error(
                        IssueCode.INVALID_ROW,
                        f"관측({obs.observed_on} {obs.status.value})이 '{order.table.raw.name}' {order.row}행 "
                        f"'{header}'({entered})와 불일치",
                        record,
                        "관측일",
                    )
    return troubled


def _check_same_day(po_id: str, items: list[tuple[Record, StatusObservation]], issues: Issues) -> bool:
    by_day: dict[date, list[tuple[Record, StatusObservation]]] = defaultdict(list)
    for record, obs in items:
        by_day[obs.observed_on].append((record, obs))
    troubled = False
    for day, same_day in by_day.items():
        if len({obs.status for _, obs in same_day}) > 1:
            troubled = True
            rows_text = ", ".join(str(record.row) for record, _ in same_day)
            for record, _ in same_day:
                issues.error(
                    IssueCode.INVALID_ROW,
                    f"발주 {po_id}의 {day} 관측 상태 불일치({rows_text}행)",
                    record,
                    "상태",
                )
    return troubled


_ID_SHEETS = (
    ("ships", "ship_id"),
    ("zones", "zone_id"),
    ("blocks", "block_id"),
    ("specs", "spec_id"),
    ("parts", "part_id"),
    ("suppliers", "supplier_id"),
    ("purchase_orders", "po_id"),
    ("activities", "activity_id"),
    ("stock", "lot_id"),
    ("pipe_systems", "system"),
    ("crews", "crew_id"),
)
"""ID가 겹치면 안 되는 시트와 그 ID 열."""

_TARGETS: Mapping[str, tuple[str, str]] = {
    "ship_id": ("호선", "ships"),
    "zone_id": ("구역", "zones"),
    "block_id": ("블록", "blocks"),
    "spec_id": ("규격", "specs"),
    "supplier_id": ("협력사", "suppliers"),
    "fabricator_id": ("협력사", "suppliers"),
    "po_id": ("발주", "purchase_orders"),
    "activity_id": ("공정", "activities"),
    "predecessor_id": ("공정", "activities"),
    "exit_activity_id": ("공정", "activities"),
    "consumed_by_activity_id": ("공정", "activities"),
    "reserved_block_id": ("블록", "blocks"),
    "a": ("부재", "parts"),
    "b": ("부재", "parts"),
    "part_ids": ("부재", "parts"),
}
"""다른 시트의 ID를 가리키는 열 → (문구의 시트 이름, 그 시트 키)."""

_OWN: Mapping[str, frozenset[str]] = {
    "ships": frozenset({"ship_id"}),
    "zones": frozenset({"zone_id"}),
    "blocks": frozenset({"block_id"}),
    "specs": frozenset({"spec_id"}),
    "parts": frozenset({"part_id"}),
    "suppliers": frozenset({"supplier_id"}),
    "purchase_orders": frozenset({"po_id"}),
    "activities": frozenset({"activity_id"}),
    "stock": frozenset(),
    "pipe_systems": frozenset(),
    "crews": frozenset({"crew_id"}),
}
"""시트 자신의 ID 열(참조가 아니다)."""


def check_references(rows: Mapping[str, list[Record]], issues: Issues) -> None:
    """ID 중복과 다른 시트를 가리키는 ID가 있는지."""
    ids = {sheet_key: _unique(rows[sheet_key], (id_key,), issues) for sheet_key, id_key in _ID_SHEETS}
    _unique(rows["po_lines"], ("po_id", "line_no"), issues)
    drawings = _unique(rows["drawings"], ("drawing_no", "revision"), issues)
    _namespace(rows, issues)
    targets = {key: (name, ids[sheet_key]) for key, (name, sheet_key) in _TARGETS.items()}
    for sheet_key, records in rows.items():
        for record in records:
            _unknown_targets(record, _OWN.get(sheet_key, frozenset()), targets, issues)
    for record in rows["parts"]:
        key = drawing_key(str(record.values.get("drawing_no")), str(record.values.get("revision")))
        if key not in drawings:
            issues.error(IssueCode.UNKNOWN_REFERENCE, f"도면 '{key}'이 '도면' 시트에 없음", record, "도면번호")
        system = record.values.get("system")
        if system is not None and ids["pipe_systems"] and str(system) not in ids["pipe_systems"]:
            issues.add(
                IssueSeverity.WARNING,
                IssueCode.UNKNOWN_REFERENCE,
                f"배관 계통 '{system}'이 '배관 계통' 시트에 없음 · 키 그대로 표시",
                record.table.raw.name,
                record.row,
                "배관 계통",
            )
        others = record.values.get("secondary_drawing_ids")
        for other in others if isinstance(others, tuple) else ():
            if str(other) not in drawings:
                issues.error(
                    IssueCode.UNKNOWN_REFERENCE, f"도면 '{other}'이 '도면' 시트에 없음", record, "다른 분야 도면"
                )
    _performers(rows["activities"], ids["crews"], issues)
    _no_consumer(rows.get("po_lines", []), issues)


def _performers(activities: Iterable[Record], crews: set[str], issues: Issues) -> None:
    """공정의 수행 주체는 직영이거나 '작업반' 시트의 작업반ID(1.32.0)."""
    for record in activities:
        performer = record.values.get("performer")
        if performer is None or code_key(str(performer)) in (code_key(DIRECT_LABEL), code_key(DIRECT_PERFORMER)):
            continue
        if str(performer) not in crews:
            issues.error(
                IssueCode.UNKNOWN_REFERENCE,
                f"'수행 주체' 값 '{performer}'이 직영도 아니고 '작업반' 시트에도 없음",
                record,
                "수행 주체",
            )


def _unknown_targets(
    record: Record, own: frozenset[str], targets: Mapping[str, tuple[str, set[str]]], issues: Issues
) -> None:
    """행 하나에서 다른 시트에 없는 ID를 가리키는 칸(목록 칸은 항목마다)."""
    for key, value in record.values.items():
        if key in own or key not in targets or value is None:
            continue
        target_name, known = targets[key]
        for item in value if isinstance(value, tuple) else (value,):
            if str(item) not in known:
                header = record.table.sheet.column(key).header
                issues.error(
                    IssueCode.UNKNOWN_REFERENCE,
                    f"'{header}' 값 '{item}'이 '{target_name}' 시트에 없음",
                    record,
                    header,
                )


def _no_consumer(lines: list[Record], issues: Issues) -> None:
    """소비 공정ID는 선택 열이지만 비면 그 품목의 새 자재 일정 영향을 계산하지 못한다(docs/engine.md(비용·일정) 5절)."""
    empty = [record for record in lines if record.values.get("consumed_by_activity_id") is None]
    if not empty:
        return
    first = empty[0]
    header = first.table.sheet.column("consumed_by_activity_id").header
    issues.add(
        IssueSeverity.WARNING,
        IssueCode.MISSING_VALUE,
        f"'{header}'이 빈 발주 품목 {len(empty)}건(첫 행 {first.row}행) · 이 품목의 자재를 다시 받아야 하는 "
        "변경은 일정 영향 계산 불가 — '연결 확인 필요'로 표시",
        first.table.raw.name,
        first.row,
        header,
    )


def _namespace(rows: Mapping[str, list[Record]], issues: Issues) -> None:
    """그래프 색인은 호선·구역·블록·부재·발주·발주 품목·공정·도면·재고 ID를 한 공간에 둔다. 종류가 다른 항목의 ID가
    같으면 한쪽이 덮여 영향 탐색이 틀어지므로 오류로 짚는다(같은 시트 안의 중복은 _unique가 짚음)."""
    owner: dict[str, Record] = {}

    def claim(entity_id: str, record: Record, column: str) -> None:
        first = owner.setdefault(entity_id, record)
        if first is not record and first.table.sheet.key != record.table.sheet.key:
            issues.error(
                IssueCode.DUPLICATE_ID,
                f"'{entity_id}'가 '{first.table.raw.name}' {first.row}행의 ID와 중복(종류가 달라도 ID 중복 불가)",
                record,
                column,
            )

    for sheet_key, key in (
        ("ships", "ship_id"),
        ("zones", "zone_id"),
        ("blocks", "block_id"),
        ("parts", "part_id"),
        ("purchase_orders", "po_id"),
        ("activities", "activity_id"),
        ("stock", "lot_id"),
    ):
        for record in rows[sheet_key]:
            if record.values.get(key) is not None:
                claim(str(record.values[key]), record, record.table.sheet.column(key).header)
    for record in rows["po_lines"]:
        po_id, line_no = record.values.get("po_id"), record.values.get("line_no")
        if po_id is not None and line_no is not None:
            claim(f"{po_id}#{line_no}", record, "품목번호")
    for record in rows["drawings"]:
        number, revision = record.values.get("drawing_no"), record.values.get("revision")
        if number is not None and revision is not None:
            claim(drawing_key(str(number), str(revision)), record, "도면번호")


def _unique(records: Iterable[Record], keys: tuple[str, ...], issues: Issues) -> set[str]:
    seen: dict[str, int] = {}
    for record in records:
        parts = [record.values.get(k) for k in keys]
        if any(p is None for p in parts):
            continue
        key = drawing_key(str(parts[0]), str(parts[1])) if len(parts) == 2 else str(parts[0])
        if key in seen:
            issues.error(IssueCode.DUPLICATE_ID, f"'{key}' — {seen[key]}행과 ID 중복", record)
        else:
            seen[key] = record.row
    return set(seen)


def check_cycles(activities: list[Record], predecessors: Mapping[str, list[Precedence]], issues: Issues) -> None:
    """선후행에 순환이 있으면 기준 일정을 계산할 수 없다(순환에 든 공정을 짚는다)."""
    graph = {
        str(r.values["activity_id"]): [p.activity_id for p in predecessors.get(str(r.values["activity_id"]), [])]
        for r in activities
    }
    indegree: Counter[str] = Counter()
    for node, before in graph.items():
        for b in before:
            indegree[node] += 1 if b in graph else 0
    ready = [n for n in graph if indegree[n] == 0]
    after: dict[str, list[str]] = defaultdict(list)
    for node, before in graph.items():
        for b in before:
            after[b].append(node)
    done = 0
    while ready:
        node = ready.pop()
        done += 1
        for nxt in after[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    if done < len(graph):
        stuck = sorted(n for n in graph if indegree[n] > 0)[:5]
        issues.add(
            IssueSeverity.ERROR,
            IssueCode.INVALID_ROW,
            f"선후행 순환 · 기준 일정 계산 불가(예: {', '.join(stuck)})",
            "선후행",
        )
