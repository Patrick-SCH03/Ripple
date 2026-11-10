"""블록별 강재 중량 변화 계약(1.34.0, docs/engine.md(비용·일정) 12절): 바뀌는 부재의 원래·새 중량을 블록별로
묶은 정보.

비용·일정·판정·곡선·대안에 쓰지 않는다. 무게중심은 좌표가 없어 싣지 않는다. 중량(t)은 소수 여섯째 자리에서
반올림한 값이고, 블록 값 = 그 블록 부재 값의 합, 전체 값 = 블록 값의 합이다(반올림 오차 안에서 — 계약 검사).
"""

from __future__ import annotations

from pydantic import Field, model_validator

from ..base import Frozen
from .vocab import WeightSource

WEIGHT_DIGITS = 6
"""중량(t) 반올림 자리(1g). 합계 검사는 반올림 오차((더한 수 + 1) × 1e-6) 안에서 본다."""


def _close(a: float, b: float, count: int) -> bool:
    return abs(a - b) <= (count + 1) * 10.0**-WEIGHT_DIGITS


class PartWeight(Frozen):
    """바뀌는 부재 하나의 원래·새 중량. 중량 정보가 없으면(source = none) 두 값이 모두 None."""

    part_id: str
    label: str
    block_id: str | None = None  # 블록을 모르는 새 부재면 None
    ops: tuple[str, ...] = Field(min_length=1)  # 이 부재를 바꾸는 연산 이름(사전 순)
    source: WeightSource
    before_t: float | None = Field(default=None, ge=0)  # 새 부재는 0
    after_t: float | None = Field(default=None, ge=0)  # 빼는 부재는 0
    from_mm: float | None = Field(default=None, gt=0)  # 두께 변경일 때만 원래·새 두께
    to_mm: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _known(self) -> PartWeight:
        unknown = self.source is WeightSource.NONE
        if unknown != (self.before_t is None) or unknown != (self.after_t is None):
            raise ValueError("중량 정보 없음이면 원래·새 중량 모두 비움, 아니면 모두 필요")
        if list(self.ops) != sorted(set(self.ops)):
            raise ValueError("부재 중량의 연산 이름은 사전 순·중복 없음 필요")
        return self

    @property
    def delta_t(self) -> float | None:
        if self.before_t is None or self.after_t is None:
            return None
        return round(self.after_t - self.before_t, WEIGHT_DIGITS)


class BlockWeight(Frozen):
    """블록 하나의 중량 변화: 중량을 아는 부재의 합(counted개)과 중량 정보 없는 부재 수(missing)."""

    block_id: str | None = None  # None = 블록을 모르는 새 부재 묶음
    name: str  # 블록 이름(지도 Block.name), 모르면 '블록 모름'
    before_t: float = Field(ge=0)
    after_t: float = Field(ge=0)
    delta_t: float
    counted: int = Field(ge=0)
    missing: int = Field(ge=0)
    parts: tuple[PartWeight, ...] = Field(min_length=1)  # 부재 ID 순

    @model_validator(mode="after")
    def _sums(self) -> BlockWeight:
        known = [p for p in self.parts if p.source is not WeightSource.NONE]
        ids = [p.part_id for p in self.parts]
        if ids != sorted(set(ids)) or any(p.block_id != self.block_id for p in self.parts):
            raise ValueError("블록 중량의 부재는 ID 순·중복 없음·같은 블록 필요")
        if (self.counted, self.missing) != (len(known), len(self.parts) - len(known)):
            raise ValueError("블록 중량의 부재 수(중량 앎·정보 없음)와 부재 목록 불일치")
        n = len(known)
        if not (
            _close(self.before_t, sum(p.before_t or 0 for p in known), n)
            and _close(self.after_t, sum(p.after_t or 0 for p in known), n)
            and _close(self.delta_t, self.after_t - self.before_t, n)
        ):
            raise ValueError("블록 중량 = 부재 중량의 합, 차이 = 새 − 원래 필요")
        return self


class WeightChange(Frozen):
    """요청이 바꾸는 부재의 블록별 강재 중량 변화(명세 12절). 바뀌는 부재가 없으면 블록 목록이 비고 합계는 0."""

    blocks: tuple[BlockWeight, ...] = ()  # 블록 ID 순, 블록 모름(None)은 끝
    before_t: float = Field(default=0, ge=0)
    after_t: float = Field(default=0, ge=0)
    delta_t: float = 0
    counted: int = Field(default=0, ge=0)
    missing: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _totals(self) -> WeightChange:
        keys = [(b.block_id is None, b.block_id or "") for b in self.blocks]
        if keys != sorted(set(keys)):
            raise ValueError("중량 변화 블록은 ID 순·중복 없음 필요(블록 모름은 끝)")
        n = len(self.blocks)
        if not (
            _close(self.before_t, sum(b.before_t for b in self.blocks), n)
            and _close(self.after_t, sum(b.after_t for b in self.blocks), n)
            and _close(self.delta_t, sum(b.delta_t for b in self.blocks), n)
        ):
            raise ValueError("중량 변화 합계 = 블록 값의 합 필요")
        if (self.counted, self.missing) != (sum(b.counted for b in self.blocks), sum(b.missing for b in self.blocks)):
            raise ValueError("중량 변화 부재 수 = 블록 부재 수의 합 필요")
        return self
