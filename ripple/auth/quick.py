"""빠른 로그인(시연 배포 전용, docs/operations.md(서비스) 2절): 아이디·비밀번호 없이 고정 계정 넷 — 담당자·파트장·
팀장·본부장 — 으로 들어간다. 파트장·본부장은 시연 기록 시드의 결재선 가상 계정(part-lead·executive)과 같은 계정이다.

- `RIPPLE_QUICK_LOGIN=on`일 때만(기본 꺼짐). 공개 주소에서 누구나 팀장이 되므로 사내 설치판에서는 켜지 않는다.
- 고정 계정은 처음 누를 때 만든다. 비밀번호는 아무도 모르는 무작위 값의 해시이고 아이디·비밀번호 로그인은 늘 거절한다.
- **잠김**: 방문자(팀장 단추로 들어온 사람 포함)가 다음 방문자의 단추를 망가뜨리지 못하게 구성원 관리(이름·역할·끄기·
  비밀번호 초기화)는 네 아이디를 거절한다(locked). 계정 파일을 손으로 고친 경우에 대비해 빠른 로그인 때마다 이름·역할·
  사용 중 상태를 아래 상수로 되돌린다(자가 복구).
- 세션은 계정마다 최근 QUICK_SESSION_LIMIT개만 남긴다 — 인증 없이 만드는 세션이 전역 상한으로 다른 계정의 세션을
  밀어내지 않게(같은 고정 계정끼리 밀리는 것은 받아들인다). 설정을 끄면 고정 계정 세션은 무효(service.resolve).
- 네 계정은 서로 다른 사람이라 담당자 계정이 올린 검토를 파트장 → 팀장 → 본부장 계정이 차례로 승인한다(자기 결정
  금지 규칙 그대로). 이미 비밀번호 해시가 있는 같은 아이디(예전 시드가 RIPPLE_DEMO_PASSWORD로 만든 계정)도 그대로 쓴다 —
  해시는 쓰지 않고(아이디·비밀번호 로그인 거절) 이름·역할만 되돌린다.

고정 계정인지는 늘 is_quick 하나로 가른다(잠금·비밀번호 로그인 거절·끈 뒤 세션 무효·첫 관리자와 계정 준비에서 빼기).
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import datetime

from ripple.contracts.auth import QuickRole, Role
from ripple.store.accounts import AccountStore, StoredAccount

from .accounts import mutate
from .passwords import hash_password
from .principal import (
    QUICK_EXECUTIVE_ID,
    QUICK_IDS,
    QUICK_LEAD_ID,
    QUICK_MEMBER_ID,
    QUICK_PART_LEAD_ID,
    AuthError,
)

QUICK_ACCOUNTS: Mapping[QuickRole, tuple[str, str]] = {
    Role.MEMBER: (QUICK_MEMBER_ID, "김설계"),
    Role.PART_LEAD: (QUICK_PART_LEAD_ID, "이파트장"),
    Role.ADMIN: (QUICK_LEAD_ID, "박팀장"),
    Role.EXECUTIVE: (QUICK_EXECUTIVE_ID, "최본부장"),
}
"""역할 → (아이디, 이름). 화면 단추 문구(web/src/pages/login/QuickChoices.tsx)와 시드 각본(ripple/api/demo_plan.py)이
이 값을 쓴다."""

QUICK_SESSION_LIMIT = 200
"""고정 계정마다 남기는 세션 수(네 계정 800개 — 전역 상한 MAX_SESSIONS 1,000보다 작다)."""


def is_quick(login_id: str) -> bool:
    """빠른 로그인 고정 계정의 아이디인가(정규화한 아이디로 묻는다)."""
    return login_id in QUICK_IDS


def locked(login_id: str) -> None:
    """구성원 관리가 고정 계정을 바꾸려 하면 403(다음 방문자의 단추가 깨지지 않게)."""
    if is_quick(login_id):
        raise AuthError(403, "forbidden", "시연용 고정 계정 변경 불가")


def restored(current: StoredAccount, role: QuickRole, now: datetime) -> StoredAccount:
    """자가 복구: 손으로 고친 이름·역할·끄기·비밀번호 바꾸기 전 상태를 상수로 되돌리고 로그인 시각을 찍은 사본
    (비밀번호를 쓰지 않는 계정)."""
    _, name = QUICK_ACCOUNTS[role]
    fixed = {"name": name, "role": role, "disabled": False, "must_change_password": False}
    return current.model_copy(update={**fixed, "last_login_at": now})


def quick_account(
    accounts: AccountStore,
    role: QuickRole,
    *,
    now: datetime,
    hash_slot: Callable[[], AbstractContextManager[None]],
) -> StoredAccount:
    """그 역할의 고정 계정을 (없으면 만들고) 상수대로 되돌려 로그인 시각을 찍고 돌려준다."""
    login_id, _ = QUICK_ACCOUNTS[role]
    if accounts.get(login_id) is None:
        _create(accounts, role, now=now, hash_slot=hash_slot)
    return mutate(accounts, login_id, lambda current: restored(current, role, now))


def _create(
    accounts: AccountStore,
    role: QuickRole,
    *,
    now: datetime,
    hash_slot: Callable[[], AbstractContextManager[None]],
) -> None:
    """고정 계정을 처음 만든다. 동시에 처음 눌러도 계정은 한 번만 생긴다(먼저 쓴 쪽 그대로)."""
    login_id, name = QUICK_ACCOUNTS[role]
    with hash_slot():
        unusable = hash_password(secrets.token_urlsafe(32))  # 아무도 모르는 값: 비밀번호로는 못 들어감
    fresh = StoredAccount(login_id=login_id, name=name, role=role, password_hash=unusable, created_at=now)

    def add(stored: dict[str, StoredAccount]) -> None:
        if login_id not in stored:
            stored[login_id] = fresh

    accounts.change(add)


__all__ = ["QUICK_ACCOUNTS", "QUICK_SESSION_LIMIT", "is_quick", "locked", "quick_account", "restored"]
