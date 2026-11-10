"""변경 후 보기(docs/engine.md(전파) 3절): 원본 색인 위에 요청의 모든 연산을 함께 반영한 차이.

원본 색인은 그대로 두고 차이만 들고 있는다: 빠지는 부재, 새 부재(임시 ID), 새 연결, 바뀐 두께·강종·규격.
연산은 정규형 해시 순으로 반영하므로 요청 안의 연산 순서는 결과에 영향이 없다.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import pairwise
from types import MappingProxyType

from ripple.contracts.change import (
    AddPart,
    AddPenetration,
    ChangeOp,
    ChangeRequest,
    DimensionChange,
    EquipmentSpecChange,
    GradeChange,
    RemovePart,
    ReroutePipe,
    ThicknessChange,
)
from ripple.contracts.domain import EntityType, PartKind, Relation
from ripple.contracts.graphview import GraphNode
from ripple.contracts.identity import canonical_json, normalized_op

from .describe import PART_KIND_NAMES
from .index import Edge, GraphIndex

ATTACH_RELATION: Mapping[PartKind, Relation | None] = MappingProxyType(
    {
        PartKind.PLATE: Relation.BUTT_WELD,
        PartKind.STIFFENER: Relation.FILLET_WELD,
        PartKind.BRACKET: Relation.FILLET_WELD,
        PartKind.COLLAR: Relation.FILLET_WELD,
        PartKind.PIPE_SPOOL: Relation.PIPE_JOINT,
        PartKind.VALVE: Relation.PIPE_JOINT,
        PartKind.PIPE_SUPPORT: Relation.SUPPORT,
        PartKind.EQUIPMENT: None,
    }
)
"""부재 추가에서 새 부재와 붙는 부재 사이의 관계(장비는 위치·도면만 이어받음)."""

FIELD_CHANGES = (ThicknessChange, GradeChange, DimensionChange, EquipmentSpecChange)


def op_key(op: ChangeOp) -> str:
    """연산 정규형의 SHA-256 앞 8자리. 같은 연산이면 ECN 번호·순서와 무관하게 같다."""
    return hashlib.sha256(canonical_json(normalized_op(op))).hexdigest()[:8]


@dataclass(frozen=True, slots=True)
class NewPart:
    part_id: str  # NEW:<연산 해시 8자리>:<순번>
    kind: PartKind
    spec_id: str
    ship_id: str
    block_id: str | None  # 모르면 None(R-X01이 알림)
    drawing_id: str | None
    system: str | None = None


@dataclass(frozen=True, slots=True)
class PlannedOp:
    """요청의 연산 하나와 그 연산이 만든 새 부재."""

    key: str
    op: ChangeOp
    new_ids: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.op.op

    def targets(self) -> tuple[str, ...]:
        """대상 부재(docs/engine.md(전파) 4절)."""
        return self.existing_targets() + self.new_ids

    def existing_targets(self) -> tuple[str, ...]:
        op = self.op
        if isinstance(op, (*FIELD_CHANGES, RemovePart)):
            return op.part_ids
        if isinstance(op, ReroutePipe):
            return op.removed_part_ids
        if isinstance(op, AddPenetration):
            return (op.plate_part_id,)
        return ()

    def removed(self) -> tuple[str, ...]:
        if isinstance(self.op, RemovePart):
            return self.op.part_ids
        if isinstance(self.op, ReroutePipe):
            return self.op.removed_part_ids
        return ()


class ChangeView:
    def __init__(self, index: GraphIndex, change: ChangeRequest) -> None:
        self.index = index
        self.fallback_ship = sorted(change.ship_ids)[0]
        ordered = sorted(change.ops, key=lambda op: (op_key(op), canonical_json(normalized_op(op))))
        self.removed: frozenset[str] = frozenset(
            part_id for op in ordered for part_id in PlannedOp(op_key(op), op).removed()
        )
        # 두께·강종·치수·장비 사양을 바꾸는 부재(강종·두께는 규격 ID를 바꾸지 않으므로 연산으로 센다)
        self.reshaped: frozenset[str] = frozenset(
            part_id for op in ordered if isinstance(op, FIELD_CHANGES) for part_id in op.part_ids
        )
        self.new_parts: dict[str, NewPart] = {}
        self._thickness: dict[str, float] = {}
        self._grade: dict[str, str] = {}
        self._spec: dict[str, str] = {}
        self._virtual: dict[str, dict[Relation, set[str]]] = defaultdict(lambda: defaultdict(set))
        self._edges: list[Edge] = []
        planned: list[PlannedOp] = []
        for op in ordered:
            key = op_key(op)
            planned.append(PlannedOp(key, op, self._apply(key, op)))
        self.ops: tuple[PlannedOp, ...] = tuple(planned)
        self.virtual_edges: tuple[Edge, ...] = tuple(self._edges)

    # ---------- 연산 반영 ----------

    def _apply(self, key: str, op: ChangeOp) -> tuple[str, ...]:
        if isinstance(op, ThicknessChange):
            self._thickness.update(dict.fromkeys(op.part_ids, op.to_mm))
        elif isinstance(op, GradeChange):
            self._grade.update(dict.fromkeys(op.part_ids, op.to_grade))
        elif isinstance(op, EquipmentSpecChange):
            self._spec.update(dict.fromkeys(op.part_ids, op.to_spec_id))
        elif isinstance(op, AddPart):
            return self._add_part(key, op)
        elif isinstance(op, ReroutePipe):
            return self._reroute(key, op)
        elif isinstance(op, AddPenetration):
            self._connect(op.plate_part_id, op.pipe_part_id, Relation.PENETRATION)
        return ()

    def _add_part(self, key: str, op: AddPart) -> tuple[str, ...]:
        block = self.index.blocks.get(op.block_id)
        attach = op.attach_to_part_id
        new = NewPart(
            part_id=f"NEW:{key}:1",
            kind=op.kind,
            spec_id=op.spec_id,
            ship_id=block.ship_id if block else self.fallback_ship,
            block_id=op.block_id if block else None,
            drawing_id=None if attach is None else self.drawing_of(attach),
        )
        self.new_parts[new.part_id] = new
        relation = ATTACH_RELATION[op.kind]
        if attach is not None and relation is not None and self.is_part(attach):
            self._connect(new.part_id, attach, relation)
        return (new.part_id,)

    def _reroute(self, key: str, op: ReroutePipe) -> tuple[str, ...]:
        removed = sorted(op.removed_part_ids)
        first = self.index.parts.get(removed[0]) if removed else None
        crossed = [self.index.parts[c] for c in sorted(op.crosses_part_ids) if c in self.index.parts]
        ship = first.ship_id if first else (crossed[0].ship_id if crossed else self.fallback_ship)
        spools = [
            NewPart(
                part_id=f"NEW:{key}:{n}",
                kind=PartKind.PIPE_SPOOL,
                spec_id=spec_id,
                ship_id=ship,
                block_id=self.block_of(first.part_id) if first else None,
                drawing_id=self.drawing_of(first.part_id) if first else None,
                system=first.system if first else None,
            )
            for n, spec_id in enumerate(op.added_spool_spec_ids, start=1)
        ]
        self.new_parts.update((s.part_id, s) for s in spools)
        ids = [s.part_id for s in spools]
        for a, b in pairwise(ids):
            self._connect(a, b, Relation.PIPE_JOINT)
        ends = sorted(
            {
                end
                for part_id in removed
                for end in self.index.out(part_id, Relation.PIPE_JOINT)
                if self.index.type_of(end) is EntityType.PART and end not in self.removed
            }
        )
        if ids and ends:
            self._connect(ids[0], ends[0], Relation.PIPE_JOINT)
            for end in ends[1:]:
                self._connect(ids[-1], end, Relation.PIPE_JOINT)
        for plate in op.crosses_part_ids:
            if ids and self.is_part(plate):
                self._connect(ids[0], plate, Relation.PENETRATION)
        return tuple(ids)

    def _connect(self, a: str, b: str, relation: Relation) -> None:
        self._virtual[a][relation].add(b)
        self._virtual[b][relation].add(a)
        self._edges.append(Edge(a, b, relation))

    # ---------- 조회 ----------

    def planned(self, op_names: Iterable[str]) -> tuple[PlannedOp, ...]:
        names = set(op_names)
        return tuple(p for p in self.ops if p.name in names)

    def targets(self, op_names: Iterable[str]) -> tuple[str, ...]:
        return tuple(sorted({t for p in self.planned(op_names) for t in p.targets()}))

    def keeps_material(self, part_id: str) -> bool:
        """이 요청 뒤에도 원래 자재가 그대로 필요한 기존 부재인가(빼거나 두께·강종·치수·장비 사양을 바꾸면 아님)."""
        return part_id in self.index.parts and part_id not in self.removed and part_id not in self.reshaped

    def is_part(self, entity_id: str) -> bool:
        return entity_id in self.new_parts or self.index.type_of(entity_id) is EntityType.PART

    def exists(self, entity_id: str) -> bool:
        return entity_id in self.new_parts or self.index.type_of(entity_id) is not None

    def neighbours(self, part_id: str, relation: Relation) -> tuple[str, ...]:
        """변경 후 보기의 이웃 부재: 빠지는 부재 제외, 새 연결 포함."""
        if part_id in self.removed:
            return ()
        found = set(self.original_neighbours(part_id, relation)) | self._virtual.get(part_id, {}).get(relation, set())
        return tuple(sorted(found - self.removed))

    def original_neighbours(self, part_id: str, relation: Relation) -> tuple[str, ...]:
        """원본 지도의 이웃 부재 중 빠지지 않는 것(빠지는 부재에서 출발하는 규칙용)."""
        return tuple(
            n
            for n in self.index.out(part_id, relation)
            if self.index.type_of(n) is EntityType.PART and n not in self.removed
        )

    def has_relation(self, part_id: str, relation: Relation) -> bool:
        """원본 지도에 그 관계가 하나라도 있는가(반대쪽 엔터티가 지도에 있어야 셈, R-X01).

        이 요청이 더하는 연결은 세지 않는다. 지도 자료가 빠졌는지를 묻는 것이기 때문이다.
        """
        expected = {
            Relation.PART_OF: EntityType.BLOCK,
            Relation.DRAWN_IN: EntityType.DRAWING,
            Relation.SUPPLIED_BY: EntityType.PO_LINE,
        }.get(relation, EntityType.PART)
        return any(self.index.type_of(t) is expected for t in self.index.out(part_id, relation))

    def lines_of(self, part_id: str) -> tuple[str, ...]:
        return tuple(
            t for t in self.index.out(part_id, Relation.SUPPLIED_BY) if self.index.type_of(t) is EntityType.PO_LINE
        )

    def block_of(self, part_id: str) -> str | None:
        if part_id in self.new_parts:
            return self.new_parts[part_id].block_id
        part = self.index.parts.get(part_id)
        if part is None or self.index.type_of(part.block_id) is not EntityType.BLOCK:
            return None
        return part.block_id

    def drawing_of(self, part_id: str) -> str | None:
        if part_id in self.new_parts:
            return self.new_parts[part_id].drawing_id
        part = self.index.parts.get(part_id)
        if part is None:
            return None
        drawing = self.index.drawing_of(part)
        return drawing if self.index.type_of(drawing) is EntityType.DRAWING else None

    def ship_of(self, part_id: str) -> str | None:
        if part_id in self.new_parts:
            return self.new_parts[part_id].ship_id
        part = self.index.parts.get(part_id)
        return None if part is None else part.ship_id

    def kind(self, part_id: str) -> PartKind:
        return self.new_parts[part_id].kind if part_id in self.new_parts else self.index.parts[part_id].kind

    def spec_id(self, part_id: str) -> str:
        if part_id in self.new_parts:
            return self.new_parts[part_id].spec_id
        return self._spec.get(part_id, self.index.parts[part_id].spec_id)

    def thickness(self, part_id: str) -> float | None:
        """변경 뒤 두께(두께 변경 대상이면 새 값)."""
        if part_id in self._thickness:
            return self._thickness[part_id]
        if part_id in self.new_parts:
            spec = self.index.specs.get(self.new_parts[part_id].spec_id)
            return None if spec is None else spec.thickness_mm
        return self.index.parts[part_id].thickness_mm

    def grade(self, part_id: str) -> str | None:
        """변경 뒤 강종(강종 변경 대상이면 새 값)."""
        if part_id in self._grade:
            return self._grade[part_id]
        if part_id in self.new_parts:
            spec = self.index.specs.get(self.new_parts[part_id].spec_id)
            return None if spec is None else spec.grade
        return self.index.parts[part_id].grade

    def connected(self, part_id: str) -> bool:
        """변경 후 보기에서 부재끼리의 연결이 하나라도 있는가."""
        relations = (Relation.BUTT_WELD, Relation.FILLET_WELD, Relation.PENETRATION, Relation.SUPPORT)
        return any(self.neighbours(part_id, r) for r in (*relations, Relation.PIPE_JOINT))

    def new_node(self, part_id: str) -> GraphNode:
        new = self.new_parts[part_id]
        op_key, number = part_id.rsplit(":", 1)  # NEW:<h8>:<n> — 한 연산이 새 부재를 여럿 만들면 번호로 가른다
        siblings = sum(1 for other in self.new_parts if other.rsplit(":", 1)[0] == op_key)
        nth = f" {number}" if siblings > 1 else ""
        return GraphNode(
            id=part_id,
            type=EntityType.PART,
            label=f"새 {PART_KIND_NAMES[new.kind]}{nth} {new.spec_id}",
            attrs={
                "kind": new.kind.value,
                "spec_id": new.spec_id,
                "block_id": new.block_id,
                "system": self.index.system_name(new.system) if new.system else None,
            },
            virtual=True,
        )
