"""데이터 폴더의 기록 파일 문(docs/operations.md(서비스) 7절): 시연 기록을 날마다 새로 채울 때 파일을 바꿔 끼우는
동안 다른 연결이 열리지 않게 한다.

- 기록·실적·수정 기록 저장소(records.sqlite3 · outcomes.sqlite3 · corrections.sqlite3)는 연결을 열 때마다 '함께' 문을
  지난다(동시에 여럿). 파일을 바꿔 끼우는 쪽은 '혼자' 문을 잡고, 열린 연결이 모두 닫힐 때까지 기다린 뒤 옮긴다 —
  한 트랜잭션은 옛 파일만 보거나 새 파일만 본다(반쯤 바뀐 폴더를 보지 않음). 열린 SQLite 파일을 옮기지 않는다.
- '혼자'를 기다리는 쪽이 있으면 새 '함께'는 그 뒤에 선다(바꿔 끼우기가 굶지 않게). 같은 스레드가 이미 '함께'를 잡고
  있으면 다시 잡을 때 기다리지 않고(중첩 연결), '혼자'를 잡은 스레드의 '함께'도 바로 지난다.
- 폴더마다 문 하나(프로세스 안, 서버 한 대 전제 — ripple/store/records/connection.py와 같음).
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

WAIT_S = 30.0  # '혼자'가 열린 연결을 기다리는 상한(넘으면 TimeoutError — 바꿔 끼우기를 포기)


class FileGate:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._shared = 0
        self._owner: int | None = None  # '혼자'를 잡은 스레드
        self._waiting = 0  # '혼자'를 기다리는 수
        self._local = threading.local()

    @contextmanager
    def shared(self) -> Iterator[None]:
        me = threading.get_ident()
        depth: int = getattr(self._local, "depth", 0)
        with self._cond:
            if self._owner == me:
                counted = False
            else:
                if depth == 0:
                    while self._owner is not None or self._waiting:
                        self._cond.wait()
                self._shared += 1
                counted = True
        self._local.depth = depth + 1
        try:
            yield
        finally:
            self._local.depth = depth
            if counted:
                with self._cond:
                    self._shared -= 1
                    self._cond.notify_all()

    @contextmanager
    def exclusive(self, wait_s: float = WAIT_S) -> Iterator[None]:
        """열린 연결이 모두 닫힐 때까지 기다린 뒤 혼자. 그 사이 새 연결은 기다린다. wait_s를 넘으면 TimeoutError."""
        me = threading.get_ident()
        with self._cond:
            if self._owner == me:
                raise RuntimeError("기록 파일 문 중첩 잠금")
            self._waiting += 1
            try:
                ready = self._cond.wait_for(lambda: self._owner is None and self._shared == 0, timeout=wait_s)
            finally:
                self._waiting -= 1
            if not ready:
                self._cond.notify_all()
                raise TimeoutError(f"기록 파일 사용 중 — {wait_s:.0f}초 안에 연결이 닫히지 않음")
            self._owner = me
        try:
            yield
        finally:
            with self._cond:
                self._owner = None
                self._cond.notify_all()


_GATES: dict[str, FileGate] = {}
_GATES_LOCK = threading.Lock()


def gate_of(folder: Path) -> FileGate:
    """그 데이터 폴더의 문(같은 폴더면 같은 문)."""
    key = os.path.normcase(os.path.abspath(folder))
    with _GATES_LOCK:
        gate = _GATES.get(key)
        if gate is None:
            gate = _GATES[key] = FileGate()
        return gate
