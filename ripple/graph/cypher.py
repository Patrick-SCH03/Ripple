"""고정 Cypher 템플릿(안전장치: 고정 템플릿만 실행).

Neo4jGraphStore는 이 사전의 키로만 쿼리를 고르고, 값은 매개변수로만 넘긴다. 레이블·관계 종류는
Cypher에서 매개변수로 쓸 수 없으므로 엔터티 종류·관계 종류마다 템플릿을 미리 만들어 둔다.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from ripple.contracts.domain import EntityType, Relation


def node_label(kind: EntityType) -> str:
    return "".join(word.capitalize() for word in kind.value.split("_"))


def node_key(kind: EntityType) -> str:
    return f"nodes:{kind.value}"


def edge_key(relation: Relation) -> str:
    return f"edges:{relation.value}"


_BASE = {
    "create_index": "CREATE INDEX entity_lookup IF NOT EXISTS FOR (n:Entity) ON (n.snapshot_id, n.id)",
    "create_snapshot_constraint": (
        "CREATE CONSTRAINT snapshot_id_unique IF NOT EXISTS FOR (s:Snapshot) REQUIRE s.id IS UNIQUE"
    ),
    "delete_entities": "MATCH (n:Entity {snapshot_id: $id}) DETACH DELETE n",
    "delete_snapshot": "MATCH (s:Snapshot {id: $id}) DETACH DELETE s",
    "save_snapshot": (
        "MERGE (s:Snapshot {id: $id}) "
        "SET s.json = $json, s.origin = $origin, s.data_mode = $data_mode, s.saved_at = datetime()"
    ),
    "load_snapshot": "MATCH (s:Snapshot {id: $id}) RETURN s.json AS json",
    "latest_snapshot": "MATCH (s:Snapshot) RETURN s.json AS json ORDER BY s.saved_at DESC LIMIT 1",
    "count_entities": "MATCH (n:Entity {snapshot_id: $id}) RETURN count(n) AS nodes",
    "count_snapshots": "MATCH (s:Snapshot {id: $id}) RETURN count(s) AS snapshots",
    "count_relations": "MATCH (a:Entity {snapshot_id: $id})-[r]->(:Entity) RETURN count(r) AS relations",
}
_NODES = {
    node_key(kind): (
        f"UNWIND $rows AS row CREATE (n:Entity:{node_label(kind)} "
        "{snapshot_id: $id, id: row.id, type: row.type, label: row.label})"
    )
    for kind in EntityType
}
_EDGES = {
    edge_key(relation): (
        "UNWIND $rows AS row "
        "MATCH (a:Entity {snapshot_id: $id, id: row.source}) "
        "MATCH (b:Entity {snapshot_id: $id, id: row.target}) "
        f"CREATE (a)-[:{relation.value.upper()}]->(b)"
    )
    for relation in Relation
}

TEMPLATES: Mapping[str, str] = MappingProxyType({**_BASE, **_NODES, **_EDGES})
