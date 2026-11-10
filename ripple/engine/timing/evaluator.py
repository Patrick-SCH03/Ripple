"""확정 시점 평가기(docs/engine.md(비용·일정) 1·6·7·8절): 요청 하나를 판정일·보류마다 평가하고 상태·곡선을 메모한다.

하루 평가는 day, 일정 위험은 risk, 선상 설치 선택지는 onboard, 곡선은 curve, 보류 권고는 hold가 맡는다.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from datetime import date
from fractions import Fraction
from typing import get_args

from ripple.contracts.analysis import AnalysisRequest, HoldAction
from ripple.contracts.domain import TransportMode
from ripple.contracts.params import ParamSet
from ripple.contracts.result import Amount, HoldAdvice, Impact, OnboardOption, ScheduleRisk
from ripple.contracts.rulebook import RuleBook

from ..cost import Params, activity_map, spec_changes
from ..cost.demand import TRANSPORT_GROUP
from ..index import GraphIndex
from ..onboard import DemandKey
from ..propagate import Propagator
from ..state import StateModel
from .context import DayScenario, EvalContext
from .curve import Curve, curve_points, search_days
from .day import DayEvaluator
from .evaluation import Evaluation
from .hold import HoldAdvisor
from .onboard import option_of, wants_option
from .risk import risk_scenario, schedule_risk

HoldKey = tuple[tuple[str, int], ...]


class Evaluator:
    """요청 하나를 판정일·보류마다 평가한다. 변경 후 보기·기준 일정·규격 표는 한 번만 만든다."""

    def __init__(self, index: GraphIndex, request: AnalysisRequest, rulebook: RuleBook, params: ParamSet) -> None:
        self.index = index
        self.request = request
        self.rulebook = rulebook
        self.params = Params(params)
        _check_grade_ratios(params)
        _check_transport_days(params)
        self.propagator = Propagator(index, request, rulebook)
        self.baseline = self.propagator.baseline
        self.changes = spec_changes(index, self.propagator.view, self.params)
        self.activity_of = activity_map(index)
        self._states: dict[HoldKey, StateModel] = {}
        self._curves: dict[HoldKey, Curve] = {}
        context = EvalContext(index, request, rulebook, self.params, self.propagator, self.changes, self.activity_of)
        self._day = DayEvaluator(context)
        self._holds = HoldAdvisor(context)

    def state(self, holds: Iterable[HoldAction]) -> StateModel:
        key = _key(holds)
        if key not in self._states:
            self._states[key] = self.propagator.state(HoldAction(po_id=p, hold_days=d) for p, d in key)
        return self._states[key]

    def evaluate(
        self,
        day: date,
        holds: Iterable[HoldAction],
        with_graph: bool = False,
        lead_ratios: Mapping[str, Fraction] | None = None,
        on_board: bool | None = None,
        fixed_onboard: Collection[DemandKey] | None = None,
    ) -> Evaluation:
        """on_board = 선상 설치 적용(None이면 요청대로, 6-8 비교는 반대로 한 번 더). fixed_onboard = 배 위로 보낼
        수요를 고르지 않고 이 수요로 고정(일정 위험이 대표 평가의 선택을 그대로 쓴다)."""
        held = tuple(holds)
        scenario = DayScenario(
            day=day,
            held=held,
            state=self.state(held),
            on_board=self.request.outfit_on_board if on_board is None else on_board,
            with_graph=with_graph,
            lead_ratios=lead_ratios,
            fixed_onboard=fixed_onboard,
        )
        return self._day.evaluate(scenario)

    def risk(self, day: date, holds: Iterable[HoldAction], representative: Evaluation) -> ScheduleRisk:
        """일정 위험(6-6): 새 자재 리드타임만 분류별 범위 끝으로 늘려 같은 날·같은 보류로 다시 평가한 일정.
        일정 부분(구역 출구·인도·위험에서만 생긴 계산 불가)만 쓰고 비용 줄·총액은 버린다.
        선상 설치는 대표 평가가 배 위로 보낸 수요를 그대로 쓴다(다시 고르면 위험 일정이 대표보다 이를 수 있음)."""
        ratios, fixed = risk_scenario(self.params, representative)
        ev = self.evaluate(day, holds, lead_ratios=ratios, fixed_onboard=fixed)
        return schedule_risk(ev, ratios, representative, self.params)

    def onboard_option(self, day: date, holds: Iterable[HoldAction], final: Evaluation) -> OnboardOption | None:
        """선상 설치 선택지(6-8): 같은 날·보류로 다른 실행 방식을 한 번 더 평가해 비교한다. 기다리는 요청이면 어느
        블록이든 탑재 지연이 선상 설치 일수보다 길 때만(짧으면 기다리는 편이 나음), 선상 설치 요청이면 늘 싣는다."""
        if not wants_option(final):
            return None
        return option_of(final, self.evaluate(day, holds, on_board=not final.on_board))

    def curve(self, holds: tuple[HoldAction, ...]) -> Curve:
        """보류 집합마다 한 번만 계산한다(보류 권고와 대안의 최적 조합이 같은 곡선을 다시 씀)."""
        key = _key(holds)
        if key not in self._curves:
            self._curves[key] = self._curve(holds)
        return self._curves[key]

    def _curve(self, holds: tuple[HoldAction, ...]) -> Curve:
        evaluations = {day: self.evaluate(day, holds) for day in search_days(self.request)}
        return curve_points(evaluations, self.request.as_of), evaluations

    def hold_advice(self, totals: dict[date, Amount]) -> tuple[HoldAdvice, ...]:
        """발주 보류 권고(8-3): 보류 곡선은 이 평가기의 메모를 쓴다."""
        return self._holds.advice(totals, self)

    def hold_impacts(self, advice: tuple[HoldAdvice, ...]) -> list[Impact]:
        return self._holds.impacts(advice)


def _key(holds: Iterable[HoldAction]) -> HoldKey:
    """보류 집합의 메모 키(발주 ID·보류 일수 순)."""
    return tuple(sorted((h.po_id, h.hold_days) for h in holds))


def _check_transport_days(params: ParamSet) -> None:
    """외자재 운송 일수(5절·6-6, 1.33.0): 운송 방식마다 transport_days.<방식>이 있어야 한다. 외자재 수요를 만나서야
    KeyError가 나지 않게 평가기를 만들 때 본다."""
    keys = (f"{TRANSPORT_GROUP}.{mode}" for mode in get_args(TransportMode))
    missing = [key for key in keys if key not in params.params]
    if missing:
        raise ValueError(
            f"파라미터 {params.version}에 외자재 운송 일수 {', '.join(missing)} 없음(docs/engine.md(비용·일정) 5절)"
        )


def _check_grade_ratios(params: ParamSet) -> None:
    """방향이 정해지지 않아 범위 없이 대표값만 두는 파라미터: 강종 단가 비율(2절), 블록 난이도 계수(4-4)."""
    for key, param in params.params.items():
        fixed = key.startswith(("steel.grade_price_ratio.", "difficulty."))
        if fixed and not param.low == param.value == param.high:
            raise ValueError(
                f"{key}: 강종 단가 비율·난이도 계수는 범위 없이 대표값만 허용(docs/engine.md(비용·일정) 2절·4-4)"
            )
