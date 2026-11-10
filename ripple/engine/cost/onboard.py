"""의장품 선상 설치 할증(docs/engine.md(비용·일정) 4-1-3, 비용 항목 C-03)과 선상 설치 일수(6-3).

선상 설치 수요(어느 수요가 배 위로 가는지)는 일정이 정하고(ripple/engine/onboard.py), 여기서는 블록마다
할증 줄 하나와 설치 일수 d_on을 낸다. 정상 설치 공수는 원래 계획에 있으므로 선상에서 더 드는 몫(배수 − 1)만
비용에 넣는다.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from ripple.contracts.result import CostItem, CostLine

from .amounts import Scenario, amount_of, hours_of
from .demand import Demand
from .inputs import CostInput, qty_text
from .rework import CREW, part_weight

ITEM = "C-03"
KIND = "onboard"
RATIO = "outfitting.on_board_ratio"
WORK = "base_work_hours_per_t.pre_outfitting"
CATEGORIES = frozenset({"pipe", "valve", "fitting"})
"""선상에서 설치할 수 있는 의장품 분류. 장비는 반입·설치 공간 문제로 뺀다(6-3)."""


@dataclass(frozen=True, slots=True)
class OnboardBlock:
    """블록 하나의 선상 설치: 수요(부재 ID 순), 선상 설치 일수, 탑재 공정."""

    demands: tuple[Demand, ...]
    days: int
    erection: str


@dataclass(frozen=True, slots=True)
class Onboard:
    lines: tuple[CostLine, ...]  # 줄 ID 순
    blocks: Mapping[str, OnboardBlock]


def onboard_cost(inp: CostInput, chosen: Mapping[str, tuple[tuple[Demand, ...], str]]) -> Onboard:
    """chosen = 블록 → (선상 설치 수요, 탑재 공정). 블록마다 할증 줄과 d_on(대표값, 최소 1일)."""
    lines: list[CostLine] = []
    blocks: dict[str, OnboardBlock] = {}
    for block_id, (demands, erection) in sorted(chosen.items()):
        line, days = _block_line(inp, block_id, demands)
        lines.append(line)
        blocks[block_id] = OnboardBlock(demands=demands, days=days, erection=erection)
    return Onboard(lines=tuple(sorted(lines, key=lambda line: line.line_id)), blocks=blocks)


def _block_line(inp: CostInput, block_id: str, demands: tuple[Demand, ...]) -> tuple[CostLine, int]:
    parts = sorted({d.part_id for d in demands})
    weights = [part_weight(inp, part_id) for part_id in parts]
    tons = sum(w for w, _ in weights)
    equivalent = {key for _, key in weights if key is not None}
    rate_key = inp.production_rate(block_id)
    params = inp.params

    def premium(sc: Scenario) -> float:
        return tons * params.get(WORK, sc) * (params.get(RATIO, sc) - 1)

    work = tons * params.value(WORK) * params.value(RATIO)  # 선상 설치 전체 공수(일정용)
    days = max(1, math.ceil(work / params.value(CREW)))
    premium_hours = premium(Scenario.VALUE)
    name = inp.label(block_id)
    line = inp.line(
        line_id=f"{ITEM}:{KIND}:{block_id}",
        rule_id=ITEM,
        entity_id=block_id,
        label=f"{name} 블록 의장품 후행 설치",
        formula=(
            f"의장품 {len(parts)}개 {qty_text(tons, 't')} × 톤당 공수(선행의장) × (후행 설치 배수 − 1) × 인건비"
            f" = {premium_hours:,.1f}시간(대표값), 후행 설치 {days}일"
        ),
        inputs={"weight_t": round(tons, 6), "hours": round(premium_hours, 3), "days": days, "parts": len(parts)},
        amount=amount_of(lambda sc: premium(sc) * params.get(rate_key, sc)),
        param_keys=(WORK, RATIO, rate_key, CREW, *equivalent),
        item=CostItem.ONBOARD,
        hours=hours_of(premium),
        reason=(
            f"납기 지연 의장품 {len(parts)}개({qty_text(tons, 't')})를 기다리지 않고 {name} 블록을 계획대로 탑재한 뒤"
            f" 선상에서 설치(후행 설치) — 블록 단계 대비 추가 공수"
            f" · 구역 출구 전 후행 설치 {days}일 소요"
        ),
    )
    return line, days
