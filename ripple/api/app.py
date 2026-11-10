"""FastAPI 앱 조립: 설정을 읽고 라우터를 붙인다.

실행: uvicorn ripple.api.app:create_app --factory
"""

from __future__ import annotations

import logging
import math
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

from fastapi import Depends, FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ripple import __version__
from ripple.auth import AuthService
from ripple.cases import CaseShelf
from ripple.config.settings import Settings
from ripple.graph.factory import open_store
from ripple.llm.base import JsonModel, RoutedModel
from ripple.llm.providers import router_from_settings
from ripple.store.accounts import AccountStore, AccountStoreError, SessionStore
from ripple.store.corrections import CorrectionLog
from ripple.store.mappings import MappingStore
from ripple.store.outcomes import OutcomeLog
from ripple.store.records import RecordStore
from ripple.store.reset import archive_records, done_scope
from ripple.store.snapshots import SnapshotStore
from ripple.store.updates import UpdateLog

from .brief import BriefService
from .demo_daily import DemoSeeder
from .deps import AppContext
from .past_cases import shared_shelf
from .routes import (
    accounts,
    analyses,
    assistant,
    auth,
    brief,
    graph,
    health,
    impacts,
    intake,
    llm,
    manage,
    ncr,
    records,
    samples,
    snapshots,
    updates,
)
from .security import origin_allowed, problem, require_view
from .status_imports import StatusImports
from .workspace import Workspaces

ModelFactory = Callable[[Settings], JsonModel | RoutedModel | None]
MAX_JSON_BYTES = 1024 * 1024
UPLOAD_PATHS = frozenset(
    {"/api/imports", "/api/status-imports", "/api/intake/proposals/xlsx"}
)  # 엑셀 본문(상한은 routes/snapshots.upload_bytes)


def body_too_large(path: str, declared: str) -> bool:
    """엑셀 올리기 밖의 /api 본문은 JSON 몇 KB라 1MB를 넘으면 읽기 전에 413(큰 본문을 다 받아 두지 않게).
    올리기는 경로에서 20MB를 스트리밍으로 센다. 길이를 밝히지 않은 본문은 화면 서버(Caddy)의 상한이 막는다."""
    return (
        path.startswith("/api/")
        and path not in UPLOAD_PATHS
        and declared.isascii()
        and declared.isdigit()
        and int(declared) > MAX_JSON_BYTES
    )


async def limit_body(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    if body_too_large(request.url.path, request.headers.get("content-length", "")):
        detail = f"요청 본문 크기 초과({MAX_JSON_BYTES // (1024 * 1024)}MB까지)"  # 올리기의 413과 같은 꼴
        return JSONResponse(status_code=413, content={"detail": detail})
    return await call_next(request)


def _json_safe(value: object) -> object:
    """JSON에 쓸 수 없는 실수(Infinity·NaN)를 글로 바꾼다(검증 오류가 받은 값을 되돌려 줄 때)."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return value


async def invalid_request(_: Request, error: Exception) -> Response:
    """계약 검증 실패는 FastAPI 기본과 같은 422 꼴로 — 다만 받은 값에 Infinity·NaN이 있으면 기본 처리기가
    응답을 JSON으로 만들지 못해 500이 되던 것을 막는다."""
    assert isinstance(error, RequestValidationError)
    return JSONResponse(status_code=422, content={"detail": _json_safe(jsonable_encoder(error.errors()))})


async def check_origin(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """상태를 바꾸는 /api 요청의 Origin이 Host와 다르면 403(bad_origin).

    SameSite=Strict 쿠키와 함께 다른 사이트가 보낸 요청(CSRF)을 막는다."""
    if request.url.path.startswith("/api/") and not origin_allowed(
        request.method, request.headers.get("origin"), request.headers.get("host")
    ):
        error = problem(403, "bad_origin", "다른 사이트에서 보낸 요청 · 처리 거부")
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail})
    return await call_next(request)


log = logging.getLogger("ripple.auth")

PUBLIC_ROUTERS = (
    health.router,
    auth.router,
    accounts.router,
    snapshots.router,
    records.router,
    brief.router,
    ncr.router,
    manage.router,
    updates.router,
    llm.router,
    intake.router,
)
"""공개(상태 확인·로그인) · 경로마다 권한을 정하는 라우터(계정·지도·기록)."""
VIEW_ROUTERS = (impacts.router, graph.router, samples.router, analyses.router, assistant.router)
"""업무 라우터: 로그인·보기 권한(작업 공간을 쓰는 경로는 get_workspace가 같은 판단을 같은 세대로 한 번 더 한다)."""


@dataclass(frozen=True, slots=True)
class _Services:
    """앱이 시작하기 전에 만드는 파일 저장소들(지도는 시작할 때 연다)."""

    context: AppContext
    auth: AuthService
    records: RecordStore
    updates: UpdateLog
    cases: CaseShelf  # 결정 도우미의 합성 과거 사례 선반(프로세스에 하나, past_cases.shared_shelf)


def create_app(
    settings: Settings | None = None,
    *,
    llm_factory: ModelFactory = router_from_settings,
    environ: Mapping[str, str] | None = None,
) -> FastAPI:
    """설정·규칙표·파라미터는 바로 읽고, 연결 지도는 앱이 시작할 때(lifespan) 읽는다.

    그래서 OpenAPI 내보내기는 지도 파일 없이도 된다. llm_factory는 외부 생성 모델을 만든다(검사에서 가짜 모델로 바꿈).
    environ은 첫 관리자 변수(RIPPLE_ADMIN_ID·RIPPLE_ADMIN_PASSWORD)를 읽는 곳(기본 os.environ, 검사에서 바꿈) —
    비밀번호라 Settings에 두지 않는다.
    """
    context = AppContext.load(settings or Settings.from_env())
    data_dir = context.settings.data_dir
    services = _Services(
        context=context,
        auth=AuthService(
            AccountStore(data_dir),
            SessionStore(data_dir),
            required=context.settings.auth_required,
            demo_login=context.settings.demo_login,
            quick_login=context.settings.quick_login,
        ),
        records=RecordStore(data_dir),
        updates=UpdateLog(data_dir),
        cases=shared_shelf(context),
    )
    app = FastAPI(
        title="Ripple API",
        version=__version__,
        description="설계변경(ECN) 영향 판단 에이전트 API. 계약: ripple/contracts",
        lifespan=_lifespan(services, llm_factory, os.environ if environ is None else environ),
    )
    app.state.context = context
    app.state.auth = services.auth
    app.state.records = services.records
    app.state.updates = services.updates
    app.state.outcomes = OutcomeLog(data_dir)
    app.state.corrections = CorrectionLog(data_dir)
    app.state.brief = BriefService()  # 결정 도우미(읽을 때 만들고 잠깐 기억)
    app.state.cases = services.cases
    app.middleware("http")(check_origin)
    app.middleware("http")(limit_body)
    app.add_exception_handler(RequestValidationError, invalid_request)
    for router in PUBLIC_ROUTERS:
        app.include_router(router, prefix="/api")
    for router in VIEW_ROUTERS:
        app.include_router(router, prefix="/api", dependencies=[Depends(require_view)])
    return app


def _lifespan(
    services: _Services, llm_factory: ModelFactory, environ: Mapping[str, str]
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """시작: 기록 비우기 표지 → 기록 저장소 → 계정 → 지도·작업 공간 → 시연 기록 시드. 끝: 지도 저장소를 닫는다."""
    settings = services.context.settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _reset_records(settings)
        services.records.start()  # 모르는 형식 판·손상이면 시작을 멈춘다(docs/records.md(기록·결재) 4절)
        _start_accounts(services.auth, environ)
        opened = open_store(settings)
        try:
            holder = Workspaces(
                services.context,
                opened.store,
                llm_factory(settings),
                SnapshotStore(settings.data_dir),
                mappings=MappingStore(settings.data_dir / "mappings.json"),
                updates=services.updates,
                cases=services.cases,
            )
            holder.start()
            # RIPPLE_DEMO_SEED=on이면 시연 기록을 채운다(요청을 받기 전 — 실시간 세계는 채운 날·시드 판이 다를 때,
            # 그 뒤로는 KST 날이 바뀔 때마다 새 날 훅으로, demo_daily.py). 결재선 가상 계정은 빠른 로그인 고정 계정이라
            # 비밀번호가 없다 — 예전 변수 RIPPLE_DEMO_PASSWORD는 읽지 않고 남아 있으면 알린다
            if environ.get("RIPPLE_DEMO_PASSWORD"):
                log.warning("RIPPLE_DEMO_PASSWORD 더는 사용 안 함(파트장·본부장은 빠른 로그인 단추) — 삭제 가능")
            seeder = DemoSeeder(services.context, holder, services.auth.accounts)
            seeder.start()
            if settings.demo_seed and settings.live_world:
                holder.on_new_day(seeder.new_day)
            app.state.workspaces = holder
            app.state.status_imports = StatusImports(holder)
            yield
        finally:
            opened.close()

    return lifespan


def _reset_records(settings: Settings) -> None:
    """기록·실적 파일을 열기 전에 비우기 표지를 처리한다(docs/operations.md(배포) 4절, 같은 표지로는 한 번만)."""
    reset = settings.reset_records
    if not reset:
        return
    done = done_scope(settings.data_dir, reset)
    if done is not None and done != settings.reset_scope:
        log.warning(
            "RIPPLE_RESET_RECORDS=%s는 이미 범위 %s로 사용됨 · 범위 %s로 비우려면 새 표지 필요",
            reset,
            done,
            settings.reset_scope,
        )
    moved = archive_records(settings.data_dir, reset, scope=settings.reset_scope)
    if moved is not None:
        what = "기록·실적·지도·상태 갱신·매핑 기억" if settings.reset_scope == "all" else "기록·실적"
        log.warning("%s 보관 폴더로 이동 완료(RIPPLE_RESET_RECORDS=%s): %s", what, reset, ", ".join(moved) or "없음")


def _start_accounts(auth_service: AuthService, environ: Mapping[str, str]) -> None:
    """로그인 모드면 계정·세션 파일을 열고 첫 관리자를 만든다. 문제는 경고로만 남긴다(시작은 계속).

    개발 모드는 계정 파일만 읽는다: 개발 관리자는 모든 권한이라 '구성원 관리'가 보이는데, 읽지 않은 저장소를 부르면
    500이 났다. 첫 관리자는 만들지 않고 세션은 쓰지 않는다. 손상된 파일은 경고만 남긴다(개발 모드는 계정과 무관하게
    켜진다).
    """
    if not auth_service.required:
        log.warning("로그인을 끈 개발 모드(RIPPLE_AUTH=off): 모든 요청을 개발 관리자로 처리")
        try:
            auth_service.accounts.load()
        except AccountStoreError as error:
            log.warning("개발 모드: 계정 파일 읽기 실패 · 구성원 관리 사용 불가: %s", error)
        return
    trouble = auth_service.start(environ.get("RIPPLE_ADMIN_ID"), environ.get("RIPPLE_ADMIN_PASSWORD"))
    if trouble:
        log.warning(trouble)
    if auth_service.quick_login:
        log.warning("빠른 로그인 켜짐(RIPPLE_QUICK_LOGIN=on): 이 주소에 들어온 누구나 담당자·파트장·팀장·본부장 가능")
    if auth_service.sessions.load_problem:
        log.warning("세션 파일 읽기 실패 · 모두 다시 로그인 필요: %s", auth_service.sessions.load_problem)
