"""공수: 새 부재 정상 제작, 블록 재작업, 작은 작업(docs/engine.md(비용·일정) 4-1-2·4-4·4-5)."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from ripple.contracts.change import AddPart, ChangeRequest, ReroutePipe
from ripple.contracts.domain import OUTFIT_PART_KINDS, ActivityKind, BlockStage, PartKind

from .amounts import Raw
from .case import Case
from .common import STAGES, STEEL, WORK, new_part_key
from .network import block_chain
from .world import World

HOURS_KEY = {
    "taper": "taper_per_joint",
    "weld_recheck": "weld_recheck_per_joint",
    "collar_resize": "collar_resize_each",
    "modify_part": "modify_part_each",
    "drawing_revision": "drawing_revision_per_drawing",
}
"""작은 작업 종류 → 공수 파라미터(minor_work_hours.*)."""
DESIGN_WORK = frozenset({"weld_recheck", "drawing_revision"})
"""설계 인력이 하는 작은 작업(그 밖은 블록 작업 인력)."""
AFTER_PAINT = ("repaint_hours", "scaffold_hours", "hot_work_hours")
"""도장 뒤 재작업 고정 항목(after_paint.*): 재도장·족장·화기작업 안전 조치 공수."""
OUTFIT_WORK = frozenset(WORK[WORK.index(ActivityKind.PRE_OUTFITTING.value) :])
"""의장품 중량이 들어가는 공정(선행의장부터 탑재까지)."""


def new_work(world: World, change: ChangeRequest) -> Raw:
    """새 부재의 정상 제작 공수(docs/engine.md(비용·일정) 4-1-2): 강재 새 부재, 공정 6개 공수 합 × 생산 단가."""
    raw: Raw = defaultdict(float)
    for op in change.ops:
        if not isinstance(op, AddPart):
            continue
        spec = world.specs[op.spec_id]
        if spec.unit != "t" or spec.category not in STEEL:
            continue
        crew = world.crew(op.block_id)
        hours = op.qty * sum(world.param(f"base_work_hours_per_t.{kind}") for kind in WORK)
        raw[(f"new_work:NEW:{new_part_key(op)}:1", "new_work")] += hours * world.param(f"labor_rate_per_hour.{crew}")
    return raw


def rework(world: World, case: Case, changed: set[str]) -> tuple[dict[str, int], Raw]:
    """블록 재작업: 블록별 영향 중량(의장품은 선행의장 공정부터만) × 확정일까지 착수한 공정마다 (공수 × 단계 배율 × 블록
    난이도 × 그 공정 수행 주체의 단가), 선행도장 이후 단계면 도장 뒤 고정 항목(재도장·족장·화기작업 공수 × 선행도장
    수행 주체 단가)을 따로 더한다(docs/engine.md(비용·일정) 4-4·4-4-1·4-4-2와 같은 식). (블록별 재작업 일수, 항목)."""
    work_days: dict[str, int] = {}
    raw: Raw = defaultdict(float)
    for block_id, weight in _weights(world, case.change, changed).items():
        chain = block_chain(case.nodes, block_id)
        stage_index = max(
            (i for i, a in enumerate(chain) if case.base_es[a.activity_id] <= case.confirm_on), default=-1
        )
        if stage_index < 0:
            continue
        block_stage = STAGES[stage_index + 2]
        factor = world.param(f"rework_multiplier.{block_stage.value}") * difficulty(world, block_id)
        hours = 0.0
        for kind in WORK[: stage_index + 1]:
            tons = weight.hull + (weight.outfit if kind in OUTFIT_WORK else 0.0)
            share = tons * factor * world.param(f"base_work_hours_per_t.{kind}")
            hours += share
            labor = world.labor_of(block_id, ActivityKind(kind))
            raw[(f"rework:{block_id}", "rework")] += share * world.param(f"labor_rate_per_hour.{labor}")
        if STAGES.index(block_stage) >= STAGES.index(BlockStage.PRE_PAINTING):
            labor = world.labor_of(block_id, ActivityKind.PRE_PAINTING)
            fixed = sum(world.param(f"after_paint.{item}") for item in AFTER_PAINT)
            raw[(f"after_paint:{block_id}", "after_paint")] += fixed * world.param(f"labor_rate_per_hour.{labor}")
        work_days[block_id] = math.ceil(hours / world.param("rework.crew_hours_per_day")) if hours > 0 else 0
    return work_days, raw


def difficulty(world: World, block_id: str) -> float:
    """블록 난이도 계수(docs/engine.md(비용·일정) 4-4와 같은 식, 반올림 포함): 형상 × 의장 밀도 × 전장품, 상한."""
    block = world.blocks[block_id]
    shape = round(world.param(f"difficulty.shape.{block.shape.value}"), 4) if block.shape is not None else 1.0
    outfit = _density(world, block.outfit_items, block.steel_weight_t, "outfit")
    electric = _density(world, block.electric_items, block.steel_weight_t, "electric")
    if block.shape is None and block.outfit_items is None and block.electric_items is None:
        return 1.0
    cap = max(world.param("difficulty.cap"), 1.0)
    return round(min(shape * outfit * electric, cap), 6)


def _density(world: World, items: int | None, weight: float, name: str) -> float:
    if items is None or weight <= 0:
        return 1.0
    top, full = world.param(f"difficulty.{name}_max"), world.param(f"difficulty.{name}_full_per_t")
    return round(1 + (top - 1) * min(1.0, items / weight / full), 4)


@dataclass
class _Weight:
    hull: float = 0.0  # 선체 부재
    outfit: float = 0.0  # 의장품(선행의장 공정부터만 다시 함)

    def add(self, kind: PartKind, tons: float) -> None:
        if kind in OUTFIT_PART_KINDS:
            self.outfit += tons
        else:
            self.hull += tons


def _weights(world: World, change: ChangeRequest, changed: set[str]) -> dict[str, _Weight]:
    """블록별 영향 중량(t, 선체·의장품 따로): 바뀌는 부재의 무게(없으면 종류별 환산 중량), 새 부재, 새 스풀."""
    weights: dict[str, _Weight] = defaultdict(_Weight)
    for part_id in sorted(changed):
        if part_id not in world.parts:
            continue
        part = world.parts[part_id]
        weights[part.block_id].add(
            part.kind,
            part.weight_kg / 1000
            if part.weight_kg is not None
            else world.param(f"rework.equivalent_weight_t.{part.kind.value}"),
        )
    for op in change.ops:
        if isinstance(op, AddPart):
            spec = world.specs[op.spec_id]
            weights[op.block_id].add(
                op.kind, op.qty if spec.unit == "t" else world.param(f"rework.equivalent_weight_t.{op.kind.value}")
            )
        elif isinstance(op, ReroutePipe) and op.removed_part_ids:
            block = world.parts[min(op.removed_part_ids)].block_id
            weights[block].add(
                PartKind.PIPE_SPOOL,
                len(op.added_spool_spec_ids) * world.param("rework.equivalent_weight_t.pipe_spool"),
            )
    return weights


def minor_work(world: World, change: ChangeRequest, minor: set[tuple[str, str, str]]) -> Raw:
    """작은 작업 표시마다 공수 × 인력 단가(용접 재검토·도면 개정은 설계, 그 밖은 블록 작업 인력)."""
    raw: Raw = defaultdict(float)
    for rule, entity, kind in sorted(minor):
        part_block = world.parts[entity].block_id if entity in world.parts else _new_block(world, change, entity)
        labor = "design" if kind in DESIGN_WORK else (world.crew(part_block) if part_block else "prime")
        hours_key = HOURS_KEY[kind]
        if kind == "drawing_revision" and world.drawing_discipline.get(entity) == "piping":
            hours_key = "drawing_revision_piping"  # 배관도 개정(엔진 cost-v8과 같은 규칙)
        raw[(f"minor:{rule}:{kind}:{entity}", "minor_work")] += world.param(
            f"minor_work_hours.{hours_key}"
        ) * world.param(f"labor_rate_per_hour.{labor}")
    return raw


def _new_block(world: World, change: ChangeRequest, new_id: str) -> str | None:
    """새 부재의 블록: 부재 추가는 연산의 블록, 새 스풀은 빼는 스풀 중 ID가 가장 앞선 것의 블록."""
    for op in change.ops:
        if isinstance(op, AddPart) and new_id == f"NEW:{new_part_key(op)}:1":
            return op.block_id
        if isinstance(op, ReroutePipe) and new_id.startswith(f"NEW:{new_part_key(op)}:") and op.removed_part_ids:
            return world.parts[min(op.removed_part_ids)].block_id
    return None
