"""Ripple 지정 양식 시트 → 지도(GraphSnapshot)와 품질 리포트(docs/input.md(엑셀 양식)). 공개 진입점은 build().

1. 표 만들기: 확정 매핑(ConfirmedMapping — 파일 시트 → 양식 시트, 머리글 행, 열 → 항목·원본 단위)대로 표를 만든다.
   매핑을 주지 않으면 지정 양식 그대로인 파일로 보고 시트 이름·첫 행 머리글이 양식과 같은 것만 읽는다(mapping.py).
   흔한 변형은 열 확인 단계(판단 계층의 매핑 제안 → 사용자 확인)에서 확정 매핑을 만든다.
2. 행 읽기: 열 종류대로 값을 읽고(단위 배율, 날짜 표기, 코드 표기 — normalize.py), 상식 범위 밖 값(단위 착오)·
   빈 필수 값·형식·코드 오류를 시트·행·열과 함께 문제로 모은다. 메모 행은 읽지 않고 경고로 남긴다.
3. 엔터티 만들기: 계약 검증 실패는 그 행의 문제로, 다른 시트 참조·ID 중복·공정 순환을 확인한다.
4. 오류가 하나도 없을 때만 지도(origin=excel_import, data_mode=real)를 만든다. 값마다 원본 시트·행(SourceRef)을 단다.

모듈: 표 만들기 sheet_tables.py · 행 읽기 rows.py · 셀 값 해석 values.py · 시트 사이 정합 integrity.py ·
엔터티 조립은 여기.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from datetime import date

from pydantic import BaseModel, ValidationError

from ripple.contracts.domain import (
    DIRECT_PERFORMER,
    Activity,
    ActivityConfirmation,
    Block,
    Connection,
    Crew,
    DataMode,
    Drawing,
    GraphSnapshot,
    LDTerms,
    MaterialSpec,
    Part,
    PipeSystem,
    POLine,
    Precedence,
    PurchaseOrder,
    Ship,
    StatusObservation,
    StockLot,
    Supplier,
    Zone,
    ZoneBoundary,
    confirmation_problem,
)
from ripple.contracts.identity import snapshot_id
from ripple.contracts.ingest import ConfirmedMapping, ImportSummary, IssueCode, IssueSeverity

from .fields import FieldDictionary, default_fields
from .integrity import check_cycles, check_observations, check_references
from .mapping import exact_mapping
from .normalize import code_key
from .rows import read
from .sheet_tables import tables
from .table_types import Issues, Record
from .template import DIRECT_LABEL, ENTERED_COLUMNS, SHEET_BY_KEY, SHEETS, TEMPLATE_VERSION, code_value
from .workbook import RawSheet

KNOWN_CHECKS: Mapping[str, str] = {
    "운송 방식은 외자재 규격에만": "transport",
    "연결의 두 끝이 같은 부재": "b",
    "실제 완료일은 실제 착수일 이후": "actual_finish",
    "블록 공정에는 블록 ID": "block_id",
    "작업반 ID로": "crew_id",
}
"""행 전체를 보는 계약 검증(ripple/contracts/domain.py) 문구의 앞부분 → 짚을 양식 열 키(문제의 열)."""


def _model[M: BaseModel](model: type[M], data: Mapping[str, object], record: Record, issues: Issues) -> M | None:
    try:
        return model.model_validate(dict(data))
    except ValidationError as error:
        first = error.errors()[0]
        message = plain_message(str(first["msg"]))
        loc = [str(p) for p in first["loc"]]
        key = loc[0] if loc else next((k for text, k in KNOWN_CHECKS.items() if message.startswith(text)), None)
        sheet = record.table.sheet
        column = next((c for c in sheet.columns if c.key == key), None)
        where = "" if column is not None or not loc else f"({'.'.join(loc)})"
        issues.add(
            IssueSeverity.ERROR,
            IssueCode.INVALID_ROW,
            f"이 행의 값 오류{where} · {message}",
            record.table.raw.name,
            record.row,
            column.header if column else None,
            record.table.file_column(column.key) if column else None,
        )
        return None


def plain_message(text: str) -> str:
    """pydantic 오류 문구의 접두('Value error, '·'Assertion failed, ')를 뗀 사람이 읽는 문장(끝 마침표 없이)."""
    for prefix in ("Value error, ", "Assertion failed, "):
        text = text.removeprefix(prefix)
    return text.rstrip(".")


def _pick(record: Record, *keys: str) -> dict[str, object]:
    return {k: record.values[k] for k in keys if record.values.get(k) is not None}


def build(
    raw: Mapping[str, RawSheet],
    file: str,
    mapping: ConfirmedMapping | None = None,
    fields: FieldDictionary | None = None,
) -> tuple[GraphSnapshot | None, ImportSummary]:
    """엑셀(읽은 시트) + 확정 매핑 → (지도, 요약). 오류가 하나라도 있으면 지도는 None.

    mapping이 없으면 지정 양식 그대로인 파일로 본다(mapping.exact_mapping).
    """
    issues = Issues()
    found = tables(raw, mapping or exact_mapping(raw), fields or default_fields(), issues)
    records = {key: read(table, issues) for key, table in found.items()}
    snapshot = None
    if not issues.has_errors:
        snapshot = _assemble(records, file, issues)
    summary = ImportSummary(
        template_version=TEMPLATE_VERSION,
        file=file,
        snapshot_id=snapshot.snapshot_id if snapshot and not issues.has_errors else None,
        counts={key: len(rows) for key, rows in records.items()},
        missing_sheets=tuple(s.name for s in SHEETS if s.key not in found and not s.required and not s.quiet),
        issues=tuple(issues.items),
    )
    return (snapshot if summary.ok else None), summary


def _all[M: BaseModel](
    model: type[M], records: Iterable[Record], data: Callable[[Record], Mapping[str, object]], issues: Issues
) -> list[M]:
    """행마다 엔터티를 만들고, 계약 검증에 실패한 행은 문제로 남기고 뺀다."""
    return [m for r in records if (m := _model(model, data(r), r, issues)) is not None]


def _assemble(records: Mapping[str, list[Record]], file: str, issues: Issues) -> GraphSnapshot | None:
    rows: defaultdict[str, list[Record]] = defaultdict(list, records)

    def sourced(record: Record) -> Mapping[str, object]:
        return {**_present(record), "source": record.source(file)}

    ships = [ship for r in rows["ships"] if (ship := _ship(r, issues)) is not None]
    zones = _all(Zone, rows["zones"], _present, issues)
    boundaries = _all(ZoneBoundary, rows["boundaries"], _present, issues)
    blocks = _all(Block, rows["blocks"], sourced, issues)
    specs = _all(MaterialSpec, rows["specs"], lambda r: _spec(r, issues), issues)
    parts = _all(Part, rows["parts"], sourced, issues)
    suppliers = _all(Supplier, rows["suppliers"], _present, issues)
    orders = _orders(rows["observations"], rows["purchase_orders"], file, issues)
    lines = _all(POLine, rows["po_lines"], sourced, issues)
    predecessors = _predecessors(rows["precedences"], issues)
    activities = _activities(rows["activity_checks"], rows["activities"], predecessors, issues)
    connections = _all(Connection, rows["connections"], _present, issues)
    stock = _all(StockLot, rows["stock"], _present, issues)
    drawings = _all(Drawing, rows["drawings"], _present, issues)
    systems = _all(PipeSystem, rows["pipe_systems"], _present, issues)
    crews = _all(Crew, rows["crews"], _crew, issues)
    if issues.has_errors:
        return None
    check_references(rows, issues)
    check_cycles(rows["activities"], predecessors, issues)
    if issues.has_errors:
        return None
    try:
        draft = GraphSnapshot(
            snapshot_id="",
            origin="excel_import",
            data_mode=DataMode.REAL,
            ships=tuple(ships),
            zones=tuple(zones),
            boundaries=tuple(boundaries),
            blocks=tuple(blocks),
            specs=tuple(specs),
            parts=tuple(parts),
            connections=tuple(connections),
            suppliers=tuple(suppliers),
            purchase_orders=tuple(orders),
            po_lines=tuple(lines),
            stock=tuple(stock),
            activities=tuple(activities),
            drawings=tuple(drawings),
            pipe_systems=tuple(systems),
            crews=tuple(crews),
        )
    except ValidationError as error:
        message = plain_message(str(error.errors()[0]["msg"]))
        issues.add(IssueSeverity.ERROR, IssueCode.INVALID_ROW, f"지도 만들기 실패 · {message}")
        return None
    return draft.model_copy(update={"snapshot_id": snapshot_id(draft)})


def _spec(record: Record, issues: Issues) -> dict[str, object]:
    """규격 행(1.33.0 외자재): 막지 않고 읽되 읽는 방식·가정을 그 행의 경고로 남긴다.

    - 원산지가 비고 운송 방식만 있으면 외자재로 읽는다(운송 방식이 있으면 들여오는 자재라는 뜻).
    - 외자재인데 운송 방식이 비면 그대로 두고 엔진이 선박(더 긴 쪽)으로 가정한다.
    국산인데 운송 방식이 적힌 행은 계약 검증이 오류로 짚는다.
    """
    values = _present(record)
    name = values.get("spec_id")
    if values.get("transport") is not None and values.get("origin") is None:
        values["origin"] = "import"
        message = f"규격 {name}: 원산지 없음 → 운송 방식이 있어 외자재로 간주 · 국산이면 운송 방식 칸 비움"
        _warn(record, issues, message, "원산지 구분")
    elif values.get("origin") == "import" and values.get("transport") is None:
        message = (
            f"규격 {name}: 외자재인데 운송 방식이 비어 있어 선박(더 긴 쪽)으로 가정해 계산 · "
            "항공이면 운송 방식 칸에 기입"
        )
        _warn(record, issues, message, "운송 방식")
    return values


def _warn(record: Record, issues: Issues, message: str, column: str) -> None:
    issues.add(IssueSeverity.WARNING, IssueCode.MISSING_VALUE, message, record.table.raw.name, record.row, column)


def _orders(
    observation_rows: Iterable[Record], order_rows: list[Record], file: str, issues: Issues
) -> list[PurchaseOrder]:
    """발주와 그 관측. 관측끼리·확인된 진입일과 모순인 발주는 관측 없이 만든다(문제는 관측 행에 남김)."""
    observed: dict[str, list[tuple[Record, StatusObservation]]] = defaultdict(list)
    for r in observation_rows:
        obs = _model(StatusObservation, {**_pick(r, "status", "observed_on"), "source": r.source(file)}, r, issues)
        if obs and r.values.get("po_id"):
            observed[str(r.values["po_id"])].append((r, obs))
    by_id = {str(r.values.get("po_id")): r for r in order_rows}
    troubled = check_observations(observed, by_id, issues)
    clean = {po: [obs for _, obs in items] for po, items in observed.items() if po not in troubled}
    return [o for r in order_rows if (o := _order(r, file, clean, issues)) is not None]


def _predecessors(precedence_rows: Iterable[Record], issues: Issues) -> dict[str, list[Precedence]]:
    """'선후행' 행 → 공정별 선행 공정."""
    predecessors: dict[str, list[Precedence]] = defaultdict(list)
    for r in precedence_rows:
        link = _model(Precedence, {"activity_id": r.values.get("predecessor_id"), **_pick(r, "lag_days")}, r, issues)
        if link and r.values.get("activity_id"):
            predecessors[str(r.values["activity_id"])].append(link)
    return predecessors


def _activities(
    check_rows: Iterable[Record],
    activity_rows: list[Record],
    predecessors: Mapping[str, list[Precedence]],
    issues: Issues,
) -> list[Activity]:
    """공정과 그 선행 공정·현장 확인."""
    checks = _checks(check_rows, activity_rows, issues)

    def activity(record: Record) -> Mapping[str, object]:
        own = str(record.values.get("activity_id"))
        performer = record.values.get("performer")
        return {
            **_present(record),
            "block_id": record.values.get("block_id"),
            "predecessors": predecessors.get(own, []),
            "confirmations": checks.get(own, []),
            **({"performer": _performer(str(performer))} if performer is not None else {}),
        }

    return _all(Activity, activity_rows, activity, issues)


def _performer(raw: str) -> str:
    """수행 주체 칸: '직영'(공백·대소문자 무시)이나 계약 값 direct는 직영, 그 밖은 작업반ID 그대로."""
    return DIRECT_PERFORMER if code_key(raw) in (code_key(DIRECT_LABEL), code_key(DIRECT_PERFORMER)) else raw


def _crew(record: Record) -> Mapping[str, object]:
    """작업반 행: 담당 공정은 공정 종류 라벨(옛 라벨 포함)이나 계약 값으로 읽는다
    (모르는 말은 그대로 두어 계약 검증이 짚음)."""
    kinds = SHEET_BY_KEY["activities"].column("kind")
    processes = record.values.get("processes") or ()
    items = processes if isinstance(processes, tuple) else (processes,)
    return {**_present(record), "processes": tuple(code_value(kinds, str(p)) or str(p) for p in items)}


def _checks(
    check_rows: Iterable[Record], activity_rows: Iterable[Record], issues: Issues
) -> dict[str, list[ActivityConfirmation]]:
    """'공정 확인' 행 → 공정별 현장 확인. 실제 착수·완료일과 어긋나면 그 확인 행의 오류로 짚는다(공정 행이 아니라)."""
    actuals = {
        str(r.values.get("activity_id")): (r.values.get("actual_start"), r.values.get("actual_finish"))
        for r in activity_rows
    }
    found: dict[str, list[ActivityConfirmation]] = defaultdict(list)
    for r in check_rows:
        check = _model(ActivityConfirmation, _pick(r, "state", "confirmed_on"), r, issues)
        own = str(r.values.get("activity_id") or "")
        if check is None or not own:
            continue
        started, finished = actuals.get(own, (None, None))
        problem = confirmation_problem(
            check,
            started if isinstance(started, date) else None,
            finished if isinstance(finished, date) else None,
        )
        if problem:
            issues.error(IssueCode.INVALID_ROW, f"공정 {own}: {problem}.", r, "확인 상태")
            continue
        found[own].append(check)
    return found


def _present(record: Record) -> dict[str, object]:
    """값이 있는 열만(빈칸은 계약 기본값을 쓰게)."""
    return {k: v for k, v in record.values.items() if v is not None}


def _ship(record: Record, issues: Issues) -> Ship | None:
    v = record.values
    ld_keys = ("ld_grace_days", "ld_rate_per_day_of_price", "ld_max_days")
    given = [v.get(k) is not None for k in ld_keys]
    terms = None
    if any(given):
        if not all(given):
            issues.error(IssueCode.INVALID_ROW, "지체상금 세 값(유예일·일률·최대일) 함께 기입 필요", record)
            return None
        terms = _model(
            LDTerms,
            {
                "grace_days": v["ld_grace_days"],
                "rate_per_day_of_price": v["ld_rate_per_day_of_price"],
                "max_days": v["ld_max_days"],
            },
            record,
            issues,
        )
        if terms is None:
            return None
    data = _pick(record, "ship_id", "ship_type", "dwt", "contract_price_krw", "delivery_date")
    return _model(Ship, {**data, "ld_terms": terms}, record, issues)


def _order(
    record: Record, file: str, observed: Mapping[str, list[StatusObservation]], issues: Issues
) -> PurchaseOrder | None:
    v = record.values
    entered = {status: v[key] for status, key in ENTERED_COLUMNS.items() if v.get(key) is not None}
    data = _pick(
        record,
        "po_id",
        "ship_id",
        "supplier_id",
        "planned_order_date",
        "material_secured_days",
        "fabrication_start_days",
        "lead_time_days",
    )
    po_id = str(v.get("po_id") or "")
    return _model(
        PurchaseOrder,
        {**data, "entered_on": entered, "observations": observed.get(po_id, []), "source": record.source(file)},
        record,
        issues,
    )
