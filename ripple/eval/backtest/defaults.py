"""백테스트 변환 기본값(defaults.yaml, docs/backtest.md 4절): 사례에 없거나 빈 값을 채우는 가정."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field

from ripple.config.loaders import read_yaml
from ripple.contracts.base import Frozen

DEFAULTS_PATH = Path(__file__).with_name("defaults.yaml")

BlockType = Literal["flat", "curved", "bow_stern"]
Performer = Literal["direct", "in_house_subcontractor"]
SpoolMethod = Literal["in_house", "outside", "dimension"]
DelayBasis = Literal["erection", "exit", "delivery"]


class BlockWeights(Frozen):
    """블록 무게가 비었을 때 블록 종류별 기본값(t)."""

    flat: float = Field(gt=0)
    curved: float = Field(gt=0)
    bow_stern: float = Field(gt=0)
    unknown: float = Field(gt=0)

    def of(self, block_type: BlockType | None) -> float:
        return self.unknown if block_type is None else float(getattr(self, block_type))


class MemberDefaults(Frozen):
    weight_t: float = Field(gt=0)
    count: int = Field(ge=1)


class SpoolDefaults(Frozen):
    method: SpoolMethod
    in_house_lead_days: int = Field(gt=0)
    weight_t: float = Field(gt=0)
    length_m: float = Field(gt=0)
    po_lines: int = Field(ge=1)


class ScheduleDefaults(Frozen):
    erection_start: date
    stage_position: float = Field(ge=0, le=1)
    exit_slack_days: int = Field(ge=0)
    float_to_delivery_days: int = Field(ge=0)
    post_exit_days: int = Field(ge=0)


class BacktestDefaults(Frozen):
    version: str = Field(pattern=r"^backtest-v\d+$")
    block_weight_t: BlockWeights
    member: MemberDefaults
    spool: SpoolDefaults
    delay_basis: DelayBasis
    schedule: ScheduleDefaults


def load_defaults(path: Path = DEFAULTS_PATH) -> BacktestDefaults:
    return BacktestDefaults.model_validate(read_yaml(path))
