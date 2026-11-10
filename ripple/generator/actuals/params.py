"""참값 시드: 참 파라미터 표본(삼각분포)과 사례 시드(docs/data.md(생성기) 6-1 참 파라미터·시드)."""

from __future__ import annotations

import math
import random

from ripple.contracts.change import ChangeRequest
from ripple.contracts.params import ParamSet

from ..rng import sub_rng

GROUPED = ("po_cancel_ratio", "rework_multiplier")
"""묶음마다 분위수 하나를 같이 써 단계 순서대로 줄지 않게 하는 파라미터 묶음."""


def sample_params(params: ParamSet, seed: int, *, fixed: bool) -> dict[str, float]:
    """키마다 삼각분포(최소, 대표값, 최대)에서 하나. 고정(fixed)이거나 범위가 없으면 대표값."""
    sampled: dict[str, float] = {}
    group_u = {name: sub_rng(seed, "actuals", "param", name).random() for name in GROUPED}
    for key, param in params.params.items():
        if fixed or param.low == param.high:
            sampled[key] = param.value
            continue
        group = key.split(".", 1)[0]
        u = group_u[group] if group in group_u else sub_rng(seed, "actuals", "param", key).random()
        width = param.high - param.low
        peak = (param.value - param.low) / width
        sampled[key] = (
            param.low + math.sqrt(u * width * (param.value - param.low))
            if u < peak
            else param.high - math.sqrt((1 - u) * width * (param.high - param.value))
        )
    return sampled


def case_rng(seed: int, change: ChangeRequest, *names: str) -> random.Random:
    """사례(설계변경)의 참값 시드: 확정일·보류와 무관하다(같은 세계에서 결정만 바꿔 비교할 수 있게, E7)."""
    return sub_rng(seed, "actuals", "case", change.ecn_id, *names)
