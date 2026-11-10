"""확정이 늦어지면(docs/engine.md(비용·일정) 8-5): 확정일 다음날부터 탐색 기간 끝까지 같은 줄 ID의 비용 줄을 본다.

- 금액(최소·대표·최대)이 처음 달라지는 날 → 그날 확정할 때의 금액, 판정 단계가 바뀌었으면 그 변화
- 금액이 바뀌기 전에 줄이 없어지는 날 → 없어짐
- 끝까지 같으면 → 본 마지막 날까지 그대로, 확정일 뒤로 평가한 날이 없으면 → 보지 않음
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from ripple.contracts.result import CostLine, Determinacy, LineOutlook, OutlookKind

from .describe import BLOCK_STAGE_NAMES, PO_STATUS_NAMES

STAGE_NAMES: dict[str, str] = {
    **{stage.value: name for stage, name in BLOCK_STAGE_NAMES.items()},
    **{status.value: name for status, name in PO_STATUS_NAMES.items()},
}
"""줄 입력의 판정 단계 값(블록 단계 또는 발주 품목 단계, 값이 겹치지 않음) → 이름."""


def outlook_of(line: CostLine, later: Sequence[tuple[date, Mapping[str, CostLine]]]) -> LineOutlook:
    """확정일 뒤의 날짜순 평가(날짜, 줄 ID → 줄)로 이 줄의 늦어지면을 정한다."""
    if not later:
        return LineOutlook(kind=OutlookKind.UNCHECKED)
    for day, lines in later:
        other = lines.get(line.line_id)
        if other is None:
            return LineOutlook(kind=OutlookKind.REMOVED, on=day)
        if other.amount != line.amount:
            return LineOutlook(kind=OutlookKind.CHANGES, on=day, amount=other.amount, note=stage_change(line, other))
    return LineOutlook(kind=OutlookKind.STEADY, checked_until=later[-1][0])


def stage_change(before: CostLine, after: CostLine) -> str | None:
    """두 줄 모두 판정 단계를 알고 그 단계가 다르면 "단계 A → B". 단계를 모르는 줄은 None."""
    if before.determinacy is not Determinacy.KNOWN or after.determinacy is not Determinacy.KNOWN:
        return None
    old, new = before.inputs.get("stage"), after.inputs.get("stage")
    if old is None or new is None or old == new:
        return None
    return f"단계 {STAGE_NAMES.get(str(old), str(old))} → {STAGE_NAMES.get(str(new), str(new))}"


def with_outlooks(
    lines: Sequence[CostLine], confirm_on: date, evaluated: Mapping[date, Sequence[CostLine]]
) -> tuple[CostLine, ...]:
    """확정일 평가의 줄마다 늦어지면을 붙인다. evaluated는 날짜 → 그날 확정할 때의 비용 줄."""
    later = [(day, {other.line_id: other for other in evaluated[day]}) for day in sorted(evaluated) if day > confirm_on]
    return tuple(line.model_copy(update={"outlook": outlook_of(line, later)}) for line in lines)
