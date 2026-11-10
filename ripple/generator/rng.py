"""시드에서 구성 요소별 난수원을 만든다.

한 구성 요소의 생성 방식을 바꿔도 다른 구성 요소의 결과가 바뀌지 않도록, 구성 요소마다
(시드, 이름) 해시로 독립된 random.Random을 쓴다.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Mapping

from .config import Span


def sub_rng(seed: int, *names: str) -> random.Random:
    digest = hashlib.sha256("|".join((str(seed), *names)).encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def uniform(rng: random.Random, span: Span) -> float:
    return rng.uniform(span.lo, span.hi)


def integer(rng: random.Random, span: Span) -> int:
    return rng.randint(math.ceil(span.lo), math.floor(span.hi))


def step(rng: random.Random, span: Span, unit: float) -> float:
    """span 안에서 unit 단위 값 하나."""
    steps = round((span.hi - span.lo) / unit)
    return round(span.lo + unit * rng.randint(0, steps), 6)


def weighted[K: str](rng: random.Random, weights: Mapping[K, float]) -> K:
    keys = sorted(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]
