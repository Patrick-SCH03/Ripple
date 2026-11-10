"""잉여 자재 전용 배분(docs/engine.md(비용·일정) 4-7). 쓸 수 있으면 엔진이 결정적으로 쓴다.

(가) 재고 → 새 규격 수요: 바뀌는 규격 부재마다(부재 ID 순) 예약 없는 로트를 로트 ID 순으로 채운다.
(나) 잉여 자재 → 다른 블록 수요: 발주 변경·취소 줄(품목, 규칙)마다 다른 품목을 품목 ID 순으로 채운다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ripple.contracts.domain import EntityType
from ripple.contracts.result import ImpactType

from .inputs import CostInput
from .material import SpecChange

STOCK_RULE = "R-M01"


@dataclass(frozen=True, slots=True)
class StockUse:
    lot_id: str
    part_id: str
    qty: float


@dataclass(frozen=True, slots=True)
class SurplusMove:
    source_line: str  # 잉여 자재의 발주 품목 L
    rule_id: str  # L의 발주 변경·취소 규칙(R-T01·R-M02)
    target_line: str  # 받는 다른 블록 발주 품목 O
    qty: float


def allocate_stock(inp: CostInput, changes: tuple[SpecChange, ...]) -> tuple[StockUse, ...]:
    candidates: dict[str, set[str]] = defaultdict(set)
    for finding in inp.findings(STOCK_RULE, ImpactType.REALLOCATE_STOCK):
        if finding.entity_type is EntityType.STOCK:
            candidates[finding.origin].add(finding.entity_id)
    remaining = {lot_id: lot.qty for lot_id, lot in inp.index.stock.items()}
    uses: list[StockUse] = []
    for ch in changes:
        need = ch.q_new
        for lot_id in sorted(candidates.get(ch.part_id, ())):
            lot = inp.index.stock[lot_id]
            if lot.reserved_block_id is not None or inp.index.specs[lot.spec_id].unit != ch.unit:
                continue
            take = min(remaining[lot_id], need)
            if take <= 0:
                continue
            uses.append(StockUse(lot_id=lot_id, part_id=ch.part_id, qty=take))
            remaining[lot_id] -= take
            need -= take
    return tuple(uses)


def _demand_left(inp: CostInput, line_id: str) -> float:
    line = inp.index.lines[line_id]
    needed = sum(inp.index.parts[p].qty for p in line.part_ids if inp.view.keeps_material(p))
    return min(line.qty, needed)


def allocate_surplus(
    inp: CostInput, losses: dict[tuple[str, str], tuple[str, ...]], quantities: dict[tuple[str, str], float]
) -> tuple[SurplusMove, ...]:
    """losses: (품목 L, 규칙) → 그 줄의 출발 부재. 대표 단계가 정해진 발주 변경·취소 줄만 넘긴다.
    받는 품목 O의 수용량 = min(O 수량, 이 요청 뒤에도 O의 자재가 필요한 부재 수량의 합). O가 미발주라
    발주 변경 영향이 없어도 이 요청이 빼거나 바꾸는 O의 부재는 수요에서 빠진다.
    """
    by_source: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for finding in inp.findings(STOCK_RULE, ImpactType.REALLOCATE_STOCK):
        if finding.entity_type is EntityType.PO_LINE and finding.path:
            by_source[finding.path[0].dst].add((finding.origin, finding.entity_id))
    remaining: dict[str, float] = {}
    moves: list[SurplusMove] = []
    for (line_id, rule_id), parts in sorted(losses.items()):
        spec = inp.index.specs[inp.index.lines[line_id].spec_id]
        if spec.unit != "t":
            continue
        left = quantities[(line_id, rule_id)]
        targets = sorted({target for origin, target in by_source.get(line_id, ()) if origin in parts})
        for target in targets:
            if target not in remaining:
                remaining[target] = _demand_left(inp, target)
            take = min(left, remaining[target])
            if take <= 0:
                continue
            moves.append(SurplusMove(source_line=line_id, rule_id=rule_id, target_line=target, qty=take))
            remaining[target] -= take
            left -= take
    return tuple(moves)
