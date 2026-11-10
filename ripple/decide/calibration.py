"""온도 보정: softmax(z / T)의 T 하나를 음의 로그우도 최소로 맞춘다(Guo 외 2017)."""

from __future__ import annotations

import math
from collections.abc import Sequence

LabeledScores = tuple[Sequence[float], int]
"""선택지별 점수와 정답 위치."""


def softmax(scores: Sequence[float], temperature: float = 1.0) -> list[float]:
    if temperature <= 0:
        raise ValueError("온도는 0 초과 필요")
    scaled = [s / temperature for s in scores]
    peak = max(scaled)
    weights = [math.exp(s - peak) for s in scaled]
    total = sum(weights)
    return [w / total for w in weights]


def negative_log_likelihood(cases: Sequence[LabeledScores], temperature: float) -> float:
    if not cases:
        raise ValueError("보정 사례 없음")
    total = 0.0
    for scores, label in cases:
        scaled = [s / temperature for s in scores]
        peak = max(scaled)
        log_partition = peak + math.log(sum(math.exp(s - peak) for s in scaled))
        total += log_partition - scaled[label]
    return total / len(cases)


def fit_temperature(
    cases: Sequence[LabeledScores],
    lowest: float = 0.05,
    highest: float = 20.0,
    iterations: int = 80,
) -> float:
    """음의 로그우도는 β = 1/T에 대해 볼록하므로 β 구간에서 황금분할 탐색으로 최소점을 찾는다."""
    lo, hi = 1 / highest, 1 / lowest
    ratio = (math.sqrt(5) - 1) / 2

    def loss(beta: float) -> float:
        return negative_log_likelihood(cases, 1 / beta)

    left, right = hi - ratio * (hi - lo), lo + ratio * (hi - lo)
    loss_left, loss_right = loss(left), loss(right)
    for _ in range(iterations):
        if loss_left < loss_right:
            hi, right, loss_right = right, left, loss_left
            left = hi - ratio * (hi - lo)
            loss_left = loss(left)
        else:
            lo, left, loss_left = left, right, loss_right
            right = lo + ratio * (hi - lo)
            loss_right = loss(right)
    return 1 / ((lo + hi) / 2)
