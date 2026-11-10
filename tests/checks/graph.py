"""지도 색인·저장소·부분 그래프의 성질. Neo4j는 서버 없이 가짜 실행기로 '고정 템플릿만 실행'을 확인한다."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from harness import Checker

from ripple.contracts.domain import EntityType, GraphSnapshot, Relation
from ripple.engine.index import GraphIndex
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.graph.cypher import TEMPLATES
from ripple.graph.memory import MemoryGraphStore
from ripple.graph.neo4j_store import Neo4jGraphStore
from ripple.graph.view import neighborhood


class FakeRunner:
    """실행된 쿼리를 기록하고 스냅샷 JSON만 흉내 내 돌려준다."""

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.parameters: list[dict[str, Any]] = []
        self.saved: dict[str, str] = {}
        self.transactions: list[list[str]] = []
        self.fail_after: int | None = None  # 트랜잭션의 n번째 쿼리에서 실패시키기

    def run_all(self, statements: Sequence[tuple[str, dict[str, Any]]]) -> None:
        staged = dict(self.saved)
        done: list[str] = []
        for number, (query, parameters) in enumerate(statements):
            if self.fail_after is not None and number >= self.fail_after:
                raise ConnectionError("연결이 끊겼어요(가짜)")
            self.queries.append(query)
            self.parameters.append(parameters)
            done.append(query)
            if query == TEMPLATES["save_snapshot"]:
                staged[parameters["id"]] = parameters["json"]
        self.saved = staged  # 모두 성공했을 때만 반영(트랜잭션)
        self.transactions.append(done)

    def run(self, query: str, parameters: dict[str, Any]) -> list[dict[str, Any]]:
        self.queries.append(query)
        self.parameters.append(parameters)
        if query == TEMPLATES["save_snapshot"]:
            self.saved[parameters["id"]] = parameters["json"]
        if query == TEMPLATES["load_snapshot"]:
            found = self.saved.get(parameters["id"])
            return [{"json": found}] if found else []
        if query == TEMPLATES["latest_snapshot"]:
            return [{"json": list(self.saved.values())[-1]}] if self.saved else []
        return []


def run(c: Checker) -> None:
    snapshot = generate(load_config()).snapshot
    index = GraphIndex(snapshot)
    _index(c, snapshot, index)
    _stores(c, snapshot)
    _view(c, index)


def _index(c: Checker, snapshot: GraphSnapshot, index: GraphIndex) -> None:
    c.section("지도 색인")
    c.check(
        "모든 부재가 자기 블록에 소속",
        all(index.out(p.part_id, Relation.PART_OF) == (p.block_id,) for p in snapshot.parts),
    )
    c.check(
        "모든 부재가 자기 발주 품목에서 공급",
        all(index.out(p.part_id, Relation.SUPPLIED_BY) == (index.line_of_part[p.part_id],) for p in snapshot.parts),
    )
    c.check(
        "부재끼리 연결은 양방향",
        all(
            x.a in index.out(x.b, Relation(x.kind.value)) and x.b in index.out(x.a, Relation(x.kind.value))
            for x in snapshot.connections
        ),
    )
    c.check(
        "발주 품목은 소비 공정으로 이어짐",
        all(index.out(li.line_id, Relation.CONSUMED_BY) == (li.consumed_by_activity_id,) for li in snapshot.po_lines),
    )
    first = snapshot.parts[0].part_id
    neighbours = index.neighbours(first)
    c.check("이웃 목록은 정렬돼 있음", list(neighbours) == sorted(neighbours))
    c.check("엔터티 종류를 알아봄", index.type_of(first) is EntityType.PART and index.type_of("없는-ID") is None)


def _stores(c: Checker, snapshot: GraphSnapshot) -> None:
    c.section("그래프 저장소")
    memory = MemoryGraphStore()
    c.check("빈 메모리 저장소의 최신 지도는 없음", memory.latest() is None)
    memory.save(snapshot)
    c.check("메모리 저장소 왕복이 같음", memory.load(snapshot.snapshot_id) == snapshot and memory.latest() == snapshot)
    c.check("없는 지도를 읽으면 KeyError", c.raises(lambda: memory.load("G-none"), KeyError))

    runner = FakeRunner()
    store = Neo4jGraphStore(runner)
    store.save(snapshot)
    templates = set(TEMPLATES.values())
    c.check("Neo4j에는 고정 템플릿만 실행", all(q in templates for q in runner.queries), len(runner.queries))
    c.check(
        "값은 매개변수로만 전달(쿼리에 지도 ID가 섞이지 않음)",
        not any(snapshot.snapshot_id in q for q in runner.queries),
    )
    node_rows = sum(
        len(p.get("rows", []))
        for q, p in zip(runner.queries, runner.parameters, strict=True)
        if q.startswith("UNWIND $rows AS row CREATE")
    )
    c.check("모든 엔터티가 노드로 저장됨", node_rows == len(GraphIndex(snapshot).entity_ids()), node_rows)
    c.check("Neo4j 저장소 왕복이 같음(원본 JSON)", store.load(snapshot.snapshot_id) == snapshot)
    c.check("Neo4j 최신 지도 조회", store.latest() == snapshot)
    c.check("Neo4j에서 없는 지도를 읽으면 KeyError", c.raises(lambda: store.load("G-none"), KeyError))
    transaction = runner.transactions[-1]
    c.check(
        "지도 교체는 한 트랜잭션이고 스냅샷 노드를 먼저 잠근 뒤 옛 엔터티를 지움(유일성 제약은 그 전에)",
        len(runner.transactions) == 1
        and TEMPLATES["create_snapshot_constraint"] in runner.queries[: runner.queries.index(transaction[0])]
        and transaction[0] == TEMPLATES["save_snapshot"]
        and transaction[1] == TEMPLATES["delete_entities"],
    )
    store.delete(snapshot.snapshot_id)
    c.check(
        "지도 삭제는 한 트랜잭션으로 엔터티와 스냅샷 노드를 지움",
        runner.transactions[-1] == [TEMPLATES["delete_entities"], TEMPLATES["delete_snapshot"]],
    )
    broken = FakeRunner()
    broken.fail_after = 3
    c.check(
        "저장 중 실패하면 아무것도 반영되지 않음(옛 그래프 유지)",
        c.raises(lambda: Neo4jGraphStore(broken).save(snapshot), ConnectionError) and not broken.saved,
    )


def _view(c: Checker, index: GraphIndex) -> None:
    c.section("화면용 부분 그래프")
    snapshot = index.snapshot
    center = next(p.part_id for p in snapshot.parts if p.block_id.endswith(":T31C"))
    alone = neighborhood(index, [center], depth=0)
    c.check("깊이 0이면 중심만", [n.id for n in alone.nodes] == [center] and not alone.edges)
    near = neighborhood(index, [center], depth=1)
    expected = {center} | {n for n, _ in index.neighbours(center)}
    c.check("깊이 1이면 중심과 직접 이웃", {n.id for n in near.nodes} == expected)
    c.check(
        "같은 요청이면 같은 부분 그래프", neighborhood(index, [center], depth=2) == neighborhood(index, [center], 2)
    )
    symmetric = [e for e in neighborhood(index, [center], depth=2).edges if e.relation is Relation.BUTT_WELD]
    pairs = {(e.source, e.target) for e in symmetric}
    c.check("양방향 연결은 한 번만 그림", all((t, s) not in pairs for s, t in pairs))
    small = neighborhood(index, [center], depth=3, max_nodes=10)
    c.check("노드 상한을 넘으면 잘렸다고 표시", small.truncated and len(small.nodes) == 10)
    c.check("없는 중심은 거부", c.raises(lambda: neighborhood(index, ["없는-ID"], 1), KeyError))
    c.check("노드 이름이 비어 있지 않음", all(n.label for n in near.nodes))
