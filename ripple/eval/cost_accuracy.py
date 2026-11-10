"""E2a 비용 정확도(docs/evaluation.md): 엔진 대표 총액 vs 숨긴 실제 모델(`ripple/generator/actuals/`) 총액.

- 실제 총액의 절댓값이 100만원 이상인 사례 = 절대 백분율 오차의 중앙값·90백분위,
  미만인 사례 = 절대 오차가 50만원 이내인 비율.
  기준: 중앙값 ≤ 25% · 90백분위 ≤ 60% · 50만원 이내 ≥ 90%(숨긴 모델을 만들기 전에 고정한 값).
- 조건: 확정일 = 기준일, 보류 없음(생성기 시나리오 날짜). 숨긴 모델은 잡음 모드(참 파라미터·항목 잡음·미반영 비용).
- 요청이 지도와 맞지 않는 사례(RequestError)는 '제외'로 세고, 판단 불가 줄·계산 불가가 있는 사례와 미반영 비용이
  생긴 사례는 포함하되 따로 센다(어디서 오차가 나는지 보이게).
- 평가 분할은 방법을 개발 분할로 고정한 뒤 최종 인증 때 한 번만 잰다(`scripts/eval_cost.py --split eval --final`).
- 참고 지표(기준 아님): 큰 사례의 부호 있는 오차 중앙값(+ = 과대 추정)과 실제 총액이 엔진 범위(최소~최대) 안에 든 비율.
  숨긴 모델은 시드마다 참 파라미터를 한 번 뽑으므로(`HiddenModel._sample_params`) 한 시드의 합격은 한 '세계'의
  결과다 — 다른 시드(`scripts/eval_cost.py --seeds …`, 개발 분할만)는 지도·일정·발주·설계변경까지 합성 세계
  전체를 다시 만든다. 원인 분리는 `scripts/eval_factors.py`(요인을 하나씩 고정).
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.params import ParamSet
from ripple.contracts.result import Determinacy
from ripple.contracts.rulebook import RuleBook
from ripple.contracts.strength import StrengthRules
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.generator.actuals import HiddenModel
from ripple.generator.build import Generated

BIG_KRW = 1_000_000  # 이 이상은 백분율 오차, 미만은 절대 오차
SMALL_TOLERANCE_KRW = 500_000
MEDIAN_MAX = 0.25
P90_MAX = 0.60
SMALL_SHARE_MIN = 0.90


@dataclass(frozen=True, slots=True)
class CostPair:
    """한 사례: 엔진 대표 총액과 숨긴 모델 실제 총액(원)."""

    ecn_id: str
    estimate: int
    actual: int
    uncertain: bool  # 판단 불가 줄이나 계산 불가 항목이 있음
    unmodeled: bool  # 숨긴 모델에 엔진이 모르는 미반영 비용이 생김
    low: int  # 엔진 범위(파라미터 범위 양 끝으로 계산한 총액)
    high: int


@dataclass(frozen=True, slots=True)
class CostAccuracy:
    cases: int
    excluded: int
    big: int
    ape_median: float | None
    ape_p90: float | None
    small: int
    small_within: float | None
    uncertain: int
    unmodeled: int
    bias_median: float | None  # 참고: 큰 사례의 (엔진 − 실제) / |실제| 중앙값
    in_range: float | None  # 참고: 실제 총액이 엔진 최소~최대 안에 든 비율

    @property
    def passed(self) -> bool:
        """기준을 모두 만족하는가(해당 사례가 없는 쪽은 따지지 않음)."""
        big_ok = self.ape_median is None or (
            self.ape_median <= MEDIAN_MAX and self.ape_p90 is not None and self.ape_p90 <= P90_MAX
        )
        small_ok = self.small_within is None or self.small_within >= SMALL_SHARE_MIN
        return self.cases > 0 and big_ok and small_ok


def p90(values: list[float]) -> float:
    """90백분위(선형 보간, 양 끝 포함 — statistics.quantiles method='inclusive'). 값이 하나면 그 값."""
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=10, method="inclusive")[-1]


def accuracy(pairs: Iterable[CostPair], excluded: int = 0) -> CostAccuracy:
    rows = list(pairs)
    big = [abs(p.estimate - p.actual) / abs(p.actual) for p in rows if abs(p.actual) >= BIG_KRW]
    signed = [(p.estimate - p.actual) / abs(p.actual) for p in rows if abs(p.actual) >= BIG_KRW]
    small = [abs(p.estimate - p.actual) for p in rows if abs(p.actual) < BIG_KRW]
    return CostAccuracy(
        cases=len(rows),
        excluded=excluded,
        big=len(big),
        ape_median=statistics.median(big) if big else None,
        ape_p90=p90(big) if big else None,
        small=len(small),
        small_within=sum(d <= SMALL_TOLERANCE_KRW for d in small) / len(small) if small else None,
        uncertain=sum(p.uncertain for p in rows),
        unmodeled=sum(p.unmodeled for p in rows),
        bias_median=statistics.median(signed) if signed else None,
        in_range=sum(p.low <= p.actual <= p.high for p in rows) / len(rows) if rows else None,
    )


def cost_pairs(
    generated: Generated,
    hidden: HiddenModel,
    rulebook: RuleBook,
    params: ParamSet,
    strength: StrengthRules,
    split: EcnSplit,
    as_of: date,
    limit: int | None = None,
) -> tuple[list[CostPair], int]:
    """분할의 설계변경마다 (엔진 대표 총액, 숨긴 모델 총액). ECN 번호 순, limit이면 앞에서 그만큼만. (사례, 제외 수)."""
    index = GraphIndex(generated.snapshot)
    ecns = sorted((e for e in generated.ecns if e.split is split), key=lambda e: e.change.ecn_id)[:limit]
    pairs: list[CostPair] = []
    excluded = 0
    for ecn in ecns:
        request = AnalysisRequest(change=ecn.change, as_of=as_of)
        try:
            result = analyze(index, request, rulebook, params, strength)
        except RequestError:
            excluded += 1
            continue
        actual = hidden.outcome(ecn.change, as_of, as_of)
        uncertain = bool(result.unresolved) or any(
            line.determinacy is not Determinacy.KNOWN for line in result.cost_lines
        )
        pairs.append(
            CostPair(
                ecn_id=ecn.change.ecn_id,
                estimate=result.total.value,
                actual=actual.total_krw,
                uncertain=uncertain,
                unmodeled=actual.unmodeled_krw > 0,
                low=result.total.low,
                high=result.total.high,
            )
        )
    return pairs, excluded
