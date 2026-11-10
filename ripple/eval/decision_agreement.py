"""E7 결정 일치(docs/evaluation.md): 엔진이 고른 (대안·확정일·보류) 조합
vs 숨긴 실제 모델(`ripple/generator/actuals/`) 기준 최선.

- 후보 = 엔진 최적 조합과 같은 공간(docs/engine.md(대안) 4절): 충족 대안(요청안 포함)
  × 확정일(확정 가능일 = 요청의 확정일부터 탐색 기간 끝까지의 곡선 날짜, 없으면 그날 하루)
  × 보류 집합(요청의 보류, 요청의 보류 ∪ 그 대안의 보류 권고). 대안 연산과 보류 권고는
  엔진 결과에서 가져오고, 숨긴 모델로 새 후보를 만들지 않는다.
- 고르는 순서는 엔진과 같다(`ripple/engine/alternatives/compare.py`): 대안 안에서
  (총액, 이른 확정일, 보류 수), 대안 사이에서 (총액, 요청안 먼저, 보류 수, 확정일, 대안 ID).
  엔진 대표 총액으로 고르면 엔진 권고와 같아야 한다 — 다르면 후보 공간이 엔진과 달라 멈춘다.
- 실제 최선 = 같은 순서를 숨긴 모델 총액으로. 숨긴 모델의 잡음은 확정일·보류와 무관해
  같은 세계에서 결정만 비교한다.
- 지표: 같은 조합 비율(대안·확정일·보류 행동이 모두 같음), 평균 후회 ÷ 평균 |실제 최선 총액|
  (후회 = 숨긴 총액(엔진 선택) − 숨긴 총액(실제 최선) ≥ 0; 사례별 비율의 평균은 작은 금액에서
  터져 쓰지 않음), 참고로 후회 0 비율. 기준: 같은 조합 ≥ 0.8 · 평균 후회 ≤ 실제 최선 비용의 5%
  (숨긴 모델을 만들기 전에 고정).
- 확정 가능일 조건: 기준일 · +10일 · +20일. 기준일 확정만 보면 비용이 시간에 따라 줄지 않아
  대개 '기준일·보류 없음'이 최적인 쉬운 사례라, 조건마다 따로 재고 모두 합격해야 합격.
- 평가 분할은 방법을 개발 분할로 고정한 뒤 최종 인증 때 한 번만
  (`scripts/eval_decision.py --split eval --final`).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from ripple.contracts.analysis import AnalysisRequest, HoldAction
from ripple.contracts.change import ChangeRequest
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.params import ParamSet
from ripple.contracts.result import (
    AlternativeOrigin,
    AlternativeResult,
    AnalysisResult,
    Determinacy,
    Eligibility,
)
from ripple.contracts.rulebook import RuleBook
from ripple.contracts.strength import StrengthRules
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.generator.actuals import HiddenModel
from ripple.generator.build import Generated

SAME_MIN = 0.8
REGRET_MAX = 0.05
CONFIRM_SHIFTS = (0, 10, 20)  # 확정 가능일 = 기준일 + 이 일수

ActualTotal = Callable[[ChangeRequest, date, Mapping[str, int]], int]
"""(변경, 확정일, 보류 발주 → 일수) → 실제 총액(원). 기본은 숨긴 모델(잡음 모드)."""


@dataclass(frozen=True, slots=True)
class Combo:
    """결정 하나: 대안 · 확정일 · 보류 행동((발주 ID, 일수), 발주 ID 순)."""

    alt_id: str
    is_request: bool
    confirm_on: date
    holds: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class Option:
    combo: Combo
    cost: int  # 고를 때 쓰는 총액(원): 엔진 대표값이나 숨긴 모델 총액


@dataclass(frozen=True, slots=True)
class DecisionCase:
    ecn_id: str
    earliest: date  # 확정 가능일(요청의 확정일)
    engine: Combo
    best: Combo
    engine_actual: int  # 엔진 선택의 숨긴 총액
    best_actual: int  # 실제 최선의 숨긴 총액
    meets: int  # 충족 대안 수(요청안 포함)
    uncertain: bool  # 판단 불가 줄이나 계산 불가 항목이 있음

    @property
    def same(self) -> bool:
        return self.engine == self.best

    @property
    def regret(self) -> int:
        return self.engine_actual - self.best_actual


@dataclass(frozen=True, slots=True)
class DecisionAgreement:
    cases: int
    excluded: int
    same: float | None
    regret_ratio: float | None  # 평균 후회 ÷ 평균 |실제 최선 총액|
    zero_regret: float | None  # 참고: 조합이 달라도 후회가 0인 사례 포함
    mean_regret: float | None  # 원
    with_alternatives: int  # 충족 대안이 둘 이상인 사례
    engine_held: int  # 엔진 권고에 보류가 든 사례
    best_held: int  # 실제 최선에 보류가 든 사례
    engine_later: int  # 엔진 권고 확정일이 확정 가능일보다 늦은 사례
    uncertain: int

    @property
    def passed(self) -> bool:
        return (
            self.cases > 0
            and self.same is not None
            and self.same >= SAME_MIN
            and self.regret_ratio is not None
            and self.regret_ratio <= REGRET_MAX
        )


def pick(options: Iterable[Option]) -> Option:
    """엔진과 같은 두 단계 순서로 하나를 고른다: 대안 안에서 (총액, 이른 확정일, 보류 수), 대안 사이에서
    (총액, 요청안 먼저, 보류 수, 확정일, 대안 ID)."""
    groups: dict[str, list[Option]] = defaultdict(list)
    for option in options:
        groups[option.combo.alt_id].append(option)
    if not groups:
        raise ValueError("고를 후보가 없어요")
    bests = [min(group, key=lambda o: (o.cost, o.combo.confirm_on, len(o.combo.holds))) for group in groups.values()]
    return min(
        bests,
        key=lambda o: (o.cost, not o.combo.is_request, len(o.combo.holds), o.combo.confirm_on, o.combo.alt_id),
    )


def agreement(cases: Iterable[DecisionCase], excluded: int = 0) -> DecisionAgreement:
    rows = list(cases)
    n = len(rows)
    regret = sum(c.regret for c in rows)
    base = sum(abs(c.best_actual) for c in rows)
    return DecisionAgreement(
        cases=n,
        excluded=excluded,
        same=sum(c.same for c in rows) / n if n else None,
        regret_ratio=(regret / base if base else (0.0 if regret == 0 else math.inf)) if n else None,
        zero_regret=sum(c.regret == 0 for c in rows) / n if n else None,
        mean_regret=regret / n if n else None,
        with_alternatives=sum(c.meets > 1 for c in rows),
        engine_held=sum(bool(c.engine.holds) for c in rows),
        best_held=sum(bool(c.best.holds) for c in rows),
        engine_later=sum(c.engine.confirm_on > c.earliest for c in rows),
        uncertain=sum(c.uncertain for c in rows),
    )


def hidden_total(hidden: HiddenModel, as_of: date) -> ActualTotal:
    """숨긴 모델 총액을 쓰는 실제 총액 함수."""

    def total(change: ChangeRequest, confirm_on: date, holds: Mapping[str, int]) -> int:
        return hidden.outcome(change, as_of, confirm_on, holds).total_krw

    return total


def _holds_key(holds: Iterable[HoldAction]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((h.po_id, h.hold_days) for h in holds))


_Run = Callable[[AnalysisRequest], AnalysisResult]
"""요청 → 엔진 결과(대안 없이)."""


def _alt_options(
    run: _Run,
    actual_total: ActualTotal,
    change: ChangeRequest,
    request: AnalysisRequest,
    alt: AlternativeResult,
    earliest: date,
) -> tuple[list[Option], list[Option]]:
    """충족 대안 하나의 후보(엔진 대표 총액, 숨긴 총액): 보류 집합마다 확정 가능일부터의 곡선 날짜."""
    alt_change = change.model_copy(update={"ops": alt.ops})
    alt_request = request.model_copy(update={"change": alt_change, "include_alternatives": False})
    base = run(alt_request)
    engine_options: list[Option] = []
    actual_options: list[Option] = []
    for held in _hold_sets(request.holds, base):
        days = _curve_days(run, alt_request, held, request.holds, base, earliest)
        held_map = {h.po_id: h.hold_days for h in held}
        for day, engine_cost in days:
            combo = Combo(
                alt_id=alt.alt_id,
                is_request=alt.origin is AlternativeOrigin.REQUEST,
                confirm_on=day,
                holds=_holds_key(held),
            )
            engine_options.append(Option(combo, engine_cost))
            actual_options.append(Option(combo, actual_total(alt_change, day, held_map)))
    return engine_options, actual_options


def _hold_sets(requested: tuple[HoldAction, ...], base: AnalysisResult) -> list[tuple[HoldAction, ...]]:
    """요청의 보류, 보류 권고가 있으면 요청의 보류 ∪ 권고(최대 보류 일수, 발주 ID 순)도."""
    hold_sets: list[tuple[HoldAction, ...]] = [requested]
    if base.timing.holds:
        advised = (
            *requested,
            *(HoldAction(po_id=a.po_id, hold_days=a.max_hold_days) for a in base.timing.holds),
        )
        hold_sets.append(tuple(sorted(advised, key=lambda h: h.po_id)))
    return hold_sets


def _curve_days(
    run: _Run,
    alt_request: AnalysisRequest,
    held: tuple[HoldAction, ...],
    requested: tuple[HoldAction, ...],
    base: AnalysisResult,
    earliest: date,
) -> list[tuple[date, int]]:
    """보류 집합 하나의 (확정일, 엔진 대표 총액): 확정 가능일부터의 곡선 날짜, 없으면 확정 가능일 하루."""
    curve = base.timing.curve if held == requested else run(alt_request.model_copy(update={"holds": held})).timing.curve
    days = [(p.confirm_on, p.total.value) for p in curve if p.confirm_on >= earliest]
    if not days:
        single = run(alt_request.model_copy(update={"holds": held}))
        days = [(earliest, single.total.value)]
    return days


def decision_case(
    index: GraphIndex,
    actual_total: ActualTotal,
    rulebook: RuleBook,
    params: ParamSet,
    strength: StrengthRules,
    change: ChangeRequest,
    as_of: date,
    shift: int,
    horizon_days: int = 60,
) -> DecisionCase:
    """설계변경 하나 · 확정 가능일 조건 하나의 사례. 요청이 지도와 맞지 않으면 RequestError.

    탐색 기간은 요청 기본값(60일)이고, 검사는 계산을 줄이려고 짧게 줄 수 있다(엔진도 같은 기간으로 고른다)."""
    earliest = as_of + timedelta(days=shift)
    request = AnalysisRequest(
        change=change, as_of=as_of, confirm_on=earliest, horizon_days=horizon_days, include_alternatives=True
    )
    result = analyze(index, request, rulebook, params, strength)
    recommendation = result.recommendation
    if recommendation is None:  # 대안을 켜면 요청안이 늘 충족이라 권고가 있다(계약)
        raise AssertionError(f"{change.ecn_id}: 대안을 켰는데 권고가 없어요")

    def run(alt_request: AnalysisRequest) -> AnalysisResult:
        return analyze(index, alt_request, rulebook, params)

    engine_options: list[Option] = []
    actual_options: list[Option] = []
    meets = [a for a in result.alternatives if a.eligibility.status is Eligibility.MEETS]
    for alt in meets:
        engine_part, actual_part = _alt_options(run, actual_total, change, request, alt, earliest)
        engine_options += engine_part
        actual_options += actual_part
    engine = Combo(
        alt_id=recommendation.alt_id,
        is_request=next(a.origin is AlternativeOrigin.REQUEST for a in meets if a.alt_id == recommendation.alt_id),
        confirm_on=recommendation.confirm_on,
        holds=_holds_key(recommendation.holds),
    )
    replay = pick(engine_options).combo
    if replay != engine:
        raise AssertionError(
            f"{change.ecn_id}(+{shift}일): 후보 공간이 엔진과 달라요 — 다시 고른 것 {replay}, 권고 {engine}"
        )
    actual = {option.combo: option.cost for option in actual_options}
    best = pick(actual_options)
    return DecisionCase(
        ecn_id=change.ecn_id,
        earliest=earliest,
        engine=engine,
        best=best.combo,
        engine_actual=actual[engine],
        best_actual=best.cost,
        meets=len(meets),
        uncertain=bool(result.unresolved)
        or any(line.determinacy is not Determinacy.KNOWN for line in result.cost_lines),
    )


def decision_cases(
    generated: Generated,
    actual_total: ActualTotal,
    rulebook: RuleBook,
    params: ParamSet,
    strength: StrengthRules,
    split: EcnSplit,
    as_of: date,
    shift: int,
    limit: int | None = None,
) -> tuple[list[DecisionCase], int]:
    """분할의 설계변경마다 한 확정 가능일 조건의 사례. ECN 번호 순, limit이면 앞에서 그만큼만. (사례, 제외 수)."""
    index = GraphIndex(generated.snapshot)
    ecns = sorted((e for e in generated.ecns if e.split is split), key=lambda e: e.change.ecn_id)[:limit]
    cases: list[DecisionCase] = []
    excluded = 0
    for ecn in ecns:
        try:
            cases.append(decision_case(index, actual_total, rulebook, params, strength, ecn.change, as_of, shift))
        except RequestError:
            excluded += 1
    return cases, excluded
