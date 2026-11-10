"""확정 시점 평가의 문맥(docs/engine.md(비용·일정) 1절): 요청마다 한 번 만드는 문맥과 판정일 하루의 조건."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date
from fractions import Fraction

from ripple.contracts.analysis import AnalysisRequest, HoldAction
from ripple.contracts.domain import ActivityKind
from ripple.contracts.rulebook import RuleBook

from ..cost import Params, SpecChange
from ..index import GraphIndex
from ..onboard import DemandKey
from ..propagate import Propagator
from ..schedule import Baseline
from ..state import StateModel


@dataclass(frozen=True, slots=True)
class EvalContext:
    """요청 하나의 평가 문맥: 평가기가 한 번 만들어 하루 평가·변경 일정·일정 영향·보류 권고에 넘긴다."""

    index: GraphIndex
    request: AnalysisRequest
    rulebook: RuleBook
    params: Params
    propagator: Propagator  # 변경 후 보기·기준 일정·보류에 따른 상태
    changes: tuple[SpecChange, ...]  # 규격 변경 표
    activity_of: Mapping[tuple[str, ActivityKind], str]  # (블록, 공정 종류) → 공정

    @property
    def baseline(self) -> Baseline:
        return self.propagator.baseline


@dataclass(frozen=True, slots=True)
class DayScenario:
    """판정일 하루 평가의 조건. state = 보류(held)에 따른 상태로, 평가기가 보류 집합마다 메모한 것을 넣는다."""

    day: date
    held: tuple[HoldAction, ...]
    state: StateModel
    on_board: bool  # 선상 설치 적용(6-3)
    with_graph: bool = False
    lead_ratios: Mapping[str, Fraction] | None = None  # 분류별 새 자재 리드타임 배율(일정 위험 6-6)
    fixed_onboard: Collection[DemandKey] | None = None  # 배 위로 보낼 수요를 고르지 않고 이 수요로 고정
