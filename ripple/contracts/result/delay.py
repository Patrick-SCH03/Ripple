"""지연 파급 비용 계약(1.32.0, docs/engine.md(비용·일정) 4-11): 총액 밖에 따로 싣는 가정 금액."""

from __future__ import annotations

from pydantic import Field, model_validator

from ..base import Frozen
from .amount import Amount
from .cost import CostFactor


class DelayRipple(Frozen):
    """구역 출구가 실제로 밀려 생기는 간접비(작업반 대기·재배치, 가정).

    지체상금 노출 금액(DeliveryImpact.exposure)처럼 총액·판정·결정 기한·대안·평가에 넣지 않는다. 공정 여유를 빼고 실제로
    밀리는 날만 센다 — 구역 출구 지연(CPM 여유 반영)만 쓰고 블록 탑재 지연은 쓰지 않는다. 지체상금과 겹치지 않게 늘어난
    인도 지연(지체상금·노출 금액이 세는 날)은 뺀다:
    days = 구역 출구 지연 최댓값 − 늘어난 인도 지연(계산하지 못했으면 0)."""

    amount: Amount
    days: int = Field(gt=0)
    exit_delay_days: int = Field(ge=0)  # 구역 출구 지연의 최댓값(ScheduleImpact.max_exit_delay_days)
    delivery_overlap_days: int = Field(ge=0)  # 뺀 날 = 늘어난 인도 지연(지체상금·노출 금액이 세는 날)
    factors: tuple[CostFactor, ...] = ()  # 하루 비용 가정값

    @model_validator(mode="after")
    def _days(self) -> DelayRipple:
        if self.days != self.exit_delay_days - self.delivery_overlap_days:
            raise ValueError("지연 파급 일수가 구역 출구 지연 최댓값 − 늘어난 인도 지연과 다름")
        if not 0 < self.amount.low <= self.amount.value <= self.amount.high:
            raise ValueError("지연 파급 비용은 0보다 큰 금액 필요")
        return self
