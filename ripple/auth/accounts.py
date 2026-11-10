"""저장된 계정 하나 다루기: 잠금 안에서 지금 사본 고치기(mutate)·찾기(existing)·공개 형태(public).

로그인·비밀번호 바꾸기(service.py)와 구성원 관리(members.py)가 함께 쓴다. 고치기는 늘 mutate로 — 검증하려고 먼저 읽은
사본으로 덮어 동시 변경을 지우지 않게.
"""

from __future__ import annotations

from collections.abc import Callable

from ripple.contracts.auth import Account
from ripple.store.accounts import AccountStore, StoredAccount

from .principal import AuthError


def mutate(accounts: AccountStore, key: str, change: Callable[[StoredAccount], StoredAccount]) -> StoredAccount:
    """잠금 안에서 지금 계정 사본에 change를 적용해 쓰고, 쓴 계정을 돌려준다(없으면 404)."""
    result: list[StoredAccount] = []

    def apply(stored: dict[str, StoredAccount]) -> None:
        current = stored.get(key)
        if current is None:
            raise AuthError(404, "not_found", "없는 계정")
        stored[key] = change(current)
        result.append(stored[key])

    accounts.change(apply)
    return result[0]


def existing(accounts: AccountStore, key: str) -> StoredAccount:
    account = accounts.get(key)
    if account is None:
        raise AuthError(404, "not_found", "없는 계정")
    return account


def public(account: StoredAccount) -> Account:
    return Account(
        login_id=account.login_id,
        name=account.name,
        role=account.role,
        disabled=account.disabled,
        must_change_password=account.must_change_password,
        created_at=account.created_at,
        last_login_at=account.last_login_at,
    )
