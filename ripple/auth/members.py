"""구성원 관리(관리자, docs/operations.md(서비스) 2절): 목록·만들기·임시 비밀번호 발급·이름·역할·끄기 바꾸기·지우기.

비밀번호 초기화·끄기·역할 변경은 계정의 세션 판을 올리고 그 계정의 세션을 지운다. 사용 중인 팀장이 한 명은 남아야 한다.
계정은 잠금 안에서 지금 사본을 읽어 바꾼다(accounts.py mutate — 검증하려고 먼저 읽은 사본으로 덮어 동시 변경을 지우지
않게).
내 줄(이름·역할·사용 여부·지우기)은 바꿀 수 없고(화면과 같은 규칙), 빠른 로그인 고정 계정은 바꿀 수 없다(quick.locked).
지우면 그 계정의 세션을 모두 끊고 아이디는 다시 쓰지 않는다 — 기록·감사에는 그때의 아이디·이름이 남아 있어(기록은 고칠
수 없는 사슬), 같은 아이디로 새 사람을 만들면 두 사람이 한 아이디로 섞인다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import datetime

from ripple.contracts.auth import Account, AccountCreate, AccountCreated, AccountUpdate, PasswordIssued, Role
from ripple.store.accounts import AccountStore, RetiredIdError, SessionStore, StoredAccount

from .accounts import existing, mutate, public
from .passwords import hash_password, temporary_password
from .principal import RESERVED_IDS, AuthError, Principal, normalize_id
from .quick import is_quick, locked


class Members:
    """계정 저장소·세션 저장소·시계·해시 자리(로그인과 같은 동시 해시 상한)를 받아 구성원을 관리한다."""

    def __init__(
        self,
        accounts: AccountStore,
        sessions: SessionStore,
        *,
        now: Callable[[], datetime],
        hash_slot: Callable[[], AbstractContextManager[None]],
    ) -> None:
        self._accounts = accounts
        self._sessions = sessions
        self._now = now
        self._hash_slot = hash_slot

    def list_accounts(self) -> tuple[Account, ...]:
        return tuple(public(a) for a in self._accounts.all())

    def create_account(self, body: AccountCreate) -> AccountCreated:
        key = normalize_id(body.login_id)
        if key in RESERVED_IDS:
            raise AuthError(409, "account_exists", "사용 불가 아이디 · 다른 아이디 필요")
        if self._accounts.is_retired(key):
            raise _retired_id()
        temporary = temporary_password()
        with self._hash_slot():
            hashed = hash_password(temporary)
        account = StoredAccount(
            login_id=key,
            name=body.name,
            role=body.role,
            password_hash=hashed,
            must_change_password=True,
            created_at=self._now(),
        )

        def add(accounts: dict[str, StoredAccount]) -> None:
            if key in accounts:
                raise AuthError(409, "account_exists", "이미 있는 아이디")
            accounts[key] = account

        try:
            self._accounts.change(add)
        except RetiredIdError:  # 확인한 사이 그 아이디의 계정이 지워짐
            raise _retired_id() from None
        return AccountCreated(account=public(account), temporary_password=temporary)

    def reset_password(self, actor: Principal, login_id: str) -> PasswordIssued:
        key = normalize_id(login_id)
        locked(key)
        if key == actor.login_id:
            raise AuthError(422, "forbidden", "내 비밀번호는 '비밀번호 바꾸기'에서 변경")
        existing(self._accounts, key)
        temporary = temporary_password()
        with self._hash_slot():
            hashed = hash_password(temporary)
        reset = mutate(
            self._accounts,
            key,
            lambda current: current.model_copy(
                update={
                    "password_hash": hashed,
                    "must_change_password": True,
                    "session_version": current.session_version + 1,
                }
            ),
        )
        self._sessions.delete_for(key, below=reset.session_version)
        return PasswordIssued(temporary_password=temporary)

    def update_account(self, actor: Principal, login_id: str, body: AccountUpdate) -> Account:
        key = normalize_id(login_id)
        locked(key)
        if key == actor.login_id:
            raise AuthError(403, "forbidden", "내 계정의 이름·역할·사용 여부는 다른 팀장만 변경 가능")
        changes = body.model_dump(exclude_none=True)
        result: list[tuple[StoredAccount, bool]] = []

        def apply(accounts: dict[str, StoredAccount]) -> None:
            current = accounts.get(key)
            if current is None:
                raise AuthError(404, "not_found", "없는 계정")
            updated = current.model_copy(update=changes)
            revoke = updated.role is not current.role or updated.disabled != current.disabled
            if revoke:
                updated = updated.model_copy(update={"session_version": current.session_version + 1})
            accounts[key] = updated
            _keep_admin(current, accounts)
            result.append((updated, revoke))

        self._accounts.change(apply)
        updated, revoke = result[0]
        if revoke:
            self._sessions.delete_for(key, below=updated.session_version)
        return public(updated)

    def delete_account(self, actor: Principal, login_id: str) -> None:
        """계정을 지우고 그 계정의 세션을 모두 끊는다. 내 계정·고정 계정은 403, 마지막 팀장은 409, 없으면 404."""
        key = normalize_id(login_id)
        locked(key)
        if key == actor.login_id:
            raise AuthError(403, "forbidden", "내 계정 삭제 불가")
        if self._accounts.delete(key, _keep_admin) is None:  # 대상은 잠금 안의 지금 사본(먼저 읽지 않음)
            raise AuthError(404, "not_found", "없는 계정")
        # 지운 계정의 세션은 이미 무효(resolve가 계정을 찾지 못함) — 파일에서도 정리한다
        self._sessions.delete_for(key)


def _keep_admin(touched: StoredAccount | None, after: Mapping[str, StoredAccount]) -> None:
    """바꾸거나 지운 계정(touched — 바꾸기 전)이 아이디로 들어오는 사용 중 팀장이었는데 그 뒤(after) 그런 팀장이
    0명이면 409.

    빠른 로그인 고정 팀장(quick-lead)은 세지 않는다 — 아이디로 들어갈 수 없고 시연 뒤 빠른 로그인을 끄면 세션도
    무효라, 셈에 넣으면 마지막 실제 팀장을 멈추거나 지운 뒤 아이디로 들어올 팀장이 없다(복구는 CLI뿐, 점검 E-5).
    첫 관리자·계정 준비 판단과 같은 규칙(service._people)이다. 실제 팀장이 원래 없던 시연 배포에서 다른 계정을
    바꾸는 일은 막지 않는다."""
    if touched is None or not _real_admin(touched):
        return
    if not any(_real_admin(a) for a in after.values()):
        raise AuthError(409, "last_admin", "아이디로 로그인하는 사용 중 팀장 1명 이상 필요")


def _real_admin(account: StoredAccount) -> bool:
    """아이디로 들어오는 사용 중인 팀장(빠른 로그인 고정 계정 아님)."""
    return account.role is Role.ADMIN and not account.disabled and not is_quick(account.login_id)


def _retired_id() -> AuthError:
    return AuthError(409, "account_exists", "지운 계정의 아이디 재사용 불가 · 다른 아이디 필요")
