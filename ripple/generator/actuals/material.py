"""자재: 연산에서 바뀌는 부재·빼는 부재·새 부재 읽기, 자재비 차이, 재고 전용(docs/engine.md(비용·일정) 4-0·4-1·4-7)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from statistics import fmean

from ripple.contracts.change import (
    AddPart,
    ChangeRequest,
    EquipmentSpecChange,
    GradeChange,
    RemovePart,
    ReroutePipe,
    ThicknessChange,
)
from ripple.contracts.domain import MaterialSpec, Part

from .amounts import Raw
from .common import new_part_key
from .world import World


@dataclass(frozen=True, slots=True)
class Material:
    """규격·수량·단가가 바뀌는 기존 부재 하나(변경 전 qty·price, 변경 후 new_*)."""

    part_id: str
    line_id: str | None
    qty: float
    price: float
    new_qty: float
    new_price: float
    lead: int
    category: str
    new_spec_id: str
    transport: str | None = None  # 1.33.0 외자재 새 발주에 더할 운송 방식(리드타임이 규격 표준·파라미터일 때만)


@dataclass(frozen=True, slots=True)
class MaterialChange:
    """설계변경의 자재 변화: 바뀌는 부재, 빼는 부재, 새 부재(임시 ID → 수량·규격)."""

    materials: list[Material]
    removed: set[str]
    added: dict[str, float]
    new_specs: dict[str, str]


def material_change(world: World, change: ChangeRequest) -> MaterialChange:
    changed, removed, added, new_specs = _ops(world, change)
    materials = [_material(world, part_id, changed[part_id]) for part_id in sorted(changed) if part_id in world.parts]
    return MaterialChange(materials, removed, added, new_specs)


def _ops(
    world: World, change: ChangeRequest
) -> tuple[dict[str, dict[str, object]], set[str], dict[str, float], dict[str, str]]:
    """연산을 부재별로 읽는다: 바뀌는 필드(두께·강종·규격), 빼는 부재, 새 부재 수량과 규격."""
    changed: dict[str, dict[str, object]] = defaultdict(dict)
    removed: set[str] = set()
    added: dict[str, float] = {}
    new_specs: dict[str, str] = {}
    for op in change.ops:
        if isinstance(op, ThicknessChange):
            for part_id in op.part_ids:
                changed[part_id]["thickness"] = op.to_mm
        elif isinstance(op, GradeChange):
            for part_id in op.part_ids:
                changed[part_id]["grade"] = op.to_grade
        elif isinstance(op, EquipmentSpecChange):
            for part_id in op.part_ids:
                changed[part_id]["spec"] = op.to_spec_id
        elif isinstance(op, RemovePart):
            removed.update(op.part_ids)
        elif isinstance(op, ReroutePipe):
            removed.update(op.removed_part_ids)
            old = [world.parts[p].qty for p in op.removed_part_ids if p in world.parts]
            each = fmean(old) if old else world.param("piping.new_spool_qty")
            for i, spec_id in enumerate(op.added_spool_spec_ids, 1):
                new_id = f"NEW:{new_part_key(op)}:{i}"
                added[new_id] = each
                new_specs[new_id] = spec_id
        elif isinstance(op, AddPart):
            new_id = f"NEW:{new_part_key(op)}:1"
            added[new_id] = op.qty
            new_specs[new_id] = op.spec_id
    return changed, removed, added, new_specs


def _material(world: World, part_id: str, fields: Mapping[str, object]) -> Material:
    """바뀌는 부재 하나의 변경 후 수량·단가·새 규격과 그 리드타임(docs/engine.md(비용·일정) 4-0)."""
    part = world.parts[part_id]
    spec = world.specs[part.spec_id]
    line_id = world.line_of(part_id)
    price = float(world.lines[line_id].unit_price_krw if line_id else spec.unit_price_krw)
    qty, new_price = part.qty, price
    thickness = fields.get("thickness")
    grade = fields.get("grade")
    if spec.unit == "t" and isinstance(thickness, float) and part.thickness_mm:
        qty *= thickness / part.thickness_mm
    if spec.unit == "t" and isinstance(grade, str) and part.grade:
        before = f"steel.grade_price_ratio.{part.grade}"
        after = f"steel.grade_price_ratio.{grade}"
        if before in world.values and after in world.values:
            new_price *= world.param(after) / world.param(before)
    target = fields.get("spec")
    if isinstance(target, str) and target in world.specs:
        new_price = float(world.specs[target].unit_price_krw)
    candidate = target if isinstance(target, str) and target in world.specs else None
    if candidate is None and (thickness is not None or grade is not None):
        candidate = _same_kind_spec(world, part, spec, grade, thickness)
    bought = world.specs[candidate or part.spec_id]
    if candidate and bought.std_lead_time_days:  # 생산 리드타임 → 외자재면 운송을 더함
        lead, transport = bought.std_lead_time_days, imported(bought)
    elif line_id:  # 원래 발주의 리드타임은 이미 운송 포함
        lead, transport = world.orders[world.lines[line_id].po_id].lead_time_days, None
    else:
        lead, transport = round(world.param(f"lead_time_days.{spec.category}")), imported(bought)
    return Material(
        part_id=part_id,
        line_id=line_id,
        qty=part.qty,
        price=price,
        new_qty=qty,
        new_price=new_price,
        lead=lead,
        category=spec.category,
        new_spec_id=candidate or part.spec_id,
        transport=transport,
    )


def imported(spec: MaterialSpec) -> str | None:
    """외자재 규격의 운송 방식(국산·모름이면 None, 외자재인데 비면 선박 가정) — 새로 발주할 때 운송 일수를 더할지."""
    return spec.import_transport


def _same_kind_spec(world: World, part: Part, spec: MaterialSpec, grade: object, thickness: object) -> str | None:
    """두께·강종이 바뀐 부재의 새 규격: 같은 분류에서 바뀐 강종·두께가 맞는 첫 규격(ID 순서)."""
    for spec_id, possible in sorted(world.specs.items()):
        if (
            possible.category == spec.category
            and possible.grade == (grade or part.grade)
            and possible.thickness_mm == (thickness or part.thickness_mm)
        ):
            return spec_id
    return None


def material_delta(world: World, material: MaterialChange) -> Raw:
    """자재비 차이(C-01): 바뀌는 부재는 변경 후 − 변경 전, 빼는 부재는 −, 새 부재는 +."""
    raw: Raw = defaultdict(float)
    for m in material.materials:
        raw[(f"material:{m.part_id}", "material_delta")] += m.new_qty * m.new_price - m.qty * m.price
    for part_id in sorted(material.removed):
        part = world.parts[part_id]
        line_id = world.line_of(part_id)
        price = world.lines[line_id].unit_price_krw if line_id else world.specs[part.spec_id].unit_price_krw
        raw[(f"material:{part_id}", "material_delta")] -= part.qty * price
    for new_id, qty in material.added.items():
        raw[(f"material:{new_id}", "material_delta")] += qty * world.specs[material.new_specs[new_id]].unit_price_krw
    return raw


def stock_reallocation(
    world: World, change: ChangeRequest, as_of: date, materials: list[Material]
) -> tuple[dict[str, float], Raw]:
    """기준일까지 입고된 미예약·미가공 재고 중 같은 분류·강종·두께로 새 수량을 채운다(로트 ID 순서).

    (부재별 채운 양(defaultdict(float)), 채운 양 × (전용 처리비 − 새 단가) 항목).
    """
    covered: dict[str, float] = defaultdict(float)
    raw: Raw = defaultdict(float)
    available = {lot.lot_id: lot.qty for lot in world.snapshot.stock}
    for m in materials:
        part = world.parts[m.part_id]
        spec = world.specs[part.spec_id]
        grade = next(
            (op.to_grade for op in change.ops if isinstance(op, GradeChange) and m.part_id in op.part_ids),
            part.grade,
        )
        thick = next(
            (op.to_mm for op in change.ops if isinstance(op, ThicknessChange) and m.part_id in op.part_ids),
            part.thickness_mm,
        )
        for lot in sorted(world.snapshot.stock, key=lambda x: x.lot_id):
            ls = world.specs[lot.spec_id]
            if lot.processed or lot.received_date > as_of or lot.reserved_block_id or ls.unit != spec.unit:
                continue
            if (ls.category, ls.grade, ls.thickness_mm) != (spec.category, grade, thick):
                continue
            take = min(available[lot.lot_id], m.new_qty - covered[m.part_id])
            if take > 0:
                covered[m.part_id] += take
                available[lot.lot_id] -= take
                raw[(f"stock:{lot.lot_id}:{m.part_id}", "reallocation")] += take * (
                    world.param("stock.reallocation_handling_per_t") - m.new_price
                )
    return covered, raw
