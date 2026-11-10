"""금액 값(원): 대표 파라미터로 계산한 값과 파라미터 범위 양 끝으로 계산한 최소·최대."""

from __future__ import annotations

from pydantic import model_validator

from ..base import Frozen


class Amount(Frozen):
    """금액(원). value는 대표 파라미터, low·high는 파라미터 범위 양 끝으로 계산한 값."""

    value: int
    low: int
    high: int

    @model_validator(mode="after")
    def _ordered(self) -> Amount:
        if not self.low <= self.value <= self.high:
            raise ValueError("금액은 최소 ≤ 대표값 ≤ 최대 필요")
        return self

    @classmethod
    def exact(cls, value: int) -> Amount:
        return cls(value=value, low=value, high=value)

    @classmethod
    def total(cls, amounts: tuple[Amount, ...] | list[Amount]) -> Amount:
        return cls(
            value=sum(a.value for a in amounts),
            low=sum(a.low for a in amounts),
            high=sum(a.high for a in amounts),
        )
