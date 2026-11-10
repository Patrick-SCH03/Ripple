"""Neo4j 통합 검사(서버 필요, CI에서는 돌리지 않음).

실행: docker compose up -d neo4j  →  uv run python tests/integration/neo4j_roundtrip.py
.env의 NEO4J_PASSWORD를 읽는다(값은 출력하지 않음).
"""

from __future__ import annotations

import io
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ripple.config.settings import PROJECT_ROOT
from ripple.engine.index import GraphIndex
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.graph.neo4j_store import DriverRunner, Neo4jGraphStore


def env_value(name: str, env_file: Path = PROJECT_ROOT / ".env") -> str | None:
    if name in os.environ:
        return os.environ[name]
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip()
    return None


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    password = env_value("NEO4J_PASSWORD")
    if not password:
        print("NEO4J_PASSWORD가 없어요(.env)")
        return 2
    uri = env_value("NEO4J_URI") or "bolt://127.0.0.1:7687"
    runner = DriverRunner(uri, "neo4j", password)
    try:
        store = Neo4jGraphStore(runner)
        snapshot = generate(load_config()).snapshot
        store.save(snapshot)
        loaded = store.load(snapshot.snapshot_id)
        expected_nodes = len(GraphIndex(snapshot).entity_ids())
        stored_nodes = store.count_entities(snapshot.snapshot_id)
        expected_edges = sum(1 for _ in GraphIndex(snapshot).edges())
        stored_edges = store.count_relations(snapshot.snapshot_id)
        store.save(snapshot)  # 같은 지도를 다시 저장해도 노드가 늘지 않아야 한다
        again = store.count_entities(snapshot.snapshot_id)
        latest = store.latest()
    finally:
        runner.close()
    fresh = generate(load_config(), 20261021).snapshot  # 이 서버에 아직 없는 지도
    runners = [DriverRunner(uri, "neo4j", password) for _ in range(2)]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda r: Neo4jGraphStore(r).save(fresh), runners))
        checker = Neo4jGraphStore(runners[0])
        fresh_snapshots = checker.count_snapshots(fresh.snapshot_id)
        fresh_nodes = checker.count_entities(fresh.snapshot_id)
        checker.delete(fresh.snapshot_id)  # 시험용 지도는 서버에 남기지 않는다
        cleaned = checker.count_snapshots(fresh.snapshot_id) == 0 and checker.count_entities(fresh.snapshot_id) == 0
    finally:
        for r in runners:
            r.close()
    results = {
        "왕복 동일(원본 JSON)": loaded == snapshot,
        "없는 지도를 동시에 처음 저장해도 스냅샷 노드 하나": fresh_snapshots == 1,
        "시험용 지도를 지우면 스냅샷·엔터티가 모두 사라짐": cleaned,
        f"동시 저장 뒤 엔터티 노드 수 = {len(GraphIndex(fresh).entity_ids())}": fresh_nodes
        == len(GraphIndex(fresh).entity_ids()),
        f"엔터티 노드 수 = {expected_nodes}": stored_nodes == expected_nodes,
        f"관계 수 = {expected_edges}": stored_edges == expected_edges,
        "다시 저장해도 노드 수 그대로": again == stored_nodes,
        "최신 지도 = 방금 저장한 지도": latest is not None and latest.snapshot_id == snapshot.snapshot_id,
    }
    for name, ok in results.items():
        print("  ✓" if ok else "  ✗", name)
    print(f"스냅샷 {snapshot.snapshot_id}, 노드 {stored_nodes}개")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
