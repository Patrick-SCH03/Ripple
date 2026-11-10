"""확정 시점 계약(docs/engine.md(비용·일정) 8절): 추가손실 곡선·추가손실 0 마감일·보류 권고·잉여 자재 전용."""

from __future__ import annotations

from datetime import date
from itertools import pairwise

from pydantic import Field, model_validator

from ..base import Frozen
from .amount import Amount
from .vocab import DeadlineKind


class CurvePoint(Frozen):
    confirm_on: date
    total: Amount  # C(t): 이날 확정할 때의 총변경비용
    additional_loss: Amount  # A(t) = C(t) − C(기준일)
    max_exit_delay_days: int = Field(ge=0)
    events: tuple[str, ...] = ()  # 이날 계단이 생긴 이유, 예: "PO-0123 자재 확보"


def additional_loss_of(total: Amount, base: Amount) -> Amount:
    """A(t) = C(t) − C(기준일). 파라미터 시나리오(최소·대표·최대)별 차이의 최소~최대를 범위로 둔다."""
    diffs = (total.low - base.low, total.value - base.value, total.high - base.high)
    return Amount(value=diffs[1], low=min(diffs), high=max(diffs))


class ZeroLossDeadline(Frozen):
    """추가손실 0 마감일: 기준일부터 추가손실 최대값(high)이 계속 0 이하인 마지막 날."""

    kind: DeadlineKind
    last_day: date


class HoldAdvice(Frozen):
    po_id: str
    rule_id: str
    max_hold_days: int = Field(ge=0)
    hold_until: date
    avoided: Amount  # 보류로 피하는 손실(탐색 기간 안에서 가장 큰 날)
    reason: str
    deadline_after: ZeroLossDeadline  # 보류했을 때의 추가손실 0 마감일
    line_ids: tuple[str, ...] = ()  # 이 변경이 바꾸는 이 발주의 품목(ID 순, 비용 줄과 잇는 데 씀)


class Reallocation(Frozen):
    lot_id: str  # 재고 로트 ID, 또는 남는 자재를 다른 블록으로 돌릴 때 그 자재의 발주 품목 ID
    rule_id: str
    spec_id: str
    to_block_id: str
    qty: float = Field(gt=0)
    saved: Amount


class TimingResult(Frozen):
    base_cost: Amount  # 기본 변경비용 = C(기준일)
    curve: tuple[CurvePoint, ...] = Field(min_length=1)
    deadline: ZeroLossDeadline
    holds: tuple[HoldAdvice, ...] = ()
    reallocations: tuple[Reallocation, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> TimingResult:
        if any((b.confirm_on - a.confirm_on).days != 1 for a, b in pairwise(self.curve)):
            raise ValueError("곡선 날짜는 하루 간격 필요")
        first = self.curve[0]
        if first.total != self.base_cost:
            raise ValueError("곡선 첫날 총비용과 기본 변경비용 불일치")
        if any(p.additional_loss != additional_loss_of(p.total, self.base_cost) for p in self.curve):
            raise ValueError("추가손실이 그날 총비용 − 기본 변경비용과 다름")
        if self.deadline != expected_deadline(self.curve):
            raise ValueError("추가손실 0 마감일과 곡선 불일치")
        return self


def expected_deadline(curve: tuple[CurvePoint, ...]) -> ZeroLossDeadline:
    """곡선에서 마감일을 정한다: 기준일부터 추가손실 high가 0 이하로 이어지는 마지막 날."""
    run = 0
    while run < len(curve) and curve[run].additional_loss.high <= 0:
        run += 1
    if run == len(curve):
        return ZeroLossDeadline(kind=DeadlineKind.NONE_IN_HORIZON, last_day=curve[-1].confirm_on)
    if run <= 1:
        return ZeroLossDeadline(kind=DeadlineKind.CONFIRM_NOW, last_day=curve[0].confirm_on)
    return ZeroLossDeadline(kind=DeadlineKind.BY_DATE, last_day=curve[run - 1].confirm_on)
