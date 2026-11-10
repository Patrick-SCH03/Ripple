"""요청을 누가 보냈는지(세션 쿠키 → Principal)와 그 일을 할 수 있는지(역할 권한)를 정한다
(docs/operations.md(서비스) 2절).

- 공개 경로: 상태 확인 · 로그인 · 체험 · 빠른 로그인 · 로그아웃 · 내 정보(로그인 안 했으면 401로 알림).
  나머지 /api는 로그인이 필요하다.
- 비밀번호를 바꾸기 전 세션은 내 정보 · 로그아웃 · 비밀번호 바꾸기 밖에서 403(password_change_required).
- 상태를 바꾸는 요청은 Origin이 있으면 요청 Host와 같아야 한다(다르거나 'null'이면 403 bad_origin).
  SameSite=Strict 쿠키와 함께 쓴다.
- 체험은 실데이터를 보지 못한다. 작업 공간을 쓰는 경로는 get_workspace(ripple/api/workspace.py) 한 번으로 권한 검사와
  처리를 같은 세대에서 한다(검사한 뒤 지도가 바뀌어도 처리는 검사한 세대로).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, Response

from ripple.auth import AuthError, AuthService, Principal
from ripple.auth.service import DEMO_SESSION_HOURS, SESSION_HOURS
from ripple.contracts.auth import AuthProblem, Permission

SESSION_COOKIE = "ripple_session"
PASSWORD_PATHS = frozenset({"/api/auth/me", "/api/auth/logout", "/api/auth/password"})
STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
FORBIDDEN: dict[Permission, str] = {
    Permission.VIEW: "권한 없음 — 이 계정으로 보기 불가",
    Permission.EXPORT: "권한 없음 — 이 계정으로 지도 내려받기 불가",
    Permission.SWITCH_MAP: "권한 없음 — 팀장만 지도 전환 가능",
    Permission.IMPORT: "권한 없음 — 팀장만 엑셀 가져오기 가능",
    Permission.MANAGE_ACCOUNTS: "권한 없음 — 팀장만 구성원 관리 가능",
    Permission.CHANGE_PASSWORD: "권한 없음 — 이 계정은 비밀번호 변경 불가",
    Permission.RECORD: "권한 없음 — 이 계정으로 기록·검토 요청 불가",
    Permission.APPROVE: "권한 없음 — 결재선의 결재자(파트장·팀장·본부장)만 승인·반려·보류 가능",
}
AUTH_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"description": "로그인이 필요함(detail = AuthProblem unauthenticated)"},
    403: {"description": "권한 없음·비밀번호를 먼저 바꿔야 함·체험 불가(detail = AuthProblem)"},
}


def problem(status: int, code: str, message: str, retry_after_s: int | None = None) -> HTTPException:
    detail = AuthProblem.model_validate({"code": code, "message": message, "retry_after_s": retry_after_s})
    headers = {"Retry-After": str(retry_after_s)} if retry_after_s else None
    return HTTPException(status_code=status, detail=detail.model_dump(mode="json"), headers=headers)


def from_error(error: AuthError) -> HTTPException:
    return problem(error.status, error.code, error.message, error.retry_after_s)


def get_auth(request: Request) -> AuthService:
    auth = getattr(request.app.state, "auth", None)
    if not isinstance(auth, AuthService):
        raise RuntimeError("로그인 서비스가 준비되지 않았습니다")
    return auth


def current_principal(request: Request, auth: Annotated[AuthService, Depends(get_auth)]) -> Principal:
    principal = auth.resolve(request.cookies.get(SESSION_COOKIE))
    if principal is None:
        raise problem(401, "unauthenticated", "로그인이 필요합니다")
    if principal.must_change_password and request.url.path not in PASSWORD_PATHS:
        raise problem(
            403,
            "password_change_required",
            "처음 로그인했거나 비밀번호가 초기화되었습니다. 새 비밀번호를 먼저 정해 주십시오",
        )
    return principal


def require(permission: Permission) -> Callable[[Principal], Principal]:
    def dependency(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if not principal.can(permission):
            raise problem(403, "forbidden", FORBIDDEN[permission])
        return principal

    dependency.__name__ = f"require_{permission.value}"
    return dependency


# 경로마다 같은 함수 객체를 써야 FastAPI가 한 요청 안에서 한 번만 계산한다
require_view = require(Permission.VIEW)
require_export = require(Permission.EXPORT)
require_switch = require(Permission.SWITCH_MAP)
require_import = require(Permission.IMPORT)
require_manage = require(Permission.MANAGE_ACCOUNTS)
require_record = require(Permission.RECORD)
require_approve = require(Permission.APPROVE)


def require_act(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
    """결재 행동 입구: 기록 권한(담당자) 또는 승인 권한(결재선의 파트장·팀장·본부장).

    행동마다의 권한은 결재 규칙(ripple/records/flow.py)이 본다.
    """
    if not (principal.can(Permission.RECORD) or principal.can(Permission.APPROVE)):
        raise problem(403, "forbidden", "권한 없음 — 이 계정으로 결재 처리 불가")
    return principal


ViewPrincipal = Annotated[Principal, Depends(require_view)]
RecordPrincipal = Annotated[Principal, Depends(require_record)]
ActPrincipal = Annotated[Principal, Depends(require_act)]
ApprovePrincipal = Annotated[Principal, Depends(require_approve)]


def demo_blocked() -> HTTPException:
    return problem(403, "demo_unavailable", "체험 불가 — 지금 실제 데이터 지도 사용 중")


def origin_allowed(method: str, origin: str | None, host: str | None) -> bool:
    """상태를 바꾸는 요청의 Origin이 요청 Host와 같은가. Origin이 없으면(서버 간·검사 도구) 허용, 'null'은 거절."""
    if method.upper() not in STATE_CHANGING or origin is None:
        return True
    if origin.strip().lower() == "null" or not host:
        return False
    parts = urlsplit(origin.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    default = ":443" if parts.scheme == "https" else ":80"
    return _strip_port(parts.netloc.lower(), default) == _strip_port(host.strip().lower(), default)


def _strip_port(netloc: str, default: str) -> str:
    return netloc[: -len(default)] if netloc.endswith(default) else netloc


def set_session(response: Response, token: str, *, secure: bool, demo: bool) -> None:
    hours = DEMO_SESSION_HOURS if demo else SESSION_HOURS
    response.set_cookie(
        SESSION_COOKIE, token, max_age=hours * 3600, path="/", secure=secure, httponly=True, samesite="strict"
    )


def clear_session(response: Response, *, secure: bool) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=secure, httponly=True, samesite="strict")
