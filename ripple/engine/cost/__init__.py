"""비용 엔진(docs/engine.md(비용·일정) 4·5절): 판정일 t의 영향에서 비용 줄·잉여 자재 전용·재작업 일수·새 자재 수요.

지체상금(4-6)은 일정 계산 뒤 timing이 붙인다. 모든 함수는 순수 계산이다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ripple.contracts.result import CostLine, Reallocation

from .amounts import Params, Scenario, amount_of, difference, round_won, worst_case
from .damages import damages_line
from .demand import Demand, demands, entry_estimate
from .inputs import CostInput, activity_map
from .material import SpecChange, material_lines, spec_changes
from .minor import minor_lines
from .new_work import new_work_lines
from .procurement import procurement
from .rework import rework


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    lines: tuple[CostLine, ...]  # 지체상금 제외, 줄 ID 순
    reallocations: tuple[Reallocation, ...]
    rework_days: dict[str, int]  # 블록 → 재작업 일수
    demands: tuple[Demand, ...]
    notes: tuple[str, ...]


def cost_breakdown(inp: CostInput, changes: tuple[SpecChange, ...]) -> CostBreakdown:
    bought = procurement(inp, changes)
    redo = rework(inp)
    needed = demands(inp, changes, bought.covered)
    # 도착일을 실제로 계산한 수요(도착일·소비 공정 있음)의 부재 — 운송 가정 문장은 이 부재의 자재비 줄에만(5절)
    waited = frozenset(d.part_id for d in needed if d.arrival is not None and d.consumer is not None)
    materials = material_lines(inp, changes, waited)
    lines = (*materials, *new_work_lines(inp), *bought.lines, *redo.lines, *minor_lines(inp))
    notes = {note for ch in changes for note in ch.notes} | {d.note for d in needed if d.note}
    return CostBreakdown(
        lines=tuple(sorted(lines, key=lambda line: line.line_id)),
        reallocations=tuple(sorted(bought.reallocations, key=lambda r: (r.lot_id, r.to_block_id, r.spec_id))),
        rework_days=redo.days,
        demands=needed,
        notes=tuple(sorted(notes)),
    )


__all__ = [
    "CostBreakdown",
    "CostInput",
    "Demand",
    "Params",
    "Scenario",
    "SpecChange",
    "activity_map",
    "amount_of",
    "cost_breakdown",
    "damages_line",
    "difference",
    "entry_estimate",
    "round_won",
    "spec_changes",
    "worst_case",
]
