"""요청을 보낸 사람(Principal)·인증 오류·아이디 규칙과 예약 아이디(docs/operations.md(서비스) 2절)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ripple.contracts.auth import LOGIN_ID_PATTERN, ROLE_PERMISSIONS, Me, Permission, Role, permissions_of

DEMO_ID = "demo"  # 체험 공용 계정(저장소 밖). 실제 계정이 이 아이디를 쓰지 못한다
DEMO_NAME = "체험 계정"
DEV_ID = "dev"
DEV_NAME = "개발 모드"
# 빠른 로그인 고정 계정(quick.py): 저장소에 있지만 빠른 로그인만 만들고 고친다 — 구성원 추가·첫 관리자로 만들 수 없고,
# 구성원 관리로 바꿀 수 없고, 아이디·비밀번호로 들어갈 수 없으며, 첫 관리자·계정 준비 판단에서 세지 않는다.
# 파트장·본부장은 시연 기록 시드의 결재선 가상 계정(ripple/api/demo_plan.py)과 같은 아이디 — 결재함·감사 기록의 이름이
# 시드와 맞는다
QUICK_MEMBER_ID = "quick-member"
QUICK_LEAD_ID = "quick-lead"
QUICK_PART_LEAD_ID = "part-lead"
QUICK_EXECUTIVE_ID = "executive"
QUICK_IDS = frozenset({QUICK_MEMBER_ID, QUICK_LEAD_ID, QUICK_PART_LEAD_ID, QUICK_EXECUTIVE_ID})
RESERVED_IDS = frozenset({DEMO_ID, DEV_ID}) | QUICK_IDS
_ID = re.compile(LOGIN_ID_PATTERN)


class AuthError(Exception):
    """API가 그대로 응답으로 바꾸는 인증 오류(상태 코드·계약 code·합니다체 문장)."""

    def __init__(self, status: int, code: str, message: str, retry_after_s: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after_s = retry_after_s


@dataclass(frozen=True, slots=True)
class Principal:
    """이 요청을 보낸 사람. token은 세션 토큰(개발 모드는 None).

    dev = 개발 모드(RIPPLE_AUTH=off): 역할과 무관하게 모든 권한.
    """

    login_id: str
    name: str
    role: Role
    must_change_password: bool = False
    demo: bool = False
    token: str | None = None
    dev: bool = False

    def can(self, permission: Permission) -> bool:
        return self.dev or permission in ROLE_PERMISSIONS[self.role]

    def me(self) -> Me:
        return Me(
            login_id=self.login_id,
            name=self.name,
            role=self.role,
            permissions=permissions_of(self.role, dev=self.dev),
            must_change_password=self.must_change_password,
        )


DEV_PRINCIPAL = Principal(login_id=DEV_ID, name=DEV_NAME, role=Role.ADMIN, dev=True)


def normalize_id(login_id: str) -> str:
    return login_id.strip().lower()


def valid_login_id(login_id: str) -> bool:
    return _ID.fullmatch(login_id) is not None
