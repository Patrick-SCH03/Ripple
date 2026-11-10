"""로컬 점수기: 선택지별 특징의 조건부 로지스틱(docs/input.md(판단 계층) 3절 2). 순수 파이썬, 결정적.

점수(선택지) = Σ w[특징 이름] × 값. 질문 안 선택지끼리 softmax를 하면 확률이다(온도 보정은 따로).
학습은 L2 정규화한 평균 음의 로그우도를 전체 배치 Adam으로 줄인다. 반복 수가 고정이라 같은 자료면
같은 가중치가 나온다.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .calibration import softmax

Features = Mapping[str, float]


@dataclass(frozen=True, slots=True)
class Example:
    """학습 사례 하나: 질문의 선택지와 선택지별 특징, 정답."""

    options: tuple[str, ...]
    features: tuple[Features, ...]  # options와 같은 순서
    label: str

    def __post_init__(self) -> None:
        if len(self.options) != len(self.features) or self.label not in self.options:
            raise ValueError("선택지·특징 개수 불일치 또는 정답이 선택지에 없음")


def score(weights: Mapping[str, float], features: Features) -> float:
    return sum(weights.get(name, 0.0) * value for name, value in features.items())


def scores(weights: Mapping[str, float], options: Sequence[str], features: Sequence[Features]) -> dict[str, float]:
    return {option: score(weights, f) for option, f in zip(options, features, strict=True)}


def train(
    examples: Sequence[Example],
    l2: float = 1e-3,
    iterations: int = 300,
    learning_rate: float = 0.1,
) -> dict[str, float]:
    """가중치(특징 이름 → 값, 이름 순). 사례가 없으면 빈 가중치."""
    if not examples:
        return {}
    names = sorted({name for ex in examples for f in ex.features for name in f})
    index = {name: i for i, name in enumerate(names)}
    compiled = [
        (
            [[(index[k], v) for k, v in f.items() if v] for f in ex.features],
            ex.options.index(ex.label),
        )
        for ex in examples
    ]
    size = len(names)
    w = [0.0] * size
    m = [0.0] * size
    v = [0.0] * size
    beta1, beta2, eps = 0.9, 0.999, 1e-8
    n = len(compiled)
    for step in range(1, iterations + 1):
        grad = [l2 * wi for wi in w]
        for options, label in compiled:
            logits = [sum(w[i] * x for i, x in option) for option in options]
            probs = softmax(logits)
            for p, option in zip(probs, options, strict=True):
                if p < 1e-12:
                    continue
                for i, x in option:
                    grad[i] += p * x / n
            for i, x in options[label]:
                grad[i] -= x / n
        for i in range(size):
            m[i] = beta1 * m[i] + (1 - beta1) * grad[i]
            v[i] = beta2 * v[i] + (1 - beta2) * grad[i] * grad[i]
            m_hat = m[i] / (1 - beta1**step)
            v_hat = v[i] / (1 - beta2**step)
            w[i] -= learning_rate * m_hat / (math.sqrt(v_hat) + eps)
    return {name: round(w[i], 6) for i, name in enumerate(names)}


def mean_log_loss(weights: Mapping[str, float], examples: Sequence[Example]) -> float:
    if not examples:
        raise ValueError("사례 없음")
    total = 0.0
    for ex in examples:
        probs = softmax([score(weights, f) for f in ex.features])
        total -= math.log(max(probs[ex.options.index(ex.label)], 1e-300))
    return total / len(examples)
