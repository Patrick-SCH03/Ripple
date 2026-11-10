"""상태 갱신 기록(docs/domain.md 12절): 적용한 갱신을 덧붙이기만 하는 표에 남긴다.

지도는 내용 해시라 값이 원래로 돌아가면 예전 지도 ID가 다시 나오지만, 누가·언제·무엇을 바꿨는지는 여기에 따로 남는다.
원문 항목(출처 포함)도 함께 저장한다. 고치거나 지우는 API는 없다.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from ripple.contracts.updates import StatusUpdate, UpdateEvent

from .append_log import connect

FILE_NAME = "updates.sqlite3"
SCHEMA = """
CREATE TABLE IF NOT EXISTS updates (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    snapshot_id TEXT NOT NULL,
    event TEXT NOT NULL,
    items TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS updates_snapshot ON updates (snapshot_id);
"""


def _insert(connection: sqlite3.Connection, event: UpdateEvent, update: StatusUpdate) -> None:
    connection.execute(
        "INSERT INTO updates (event_id, snapshot_id, event, items) VALUES (?, ?, ?, ?)",
        (event.event_id, event.snapshot_id, event.model_dump_json(), update.model_dump_json()),
    )


class UpdateLogError(RuntimeError):
    """기록 파일을 읽거나 쓰지 못함(명사형)."""


class UpdateLog:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / FILE_NAME
        self._lock = threading.Lock()

    def append(self, event: UpdateEvent, update: StatusUpdate) -> None:
        with self._lock:
            connection = connect(self.path, SCHEMA)
            try:
                with connection:
                    _insert(connection, event, update)
            except sqlite3.Error as error:
                raise UpdateLogError(f"상태 갱신 기록 저장 실패({error})") from error
            finally:
                connection.close()

    @contextmanager
    def recording(self, event: UpdateEvent, update: StatusUpdate, undo: Callable[[], None]) -> Iterator[None]:
        """기록을 넣고 안의 일(지도 활성 전환)이 끝나면 확정, 실패하면 되돌린다.

        적용되지 않은 갱신이 기록에 남지 않게. 안의 일은 됐는데 확정이 실패하면 undo(안의 일 되돌리기)를 부른 뒤
        UpdateLogError — 기록 없는 갱신 지도가 활성으로 남지 않게.
        """
        with self._lock:
            connection = connect(self.path, SCHEMA)
            try:
                _insert(connection, event, update)
            except sqlite3.Error as error:
                connection.close()
                raise UpdateLogError(f"상태 갱신 기록 저장 실패({error})") from error
            try:
                try:
                    yield
                except BaseException:
                    connection.rollback()
                    raise
                try:
                    connection.commit()
                except sqlite3.Error as error:
                    connection.rollback()
                    undo()
                    raise UpdateLogError(f"상태 갱신 기록 저장 실패({error})") from error
            finally:
                connection.close()

    def known(self, event_ids: Iterable[str]) -> set[str]:
        """기록에 있는(확정된) 갱신 ID."""
        wanted = list(dict.fromkeys(event_ids))
        if not wanted or not self.path.exists():
            return set()
        with self._lock:
            connection = connect(self.path, SCHEMA)
            try:
                marks = ",".join("?" for _ in wanted)
                rows = connection.execute(
                    f"SELECT event_id FROM updates WHERE event_id IN ({marks})", wanted
                ).fetchall()
            finally:
                connection.close()
        return {row[0] for row in rows}

    def recent(self, limit: int = 50) -> tuple[UpdateEvent, ...]:
        """최근 것부터."""
        with self._lock:
            if not self.path.exists():
                return ()
            connection = connect(self.path, SCHEMA)
            try:
                rows = connection.execute("SELECT event FROM updates ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
            finally:
                connection.close()
        return tuple(UpdateEvent.model_validate_json(row[0]) for row in rows)
