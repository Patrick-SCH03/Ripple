"""로그인 · 체험 · 빠른 로그인 · 로그아웃 · 내 정보 · 비밀번호 바꾸기(docs/operations.md(서비스) 2절). 세션은
HttpOnly·SameSite=Strict 쿠키."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from ripple.auth import AuthError, AuthService, Principal
from ripple.contracts.auth import LoginRequest, Me, PasswordChange, QuickLogin
from ripple.contracts.domain import DataMode

from ..deps import AppContext, get_context
from ..security import SESSION_COOKIE, clear_session, current_principal, demo_blocked, from_error, get_auth, set_session
from ..workspace import Workspaces, get_workspaces

router = APIRouter(tags=["auth"])

Auth = Annotated[AuthService, Depends(get_auth)]
Context = Annotated[AppContext, Depends(get_context)]


def _sign_in(
    start: Callable[[], tuple[Principal, str]],
    request: Request,
    response: Response,
    auth: AuthService,
    context: AppContext,
    *,
    demo: bool,
) -> Me:
    """로그인·체험·빠른 로그인의 공통 끝: 새 세션 쿠키를 붙이고 같은 브라우저의 이전 세션은 정리한다."""
    try:
        principal, token = start()
    except AuthError as error:
        raise from_error(error) from None
    auth.logout(request.cookies.get(SESSION_COOKIE))
    set_session(response, token, secure=context.settings.cookie_secure, demo=demo)
    return principal.me()


@router.post(
    "/auth/login",
    responses={
        401: {"description": "아이디 또는 비밀번호가 맞지 않음(invalid_credentials)"},
        403: {"description": "사용이 멈춘 계정(account_disabled)"},
        429: {"description": "여러 번 틀림(too_many_attempts, Retry-After)"},
        503: {"description": "로그인 요청이 몰림(busy)"},
    },
)
def login(body: LoginRequest, request: Request, response: Response, auth: Auth, context: Context) -> Me:
    return _sign_in(lambda: auth.login(body.login_id, body.password), request, response, auth, context, demo=False)


@router.post(
    "/auth/demo",
    responses={
        403: {"description": "활성 지도가 실데이터라 체험 불가(demo_unavailable)"},
        404: {"description": "체험 로그인을 켜지 않음(demo_unavailable)"},
    },
)
def demo(
    request: Request,
    response: Response,
    auth: Auth,
    context: Context,
    holder: Annotated[Workspaces, Depends(get_workspaces)],
) -> Me:
    current = holder.current
    if current is not None and current.data_mode is DataMode.REAL:
        raise demo_blocked()
    return _sign_in(auth.demo, request, response, auth, context, demo=True)


@router.post(
    "/auth/quick",
    responses={
        403: {"description": "사용이 멈춘 계정(account_disabled)"},
        404: {"description": "빠른 로그인을 켜지 않음·개발 모드(quick_unavailable)"},
        503: {"description": "처음 만드는 계정의 해시 계산이 몰림(busy)"},
    },
)
def quick(body: QuickLogin, request: Request, response: Response, auth: Auth, context: Context) -> Me:
    """1.30.0 빠른 로그인(시연 배포 전용, RIPPLE_QUICK_LOGIN=on): 고른 역할의 고정 계정으로 로그인과 같은 세션."""
    return _sign_in(lambda: auth.quick(body.role), request, response, auth, context, demo=False)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, auth: Auth, context: Context) -> Response:
    auth.logout(request.cookies.get(SESSION_COOKIE))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session(response, secure=context.settings.cookie_secure)
    return response


@router.get("/auth/me", responses={401: {"description": "로그인하지 않음(unauthenticated)"}})
def me(principal: Annotated[Principal, Depends(current_principal)]) -> Me:
    return principal.me()


@router.post(
    "/auth/password",
    responses={
        401: {"description": "로그인하지 않음"},
        403: {"description": "체험 계정(forbidden)"},
        422: {"description": "지금 비밀번호가 틀림(invalid_credentials) 또는 새 비밀번호 규칙 위반(weak_password)"},
        429: {"description": "지금 비밀번호를 여러 번 틀림"},
    },
)
def change_password(
    body: PasswordChange,
    response: Response,
    principal: Annotated[Principal, Depends(current_principal)],
    auth: Auth,
    context: Context,
) -> Me:
    try:
        changed, token = auth.change_password(principal, body.current_password, body.new_password)
    except AuthError as error:
        raise from_error(error) from None
    set_session(response, token, secure=context.settings.cookie_secure, demo=False)
    return changed.me()
