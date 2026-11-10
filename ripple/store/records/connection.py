"""기록 파일 연결과 트랜잭션: 쓰기는 프로세스 잠금 + BEGIN IMMEDIATE, 읽기는 잠금 없이 한 시점(WAL)."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

from ..gate import gate_of

Transaction = Callable[[], AbstractContextManager[sqlite3.Connection]]
"""트랜잭션 하나를 여는 함수(쓰기·읽기 협력 객체가 받는다)."""


class Connections:
    """기록 파일 하나의 연결. 서버 한 대 전제(복제본 없음)라 잠금은 프로세스 안의 것 하나로 충분하다."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self._gate = gate_of(path.parent)  # 시연 기록을 바꿔 끼우는 동안은 연결을 열지 않는다

    @contextmanager
    def open(self) -> Iterator[sqlite3.Connection]:
        with self._gate.shared():
            db = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
            try:
                db.execute("PRAGMA foreign_keys = ON")
                db.execute("PRAGMA synchronous = FULL")
                yield db
            finally:
                db.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """읽기 한 트랜잭션: 그 안의 SELECT는 모두 같은 시점(WAL 스냅숏)을 본다.
        보기 범위(실데이터) 판단과 돌려줄 내용이 사이에 들어온 커밋으로 어긋나지 않게."""
        with self.open() as db:
            db.execute("BEGIN")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """한 트랜잭션: 블록이 예외 없이 끝나면 커밋, 아니면 모두 되돌린다."""
        with self.lock, self.open() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")
