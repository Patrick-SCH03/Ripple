"""새 규격 자재 리드타임: 판 실제 입고 지연 분위수 표와 뽑기(docs/data.md(생성기) 6-1 새 규격 리드타임)."""

from __future__ import annotations

import random
from itertools import pairwise

from .common import won

PLATE_DELAY_DAYS: tuple[tuple[float, int], ...] = (
    (0.0, -45),
    (0.01, -45),
    (0.05, -24),
    (0.10, -18),
    (0.15, -15),
    (0.20, -12),
    (0.25, -9),
    (0.30, -6),
    (0.35, -4),
    (0.40, -2),
    (0.45, 1),
    (0.50, 2),
    (0.55, 3),
    (0.60, 4),
    (0.65, 5),
    (0.70, 6),
    (0.75, 7),
    (0.80, 9),
    (0.85, 11),
    (0.90, 14),
    (0.95, 16),
    (0.99, 22),
    (1.0, 22),
)
"""판 새 규격 자재의 실제 입고 지연(일) 분위수(actuals-v2): 비공개 현업 강재 재고 집계
판 입고일 − 계약납기일의 1·5·10·…·95·99백분위(1백분위 아래·99백분위 위는 끝값).
사이는 선형 보간 뒤 반올림한다(docs/data.md(생성기) 6-1)."""


def quantile_days(table: tuple[tuple[float, int], ...], u: float) -> int:
    """분위수 표(누적 확률 오름차순, 0과 1 포함)에서 확률 u의 일수: 사이는 선형 보간 뒤 반올림(0.5는 0에서 먼 쪽)."""
    for (q0, d0), (q1, d1) in pairwise(table):
        if u <= q1:
            return won(d0 + (d1 - d0) * (u - q0) / (q1 - q0)) if q1 > q0 else d1
    return table[-1][1]


def drawn_lead_days(rng: random.Random, category: str, lead: int) -> int:
    """판은 리드타임 + 실제 입고 지연 분위수(PLATE_DELAY_DAYS), 그 밖은 리드타임 × U(0.9, 1.2)(가정 — 형강 입고 지연은
    집계 분포가 둘로 갈려 쓰지 않음)."""
    if category == "plate":
        return lead + quantile_days(PLATE_DELAY_DAYS, rng.random())
    return round(lead * rng.uniform(0.9, 1.2))
