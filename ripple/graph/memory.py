"""메모리 저장소: 테스트와 오프라인 시연용."""

from __future__ import annotations

from ripple.contracts.domain import GraphSnapshot


class MemoryGraphStore:
    def __init__(self) -> None:
        self._snapshots: dict[str, GraphSnapshot] = {}
        self._latest: str | None = None

    def save(self, snapshot: GraphSnapshot) -> None:
        self._snapshots[snapshot.snapshot_id] = snapshot
        self._latest = snapshot.snapshot_id

    def load(self, snapshot_id: str) -> GraphSnapshot:
        try:
            return self._snapshots[snapshot_id]
        except KeyError:
            raise KeyError(f"저장된 지도 없음: {snapshot_id}") from None

    def latest(self) -> GraphSnapshot | None:
        return None if self._latest is None else self._snapshots[self._latest]
