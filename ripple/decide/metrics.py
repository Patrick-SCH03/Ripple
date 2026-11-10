"""판단 계층 지표(합격 기준 E8)."""

from __future__ import annotations

from collections.abc import Sequence


def expected_calibration_error(top_probs: Sequence[float], correct: Sequence[bool], bins: int = 15) -> float:
    """최상위 확률을 같은 폭 구간으로 나눠 |정확도 − 평균 확률|을 표본 비율로 가중 평균한다."""
    if len(top_probs) != len(correct) or not top_probs:
        raise ValueError("확률·정답 여부 길이 불일치 또는 빈 값")
    totals = [0] * bins
    hits = [0] * bins
    mass = [0.0] * bins
    for p, ok in zip(top_probs, correct, strict=True):
        index = min(int(p * bins), bins - 1)
        totals[index] += 1
        hits[index] += ok
        mass[index] += p
    n = len(top_probs)
    return sum(abs(hits[i] - mass[i]) / n for i in range(bins) if totals[i])


def coverage(sets: Sequence[Sequence[str]], labels: Sequence[str]) -> float:
    if len(sets) != len(labels) or not sets:
        raise ValueError("집합·정답 길이 불일치 또는 빈 값")
    return sum(label in chosen for chosen, label in zip(sets, labels, strict=True)) / len(sets)
