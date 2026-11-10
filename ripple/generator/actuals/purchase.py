"""발주: 발주 변경·취소 손실, 남는 강재 전용, 새 규격 급발주 할증(docs/engine.md(비용·일정) 4-2·4-3·4-7)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date, timedelta

from ripple.contracts.change import DimensionChange
from ripple.contracts.domain import POStatus

from .amounts import Raw
from .case import Case
from .common import STEEL
from .material import Material, MaterialChange
from .world import World


def purchase_costs(world: World, case: Case, material: MaterialChange, covered: Mapping[str, float]) -> Raw:
    """확정일에 발주된 품목의 손실(R-T01 바뀌는 부재, R-M02 빼는 부재), 전용 처리비, 재고로 못 채운 새 수량의 할증."""
    raw: Raw = defaultdict(float)
    losses: dict[tuple[str, str], float] = defaultdict(float)
    premiums: dict[str, list[Material]] = defaultdict(list)
    for m in material.materials:
        if m.line_id and case.line_stage(world, m.line_id) is not POStatus.NOT_ORDERED:
            losses[(m.line_id, "R-T01")] += m.qty
            premiums[m.line_id].append(m)
    for part_id in sorted(material.removed):
        for line_id in world.part_lines.get(part_id, ()):
            if case.line_stage(world, line_id) is not POStatus.NOT_ORDERED:
                losses[(line_id, "R-M02")] += world.parts[part_id].qty

    moves = _reallocated_moves(world, case, material, losses)
    for (source, target), qty in moves.items():
        raw[(f"handling:{source}:{target}", "reallocation")] += qty * world.param("stock.reallocation_handling_per_t")
    for (line_id, rule), qty in losses.items():
        stage = case.line_stage(world, line_id)
        ratio = world.param(f"po_cancel_ratio.{stage.value}")
        if world.specs[world.lines[line_id].spec_id].category in STEEL:  # 강재는 고철 잔존가치 상한
            ratio = min(ratio, world.param("steel.max_cancel_loss_ratio"))
        raw[(f"po:{line_id}:{rule}", "po_loss")] += qty * world.lines[line_id].unit_price_krw * ratio
    for line_id, entries in premiums.items():
        raw[(f"premium:{line_id}", "premium")] += world.param("reorder.expedite_premium_ratio") * sum(
            (m.new_qty - covered[m.part_id]) * m.new_price for m in entries
        )
    return raw


def _reallocated_moves(
    world: World, case: Case, material: MaterialChange, losses: dict[tuple[str, str], float]
) -> dict[tuple[str, str], float]:
    """입고된 강재 손실 품목을 같은 규격의 미입고 품목으로 옮긴다(확정일부터 60일 안에 착수하는 소비 공정,
    다른 블록의 안 바뀌는 부재만큼). 옮긴 양만큼 손실에서 빼고 (원 품목, 받는 품목) → 양을 돌려준다.
    """
    reshaped = {m.part_id for m in material.materials} | material.removed
    reshaped.update(p for op in case.change.ops if isinstance(op, DimensionChange) for p in op.part_ids)
    remaining_target: dict[str, float] = {}
    moves: dict[tuple[str, str], float] = defaultdict(float)
    horizon = case.confirm_on + timedelta(days=60)
    for (line_id, rule), qty in sorted(losses.items()):
        line = world.lines[line_id]
        if world.specs[line.spec_id].unit != "t" or case.line_stage(world, line_id) is not POStatus.RECEIVED:
            continue
        source_block = world.parts[line.part_ids[0]].block_id
        for other in sorted(world.lines.values(), key=lambda x: x.line_id):
            if other.line_id == line_id or other.spec_id != line.spec_id:
                continue
            if case.line_stage(world, other.line_id) in (POStatus.RECEIVED, POStatus.PROCESSED):
                continue
            consumer = other.consumed_by_activity_id
            if consumer is None or not case.confirm_on < case.base_es.get(consumer, date.min) <= horizon:
                continue
            kept = [p for p in other.part_ids if p not in reshaped and world.parts[p].block_id != source_block]
            if not kept:
                continue
            left = remaining_target.setdefault(other.line_id, min(other.qty, sum(world.parts[p].qty for p in kept)))
            take = min(qty, left)
            if take > 0:
                losses[(line_id, rule)] -= take
                moves[(line_id, other.line_id)] += take
                remaining_target[other.line_id] -= take
                qty -= take
    return moves
