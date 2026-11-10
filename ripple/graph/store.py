"""연결 지도 저장소 인터페이스. 엔진·API는 이 인터페이스만 알고, 구현(메모리·Neo4j)은 바꿔 끼운다."""

from __future__ import annotations

from typing import Protocol

from ripple.contracts.domain import GraphSnapshot


class GraphStore(Protocol):
    def save(self, snapshot: GraphSnapshot) -> None: ...

    def load(self, snapshot_id: str) -> GraphSnapshot:
        """없는 ID면 KeyError."""
        ...

    def latest(self) -> GraphSnapshot | None: ...
