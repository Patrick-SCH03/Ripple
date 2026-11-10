"""지도 색인: 스냅샷 → 엔터티 조회와 관계별 인접 목록(표준 라이브러리만).

엣지 방향(docs/domain.md 2절)
- 부재 → 블록, 블록 → 구역, 구역 → 선박, 발주 품목 → 발주, 공정 → 블록: part_of(소속)
- 부재 → 발주 품목: supplied_by · 부재 → 도면: drawn_in · 발주 품목 → 공정: consumed_by
- 선행 공정 → 후행 공정: precedes
- 부재 ↔ 부재(용접·관통·지지·배관 연결): 양방향으로 넣는다
이웃은 ID 순으로 정렬해 순회 결과가 늘 같게 한다.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass

from ripple.contracts.domain import (
    Activity,
    Block,
    Crew,
    Drawing,
    EntityType,
    GraphSnapshot,
    MaterialSpec,
    Part,
    POLine,
    PurchaseOrder,
    Relation,
    Ship,
    StockLot,
    Zone,
    drawing_key,
)


@dataclass(frozen=True, slots=True)
class Edge:
    source: str
    target: str
    relation: Relation


class GraphIndex:
    def __init__(self, snapshot: GraphSnapshot) -> None:
        self.snapshot = snapshot
        self.ships: dict[str, Ship] = {s.ship_id: s for s in snapshot.ships}
        self.zones: dict[str, Zone] = {z.zone_id: z for z in snapshot.zones}
        self.blocks: dict[str, Block] = {b.block_id: b for b in snapshot.blocks}
        self.parts: dict[str, Part] = {p.part_id: p for p in snapshot.parts}
        self.specs: dict[str, MaterialSpec] = {s.spec_id: s for s in snapshot.specs}
        self.orders: dict[str, PurchaseOrder] = {p.po_id: p for p in snapshot.purchase_orders}
        self.lines: dict[str, POLine] = {li.line_id: li for li in snapshot.po_lines}
        self.activities: dict[str, Activity] = {a.activity_id: a for a in snapshot.activities}
        self.drawings: dict[str, Drawing] = {d.drawing_id: d for d in snapshot.drawings}
        self.stock: dict[str, StockLot] = {s.lot_id: s for s in snapshot.stock}
        self.system_names: dict[str, str] = {s.system: s.name for s in snapshot.pipe_systems}
        self.crews: dict[str, Crew] = {c.crew_id: c for c in snapshot.crews}  # 1.32.0 작업반(그래프 엔터티 아님)
        self._types: dict[str, EntityType] = {}
        for ids, kind in (
            (self.ships, EntityType.SHIP),
            (self.zones, EntityType.ZONE),
            (self.blocks, EntityType.BLOCK),
            (self.parts, EntityType.PART),
            (self.orders, EntityType.PO),
            (self.lines, EntityType.PO_LINE),
            (self.activities, EntityType.ACTIVITY),
            (self.drawings, EntityType.DRAWING),
            (self.stock, EntityType.STOCK),
        ):
            for entity_id in ids:
                self._types[entity_id] = kind

        out: dict[str, dict[Relation, set[str]]] = defaultdict(lambda: defaultdict(set))
        incoming: dict[str, dict[Relation, set[str]]] = defaultdict(lambda: defaultdict(set))
        for edge in _edges(snapshot):
            out[edge.source][edge.relation].add(edge.target)
            incoming[edge.target][edge.relation].add(edge.source)
        self._out = {n: {r: tuple(sorted(t)) for r, t in rel.items()} for n, rel in out.items()}
        self._in = {n: {r: tuple(sorted(s)) for r, s in rel.items()} for n, rel in incoming.items()}
        self.line_of_part: dict[str, str] = {}
        for line in snapshot.po_lines:
            for part_id in line.part_ids:
                self.line_of_part[part_id] = line.line_id

    def type_of(self, entity_id: str) -> EntityType | None:
        return self._types.get(entity_id)

    def entity_ids(self) -> tuple[str, ...]:
        return tuple(self._types)

    def out(self, entity_id: str, relation: Relation) -> tuple[str, ...]:
        return self._out.get(entity_id, {}).get(relation, ())

    def into(self, entity_id: str, relation: Relation) -> tuple[str, ...]:
        return self._in.get(entity_id, {}).get(relation, ())

    def neighbours(self, entity_id: str) -> tuple[tuple[str, Relation], ...]:
        """나가고 들어오는 모든 이웃(방향 무시), (이웃 ID, 관계) 순으로 정렬."""
        found = {(t, r) for r, ts in self._out.get(entity_id, {}).items() for t in ts}
        found |= {(s, r) for r, ss in self._in.get(entity_id, {}).items() for s in ss}
        return tuple(sorted(found))

    def edges(self) -> Iterator[Edge]:
        for source in sorted(self._out):
            for relation in sorted(self._out[source]):
                for target in self._out[source][relation]:
                    yield Edge(source, target, relation)

    def drawing_of(self, part: Part) -> str:
        return drawing_key(part.drawing_no, part.revision)

    def system_name(self, system: str) -> str:
        """배관 계통의 현장 이름. 지도에 이름표가 없으면 키를 그대로."""
        return self.system_names.get(system, system)


def _edges(snapshot: GraphSnapshot) -> Iterator[Edge]:
    for zone in snapshot.zones:
        yield Edge(zone.zone_id, zone.ship_id, Relation.PART_OF)
    for block in snapshot.blocks:
        yield Edge(block.block_id, block.zone_id, Relation.PART_OF)
    for part in snapshot.parts:
        yield Edge(part.part_id, part.block_id, Relation.PART_OF)
        yield Edge(part.part_id, drawing_key(part.drawing_no, part.revision), Relation.DRAWN_IN)
    for line in snapshot.po_lines:
        yield Edge(line.line_id, line.po_id, Relation.PART_OF)
        for part_id in line.part_ids:
            yield Edge(part_id, line.line_id, Relation.SUPPLIED_BY)
        if line.consumed_by_activity_id is not None:
            yield Edge(line.line_id, line.consumed_by_activity_id, Relation.CONSUMED_BY)
    for activity in snapshot.activities:
        if activity.block_id is not None:
            yield Edge(activity.activity_id, activity.block_id, Relation.PART_OF)
        for predecessor in activity.predecessors:
            yield Edge(predecessor.activity_id, activity.activity_id, Relation.PRECEDES)
    for connection in snapshot.connections:
        relation = Relation(connection.kind.value)
        yield Edge(connection.a, connection.b, relation)
        yield Edge(connection.b, connection.a, relation)
