"""메모리 TTL 보관(제네릭): 문서 접수 제안처럼 잠깐 들고 있다가 버리는 값. 서버를 다시 켜면 비워진다."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable


class TtlStore[T]:
    def __init__(self, ttl_s: float = 7200.0, limit: int = 200, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_s
        self._limit = limit
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, key: str, value: T) -> None:
        with self._lock:
            self._sweep()
            self._items[key] = (self._clock() + self._ttl, value)
            self._items.move_to_end(key)
            while len(self._items) > self._limit:
                self._items.popitem(last=False)

    def get(self, key: str) -> T | None:
        with self._lock:
            self._sweep()
            found = self._items.get(key)
            return None if found is None else found[1]

    def pop(self, key: str) -> T | None:
        """꺼내며 지운다(한 번만 쓰는 값 — 확정한 제안을 두 번 확정하지 않게)."""
        with self._lock:
            self._sweep()
            found = self._items.pop(key, None)
            return None if found is None else found[1]

    def __len__(self) -> int:
        with self._lock:
            self._sweep()
            return len(self._items)

    def _sweep(self) -> None:
        now = self._clock()
        expired = [k for k, (until, _) in self._items.items() if until <= now]
        for key in expired:
            del self._items[key]
