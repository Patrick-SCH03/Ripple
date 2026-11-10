"""강도 사전검사 규칙 계약(rules/strength.yaml, docs/engine.md(대안) 2-2).

요청안 대비 상대 비교에만 쓰는 값이다. 선급 규칙 원문·표는 싣지 않고 조항 번호만 출처에 적는다.
"""

from __future__ import annotations

from datetime import date
from itertools import pairwise

from pydantic import Field, model_validator

from .base import Frozen
from .params import ParamStatus


class Sourced(Frozen):
    status: ParamStatus
    source: str | None = None
    mentor_question: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _evidence_has_source(self) -> Sourced:
        if self.status is ParamStatus.EVIDENCE and not self.source:
            raise ValueError("근거 있는 값에는 출처 필요")
        return self


class MaterialFactors(Sourced):
    values: dict[int, float]  # 항복 강도(MPa) → 재료 계수 k


class YieldStrengths(Sourced):
    values: dict[str, int]  # 강종 → 최소 항복 강도(MPa)


class Upgrades(Sourced):
    values: dict[str, str]  # 강종 → 상향 강종


class Scalar(Sourced):
    value: float = Field(gt=0)


class StrengthRules(Frozen):
    version: str = Field(pattern=r"^strength-v\d+$")
    updated: date
    material_factor: MaterialFactors
    yield_strength: YieldStrengths
    upgrade: Upgrades
    plate_corrosion_addition_mm: Scalar
    max_plate_thickness_mm: Scalar

    @model_validator(mode="after")
    def _consistent(self) -> StrengthRules:
        factors = self.material_factor.values
        ordered = sorted(factors)
        if any(factors[a] <= factors[b] for a, b in pairwise(ordered)):
            raise ValueError("재료 계수가 항복 강도가 높을수록 작지 않음")
        missing = sorted({y for y in self.yield_strength.values.values()} - set(factors))
        if missing:
            raise ValueError(f"재료 계수 없는 항복 강도: {missing}")
        for low, high in self.upgrade.values.items():
            if low not in self.yield_strength.values or high not in self.yield_strength.values:
                raise ValueError(f"강종 상향 {low} → {high}에 항복 강도 없는 강종 있음")
            if self.yield_strength.values[high] <= self.yield_strength.values[low]:
                raise ValueError(f"강종 상향 {low} → {high}의 항복 강도 상승 필요")
        return self

    def k(self, grade: str | None) -> float | None:
        """강종의 재료 계수. 강종을 모르거나 표에 없으면 None(설계자 확인)."""
        if grade is None or grade not in self.yield_strength.values:
            return None
        return self.material_factor.values[self.yield_strength.values[grade]]
