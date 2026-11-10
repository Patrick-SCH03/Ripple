"""수정 기록 저장소(docs/input.md(문서 접수) 7절): 사람이 AI·규칙 제안을 받아들이고 고친 것을 덧붙이기만 하는 표에
남긴다.

기록·감사 사슬(records.sqlite3)과 따로 둔다 — 감사 확인에 영향이 없다. 실데이터 행에는 원문이 없다(계약이 막는다).
"""

from __future__ import annotations

import sqlite3
import threading
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

from ripple.contracts.corrections import CorrectionAction, CorrectionEvent, CorrectionRate, CorrectionSummary
from ripple.contracts.domain import DataMode

from .append_log import connect
from .gate import gate_of

FILE_NAME = "corrections.sqlite3"
SCHEMA = """
CREATE TABLE IF NOT EXISTS corrections (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    data_mode TEXT NOT NULL,
    event TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS corrections_at ON corrections (at);
"""


class CorrectionLogError(RuntimeError):
    """수정 기록 파일을 읽거나 쓰지 못함(명사형)."""


class CorrectionLog:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / FILE_NAME
        self._lock = threading.Lock()
        self._gate = gate_of(data_dir)

    def append(self, events: Sequence[CorrectionEvent]) -> None:
        if not events:
            return
        with self._gate.shared(), self._lock:  # 바꿔 끼우는 동안은 기다림(gate.py)
            connection = connect(self.path, SCHEMA)
            try:
                with connection:
                    connection.executemany(
                        "INSERT INTO corrections (at, data_mode, event) VALUES (?, ?, ?)",
                        [(e.at.isoformat(), e.data_mode.value, e.model_dump_json()) for e in events],
                    )
            except sqlite3.Error as error:
                raise CorrectionLogError(f"수정 기록 저장 실패({error})") from error
            finally:
                connection.close()

    def events(self, since: datetime | None = None, include_real: bool = True) -> list[CorrectionEvent]:
        with self._gate.shared(), self._lock:  # 바꿔 끼우는 동안은 기다림(gate.py)
            if not self.path.exists():
                return []
            connection = connect(self.path, SCHEMA)
            try:
                query = "SELECT event FROM corrections WHERE (? IS NULL OR at >= ?)"
                params: list[object] = [None if since is None else since.isoformat()] * 2
                if not include_real:
                    query += " AND data_mode = ?"
                    params.append(DataMode.SYNTHETIC.value)
                rows = connection.execute(query + " ORDER BY seq", params).fetchall()
            except sqlite3.Error as error:
                raise CorrectionLogError(f"수정 기록 읽기 실패({error})") from error
            finally:
                connection.close()
        return [CorrectionEvent.model_validate_json(row[0]) for row in rows]


def summarize(events: Iterable[CorrectionEvent], since: datetime | None = None) -> CorrectionSummary:
    """칸·채움 방식·항목별 사람 결정 집계. 체험·개발 모드 행은 빼고 개수만 센다."""
    counted: dict[str, dict[CorrectionAction, int]] = defaultdict(lambda: defaultdict(int))
    rows = excluded = 0
    for event in events:
        if event.demo or event.dev:
            excluded += 1
            continue
        rows += 1
        keys = ["item"] if event.slot == "item" else [f"slot:{event.slot}"]
        if event.method and event.slot != "item":
            keys.append(f"method:{event.method}")
        if event.extractor:
            keys.append(f"extractor:{event.extractor}")
        for key in keys:
            counted[key][event.action] += 1
    rates = tuple(
        CorrectionRate(
            key=key,
            decided=sum(actions.values()),
            accepted=actions[CorrectionAction.ACCEPT],
            edited=actions[CorrectionAction.EDIT] + actions[CorrectionAction.ADD],
            dropped=actions[CorrectionAction.DROP],
            handed_off=actions[CorrectionAction.HANDOFF],
        )
        for key, actions in sorted(counted.items())
    )
    return CorrectionSummary(since=since, rows=rows, excluded=excluded, rates=rates)
