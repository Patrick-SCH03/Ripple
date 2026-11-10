"""외부 AI 사용량 한도(docs/input.md(외부 AI) 6절): 하루(KST) 전체·계정당 외부 모델 호출 수.

단위는 실제 외부 모델 호출 한 번이다(헤지로 두 모델을 부르면 두 번). 호출 직전에 잠금 안에서 확인하고 늘리며(예약),
예약하지 못하면 그 모델을 부르지 않는다 — 비서는 지금처럼 서버 규칙 해석·기본 설명으로 간다.
누가 부르는지는 비서 경로가 요청 범위로 알려 준다(acting_as). 헤지 스레드는 이 값을 물려받지 않으므로 경로(Router)가
요청 스레드에서 읽어 둔 값을 쓴다.

기록: 데이터 폴더 llm_usage.json({날짜, 전체, 계정별}) — 고유한 임시 파일에 쓰고 디스크에 내린 뒤 바꿔 끼운다.
재시작해도 그날 수는 남고, 날짜가 바뀌면 0부터. 파일이 깨졌으면 그날 한도를 다 쓴 것으로 본다(넘치지 않는 쪽).
쓰기에 실패하면 그 호출은 부르지 않고 세지도 않는다(저장소가 돌아오면 남은 한도 그대로). 서버 한 대 전제(복제본 없음).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pydantic import Field

from ripple.config.files import write_atomic
from ripple.contracts.base import Frozen

from .base import LlmUnavailable

KST = timezone(timedelta(hours=9))  # 서머타임 없음
FILE_NAME = "llm_usage.json"
UNKNOWN = "(unknown)"  # 계정을 모르는 호출(개발 모드·검사)의 몫


class QuotaLimits(Frozen):
    """params/llm_v1.yaml의 quota 절. 0이면 그 한도로는 아무 호출도 받지 않는다."""

    daily_total: int = Field(ge=0)
    daily_per_account: int = Field(ge=0)


class QuotaExceeded(LlmUnavailable):
    """오늘 한도를 다 써서 외부 모델을 부르지 않았다."""


@dataclass(slots=True)
class TurnUsage:
    """한 요청(비서 차례) 동안 한도 때문에 부르지 못한 호출이 있었는가. 헤지 스레드에서도 쓴다."""

    limited: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def mark(self) -> None:
        with self._lock:
            self.limited = True


_actor: ContextVar[str | None] = ContextVar("llm_actor", default=None)
_usage: ContextVar[TurnUsage | None] = ContextVar("llm_usage", default=None)


@contextmanager
def acting_as(login_id: str) -> Iterator[TurnUsage]:
    """이 요청의 외부 호출을 login_id의 몫으로 센다. 끝나면 이전 값으로 되돌린다."""
    usage = TurnUsage()
    actor_token = _actor.set(login_id)
    usage_token = _usage.set(usage)
    try:
        yield usage
    finally:
        _actor.reset(actor_token)
        _usage.reset(usage_token)


def current_actor() -> str:
    return _actor.get() or UNKNOWN


def current_usage() -> TurnUsage | None:
    return _usage.get()


def limited_now() -> bool:
    usage = _usage.get()
    return usage is not None and usage.limited


class UsageLedger:
    """하루 호출 수 장부. reserve가 True면 그 호출을 부를 수 있다(이미 센 뒤)."""

    def __init__(self, path: Path, limits: QuotaLimits, clock: Callable[[], datetime] = lambda: datetime.now(KST)):
        self.path = path
        self.limits = limits
        self._clock = clock
        self._lock = threading.Lock()
        self._day: date | None = None
        self._total = 0
        self._accounts: dict[str, int] = {}
        self._load()

    def reserve(self, account: str) -> bool:
        """한도 안이면 세고 True. 파일에 먼저 쓰고 성공해야 메모리에 반영한다 — 쓰기에 실패하면 그 호출은 부르지 않고
        (LlmUnavailable) 세지도 않으므로, 저장소가 돌아오면 남은 한도를 그대로 쓴다."""
        with self._lock:
            self._roll()
            used = self._accounts.get(account, 0)
            if self._total >= self.limits.daily_total or used >= self.limits.daily_per_account:
                return False
            accounts = {**self._accounts, account: used + 1}
            try:
                self._save(self._total + 1, accounts)
            except OSError as error:
                raise LlmUnavailable("사용량 기록 실패 · 외부 AI 호출 안 함") from error
            self._total, self._accounts = self._total + 1, accounts
            return True

    def snapshot(self) -> tuple[date | None, int, dict[str, int]]:
        with self._lock:
            self._roll()
            return self._day, self._total, dict(self._accounts)

    def _today(self) -> date:
        return self._clock().astimezone(KST).date()

    def _roll(self) -> None:
        today = self._today()
        if self._day != today:
            self._day, self._total, self._accounts = today, 0, {}

    def _load(self) -> None:
        today = self._today()
        self._day = today
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            day = date.fromisoformat(data["date"])
            total = int(data["total"])
            accounts = {str(k): int(v) for k, v in data["accounts"].items()}
            if total < 0 or any(v < 0 for v in accounts.values()):
                raise ValueError("음수 사용량")
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self._total = self.limits.daily_total  # 깨진 장부 = 오늘 한도를 다 쓴 것(넘치지 않는 쪽)
            return
        if day == today:
            self._total, self._accounts = total, accounts

    def _save(self, total: int, accounts: dict[str, int]) -> None:
        """고유한 임시 파일 → 디스크에 내림 → 바꿔 끼우기(ripple/config/files.py write_atomic, Windows 짧은 잠금에 다시
        시도). 실패하면 임시 파일을 지우고 원래 장부는 그대로 — 호출자가 그 호출을 부르지 않는다."""
        assert self._day is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = {"date": self._day.isoformat(), "total": total, "accounts": accounts}
        write_atomic(self.path, json.dumps(body, ensure_ascii=False, sort_keys=True))
