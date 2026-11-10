"""E2' 일정 정확도(docs/evaluation.md): 엔진 일정 지연 vs 숨긴 실제 모델(`ripple/generator/actuals/`) 지연.

- 비교 값 두 가지: 구역 출구 최대 지연(일)과 늘어난 인도 지연(일, 엔진·숨긴 모델 모두 계산된
  사례만 — 경계 조건이 없는 출구가 늦어지면 둘 다 계산하지 않는다).
- 비교 값마다: 평균 절대 오차(일) · 오차 7일 이상 사례 비율 · 지연 발생(> 0) 여부의 오경보율
  (실제 0인 사례 중 엔진 > 0)과 누락률(실제 > 0인 사례 중 엔진 0). 기준: 평균 절대 오차 ≤ 2일 ·
  7일 이상 ≤ 5% · 오경보율·누락률 각 ≤ 10%(숨긴 모델을 만들기 전에 고정한 값). 두 비교 값 모두
  충족해야 합격이고, 분모가 0인 지표는 따지지 않는다.
- 조건: E2a(`cost_accuracy.py`)와 같다 — 확정일 = 기준일, 보류 없음, 대안 끔, 숨긴 모델 잡음
  모드. 요청이 지도와 맞지 않는 사례(RequestError)는 '제외'로 세고, 판단 불가 줄·계산 불가가 있는
  사례는 포함하되 따로 센다.
- 평가 분할은 방법을 개발 분할로 고정한 뒤 최종 인증 때 한 번만
  (`scripts/eval_schedule.py --split eval --final`).
- 참고(합격과 무관): 일정 위험(docs/engine.md(비용·일정) 6-6)의 구역 출구 최대 지연이 실제 지연을 얼마나 덮는지.
  숨긴 모델의 리드타임 변동은 판만 실제 입고 지연 분포(actuals-v2)이고 그 밖은 우리가 정한 범위라 참고로만 본다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.params import ParamSet
from ripple.contracts.result import Determinacy
from ripple.contracts.rulebook import RuleBook
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.generator.actuals import HiddenModel
from ripple.generator.build import Generated

MAE_MAX = 2.0  # 평균 절대 오차(일)
LARGE_DAYS = 7  # 이 이상 틀리면 '크게 틀림'
LARGE_SHARE_MAX = 0.05
FALSE_ALARM_MAX = 0.10
MISS_MAX = 0.10


@dataclass(frozen=True, slots=True)
class DelayPair:
    """한 사례: 엔진과 숨긴 모델의 구역 출구 최대 지연·늘어난 인도 지연(일, 계산하지 않았으면 None)."""

    ecn_id: str
    exit_estimate: int
    exit_actual: int
    delivery_estimate: int | None
    delivery_actual: int | None
    uncertain: bool  # 판단 불가 줄이나 계산 불가 항목이 있음
    exit_risk: int | None = None  # 일정 위험의 구역 출구 최대 지연(위험이 없는 결과면 None)


@dataclass(frozen=True, slots=True)
class DelayAccuracy:
    """비교 값 하나의 지표(사례가 없거나 분모가 0이면 None)."""

    cases: int
    delayed: int  # 실제로 지연이 생긴(> 0) 사례
    mae: float | None
    large_share: float | None
    false_alarm: float | None
    miss: float | None

    @property
    def passed(self) -> bool:
        return (
            (self.mae is None or self.mae <= MAE_MAX)
            and (self.large_share is None or self.large_share <= LARGE_SHARE_MAX)
            and (self.false_alarm is None or self.false_alarm <= FALSE_ALARM_MAX)
            and (self.miss is None or self.miss <= MISS_MAX)
        )


@dataclass(frozen=True, slots=True)
class ScheduleAccuracy:
    cases: int
    excluded: int
    uncertain: int
    exit: DelayAccuracy  # 구역 출구 최대 지연
    delivery: DelayAccuracy  # 늘어난 인도 지연(둘 다 계산된 사례만)

    @property
    def passed(self) -> bool:
        """두 비교 값 모두 기준 충족(인도 지연을 계산한 사례가 없으면 그쪽은 따지지 않음)."""
        return self.cases > 0 and self.exit.passed and self.delivery.passed


@dataclass(frozen=True, slots=True)
class RiskReference:
    """일정 위험 참고(합격과 무관): 실제 지연 사례 중 위험 > 0 · 실제 0인 사례 중 위험 > 0 · 실제 ≤ 위험."""

    cases: int  # 위험이 있는 사례
    delayed: int  # 실제 출구 지연 > 0
    delayed_flagged: int  # 그중 위험 > 0
    on_time: int  # 실제 0
    on_time_flagged: int  # 그중 위험 > 0
    covered: int  # 실제 ≤ 위험


def risk_reference(pairs: Iterable[DelayPair]) -> RiskReference:
    rows = [(p.exit_actual, p.exit_risk) for p in pairs if p.exit_risk is not None]
    return RiskReference(
        cases=len(rows),
        delayed=sum(actual > 0 for actual, _ in rows),
        delayed_flagged=sum(actual > 0 and risk > 0 for actual, risk in rows),
        on_time=sum(actual <= 0 for actual, _ in rows),
        on_time_flagged=sum(actual <= 0 and risk > 0 for actual, risk in rows),
        covered=sum(actual <= risk for actual, risk in rows),
    )


def delay_accuracy(pairs: Iterable[tuple[int, int]]) -> DelayAccuracy:
    """(엔진, 실제) 일수 쌍으로 비교 값 하나의 지표."""
    rows = list(pairs)
    errors = [abs(estimate - actual) for estimate, actual in rows]
    on_time = [estimate for estimate, actual in rows if actual <= 0]
    delayed = [estimate for estimate, actual in rows if actual > 0]
    return DelayAccuracy(
        cases=len(rows),
        delayed=len(delayed),
        mae=sum(errors) / len(errors) if errors else None,
        large_share=sum(e >= LARGE_DAYS for e in errors) / len(errors) if errors else None,
        false_alarm=sum(e > 0 for e in on_time) / len(on_time) if on_time else None,
        miss=sum(e <= 0 for e in delayed) / len(delayed) if delayed else None,
    )


def accuracy(pairs: Iterable[DelayPair], excluded: int = 0) -> ScheduleAccuracy:
    rows = list(pairs)
    return ScheduleAccuracy(
        cases=len(rows),
        excluded=excluded,
        uncertain=sum(p.uncertain for p in rows),
        exit=delay_accuracy((p.exit_estimate, p.exit_actual) for p in rows),
        delivery=delay_accuracy(
            (p.delivery_estimate, p.delivery_actual)
            for p in rows
            if p.delivery_estimate is not None and p.delivery_actual is not None
        ),
    )


def delay_pairs(
    generated: Generated,
    hidden: HiddenModel,
    rulebook: RuleBook,
    params: ParamSet,
    split: EcnSplit,
    as_of: date,
    limit: int | None = None,
) -> tuple[list[DelayPair], int]:
    """분할의 설계변경마다 (엔진, 숨긴 모델) 지연. ECN 번호 순, limit이면 앞에서 그만큼만. (사례, 제외 수)."""
    index = GraphIndex(generated.snapshot)
    ecns = sorted((e for e in generated.ecns if e.split is split), key=lambda e: e.change.ecn_id)[:limit]
    pairs: list[DelayPair] = []
    excluded = 0
    for ecn in ecns:
        try:
            result = analyze(index, AnalysisRequest(change=ecn.change, as_of=as_of), rulebook, params)
        except RequestError:
            excluded += 1
            continue
        actual = hidden.outcome(ecn.change, as_of, as_of)
        delivery = result.schedule.delivery
        risk = result.schedule.risk
        pairs.append(
            DelayPair(
                ecn_id=ecn.change.ecn_id,
                exit_estimate=result.schedule.max_exit_delay_days,
                exit_actual=actual.max_exit_delay_days,
                delivery_estimate=None if delivery is None else delivery.added_delay_days,
                delivery_actual=actual.delivery_added_days,
                uncertain=bool(result.unresolved)
                or any(line.determinacy is not Determinacy.KNOWN for line in result.cost_lines),
                exit_risk=None if risk is None else risk.max_exit_delay_days,
            )
        )
    return pairs, excluded
