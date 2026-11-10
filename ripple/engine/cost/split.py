"""총변경비용의 구분별 합(docs/engine.md(비용·일정) 4-12, 계약 1.35.0): 추가 공수(MH·금액) · 추가 재료비(자재 차이 ·
구매) · 지체상금.

새 계산은 없다 — 비용 줄마다 이미 붙은 구분·공수를 더할 뿐이다. 그래서 공수 + 재료비 + 지체상금 = 총액
(시나리오마다)이고, 총액 밖 금액(지연 파급 비용·지체상금 노출)은 들어가지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ripple.contracts.result import (
    HOURS_DIGITS,
    PURCHASE_ITEMS,
    Amount,
    CostKind,
    CostLine,
    CostSplit,
    WorkHours,
)


def cost_split(lines: Iterable[CostLine]) -> CostSplit:
    """비용 줄(모두 구분이 있는 새 판 줄)의 구분별 합. 구분이 빠진 줄이 있으면 ValueError(계산 경로 누락)."""
    rows = tuple(lines)
    missing = [line.line_id for line in rows if line.kind is None]
    if missing:
        raise ValueError(f"비용 줄 구분 누락: {missing[:3]}")

    def total(keep: Callable[[CostLine], bool]) -> Amount:
        return Amount.total([line.amount for line in rows if keep(line)])

    hours = [line.hours for line in rows if line.hours is not None]
    return CostSplit(
        labor_hours=WorkHours(
            value=round(sum(h.value for h in hours), HOURS_DIGITS),
            low=round(sum(h.low for h in hours), HOURS_DIGITS),
            high=round(sum(h.high for h in hours), HOURS_DIGITS),
        ),
        labor=total(lambda line: line.kind is CostKind.LABOR),
        material=total(lambda line: line.kind is CostKind.MATERIAL),
        material_diff=total(lambda line: line.kind is CostKind.MATERIAL and line.item not in PURCHASE_ITEMS),
        purchase=total(lambda line: line.item in PURCHASE_ITEMS),
        damages=total(lambda line: line.kind is CostKind.DAMAGES),
    )
