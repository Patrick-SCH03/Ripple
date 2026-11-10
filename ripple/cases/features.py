"""비슷한 정도(결정적 점수): 분석 결과에서 사례의 특징(연산·블록·구역·계통·목적·크기)을 뽑고, 같은 연산 종류 안에서
점수를 매겨 사람이 읽는 '같은 점'을 붙인다. 숫자는 쓰지 않는 순수 계산이다(지도 조회표만 받는다)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from ripple.contracts.assistant import INTENT_LABELS
from ripple.contracts.change import (
    AddPart,
    AddPenetration,
    ChangeIntent,
    ChangeOp,
    DimensionChange,
    EquipmentSpecChange,
    GradeChange,
    RemovePart,
    ReroutePipe,
    ThicknessChange,
)
from ripple.contracts.domain import EntityType, GraphSnapshot
from ripple.contracts.result import AnalysisResult

from .settings import Similarity

OP_NAMES: Mapping[str, str] = MappingProxyType(
    {
        "thickness": "두께 변경",
        "grade": "강종 변경",
        "dimension": "치수 변경",
        "add_part": "부재 추가",
        "remove_part": "부재 삭제",
        "reroute_pipe": "배관 경로 변경",
        "equipment_spec": "장비 사양 변경",
        "add_penetration": "관통부 추가",
    }
)
"""'같은 두께 변경'처럼 같은 점 첫 줄에 쓰는 연산 이름."""

ROLES = frozenset({"target", "removed", "new"})  # 부분 그래프에서 바뀌는 부재 노드의 역할
DIMENSIONS = MappingProxyType({"length_mm": "길이", "width_mm": "폭", "height_mm": "높이", "diameter_mm": "지름"})


@dataclass(frozen=True, slots=True)
class MapLookup:
    """지도 조회표: 부재 → 블록·계통 이름, 블록 → 구역, 구역 → 이름. 분석 결과의 부분 그래프로 모자랄 때 쓴다."""

    part_block: Mapping[str, str] = field(default_factory=dict)
    part_system: Mapping[str, str] = field(default_factory=dict)
    block_zone: Mapping[str, str] = field(default_factory=dict)
    zone_name: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def of(cls, snapshot: GraphSnapshot) -> MapLookup:
        names = {s.system: s.name for s in snapshot.pipe_systems}
        return cls(
            part_block={p.part_id: p.block_id for p in snapshot.parts},
            part_system={p.part_id: names.get(p.system, p.system) for p in snapshot.parts if p.system},
            block_zone={b.block_id: b.zone_id for b in snapshot.blocks if b.zone_id},
            zone_name={z.zone_id: z.name for z in snapshot.zones},
        )


@dataclass(frozen=True, slots=True)
class Size:
    """변경 크기: 수(가까운 정도를 잼) 또는 값(같은지만 봄). text = 그 사례 자신의 크기 표현."""

    number: float | None
    value: str | None
    text: str


@dataclass(frozen=True, slots=True)
class Features:
    op: str
    intent: ChangeIntent | None
    blocks: frozenset[str]
    zones: frozenset[str]
    systems: frozenset[str]
    size: Size | None
    ops_key: str  # 연산 그대로(같은 변경이면 같은 값 — 자기 자신을 과거 사례로 보이지 않게)


@dataclass(frozen=True, slots=True)
class Match:
    score: float
    same: tuple[str, ...]


def op_parts(op: ChangeOp) -> tuple[str, ...]:
    """연산이 직접 가리키는 지도 부재(새 부재 제외)."""
    if isinstance(op, ReroutePipe):
        return op.removed_part_ids
    if isinstance(op, AddPenetration):
        return (op.plate_part_id, op.pipe_part_id)
    if isinstance(op, AddPart):
        return () if op.attach_to_part_id is None else (op.attach_to_part_id,)
    return tuple(getattr(op, "part_ids", ()))


def size_of(op: ChangeOp) -> Size | None:
    """연산마다 비교할 크기. 보강재 추가는 수량 단위가 규격마다 달라 비교하지 않는다."""
    if isinstance(op, ThicknessChange):
        delta = op.to_mm - op.from_mm
        return Size(delta, None, f"두께 {delta:+.1f}mm")
    if isinstance(op, DimensionChange):
        ratio = (op.to_value - op.from_value) / op.from_value
        return Size(ratio, None, f"{DIMENSIONS[op.field]} {ratio:+.0%}")
    if isinstance(op, RemovePart):
        return Size(float(len(op.part_ids)), None, f"{len(op.part_ids)}개 삭제")
    if isinstance(op, ReroutePipe):
        removed, added = len(op.removed_part_ids), len(op.added_spool_spec_ids)
        return Size(float(removed + added), None, f"스풀 {removed}개 → {added}개")
    if isinstance(op, AddPenetration):
        return Size(op.diameter_mm, None, f"관통 지름 {op.diameter_mm:.0f}mm")
    if isinstance(op, GradeChange):
        return Size(None, op.to_grade, f"목표 강종({op.to_grade})")
    if isinstance(op, EquipmentSpecChange):
        return Size(None, op.to_spec_id, f"목표 사양({op.to_spec_id})")
    return None


def features_of(result: AnalysisResult, lookup: MapLookup) -> Features:
    """분석 결과(요청·부분 그래프)와 지도 조회표로 특징을 뽑는다. 첫 연산을 대표로 본다(생성 사례는 연산 하나)."""
    change = result.request.change
    op = change.ops[0]
    nodes = result.graph.nodes
    changed = [n for n in nodes if n.type is EntityType.PART and n.attrs.get("role") in ROLES]
    blocks = {str(n.attrs["block_id"]) for n in changed if isinstance(n.attrs.get("block_id"), str)}
    blocks |= {lookup.part_block[p] for p in op_parts(op) if p in lookup.part_block}
    if isinstance(op, AddPart):
        blocks.add(op.block_id)
    graph_zones = {n.id: n.attrs.get("zone_id") for n in nodes if n.type is EntityType.BLOCK}
    zones = {str(z) for b in blocks if isinstance(z := graph_zones.get(b) or lookup.block_zone.get(b), str)}
    systems = {str(n.attrs["system"]) for n in changed if isinstance(n.attrs.get("system"), str) and n.attrs["system"]}
    systems |= {lookup.part_system[p] for p in op_parts(op) if p in lookup.part_system}
    return Features(
        op=op.op,
        intent=change.intent,
        blocks=frozenset(blocks),
        zones=frozenset(zones),
        systems=frozenset(systems),
        size=size_of(op),
        ops_key=str([o.model_dump(mode="json") for o in change.ops]),
    )


def closeness(a: Size | None, b: Size | None) -> float:
    """0~1: 수는 1 − |차| ÷ 큰 쪽(부호가 다르면 0), 값은 같으면 1."""
    if a is None or b is None:
        return 0.0
    if a.value is not None or b.value is not None:
        return 1.0 if a.value == b.value else 0.0
    x, y = a.number or 0.0, b.number or 0.0
    if x == y:
        return 1.0
    if x * y < 0:
        return 0.0
    return max(0.0, 1 - abs(x - y) / max(abs(x), abs(y)))


def _suffixed(name: str, kind: str) -> str:
    """'화물탱크 구역'은 그대로, '평형수'는 '평형수 계통'(같은 말을 두 번 쓰지 않게)."""
    return name if name.endswith(kind) else f"{name} {kind}"


def _codes(ids: Iterable[str]) -> str:
    return ", ".join(sorted(i.split(":")[-1] for i in ids))


def match(query: Features, case: Features, weights: Similarity, lookup: MapLookup) -> Match | None:
    """같은 연산 종류가 아니면 None. 점수 = 같은 블록·구역·계통·목적 + 크기 가까움. same은 점수에 든 순서."""
    if query.op != case.op:
        return None
    score = 0.0
    same = [f"같은 {OP_NAMES.get(case.op, case.op)}"]
    blocks = query.blocks & case.blocks
    zones = query.zones & case.zones
    if blocks:
        score += weights.block
        same.append(f"같은 블록 {_codes(blocks)}")
    if zones:
        score += weights.zone
        if not blocks:
            names = sorted(lookup.zone_name.get(z, z.split(":")[-1]) for z in zones)
            same.append("같은 " + ", ".join(_suffixed(n, "구역") for n in names))
    systems = query.systems & case.systems
    if systems:
        score += weights.system
        same.append("같은 " + ", ".join(_suffixed(s, "계통") for s in sorted(systems)))
    if query.intent is not None and query.intent == case.intent:
        score += weights.intent
        same.append(f"같은 목적({INTENT_LABELS[query.intent]})")
    near = closeness(query.size, case.size)
    score += weights.size * near
    if case.size is not None and near >= weights.size_close:
        same.append(f"같은 {case.size.text}" if case.size.value is not None else f"비슷한 크기({case.size.text})")
    return Match(score=round(score, 6), same=tuple(same))
