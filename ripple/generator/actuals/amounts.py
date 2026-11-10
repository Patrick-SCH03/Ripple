"""잡음 전 항목 금액: 항목 계산 모듈마다 제 몫을 돌려주고 입구가 차례로 합친다(docs/data.md(생성기) 6-1 항목)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

Raw = dict[tuple[str, str], float]
"""(항목 키, 비용 구분) → 원(반올림 전). 모듈마다 자기 몫을 defaultdict(float)에 더해 돌려준다
(항목 키 접두어 material·new_work·stock·handling·po·premium·rework·minor·ld가 모듈마다 달라 몫끼리 겹치지 않는다)."""


def merged(*parts: Mapping[tuple[str, str], float]) -> Raw:
    """모듈별 몫을 주어진 순서대로 더한다."""
    raw: Raw = defaultdict(float)
    for part in parts:
        for key, value in part.items():
            raw[key] += value
    return raw
