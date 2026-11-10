"""합성 NCR 묶음 계약(1.32.0 안에서 추가, docs/records.md '합성 NCR'): 사전 점검 유형별 부적합 보고 건수의 시연 재료.

실제 NCR 이력이 없어 합성 모드에서만 생성기 설정·씨앗으로 만든다(ripple/cases/ncr.py). 모든 문장에 '합성 묶음(시연)'을
적고, 건수만 보인다(비율·대표 손실 금액은 없다). 실데이터 모드에서는 만들지 않는다(빈 묶음 + 이유).
과거 이력으로 엔진을 검증했다는 뜻이 아니다.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Literal

from pydantic import Field, model_validator

from .base import Frozen
from .domain import BlockStage
from .result.precheck import PRECHECK_RULE_NAMES

SYNTHETIC_LABEL = "합성 묶음(시연)"
"""합성 NCR의 모든 문장에 들어가는 표기."""

NcrType = Literal["P-01", "P-02", "P-03", "P-04", "P-05", "P-06", "X-01", "X-02"]

NCR_TYPE_NAMES: Mapping[str, str] = MappingProxyType(
    {**PRECHECK_RULE_NAMES, "X-01": "기타(치수·취부 오차)", "X-02": "기타(자재 착오)"}
)
"""NCR 유형 → 이름: 사전 점검 규칙 6종(P-01~P-06)과 같은 이름 + 기타 2종."""


class NcrDiscipline(StrEnum):
    """분야(선체·배관·선장·기장·전장)."""

    HULL = "hull"  # 선체
    PIPING = "piping"  # 배관
    HULL_OUTFITTING = "hull_outfitting"  # 선장(선체 의장)
    MACHINERY = "machinery"  # 기장(기관 의장)
    ELECTRIC = "electric"  # 전장


class NcrRecord(Frozen):
    """합성 NCR 한 건: 유형 · 분야 짝(원인 분야 → 상대 분야) · 발견 단계 · 조치 수행 주체 · 원인 한 줄 · 조치 한 줄."""

    ncr_id: str = Field(pattern=r"^NCR-S-\d{4}$")
    ncr_type: NcrType
    disciplines: tuple[NcrDiscipline, NcrDiscipline]
    found_stage: BlockStage
    performer: str = Field(min_length=1, max_length=40)  # 조치한 작업반 이름 또는 '직영'
    cause: str = Field(min_length=1, max_length=200)
    action: str = Field(min_length=1, max_length=200)
    synthetic: Literal[True] = True

    @model_validator(mode="after")
    def _labelled(self) -> NcrRecord:
        if SYNTHETIC_LABEL not in self.cause or SYNTHETIC_LABEL not in self.action:
            raise ValueError(f"합성 NCR 문장에 '{SYNTHETIC_LABEL}' 표기 필요")
        return self


class NcrTypeCount(Frozen):
    ncr_type: NcrType
    name: str = Field(min_length=1)
    count: int = Field(ge=0)


class NcrSummary(Frozen):
    """합성 NCR 요약(GET /api/ncrs/summary): 유형별 건수와 최근 n건(번호가 클수록 최근). 건수만 — 비율·금액 없음."""

    available: bool  # 합성 묶음이 있는가(실데이터 모드면 거짓)
    synthetic: bool  # 합성 묶음인가(화면에 '합성 묶음(시연)'으로 늘 표시)
    label: str = SYNTHETIC_LABEL
    version: str | None = None  # 묶음 설정 판(params/ncr_v1.yaml)
    reason: str | None = None  # 비었을 때 이유
    total: int = Field(default=0, ge=0)
    counts: tuple[NcrTypeCount, ...] = ()  # 유형 순(P-01 … X-02), 0건 유형도 싣는다
    recent: tuple[NcrRecord, ...] = ()  # 최근 n건(번호 큰 순)

    @model_validator(mode="after")
    def _consistent(self) -> NcrSummary:
        if self.available != self.synthetic:
            raise ValueError("NCR 묶음은 합성 모드 전용")
        if not self.available and (self.total or self.recent or any(c.count for c in self.counts)):
            raise ValueError("묶음이 없는데 건수·최근 건 있음")
        if not self.available and not self.reason:
            raise ValueError("묶음 없음 — 이유 필요")
        if self.total != sum(c.count for c in self.counts):
            raise ValueError("NCR 총 건수가 유형별 건수의 합과 다름")
        return self
