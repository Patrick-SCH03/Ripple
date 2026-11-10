"""Neo4j 저장소. 스냅샷 원본 JSON을 스냅샷 노드에 두어 load가 계약과 그대로 같게 되돌린다.
엔터티 노드·관계는 조회와 Neo4j Browser 시각화용이다. 모든 쿼리는 cypher.TEMPLATES에서만 고른다.

지도 교체(스냅샷 노드 → 옛 엔터티 삭제 → 노드·관계 생성)는 한 쓰기 트랜잭션이다. 중간에 실패하면 옛 그래프가
그대로 남는다. 스냅샷 ID에 유일성 제약을 두고 스냅샷 노드를 먼저 MERGE해 잠그므로, 아직 없는 지도를 동시에
처음 저장해도 노드가 하나만 생기고 차례로 처리된다(제약 없는 MERGE는 동시 생성을 막지 못함).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any, Protocol

from ripple.contracts.domain import EntityType, GraphSnapshot, Relation
from ripple.engine.describe import describe
from ripple.engine.index import GraphIndex

from .cypher import TEMPLATES, edge_key, node_key

Row = dict[str, Any]
Statement = tuple[str, dict[str, Any]]


class CypherRunner(Protocol):
    def run(self, query: str, parameters: dict[str, Any]) -> list[Row]: ...

    def run_all(self, statements: Sequence[Statement]) -> None:
        """여러 쓰기 쿼리를 한 트랜잭션으로(하나라도 실패하면 모두 되돌림)."""
        ...


class DriverRunner:
    """neo4j 공식 드라이버 위의 실행기."""

    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j") -> None:
        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._database = database

    def run(self, query: str, parameters: dict[str, Any]) -> list[Row]:
        records, _, _ = self._driver.execute_query(query, parameters, database_=self._database)
        return [dict(record.data()) for record in records]

    def run_all(self, statements: Sequence[Statement]) -> None:
        def work(tx: Any) -> None:
            for query, parameters in statements:
                tx.run(query, parameters).consume()

        with self._driver.session(database=self._database) as session:
            session.execute_write(work)

    def close(self) -> None:
        self._driver.close()


class Neo4jGraphStore:
    def __init__(self, runner: CypherRunner) -> None:
        self._runner = runner

    def save(self, snapshot: GraphSnapshot) -> None:
        index = GraphIndex(snapshot)
        self._run("create_index")  # 스키마 변경은 데이터 쓰기와 한 트랜잭션에 넣을 수 없다
        self._run("create_snapshot_constraint")
        key = snapshot.snapshot_id
        statements: list[Statement] = [
            (
                TEMPLATES["save_snapshot"],
                {
                    "id": key,
                    "json": snapshot.model_dump_json(),
                    "origin": snapshot.origin,
                    "data_mode": snapshot.data_mode.value,
                },
            ),
            (TEMPLATES["delete_entities"], {"id": key}),
        ]
        nodes: dict[EntityType, list[Row]] = defaultdict(list)
        for entity_id in sorted(index.entity_ids()):
            node = describe(index, entity_id)
            nodes[node.type].append({"id": node.id, "type": node.type.value, "label": node.label})
        statements += [(TEMPLATES[node_key(k)], {"id": key, "rows": nodes[k]}) for k in EntityType if nodes[k]]
        edges: dict[Relation, list[Row]] = defaultdict(list)
        for edge in index.edges():
            edges[edge.relation].append({"source": edge.source, "target": edge.target})
        statements += [(TEMPLATES[edge_key(r)], {"id": key, "rows": edges[r]}) for r in Relation if edges[r]]
        self._runner.run_all(statements)

    def delete(self, snapshot_id: str) -> None:
        """지도 하나를 통째로 지운다(엔터티·관계·스냅샷 노드를 한 트랜잭션으로)."""
        self._runner.run_all(
            [(TEMPLATES["delete_entities"], {"id": snapshot_id}), (TEMPLATES["delete_snapshot"], {"id": snapshot_id})]
        )

    def load(self, snapshot_id: str) -> GraphSnapshot:
        rows = self._run("load_snapshot", id=snapshot_id)
        if not rows:
            raise KeyError(f"저장된 지도 없음: {snapshot_id}")
        return GraphSnapshot.model_validate_json(rows[0]["json"])

    def latest(self) -> GraphSnapshot | None:
        rows = self._run("latest_snapshot")
        return GraphSnapshot.model_validate_json(rows[0]["json"]) if rows else None

    def count_entities(self, snapshot_id: str) -> int:
        rows = self._run("count_entities", id=snapshot_id)
        return int(rows[0]["nodes"]) if rows else 0

    def count_snapshots(self, snapshot_id: str) -> int:
        rows = self._run("count_snapshots", id=snapshot_id)
        return int(rows[0]["snapshots"]) if rows else 0

    def count_relations(self, snapshot_id: str) -> int:
        rows = self._run("count_relations", id=snapshot_id)
        return int(rows[0]["relations"]) if rows else 0

    def _run(self, key: str, **parameters: Any) -> list[Row]:
        return self._runner.run(TEMPLATES[key], parameters)
