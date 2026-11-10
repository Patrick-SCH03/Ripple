"""설정에 맞는 지도 저장소를 연다. Neo4j 비밀번호는 여기서만 환경 변수에서 읽고 남기지 않는다."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ripple.config.settings import Settings

from .memory import MemoryGraphStore
from .neo4j_store import DriverRunner, Neo4jGraphStore
from .store import GraphStore


@dataclass(frozen=True, slots=True)
class OpenedStore:
    store: GraphStore
    close: Callable[[], None]


def open_store(settings: Settings, env: Mapping[str, str] | None = None) -> OpenedStore:
    if settings.graph_store == "memory":
        return OpenedStore(MemoryGraphStore(), lambda: None)
    password = (os.environ if env is None else env).get("NEO4J_PASSWORD")
    if not password:
        raise ValueError("RIPPLE_GRAPH_STORE=neo4j에는 NEO4J_PASSWORD 환경 변수 필요")
    runner = DriverRunner(settings.neo4j_uri, settings.neo4j_user, password)
    return OpenedStore(Neo4jGraphStore(runner), runner.close)
