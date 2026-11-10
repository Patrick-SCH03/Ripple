"""되묻기 집합: 분할 conformal, 점수 s = 1 − p(정답)(Angelopoulos·Bates 2021)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def conformal_qhat(true_label_probs: Sequence[float], alpha: float) -> float:
    """보정 사례의 정답 확률로 q̂를 구한다. 표본이 모자라면 1.0(모든 선택지)을 돌려준다."""
    if not 0 < alpha < 1:
        raise ValueError("alpha는 0과 1 사이 값 필요")
    n = len(true_label_probs)
    rank = math.ceil((n + 1) * (1 - alpha))
    if n == 0 or rank > n:
        return 1.0
    return sorted(1 - p for p in true_label_probs)[rank - 1]


def ranked(probabilities: Mapping[str, float]) -> list[tuple[str, float]]:
    """확률 내림차순. 같으면 ID 순으로 정해 선택지 순서에 기대지 않는다."""
    return sorted(probabilities.items(), key=lambda item: (-item[1], item[0]))


def prediction_set(probabilities: Mapping[str, float], qhat: float) -> tuple[str, ...]:
    order = ranked(probabilities)
    top = order[0][0]
    return tuple(key for key, p in order if key == top or 1 - p <= qhat)
