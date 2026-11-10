"""E2a 비용 정확도 도구의 성질(ripple/eval/cost_accuracy.py): 손으로 센 지표·참고 지표 · 경계 · 기준 판정 · 결정성.

전체 개발 분할 측정은 `scripts/eval_cost.py`(시간이 걸려 여기서는 앞 12건으로 결정성만 본다).
"""

from __future__ import annotations

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook, load_strength
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.dataset import EcnSplit
from ripple.eval.cost_accuracy import CostAccuracy, CostPair, accuracy, cost_pairs, p90
from ripple.generator.actuals import HiddenModel
from ripple.generator.build import generate
from ripple.generator.io import load_config


def _pair(
    estimate: int,
    actual: int,
    *,
    uncertain: bool = False,
    unmodeled: bool = False,
    low: int | None = None,
    high: int | None = None,
) -> CostPair:
    return CostPair(
        ecn_id="E",
        estimate=estimate,
        actual=actual,
        uncertain=uncertain,
        unmodeled=unmodeled,
        low=estimate if low is None else low,
        high=estimate if high is None else high,
    )


def _summary(median: float | None, p90_: float | None, small_within: float | None) -> CostAccuracy:
    """기준 판정만 보려고 지표를 직접 넣은 요약(큰 사례·작은 사례가 없으면 None)."""
    return CostAccuracy(
        cases=1,
        excluded=0,
        big=0 if median is None else 1,
        ape_median=median,
        ape_p90=p90_,
        small=0 if small_within is None else 1,
        small_within=small_within,
        uncertain=0,
        unmodeled=0,
        bias_median=None,
        in_range=None,
    )


def run(c: Checker) -> None:
    c.section("E2a 비용 정확도 도구(손으로 센 지표·경계·기준·결정성)")
    # 큰 사례 3건: 오차 10% · 20% · 50%(음수 실제값은 절댓값 기준), 작은 사례 2건: 오차 40만원 · 60만원
    # 엔진 범위: 1번(90만~120만)과 3번(−350만~−190만)만 실제를 품는다
    rows = [
        _pair(1_100_000, 1_000_000, low=900_000, high=1_200_000),
        _pair(2_400_000, 2_000_000, uncertain=True),
        _pair(-3_000_000, -2_000_000, unmodeled=True, low=-3_500_000, high=-1_900_000),
        _pair(900_000, 500_000),
        _pair(0, 600_000),
    ]
    got = accuracy(rows, excluded=1)
    c.check(
        "100만원 이상은 백분율 오차(중앙값 20%·90백분위 44%), 미만은 50만원 이내 비율(1/2), 제외·판단 불가·미반영 수",
        got.cases == 5
        and got.excluded == 1
        and got.big == 3
        and abs((got.ape_median or 0) - 0.2) < 1e-12
        and abs((got.ape_p90 or 0) - 0.44) < 1e-12
        and got.small == 2
        and got.small_within == 0.5
        and got.uncertain == 1
        and got.unmodeled == 1
        and not got.passed,
        got,
    )
    c.check(
        "참고 지표: 큰 사례 부호 있는 오차 중앙값 +10%(+10%·+20%·−50%), 엔진 범위 안 2/5(양 끝 포함), 사례 없으면 없음",
        abs((got.bias_median or 0) - 0.1) < 1e-12
        and got.in_range == 0.4
        and accuracy([_pair(5, 7, low=7, high=9), _pair(5, 3, low=1, high=3)]).in_range == 1.0
        and accuracy([]).bias_median is None
        and accuracy([]).in_range is None,
        got,
    )
    edge = accuracy([_pair(1_500_000, 1_000_000), _pair(999_999 + 500_000, 999_999)])
    c.check(
        "경계: 실제 100만원은 '이상'(백분율), 99만9,999원은 '미만'(오차 50만원 = 이내)",
        edge.big == 1 and edge.small == 1 and edge.small_within == 1.0,
        edge,
    )
    good = accuracy([_pair(1_200_000, 1_000_000) for _ in range(9)] + [_pair(1_000_000, 1_000_000)])
    c.check(
        "기준: 중앙값 ≤ 25% · 90백분위 ≤ 60% · 50만원 이내 ≥ 90%면 합격, 사례가 없으면 불합격",
        good.passed and not accuracy([]).passed and p90([0.3]) == 0.3,
        good,
    )
    # 중앙값만 어김(30% × 3), 90백분위만 어김(10% × 8 + 100% × 2 → 90백분위 100%)
    median_only = accuracy([_pair(1_300_000, 1_000_000) for _ in range(3)])
    p90_only = accuracy([_pair(1_100_000, 1_000_000) for _ in range(8)] + [_pair(2_000_000, 1_000_000)] * 2)
    c.check(
        "기준 경계: 중앙값 25%·90백분위 60%·50만원 이내 90%는 합격, 바로 바깥·큰 사례 기준 하나만 어김은 미달",
        _summary(0.25, 0.60, 0.90).passed
        and not _summary(0.2500001, 0.60, 0.90).passed
        and not _summary(0.25, 0.6000001, 0.90).passed
        and not _summary(0.25, 0.60, 0.8999999).passed
        and _summary(0.25, 0.60, None).passed
        and _summary(None, None, 0.95).passed
        and not median_only.passed
        and median_only.ape_p90 is not None
        and median_only.ape_p90 <= 0.60
        and not p90_only.passed
        and p90_only.ape_median is not None
        and p90_only.ape_median <= 0.25,
        (median_only, p90_only),
    )
    config = load_config()
    generated = generate(config)
    settings = Settings.from_env({})
    hidden = HiddenModel(generated, PROJECT_ROOT / "params" / "cost_v1.yaml")
    rulebook, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    strength = load_strength(settings.strength_path)
    first = cost_pairs(generated, hidden, rulebook, params, strength, EcnSplit.DEV, config.scenario_date, limit=12)
    second = cost_pairs(generated, hidden, rulebook, params, strength, EcnSplit.DEV, config.scenario_date, limit=12)
    c.check(
        "개발 분할 앞 12건: 두 번 재도 같은 사례·금액(고정 시드), 제외 + 사례 = 12, ECN 번호 순, 최소 ≤ 대표 ≤ 최대",
        first == second
        and len(first[0]) + first[1] == 12
        and [p.ecn_id for p in first[0]] == sorted(p.ecn_id for p in first[0])
        and all(p.low <= p.estimate <= p.high for p in first[0]),
    )
