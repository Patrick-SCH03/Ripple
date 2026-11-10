"""실적 기록(docs/records.md(기록·결재) 11절): 실행·종료한 설계변경의 실제 비용·지연을 덧붙이기만 하는 표에 남긴다.

기록·감사 사슬(records.sqlite3)과 따로 둔다 — 감사 확인에 영향이 없다.
고치면 새 줄을 더하고, ECN마다 마지막 줄이 지금 값이다.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ripple.contracts.outcomes import OutcomeEntry

from .append_log import connect
from .gate import gate_of

FILE_NAME = "outcomes.sqlite3"
SCHEMA = """
CREATE TABLE IF NOT EXISTS outcomes (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ecn_id TEXT NOT NULL,
    entry TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS outcomes_ecn ON outcomes (ecn_id, seq);
"""


class OutcomeLogError(RuntimeError):
    """실적 파일을 읽거나 쓰지 못함(명사형)."""


class OutcomeLog:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / FILE_NAME
        self._lock = threading.Lock()
        self._gate = gate_of(data_dir)

    def append(self, entry: OutcomeEntry) -> None:
        with self._gate.shared(), self._lock:  # 바꿔 끼우는 동안은 기다림(gate.py)
            connection = connect(self.path, SCHEMA)
            try:
                with connection:
                    connection.execute(
                        "INSERT INTO outcomes (ecn_id, entry) VALUES (?, ?)", (entry.ecn_id, entry.model_dump_json())
                    )
            except sqlite3.Error as error:
                raise OutcomeLogError(f"실적 저장 실패({error})") from error
            finally:
                connection.close()

    def latest(self) -> dict[str, OutcomeEntry]:
        """ECN마다 마지막 줄(지금 값)."""
        with self._gate.shared(), self._lock:  # 바꿔 끼우는 동안은 기다림(gate.py)
            if not self.path.exists():
                return {}
            connection = connect(self.path, SCHEMA)
            try:
                rows = connection.execute(
                    "SELECT o.entry FROM outcomes o "
                    "JOIN (SELECT ecn_id, MAX(seq) AS seq FROM outcomes GROUP BY ecn_id) m "
                    "ON o.seq = m.seq ORDER BY o.ecn_id"
                ).fetchall()
            except sqlite3.Error as error:
                raise OutcomeLogError(f"실적 읽기 실패({error})") from error
            finally:
                connection.close()
        entries = (OutcomeEntry.model_validate_json(row[0]) for row in rows)
        return {entry.ecn_id: entry for entry in entries}

    def get(self, ecn_id: str) -> OutcomeEntry | None:
        return self.latest().get(ecn_id)
