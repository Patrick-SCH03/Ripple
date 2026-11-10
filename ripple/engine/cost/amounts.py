"""금액 시나리오 셋(docs/engine.md(비용·일정) 2절): low·value·high로 같은 산식을 세 번 계산한다."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from enum import Enum

from ripple.contracts.params import ParamSet
from ripple.contracts.result import HOURS_DIGITS, Amount, WorkHours, additional_loss_of


class Scenario(Enum):
    LOW = "low"
    VALUE = "value"
    HIGH = "high"


SCENARIOS: tuple[Scenario, ...] = (Scenario.LOW, Scenario.VALUE, Scenario.HIGH)


class Params:
    """파라미터를 시나리오별로 읽는다. 쓴 키를 모아 비용 줄의 근거로 남긴다."""

    def __init__(self, params: ParamSet) -> None:
        self.raw = params
        self.version = params.version

    def get(self, key: str, scenario: Scenario) -> float:
        param = self.raw.get(key)
        if scenario is Scenario.LOW:
            return param.low
        if scenario is Scenario.HIGH:
            return param.high
        return param.value

    def value(self, key: str) -> float:
        return self.raw.value(key)

    def has(self, key: str) -> bool:
        return key in self.raw.params


def round_won(amount: float) -> int:
    """원 단위 반올림(0.5는 0에서 먼 쪽)."""
    magnitude = math.floor(abs(amount) + 0.5)
    return magnitude if amount >= 0 else -magnitude


def amount_of(formula: Callable[[Scenario], float]) -> Amount:
    """범위가 있는 파라미터가 모두 금액을 키우는 방향인 산식을 세 시나리오로 계산한다."""
    low, value, high = (round_won(formula(s)) for s in SCENARIOS)
    return Amount(value=value, low=low, high=high)


def hours_of(formula: Callable[[Scenario], float]) -> WorkHours:
    """공수(MH) 시나리오 셋: 금액 산식이 인건비를 곱하기 전에 쓴 바로 그 시간(docs/engine.md(비용·일정) 4-12).
    반올림 자리는 줄 입력 inputs.hours와 같다."""
    low, value, high = (round(formula(s), HOURS_DIGITS) for s in SCENARIOS)
    return WorkHours(value=value, low=low, high=high)


def worst_hours(per_stage: Sequence[WorkHours], chosen: WorkHours) -> WorkHours:
    """단계를 모를 때의 공수: 대표 = 금액 대표값을 만든 단계(chosen)의 공수, 최소·최대 = 단계별 최소의 최솟값·최대의
    최댓값(금액 worst_case와 같은 짝)."""
    return WorkHours(value=chosen.value, low=min(h.low for h in per_stage), high=max(h.high for h in per_stage))


def worst_case(per_stage: Sequence[Amount]) -> Amount:
    """단계를 모를 때: low는 최솟값, value·high는 최댓값(docs/engine.md(비용·일정) 2절)."""
    return Amount(
        value=max(a.value for a in per_stage),
        low=min(a.low for a in per_stage),
        high=max(a.high for a in per_stage),
    )


def difference(minuend: Amount, subtrahend: Amount) -> Amount:
    """같은 시나리오끼리 뺀 세 값의 최소~최대(추가손실·피하는 손실) — 계약 검사의 additional_loss_of와 같은 식."""
    return additional_loss_of(minuend, subtrahend)


def mixed(gain: Callable[[Scenario], float], cost: Callable[[Scenario], float]) -> Amount:
    """이득 − 비용(절감액): low는 이득 low − 비용 high, high는 이득 high − 비용 low."""
    low = round_won(gain(Scenario.LOW) - cost(Scenario.HIGH))
    value = round_won(gain(Scenario.VALUE) - cost(Scenario.VALUE))
    high = round_won(gain(Scenario.HIGH) - cost(Scenario.LOW))
    return Amount(value=value, low=min(low, value), high=max(high, value))
