"""분석 결과 엑셀의 표 시트: 영향 목록 · 비용 근거 · 가정값 · 확정 시점 곡선 · 대안 비교(out_analysis.py가 조립).

줄 순서는 화면과 같게(비용은 금액 큰 순, 곡선은 날짜 순, 대안은 결과 순서 = 요청안 → 충족 순위 → 나머지),
영향은 심각도 높은 순. 값은 결과 필드 그대로다.
"""

from __future__ import annotations

from collections.abc import Iterable

from openpyxl.worksheet.worksheet import Worksheet

from ripple.contracts.result import AnalysisResult, CostLine, Impact, LineOutlook

from .out_labels import (
    COST_ITEM,
    COST_KIND,
    DETERMINACY,
    ELIGIBILITY,
    ENTITY,
    IMPACT,
    INPUT,
    ORIGIN,
    PARAM_STATUS,
    RELATION,
    SEVERITY,
    SEVERITY_RANK,
    SHAPE,
    name,
)
from .out_table import DAY, DECIMAL, MONEY, Cell, Column, note_rows, table

__all__ = ["alternatives_sheet", "cost_sheet", "curve_sheet", "factor_sheet", "impact_sheet"]

RATIO = "0.0%"


def _path(impact: Impact) -> str:
    """근거 경로: 변경 지점 → (관계) → … → 이 엔터티(ID)."""
    if not impact.path:
        return ""
    steps = [impact.path[0].src]
    steps += [f"({name(RELATION, hop.relation)}) {hop.dst}" for hop in impact.path]
    return " → ".join(steps)


def impact_sheet(ws: Worksheet, result: AnalysisResult) -> None:
    labels = {node.id: node.label for node in result.graph.nodes}
    ordered = sorted(
        result.impacts, key=lambda i: (SEVERITY_RANK.get(i.severity.value, 9), i.entity_type.value, i.entity_id)
    )
    rows: Iterable[list[Cell]] = (
        [
            name(SEVERITY, i.severity),
            name(ENTITY, i.entity_type),
            i.entity_id,
            labels.get(i.entity_id, ""),
            name(IMPACT, i.impact_type),
            i.rule_id,
            _path(i),
            i.note or None,
        ]
        for i in ordered
    )
    columns = [
        Column("심각도", 8),
        Column("대상 종류", 10),
        Column("대상 ID", 26),
        Column("이름", 30),
        Column("영향", 14),
        Column("규칙", 8),
        Column("근거 경로", 70, wrap=True),
        Column("메모", 50, wrap=True),
    ]
    table(ws, columns, rows)


def _num(value: float) -> str:
    """글 속 숫자: 정수면 천 단위, 아니면 소수 셋째 자리까지(끝 0 없앰)."""
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.3f}".rstrip("0").rstrip(".")


def _inputs(line: CostLine) -> str:
    parts = [
        f"{INPUT[key]} {_num(value)}"
        for key, value in line.inputs.items()
        if key in INPUT and isinstance(value, (int, float))
    ]
    return " · ".join(parts)


def _factors(line: CostLine) -> str:
    """가정값 글: '인건비(직영) 50,000원/시간(40,000~60,000)', 비율은 %로('취소·변경률(가공) 80%(55~100%)')."""

    def one(label: str, unit: str, value: float, low: float, high: float) -> str:
        if unit == "비율":
            return f"{label} {_num(value * 100)}%({_num(low * 100)}~{_num(high * 100)}%)"
        return f"{label} {_num(value)}{unit}({_num(low)}~{_num(high)})"

    return " · ".join(one(f.label, f.unit, f.value, f.low, f.high) for f in line.factors)


def _outlook(outlook: LineOutlook | None) -> str:
    if outlook is None:
        return ""
    kind = outlook.kind.value
    if kind == "changes" and outlook.on and outlook.amount:
        note = f", {outlook.note}" if outlook.note else ""
        return f"{outlook.on.isoformat()} 확정부터 {outlook.amount.value:,}원{note}"
    if kind == "removed" and outlook.on:
        return f"{outlook.on.isoformat()} 확정부터 이 비용 없음"
    if kind == "steady" and outlook.checked_until:
        return f"{outlook.checked_until.isoformat()}까지 그대로"
    return "확정일 이후 검토한 날 없음"


def _sources(line: CostLine) -> str:
    return " · ".join(
        "/".join(str(part) for part in (s.file, s.sheet, s.row) if part is not None) for s in line.sources
    )


def _multiplier(line: CostLine) -> float | None:
    """재작업 배수(확정일 단계, 가정값 대표값). 재작업 줄이 아니면 None."""
    factor = next((f for f in line.factors if any(k.startswith("rework_multiplier.") for k in f.keys)), None)
    return factor.value if factor else None


def _difficulty(line: CostLine) -> str | None:
    """난이도 내역: 1보다 큰 계수만 '곡블록 1.3 × 의장 밀도 1.02'(화면 '배수·난이도' 줄과 같음), 상한이면 덧붙임."""
    d = line.difficulty
    if d is None:
        return None
    shape = name(SHAPE, d.shape) if d.shape else "형상"
    named = ((shape, d.shape_factor), ("의장 밀도", d.outfit_factor), ("전장품", d.electric_factor))
    text = " × ".join(f"{label} {_multiple(value)}" for label, value in named if value > 1) or "보정 없음"
    return f"{text} · 상한 {_multiple(d.cap)} 적용" if d.capped else text


def _multiple(value: float) -> str:
    """배수·계수 표기(화면 multipleText와 같음): 소수 둘째 자리, 끝 0 하나는 지움(2 → 2.0, 1.30 → 1.3)."""
    text = f"{value:.2f}"
    return text[:-1] if text.endswith("0") else text


def _performer(line: CostLine) -> str | None:
    """수행 주체(1.32.0 사내 협력사): 작업반 몫 줄은 그 작업반 이름(줄 이름 '… — ○○ 작업반 추가 공비'),
    나눈 직영 몫은 '직영'."""
    head, _, tail = line.label.rpartition(" — ")
    if not head:
        return None
    if tail.endswith(" 추가 공비"):
        return tail.removesuffix(" 추가 공비")
    crew = line.inputs.get("crew_id")
    return str(crew) if crew is not None else (tail if tail == "직영" else None)


KIND_ORDER = {"labor": 0, "material": 1, "damages": 2}
"""비용 근거 시트의 묶음 순서(1.35.0 구분): 공수 → 재료비 → 지체상금. 구분이 없는 옛 결과는 금액 큰 순 그대로."""


def cost_order(line: CostLine) -> tuple[int, int, str]:
    """비용 근거 줄 순서: 구분 묶음(공수 → 재료비 → 지체상금) 안에서 금액 큰 순, 같으면 줄 ID 순."""
    kind = KIND_ORDER.get(line.kind.value, 9) if line.kind is not None else 0
    return (kind, -line.amount.value, line.line_id)


def _cost_row(index: int, line: CostLine) -> list[Cell]:
    """비용 근거 한 줄(칸 순서는 COST_COLUMNS와 같음)."""
    hours = line.hours
    return [
        index,
        line.label,
        name(COST_KIND, line.kind) if line.kind else None,
        name(COST_ITEM, line.item) if line.item else None,
        line.entity_id,
        line.rule_id,
        line.formula,
        _inputs(line) or None,
        _factors(line) or None,
        line.amount.value,
        line.amount.low,
        line.amount.high,
        hours.value if hours else None,
        hours.low if hours else None,
        hours.high if hours else None,
        name(DETERMINACY, line.determinacy),
        _outlook(line.outlook) or None,
        line.reason,
        _sources(line) or None,
        _multiplier(line),
        round(line.difficulty.value, 6) if line.difficulty else None,
        _difficulty(line),
        _performer(line),
    ]


def cost_sheet(ws: Worksheet, result: AnalysisResult) -> None:
    """비용 줄 하나가 한 줄. 마지막 줄은 결과의 총변경비용(줄 합 = 총액은 계약이 검사).
    재작업 줄은 배수와 난이도 계수를 따로 칸에 두고(곱한 값 하나로 읽히지 않게), 작업반 몫 줄은 수행 주체를 적는다.
    1.35.0 구분(공수·재료비·지체상금)·세부 구분·공수(MH)는 결과 필드 그대로(구분이 없는 옛 결과는 빈칸)."""
    rows = [_cost_row(index, line) for index, line in enumerate(sorted(result.cost_lines, key=cost_order), start=1)]
    total = result.total
    hours = result.cost_split.labor_hours if result.cost_split else None
    last: list[Cell] = [None, "합계(총변경비용)", None, None, None, None, None, None, None]
    last += [total.value, total.low, total.high]
    if hours is not None:
        last += [hours.value, hours.low, hours.high]
    rows.append(last)
    table(ws, COST_COLUMNS, rows)


COST_COLUMNS = [
    Column("순서", 6),
    Column("항목", 30),
    Column("구분", 8),
    Column("세부 구분", 14),
    Column("대상", 24),
    Column("규칙", 8),
    Column("계산식", 50, wrap=True),
    Column("입력값", 34, wrap=True),
    Column("가정값(공수·단가·배수)", 60, wrap=True),
    Column("금액 대표(원)", 15, MONEY),
    Column("최소(원)", 14, MONEY),
    Column("최대(원)", 14, MONEY),
    Column("공수 대표(MH)", 12, DECIMAL),
    Column("공수 최소(MH)", 12, DECIMAL),
    Column("공수 최대(MH)", 12, DECIMAL),
    Column("계산", 12),
    Column("확정이 늦어지면", 34, wrap=True),
    Column("발생 사유", 60, wrap=True),
    Column("원본 위치", 24),
    Column("재작업 배수", 10, DECIMAL),
    Column("난이도 계수", 10, DECIMAL),
    Column("난이도 내역", 34, wrap=True),
    Column("수행 주체(작업반)", 16),
]
"""비용 근거 시트 칸(1.35.0: 항목 다음 구분·세부 구분, 금액 다음 공수 MH 셋)."""


def factor_sheet(ws: Worksheet, result: AnalysisResult) -> None:
    """비용 줄이 쓴 가정값(공수·단가·배수·비율) 하나가 한 줄 — 숫자로 걸러 보는 용도. 비율은 %로."""
    lines = sorted(result.cost_lines, key=lambda c: (-c.amount.value, c.line_id))
    pairs = [(line, factor) for line in lines for factor in line.factors]
    rows: list[list[Cell]] = [
        [line.label, line.entity_id, f.label, f.unit, f.value, f.low, f.high, name(PARAM_STATUS, f.status)]
        for line, f in pairs
    ]
    columns = [
        Column("비용 항목", 30),
        Column("대상", 24),
        Column("가정값", 34),
        Column("단위", 10),
        Column("대표", 12, DECIMAL),
        Column("최소", 12, DECIMAL),
        Column("최대", 12, DECIMAL),
        Column("근거 상태", 10),
    ]
    table(ws, columns, rows)
    for offset, (_, f) in enumerate(pairs, start=2):
        if f.unit == "비율":
            for col in (5, 6, 7):
                ws.cell(row=offset, column=col).number_format = RATIO


def curve_sheet(ws: Worksheet, result: AnalysisResult) -> None:
    """확정일마다(기준일 → 탐색 기간 끝) 총변경비용·추가손실·구역 출구 지연과 그날 바뀐 이유."""
    deadline = result.timing.deadline
    marked = deadline.kind.value != "none_in_horizon"

    def mark(index: int, day: object) -> str | None:
        notes = ["기준일"] if index == 0 else []
        if marked and day == deadline.last_day:
            notes.append("결정 기한")
        return " · ".join(notes) or None

    rows = [
        [
            p.confirm_on,
            mark(i, p.confirm_on),
            p.total.value,
            p.total.low,
            p.total.high,
            p.additional_loss.value,
            p.additional_loss.low,
            p.additional_loss.high,
            p.max_exit_delay_days,
            ", ".join(p.events) or None,
        ]
        for i, p in enumerate(result.timing.curve)
    ]
    columns = [
        Column("확정일", 12, DAY),
        Column("표시", 20),
        Column("총변경비용 대표(원)", 18, MONEY),
        Column("최소(원)", 14, MONEY),
        Column("최대(원)", 14, MONEY),
        Column("추가손실 대표(원)", 16, MONEY),
        Column("추가손실 최소(원)", 16, MONEY),
        Column("추가손실 최대(원)", 16, MONEY),
        Column("구역 출구 최대 지연(일)", 20),
        Column("그날 바뀐 이유", 60, wrap=True),
    ]
    table(ws, columns, rows)


def alternatives_sheet(ws: Worksheet, result: AnalysisResult, *, known_notes: tuple[str, ...]) -> None:
    """대안 포함 분석의 대안 표(대안 탭과 같은 계산) + 아래에 대안 계산에서만 생긴 한계·가정 문장."""
    advised = result.recommendation.alt_id if result.recommendation else None
    rows = [
        [
            "권고" if a.alt_id == advised else None,
            a.rank,
            a.label,
            name(ORIGIN, a.origin),
            name(ELIGIBILITY, a.eligibility.status),
            a.eligibility.criterion,
            a.eligibility.note or None,
            a.eligibility.ratio_vs_request,
            "예" if a.scope_reduced else None,
            a.max_exit_delay_days,
            a.impacted_count,
            a.deadline.last_day if a.deadline else None,
            a.total.value,
            a.total.low,
            a.total.high,
            a.best_confirm_on,
            a.best_total.value if a.best_total else None,
            " · ".join(f"{h.po_id} {h.hold_days}일" for h in a.best_holds) or None,
            a.eligibility.basis or None,
        ]
        for a in result.alternatives
    ]
    columns = [
        Column("권고", 6),
        Column("충족 순위", 9),
        Column("대안", 40),
        Column("구분", 10),
        Column("판정", 12),
        Column("조건", 34, wrap=True),
        Column("판정 설명", 40, wrap=True),
        Column("요청안 대비 강도 비율", 12, DECIMAL),
        Column("적용 범위 축소", 10),
        Column("구역 출구 지연(일)", 12),
        Column("영향 수", 8),
        Column("결정 기한", 14, DAY),
        Column("총변경비용 대표(원)", 18, MONEY),
        Column("최소(원)", 14, MONEY),
        Column("최대(원)", 14, MONEY),
        Column("최저 비용 확정일", 14, DAY),
        Column("그날 총변경비용(원)", 18, MONEY),
        Column("병행 보류", 20),
        Column("판정 근거(식·조항)", 60, wrap=True),
    ]
    table(ws, columns, rows)
    extra = [note for note in result.notes if note not in known_notes]
    note_rows(ws, ["대안 계산의 한계·가정", *extra])
