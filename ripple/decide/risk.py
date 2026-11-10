"""자동 진행 문턱 선택(Learn then Test, Angelopoulos 외 2021)과 이항 신뢰하한."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TopOutcome:
    """보정된 최상위 확률 하나와 그 결과."""

    top_prob: float
    correct: bool
    eligible: bool  # 최상위가 '해당 없음'이 아님(자동 진행 후보)


def binomial_cdf(k: int, n: int, p: float) -> float:
    """P(Binom(n, p) ≤ k). 로그 공간에서 더해 큰 n에서도 안정적이다."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    logs = [
        math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * math.log(p) + (n - i) * math.log1p(-p)
        for i in range(k + 1)
    ]
    peak = max(logs)
    return min(1.0, math.exp(peak) * sum(math.exp(v - peak) for v in logs))


def auto_predicate(eligible: bool, top_prob: float, threshold: float | None) -> bool:
    """자동 진행 술어: '해당 없음'이 아니고 p(최상위) ≥ 문턱.

    τ 검정, 되묻기 집합 보정, 라우터가 모두 이 정의 하나를 쓴다(검정 집단 = 실제 자동 진행 집단).
    """
    return threshold is not None and eligible and top_prob >= threshold


def auto_selected(outcomes: Sequence[TopOutcome], threshold: float) -> list[TopOutcome]:
    return [o for o in outcomes if auto_predicate(o.eligible, o.top_prob, threshold)]


def threshold_grid(confidences: Sequence[float], coverage_levels: Sequence[float]) -> tuple[float, ...]:
    """검정할 문턱 목록(내림차순). 신뢰도 상위 비율 c마다 그 경계값을 문턱으로 삼는다.

    신뢰도는 τ 분할과 독립인 자료(온도 분할)에서 와야 검정 순서가 τ 분할 결과에 기대지 않는다.
    상위 구간부터 검정하므로 첫 검정부터 표본이 충분하다.
    """
    ordered = sorted(confidences, reverse=True)
    if not ordered:
        return ()
    grid: list[float] = []
    for level in sorted(coverage_levels):
        threshold = ordered[min(len(ordered), max(1, math.ceil(level * len(ordered)))) - 1]
        if not grid or threshold < grid[-1]:
            grid.append(threshold)
    return tuple(grid)


def ltt_threshold(
    outcomes: Sequence[TopOutcome],
    grid: Sequence[float],
    epsilon: float,
    delta: float,
) -> float | None:
    """내림차순 문턱을 차례로 검정해 '자동 진행 건 오류율 ≤ ε'을 신뢰도 1 − δ로 보장하는 가장 낮은 문턱.

    각 문턱의 귀무가설 '오류율 > ε'을 이항 꼬리 p값 P(Binom(m, ε) ≤ k) ≤ δ로 기각한다.
    처음으로 기각하지 못한 문턱에서 멈춘다(고정 순서 검정). 하나도 기각하지 못하면 None.
    """
    chosen: float | None = None
    for threshold in grid:
        selected = auto_selected(outcomes, threshold)
        errors = sum(not o.correct for o in selected)
        p_value = binomial_cdf(errors, len(selected), epsilon) if selected else 1.0
        if p_value > delta:
            break
        chosen = threshold
    return chosen


def clopper_pearson_lower(successes: int, n: int, confidence: float = 0.95) -> float:
    """성공률의 단측 Clopper–Pearson 하한 L: P(Binom(n, L) ≥ successes) = 1 − confidence."""
    if not 0 <= successes <= n:
        raise ValueError("성공 수는 0 이상 n 이하 필요")
    if successes == 0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if binomial_cdf(successes - 1, n, mid) > confidence:
            lo = mid
        else:
            hi = mid
    return lo
