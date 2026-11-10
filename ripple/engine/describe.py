"""엔터티를 사람이 읽는 이름·속성으로 바꾼다(화면 노드, 변경 그래프, 근거 메모가 함께 쓴다)."""

from __future__ import annotations

from collections.abc import Callable

from ripple.contracts.domain import ActivityKind, BlockStage, EntityType, PartKind, POStatus, Relation
from ripple.contracts.graphview import AttrValue, GraphNode

from .index import GraphIndex

ACTIVITY_NAMES = {
    ActivityKind.SUB_ASSEMBLY: "소조립",
    ActivityKind.PANEL: "판넬조립",  # 옛 이름 판계(값 panel 그대로)
    ActivityKind.ASSEMBLY: "대조립",  # 옛 이름 조립(값 assembly 그대로)
    ActivityKind.PRE_OUTFITTING: "선행의장",
    ActivityKind.PRE_PAINTING: "선행도장",
    ActivityKind.PRE_ERECTION: "PE",
    ActivityKind.ERECTION: "탑재",
}
MILESTONE_NAMES = {"exit": "구역 탑재 완료", "launch": "진수", "sea_trial": "시운전", "delivery": "인도"}
PART_KIND_NAMES = {
    PartKind.PLATE: "판",
    PartKind.STIFFENER: "보강재",
    PartKind.BRACKET: "브라켓",
    PartKind.COLLAR: "칼라",
    PartKind.PIPE_SPOOL: "배관 스풀",
    PartKind.VALVE: "밸브",
    PartKind.PIPE_SUPPORT: "서포트",
    PartKind.EQUIPMENT: "장비",
}
RELATION_NAMES = {
    Relation.PART_OF: "소속",
    Relation.SUPPLIED_BY: "공급 발주 품목",
    Relation.BUTT_WELD: "맞대기 용접",
    Relation.FILLET_WELD: "필릿 용접",
    Relation.PENETRATION: "관통",
    Relation.SUPPORT: "지지",
    Relation.PIPE_JOINT: "배관 연결",
    Relation.DRAWN_IN: "도면",
    Relation.CONSUMED_BY: "소비 공정",
    Relation.PRECEDES: "선후행",
    Relation.SAME_SPEC: "같은 규격",
}
PO_STATUS_NAMES = {
    POStatus.NOT_ORDERED: "미발주",
    POStatus.ORDERED: "발주",
    POStatus.MATERIAL_SECURED: "자재 확보",
    POStatus.IN_FABRICATION: "제작",
    POStatus.RECEIVED: "입고",
    POStatus.PROCESSED: "가공",
}
BLOCK_STAGE_NAMES = {
    BlockStage.NOT_STARTED: "미착수",
    BlockStage.STEEL_RECEIVED: "강재 입고",
    BlockStage.SUB_ASSEMBLY: "소조립",
    BlockStage.PANEL: "판넬조립",
    BlockStage.ASSEMBLY: "대조립",
    BlockStage.PRE_OUTFITTING: "선행의장",
    BlockStage.PRE_PAINTING: "선행도장",
    BlockStage.PRE_ERECTION: "PE",
    BlockStage.ERECTED: "탑재",
}


Described = tuple[str, dict[str, AttrValue]]
"""엔터티 종류별 (이름, 속성)."""


def describe(index: GraphIndex, entity_id: str) -> GraphNode:
    kind = index.type_of(entity_id)
    if kind is None:
        raise KeyError(f"지도에 없는 엔터티: {entity_id}")
    describer = _DESCRIBERS.get(kind)
    label, attrs = describer(index, entity_id) if describer is not None else (entity_id, {})
    return GraphNode(id=entity_id, type=kind, label=label, attrs=attrs)


def _part(index: GraphIndex, entity_id: str) -> Described:
    part = index.parts[entity_id]
    return part.name, {
        "kind": part.kind.value,
        "spec_id": part.spec_id,
        "thickness_mm": part.thickness_mm,
        "grade": part.grade,
        "system": index.system_name(part.system) if part.system else None,
        "block_id": part.block_id,
    }


def _block(index: GraphIndex, entity_id: str) -> Described:
    block = index.blocks[entity_id]
    return f"{entity_id.split(':')[-1]} {block.name}", {
        "zone_id": block.zone_id,
        "steel_weight_t": block.steel_weight_t,
    }


def _zone(index: GraphIndex, entity_id: str) -> Described:
    return index.zones[entity_id].name, {}


def _ship(index: GraphIndex, entity_id: str) -> Described:
    return f"{entity_id} 수에즈막스", {}


def _order(index: GraphIndex, entity_id: str) -> Described:
    order = index.orders[entity_id]
    planned = order.planned_order_date
    return f"{entity_id} 발주", {
        "supplier_id": order.supplier_id,
        "planned_order_date": planned.isoformat() if planned else None,
        "lead_time_days": order.lead_time_days,
    }


def _line(index: GraphIndex, entity_id: str) -> Described:
    line = index.lines[entity_id]
    label = f"{line.po_id} #{line.line_no} {line.spec_id}"
    return label, {"spec_id": line.spec_id, "qty": line.qty, "unit_price_krw": line.unit_price_krw}


def _activity(index: GraphIndex, entity_id: str) -> Described:
    activity = index.activities[entity_id]
    if activity.kind is ActivityKind.MILESTONE:
        tail = entity_id.split(":")[-1]
        zone = entity_id.split(":")[1] if tail == "exit" else ""
        label = f"{zone} {MILESTONE_NAMES.get(tail, tail)}".strip()
    else:
        label = f"{(activity.block_id or '').split(':')[-1]} {ACTIVITY_NAMES[activity.kind]}"
    return label, {
        "kind": activity.kind.value,
        "planned_start": activity.planned_start.isoformat(),
        "duration_days": activity.duration_days,
        "actual_start": activity.actual_start.isoformat() if activity.actual_start else None,
    }


def _drawing(index: GraphIndex, entity_id: str) -> Described:
    drawing = index.drawings[entity_id]
    return f"{drawing.drawing_no} 개정 {drawing.revision}", {"discipline": drawing.discipline}


def _stock(index: GraphIndex, entity_id: str) -> Described:
    lot = index.stock[entity_id]
    return f"{entity_id} {lot.spec_id}", {
        "spec_id": lot.spec_id,
        "qty": lot.qty,
        "reserved_block_id": lot.reserved_block_id,
    }


_DESCRIBERS: dict[EntityType, Callable[[GraphIndex, str], Described]] = {
    EntityType.PART: _part,
    EntityType.BLOCK: _block,
    EntityType.ZONE: _zone,
    EntityType.SHIP: _ship,
    EntityType.PO: _order,
    EntityType.PO_LINE: _line,
    EntityType.ACTIVITY: _activity,
    EntityType.DRAWING: _drawing,
    EntityType.STOCK: _stock,
}
