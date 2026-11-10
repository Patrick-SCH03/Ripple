"""작업별 생성 모델 경로와 헤지 전환(params/llm_v1.yaml).

작업(rewrite: 해석 보조, explain: 설명 고르기)마다 (제공자, 모델) 순서 목록이 있다. 첫 모델이 hedge_after_s 안에
받아들일 만한 답(작업 검사 통과)을 못 주면 — 실패하면 바로 — 다음 모델을 함께 시작해 먼저 온 받아들일 만한 답을
쓴다. 전체 budget_s가 지나면 더 기다리지 않는다(늦게 끝난 호출은 버리고, 호출 기록은 어댑터가 남긴다).
모델을 바꿔도 숫자·판정은 엔진이 만들므로 분석 결과는 같다.
사용량 장부(ripple/llm/quota.py)가 있으면 모델마다 부르기 직전에 한도를 예약하고, 못 하면 그 모델을 부르지 않는다.
실제로 부른 호출은 최근 CALL_LOG개를 메모리에 남긴다(시각·작업·모델·성공 여부·걸린 시간 — 관리자 화면 'AI 호출 기록').
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from ripple.config.loaders import read_yaml
from ripple.contracts.base import Frozen
from ripple.contracts.system import LlmCall

from .base import Accept, JsonModel, LlmUnavailable, Schema
from .quota import QuotaExceeded, QuotaLimits, TurnUsage, UsageLedger, current_actor, current_usage

PROVIDERS = ("claude",)
CALL_LOG = 200


class ModelSpec(Frozen):
    provider: Literal["claude"]
    model: str = Field(min_length=1)
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None  # 생각 깊이, 없으면 모델 기본


class RouteSpec(Frozen):
    hedge_after_s: float = Field(gt=0)
    budget_s: float = Field(gt=0)
    models: tuple[ModelSpec, ...] = Field(min_length=1)


class LlmRoutes(Frozen):
    version: str
    routes: dict[str, RouteSpec]
    quota: QuotaLimits | None = None  # 있으면 하루 호출 한도, 없으면 한도 없음(지금 기본)


def load_routes(path: Path) -> LlmRoutes:
    return LlmRoutes.model_validate(read_yaml(path))


@dataclass(frozen=True, slots=True)
class Route:
    models: tuple[JsonModel, ...]
    hedge_after_s: float
    budget_s: float


class Router:
    """작업 이름으로 경로를 골라 헤지 전환으로 부른다(Guarded가 작업 이름·작업 검사를 넘긴다)."""

    def __init__(
        self,
        routes: Mapping[str, Route],
        version: str = "",
        workers: int = 16,
        ledger: UsageLedger | None = None,
    ) -> None:
        self.routes = dict(routes)
        self.version = version
        self.ledger = ledger
        self.name = "router:" + ",".join(f"{task}={'>'.join(m.name for m in r.models)}" for task, r in routes.items())
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="llm")
        self._calls: deque[LlmCall] = deque(maxlen=CALL_LOG)
        self._calls_lock = threading.Lock()

    def generate_json(self, prompt: str, schema: Schema, timeout_s: float) -> object:
        return self.generate_routed("default", prompt, schema, None)

    def generate_routed(self, task: str, prompt: str, schema: Schema, accept: Accept | None) -> object:
        route = self.routes.get(task) or self.routes.get("default")
        if route is None:
            raise LlmUnavailable(f"'{task}' 작업의 모델 경로 없음")
        ledger, account, usage = self.ledger, current_actor(), current_usage()  # 요청 스레드에서 읽어 둔다
        reserve = None if ledger is None else (lambda: ledger.reserve(account))

        def log(model: JsonModel, ok: bool, error: str, seconds: float) -> None:
            call = LlmCall(
                at=datetime.now(UTC),
                task=task,
                model=model.name,
                ok=ok,
                error=error,
                latency_ms=round(seconds * 1000),
            )
            with self._calls_lock:
                self._calls.append(call)

        return hedged(route, prompt, schema, accept, self._pool, reserve, usage, log)

    def recent_calls(self) -> tuple[LlmCall, ...]:
        """실제로 부른 외부 호출, 최근 것부터(한도로 부르지 않은 호출은 없음)."""
        with self._calls_lock:
            return tuple(reversed(self._calls))


def hedged(
    route: Route,
    prompt: str,
    schema: Schema,
    accept: Accept | None,
    pool: ThreadPoolExecutor,
    reserve: Callable[[], bool] | None = None,
    usage: TurnUsage | None = None,
    log: Callable[[JsonModel, bool, str, float], None] | None = None,
) -> object:
    """먼저 온 받아들일 만한 답. 모두 실패하거나 전체 시간이 지나면 LlmUnavailable(실패 종류만 담음).

    풀이 꽉 차 대기열에 남은 호출은 실행 직전에 요청이 끝났는지·시간이 남았는지 보고, 끝났으면 외부 호출 없이 접는다
    (남은 시간도 그때 다시 잰다). 요청이 끝나면(채택·실패·시간 초과) 아직 시작하지 않은 호출은 취소한다.
    """
    attempt = _Attempt(prompt, schema, time.monotonic(), route.budget_s, reserve, usage, log)
    waiting = list(route.models)
    running: dict[Future[object], JsonModel] = {}
    failures: list[str] = []

    def start() -> None:
        model = waiting.pop(0)
        running[pool.submit(attempt, model)] = model

    try:
        start()
        next_start = time.monotonic() + route.hedge_after_s
        while running or waiting:
            now = time.monotonic()
            if now >= attempt.deadline:
                failures.append("시간 초과")
                break
            if waiting and (not running or now >= next_start):
                start()
                next_start = now + route.hedge_after_s
                continue
            until = min(attempt.deadline, next_start) if waiting else attempt.deadline
            done, _ = wait(list(running), timeout=max(until - now, 0.0), return_when=FIRST_COMPLETED)
            found, data = _first_accepted(done, running, accept, failures)
            if found:
                return data
        raise LlmUnavailable("받아들일 만한 답 없음(" + ", ".join(failures) + ")")
    finally:
        attempt.finished.set()
        for future in running:
            future.cancel()  # 시작 전이면 취소(이미 도는 호출은 어댑터 제한 시간으로 끝난다)


class _Attempt:
    """헤지 요청 하나의 모델 호출(풀에서 실행). 실행 직전에 끝났는지·시간·한도를 보고, 결과를 호출 기록에 남긴다."""

    def __init__(
        self,
        prompt: str,
        schema: Schema,
        started_at: float,
        budget_s: float,
        reserve: Callable[[], bool] | None,
        usage: TurnUsage | None,
        log: Callable[[JsonModel, bool, str, float], None] | None,
    ) -> None:
        self.prompt = prompt
        self.schema = schema
        self.started_at = started_at
        self.budget_s = budget_s
        self.deadline = started_at + budget_s
        self.reserve = reserve
        self.usage = usage
        self.log = log
        self.finished = threading.Event()

    def __call__(self, model: JsonModel) -> object:
        # 예산 − 지난 시간(마감 − 지금과 같은 값이지만, 시계가 아직 같은 눈금이면 예산을 소수 오차로 넘지 않게)
        remaining = self.budget_s - (time.monotonic() - self.started_at)
        if self.finished.is_set() or remaining <= 0:
            raise LlmUnavailable("시작 전에 요청 종료")
        if self.reserve is not None and not self.reserve():  # 부르기 직전에 한도 예약(헤지의 다음 모델도 같음)
            if self.usage is not None:
                self.usage.mark()
            raise QuotaExceeded("오늘 외부 AI 사용 한도 소진")
        started = time.monotonic()
        try:
            answer = model.generate_json(self.prompt, self.schema, remaining)
        except Exception as error:
            if self.log is not None:
                self.log(model, False, type(error).__name__, time.monotonic() - started)
            raise
        if self.log is not None:
            self.log(model, True, "", time.monotonic() - started)
        return answer


def _first_accepted(
    done: set[Future[object]],
    running: dict[Future[object], JsonModel],
    accept: Accept | None,
    failures: list[str],
) -> tuple[bool, object]:
    """끝난 호출 중 받아들일 만한 첫 답(있으면 True). 실패와 검사 불통과는 failures에 남긴다."""
    for future in done:
        model = running.pop(future)
        try:
            data = future.result()
        except Exception as error:  # 어댑터는 LlmUnavailable을 내지만 다른 예외도 이 모델의 실패로 본다
            failures.append(f"{model.name} {type(error).__name__}")
            continue
        if accept is None or accept(data):
            return True, data
        failures.append(f"{model.name} 작업 검사 불통과")
    return False, None


ModelMaker = Callable[[str, str, str | None], JsonModel | None]


def build_router(
    providers: Sequence[str], path: Path, make: ModelMaker, ledger_path: Path | None = None
) -> Router | None:
    """켠 제공자 중 키가 있는 모델만 남긴 작업별 경로. 남는 경로가 없으면 None(규칙 기반·기본 설명만).
    설정 파일에 quota가 있고 ledger_path가 있으면 그 파일로 하루 호출 수를 센다. quota가 없으면 한도 없이 부른다."""
    if not providers:
        return None
    config = load_routes(path)
    made: dict[tuple[str, str, str | None], JsonModel | None] = {}
    routes: dict[str, Route] = {}
    for task, spec in config.routes.items():
        models: list[JsonModel] = []
        for item in spec.models:
            if item.provider not in providers:
                continue
            key = (item.provider, item.model, item.effort)
            if key not in made:
                made[key] = make(item.provider, item.model, item.effort)
            model = made[key]
            if model is not None:
                models.append(model)
        if models:
            routes[task] = Route(models=tuple(models), hedge_after_s=spec.hedge_after_s, budget_s=spec.budget_s)
    if not routes:
        return None
    ledger = None if config.quota is None or ledger_path is None else UsageLedger(ledger_path, config.quota)
    return Router(routes, version=config.version, ledger=ledger)
