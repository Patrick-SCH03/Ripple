"""로그인 실패 제한: 아이디마다 15분 안에 5번 틀리면 그 창이 끝날 때까지 막는다(메모리, 서버를 다시 켜면 비워짐).

클라이언트 IP는 쓰지 않는다 — Railway 앞단의 X-Forwarded-For·X-Real-IP를 어디까지 믿을지 공식 문서로 정해져 있지 않아,
IP로 묶으면 모든 사용자가 한 IP로 보여 한 사람의 실패가 모두를 막을 수 있다(docs/operations.md(서비스) 2절).

검사 중인 시도도 센다: 잠금 확인과 실패 기록 사이에 비밀번호 해시 대기가 끼므로, 확인할 때 자리(reserve)를 잡고
결과를 적은 뒤 돌려준다(release). 최근 실패 + 검사 중인 시도가 상한이면 막는다 — 동시에 들어온 요청이 함께 확인을
지나 상한보다 많이 검사되지 않게.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict, deque

WINDOW_S = 15 * 60
LIMIT = 5
MAX_KEYS = 10_000  # 없는 아이디를 계속 넣어도 메모리가 끝없이 늘지 않게(오래된 것부터 버림)
BUSY_RETRY_S = 1
"""실패는 상한 아래인데 검사 중인 시도로 자리가 찬 경우 다시 해도 되는 때(검사는 몇 초 안에 끝난다)."""


class LoginThrottle:
    def __init__(self, *, window_s: float = WINDOW_S, limit: int = LIMIT) -> None:
        self.window_s = window_s
        self.limit = limit
        self._lock = threading.Lock()
        self._failures: OrderedDict[str, deque[float]] = OrderedDict()
        self._pending: dict[str, int] = {}

    def retry_after(self, key: str, now: float) -> int | None:
        """막혀 있으면 다시 해도 되는 때까지 남은 초(올림), 아니면 None."""
        with self._lock:
            return self._wait(key, now)

    def reserve(self, key: str, now: float) -> int | None:
        """한 번 검사할 자리를 잡는다. 막혀 있으면 남은 초(자리를 잡지 않음). 잡았으면 None — 결과(fail·succeed)를
        적은 뒤 release로 꼭 돌려준다."""
        with self._lock:
            wait = self._wait(key, now)
            if wait is None:
                self._pending[key] = self._pending.get(key, 0) + 1
            return wait

    def release(self, key: str) -> None:
        with self._lock:
            left = self._pending.get(key, 0) - 1
            if left > 0:
                self._pending[key] = left
            else:
                self._pending.pop(key, None)

    def fail(self, key: str, now: float) -> None:
        with self._lock:
            times = self._recent(key, now)
            times.append(now)
            self._failures[key] = times
            self._failures.move_to_end(key)
            while len(self._failures) > MAX_KEYS:
                self._failures.popitem(last=False)

    def succeed(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def _wait(self, key: str, now: float) -> int | None:
        """잠금 안: 최근 실패 + 검사 중인 시도가 상한이면 남은 초."""
        times = self._recent(key, now)
        if len(times) >= self.limit:
            return max(1, math.ceil(times[0] + self.window_s - now))
        if len(times) + self._pending.get(key, 0) >= self.limit:
            return BUSY_RETRY_S
        return None

    def _recent(self, key: str, now: float) -> deque[float]:
        times = self._failures.get(key, deque())
        while times and times[0] <= now - self.window_s:
            times.popleft()
        return times
