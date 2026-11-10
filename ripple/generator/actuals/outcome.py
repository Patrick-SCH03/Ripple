"""결과: 항목·사례 결과 형식, 항목 잡음과 미반영 비용(docs/data.md(생성기) 6-1 항목)."""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date

from .common import won


@dataclass(frozen=True, slots=True)
class ActualItem:
    key: str
    family: str
    krw: int


@dataclass(frozen=True, slots=True)
class ActualOutcome:
    items: tuple[ActualItem, ...]
    unmodeled_krw: int
    total_krw: int
    exit_delay_days: dict[str, int]
    max_exit_delay_days: int
    delivery_added_days: int | None
    activity_start_dates: dict[str, date]


def noisy_items(
    raw: Mapping[tuple[str, str], float], item_rng: Callable[[str], random.Random] | None
) -> tuple[ActualItem, ...]:
    """0원이 아닌 항목(키 순서)마다 곱 잡음 lognormal(0, 0.15). item_rng(항목 키)가 없으면 잡음 없음."""
    return tuple(
        ActualItem(key, family, _noisy(key, value, item_rng))
        for (key, family), value in sorted(raw.items())
        if won(value) != 0
    )


def _noisy(key: str, value: float, item_rng: Callable[[str], random.Random] | None) -> int:
    if item_rng is None or value == 0:
        return won(value)
    return won(value * math.exp(item_rng(key).gauss(0, 0.15)))


def unmodeled_krw(rng: random.Random | None, items: tuple[ActualItem, ...]) -> int:
    """사례마다 확률 0.1로 미반영 비용 = U(0.1, 0.4) × 양수 항목 합. rng가 없으면 0."""
    if rng is None or rng.random() >= 0.1:
        return 0
    return won(rng.uniform(0.1, 0.4) * sum(item.krw for item in items if item.krw > 0))


def assemble(
    items: tuple[ActualItem, ...],
    unmodeled: int,
    delays: dict[str, int],
    delivery: int | None,
    starts: dict[str, date],
) -> ActualOutcome:
    """항목·미반영 비용·출구 지연·인도 지연·변경 일정 착수일로 사례 결과를 만든다."""
    return ActualOutcome(
        items=items,
        unmodeled_krw=unmodeled,
        total_krw=sum(i.krw for i in items) + unmodeled,
        exit_delay_days=delays,
        max_exit_delay_days=max(delays.values(), default=0),
        delivery_added_days=delivery,
        activity_start_dates=starts,
    )
