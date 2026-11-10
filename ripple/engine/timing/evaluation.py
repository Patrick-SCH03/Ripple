"""판정일 하루의 평가 결과(docs/engine.md(비용·일정) 1절): 비용 줄·총액·변경 일정·영향·계산하지 못한 이유."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from ripple.contracts.result import Amount, CostLine, Impact, Reallocation, ScheduleImpact, Unresolved

from ..cost import Demand
from ..cost.onboard import OnboardBlock
from ..propagate import Propagation


@dataclass(frozen=True, slots=True)
class Evaluation:
    day: date
    propagation: Propagation
    lines: tuple[CostLine, ...]  # 줄 ID 순, 지체상금 포함
    total: Amount
    schedule: ScheduleImpact
    max_exit_delay: int
    impacts: tuple[Impact, ...]  # 1단계 영향 + 일정 지연(R-S01) + 인도 지연(R-L01), 키 순
    unresolved: tuple[Unresolved, ...]
    reallocations: tuple[Reallocation, ...]
    demands: tuple[Demand, ...]
    notes: tuple[str, ...]
    onboard: Mapping[str, OnboardBlock]  # 선상 설치 수요가 있는 블록(6-3 정의, 적용 여부와 무관)
    on_board: bool  # 이 평가가 선상 설치를 적용했는가
