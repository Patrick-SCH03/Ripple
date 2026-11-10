"""로그인·계정·역할 계약(docs/operations.md(서비스) 2절).

비밀번호 해시·세션 토큰 같은 저장 형식은 ripple/store에 두고 API로 내보내지 않는다. 체험(demo)은 저장소에 없는 공용
계정이라 계정 목록·추가·변경에 나오지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints

from .base import Frozen

LOGIN_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{2,31}$"  # 영문 소문자·숫자로 시작, 3~32자
PASSWORD_MIN = 10
PASSWORD_MAX = 128
NAME_MAX = 40


class Role(StrEnum):
    ADMIN = "admin"  # 팀장(관리자 권한): 결재(팀장 단계 + 파트장·본부장 전결) · 구성원 관리 · 지도 전환 · 엑셀 가져오기
    MEMBER = (
        "member"  # 담당자: 분석 · 비서 · 기록 · 검토 요청 · 무비용 담당자 처리 · 실행 · 상태 갱신 · 지도 엑셀 내려받기
    )
    DEMO = "demo"  # 체험: 합성 데이터만 본다(공용, 비밀번호 없음)
    PART_LEAD = (
        "part_lead"  # 결재선 1단계 파트장: 자기 단계 승인·반려·보류 · 결재·현황(docs/records.md(기록·결재) 14절)
    )
    EXECUTIVE = "executive"  # 결재선 3단계 본부장·실장: 자기 단계 승인·반려·보류 · 결재·현황


class Permission(StrEnum):
    VIEW = "view"  # 지도 보기 · 분석 · 영향 · 대안 · 비서 · 샘플
    EXPORT = "export"  # 지도 엑셀 내려받기(체험은 합성 지도만 — API가 지도마다 판단)
    SWITCH_MAP = "switch_map"  # 활성 지도 바꾸기(모두가 같은 작업 공간을 쓴다)
    IMPORT = "import"  # 엑셀 가져오기 · 확정
    MANAGE_ACCOUNTS = "manage_accounts"  # 구성원 추가 · 비밀번호 초기화 · 끄기 · 역할 변경
    CHANGE_PASSWORD = "change_password"  # 내 비밀번호 바꾸기
    RECORD = "record"  # 분석을 기록으로 남기기 · 검토 요청 · 실행 · 종료(docs/records.md)
    APPROVE = "approve"  # 승인 · 반려 · 보류(관리자 = 승인권자)


# 관리자는 결재자다: 기록·검토 요청·실행·상태 갱신은 담당자 일이라 관리자에게서 RECORD를 뺀다.
# 파트장·본부장은 결재만 한다(구성원 관리·지도 전환·가져오기는 팀장). 어느 단계를 결정하는지는 결재 규칙
# (ripple/records/approval.py 역할 → 단계)이 본다.
# 개발 모드(RIPPLE_AUTH=off)는 역할과 무관하게 모든 권한(Principal.dev).
_APPROVER = frozenset({Permission.VIEW, Permission.EXPORT, Permission.CHANGE_PASSWORD, Permission.APPROVE})
ROLE_PERMISSIONS: Mapping[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission) - {Permission.RECORD},
    Role.MEMBER: frozenset({Permission.VIEW, Permission.EXPORT, Permission.CHANGE_PASSWORD, Permission.RECORD}),
    Role.DEMO: frozenset({Permission.VIEW, Permission.EXPORT}),
    Role.PART_LEAD: _APPROVER,
    Role.EXECUTIVE: _APPROVER,
}

LoginId = Annotated[str, StringConstraints(pattern=LOGIN_ID_PATTERN)]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX)]
# 저장소에 두는 계정의 역할(체험 제외). 파트장·본부장을 쓴 계정 파일은 이 역할을 모르는 옛 코드가 읽지 못해
# 시작을 멈춘다
StaffRole = Literal[Role.ADMIN, Role.MEMBER, Role.PART_LEAD, Role.EXECUTIVE]
# 빠른 로그인 역할: 담당자·파트장·팀장·본부장(고정 계정 표 quick.QUICK_ACCOUNTS와 같은 범위, 1.33.0 안에서
# 파트장·본부장을 더함 — 화면 단추는 10-30부터 담당자·파트장 둘). 체험은 빠른 로그인이 아니다
QuickRole = Literal[Role.ADMIN, Role.MEMBER, Role.PART_LEAD, Role.EXECUTIVE]


def permissions_of(role: Role, *, dev: bool = False) -> tuple[Permission, ...]:
    """화면에 내보내는 순서: Permission 정의 순. 개발 모드는 모든 권한."""
    allowed = frozenset(Permission) if dev else ROLE_PERMISSIONS[role]
    return tuple(p for p in Permission if p in allowed)


class Me(Frozen):
    """로그인한 사람. 화면은 permissions로 단추를 보이고 숨긴다(막는 것은 서버)."""

    login_id: str
    name: str
    role: Role
    permissions: tuple[Permission, ...]
    must_change_password: bool = False  # 첫 로그인·초기화 뒤: 비밀번호를 바꿀 때까지 업무 API는 403


class AuthOptions(Frozen):
    """로그인 전에 화면이 알아야 하는 설정(상태 확인에 실린다)."""

    required: bool  # False면 개발 모드(RIPPLE_AUTH=off): 모든 요청을 개발 관리자로 처리
    demo_login: bool  # 체험 로그인을 켰나(켜져 있어도 활성 지도가 실데이터면 체험은 막힌다)
    accounts_ready: bool  # 켜진 관리자가 한 명이라도 있나(없으면 로그인 화면이 배포 안내를 보인다)
    # 1.30.0 빠른 로그인(RIPPLE_QUICK_LOGIN, 시연 배포 전용)을 켰나: 켜져 있으면 로그인 화면이 입력 칸 대신 역할 단추
    # 넷(담당자·파트장·팀장·본부장)만 보인다. 개발 모드(required=False)에서는 늘 거짓
    quick_login: bool = False


class LoginRequest(Frozen):
    login_id: str = Field(max_length=64)  # 서버가 앞뒤 공백을 지우고 소문자로 바꿔 대조한다
    password: str = Field(max_length=PASSWORD_MAX)


class QuickLogin(Frozen):
    """1.30.0 빠른 로그인: 고른 역할의 고정 계정으로 들어간다(아이디·비밀번호 없음, 켜져 있을 때만). 역할은 담당자·
    파트장·팀장·본부장(1.33.0 안에서 파트장·본부장을 더함 — 시드의 결재선 가상 계정과 같은 계정)."""

    role: QuickRole


class PasswordChange(Frozen):
    current_password: str = Field(max_length=PASSWORD_MAX)
    # 규칙(PASSWORD_MIN자 이상·아이디 포함 금지 등)은 서버가 보고 422 weak_password로 이유를 알린다
    new_password: str = Field(max_length=PASSWORD_MAX)


class Account(Frozen):
    """구성원 관리 화면의 한 줄(비밀번호 해시는 없음)."""

    login_id: LoginId
    name: DisplayName
    role: StaffRole
    disabled: bool = False
    must_change_password: bool = False
    created_at: AwareDatetime
    last_login_at: AwareDatetime | None = None


class AccountList(Frozen):
    items: tuple[Account, ...]


class AccountCreate(Frozen):
    login_id: LoginId
    name: DisplayName
    role: StaffRole = Role.MEMBER


class AccountUpdate(Frozen):
    """바꿀 것만 보낸다. 켜진 팀장(관리자)이 0명이 되는 변경은 거절(409 last_admin)."""

    name: DisplayName | None = None
    role: StaffRole | None = None
    disabled: bool | None = None


class AccountCreated(Frozen):
    account: Account
    temporary_password: str  # 이 응답에만 있다(저장소에는 해시만). 첫 로그인 때 바꾸게 한다


class PasswordIssued(Frozen):
    temporary_password: str


class AuthProblem(Frozen):
    """401·403·409·422·429·503 응답 detail. message는 사람이 읽는 문구(로그인·비밀번호는 합니다체, 그 밖은 명사형)."""

    code: Literal[
        "unauthenticated",
        "invalid_credentials",
        "too_many_attempts",
        "forbidden",
        "password_change_required",
        "account_disabled",
        "bad_origin",
        "demo_unavailable",
        "quick_unavailable",
        "account_exists",
        "last_admin",
        "weak_password",
        "busy",
        "not_found",
    ]
    message: str
    retry_after_s: int | None = Field(default=None, ge=0)  # too_many_attempts: 다시 해도 되는 때까지(초)
