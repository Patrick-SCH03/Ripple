"""합성 과거 사례 설정(params/cases_v1.yaml): 결정 종류·결정 시점을 뽑는 가정과 비슷한 정도 점수."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field, model_validator

from ripple.config.loaders import read_yaml
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.base import Frozen

DEFAULT_PATH = PROJECT_ROOT / "params" / "cases_v1.yaml"


class Choice(StrEnum):
    """합성 사례의 결정·진행 방식(화면 이름은 CHOSEN)."""

    AS_REQUESTED = "as_requested"
    HOLD_PO = "hold_po"
    REJECT = "reject"
    HOLD = "hold"


class Timing(Frozen):
    late_share: float = Field(ge=0, le=1)
    early_max_days: int = Field(ge=0, le=60)
    late_max_days: int = Field(ge=1, le=60)
    no_deadline_max_days: int = Field(ge=0, le=60)


class Similarity(Frozen):
    block: float = Field(ge=0)
    zone: float = Field(ge=0)
    system: float = Field(ge=0)
    intent: float = Field(ge=0)
    size: float = Field(ge=0)
    size_close: float = Field(ge=0, le=1)
    threshold: float = Field(gt=0)

    @model_validator(mode="after")
    def _block_first(self) -> Similarity:
        """같은 블록 사례가 늘 앞에 오게: 같은 블록 최소(블록 + 구역) > 다른 블록 최대(구역 + 계통 + 목적 + 크기)."""
        if self.block + self.zone <= self.zone + self.system + self.intent + self.size:
            raise ValueError("같은 블록 점수가 다른 블록 사례의 최대 점수 이하 — 더 큰 값 필요")
        return self


class CaseSettings(Frozen):
    version: str = Field(min_length=1)
    count: int = Field(ge=1, le=200)
    decisions: dict[Choice, float]
    timing: Timing
    similarity: Similarity
    keep_maps: int = Field(ge=1, le=20)

    @model_validator(mode="after")
    def _weights(self) -> CaseSettings:
        if self.decisions.get(Choice.AS_REQUESTED, 0) <= 0 or any(w < 0 for w in self.decisions.values()):
            raise ValueError("결정 비율 오류 — 모두 0 이상, '요청대로 승인'은 0 초과 필요(늘 할 수 있는 결정)")
        return self


def load_settings(path: Path = DEFAULT_PATH) -> CaseSettings:
    return CaseSettings.model_validate(read_yaml(path))
