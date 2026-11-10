"""로그인·세션·구성원 관리(docs/operations.md(서비스) 2절). API는 이 서비스만 부르고, 저장은 ripple/store/accounts.py.

- 세션은 서버 쪽(무작위 토큰, 저장은 해시만): 관리자·담당자 12시간, 체험 2시간 절대 만료.
- 비밀번호 변경·초기화·끄기·역할 변경은 계정의 세션 판을 올리고 세션을 지운다(변경한 본인은 새 세션). 세션은 만들 때의
  판을 가져 판이 다르면 무효 — 로그인 검증과 관리자 초기화가 엇갈려도 옛 비밀번호의 세션이 남지 않는다.
- 계정은 잠금 안에서 지금 사본을 읽어 바꾼다(검증하려고 먼저 읽은 사본으로 덮어 동시 변경을 지우지 않게).
- 개발 모드(required=False)는 모든 요청을 '개발 모드' 관리자로 처리한다(RIPPLE_AUTH=off, 이미지·배포에는 두지 않음).

요청한 사람·오류·아이디 규칙은 principal.py, 구성원 관리(관리자)는 members.py, 저장된 계정 고치기·찾기는 accounts.py,
빠른 로그인(시연 배포 전용 고정 계정)은 quick.py.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from ripple.contracts.auth import (
    Account,
    AccountCreate,
    AccountCreated,
    AccountUpdate,
    AuthOptions,
    PasswordIssued,
    Permission,
    QuickRole,
    Role,
)
from ripple.store.accounts import AccountStore, SessionStore, StoredAccount, StoredSession

from .accounts import existing, mutate
from .members import Members
from .passwords import burn_time, hash_password, password_problem, verify_password
from .principal import (
    DEMO_ID,
    DEMO_NAME,
    DEV_PRINCIPAL,
    RESERVED_IDS,
    AuthError,
    Principal,
    normalize_id,
    valid_login_id,
)
from .quick import QUICK_SESSION_LIMIT, is_quick, quick_account
from .throttle import LoginThrottle

SESSION_HOURS = 12
DEMO_SESSION_HOURS = 2
HASH_SLOTS = 2  # 비밀번호 해시(scrypt 32MiB)는 동시에 2개까지
HASH_WAIT_S = 10.0


class AuthService:
    def __init__(
        self,
        accounts: AccountStore,
        sessions: SessionStore,
        *,
        required: bool = True,
        demo_login: bool = False,
        quick_login: bool = False,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        throttle: LoginThrottle | None = None,
    ) -> None:
        self.accounts = accounts
        self.sessions = sessions
        self.required = required
        self.demo_login = demo_login
        self.quick_login = quick_login  # 빠른 로그인(quick.py) — 개발 모드에서는 쓰지 않는다
        self._now = now
        self._monotonic = monotonic
        self._throttle = throttle or LoginThrottle()
        self._hashing = threading.BoundedSemaphore(HASH_SLOTS)
        # 해시 자리는 부를 때마다 self._hash_slot(인스턴스에서 바꿔 끼워도 구성원 관리가 같은 것을 쓴다)
        self._members = Members(accounts, sessions, now=now, hash_slot=lambda: self._hash_slot())

    # ---------- 시작 ----------

    def start(self, admin_id: str | None = None, admin_password: str | None = None) -> str | None:
        """저장소를 읽고, 계정이 하나도 없으면 첫 관리자를 만든다. 첫 관리자 변수에 문제가 있으면 그 이유(만들지 않음).

        빠른 로그인 고정 계정은 세지 않는다(시연 뒤 빠른 로그인을 끄고 첫 관리자 변수를 넣으면 관리자가 생기게).
        계정 파일이 손상됐으면 AccountStoreError가 그대로 올라가 앱이 시작하지 않는다.
        """
        self.accounts.load()
        self.sessions.load(self._now())
        if self._people() or not (admin_id or admin_password):
            return None
        if not admin_id or not admin_password:
            return "RIPPLE_ADMIN_ID와 RIPPLE_ADMIN_PASSWORD를 함께 넣어 주십시오(첫 관리자를 만들지 않았습니다)"
        key = normalize_id(admin_id)
        if not valid_login_id(key) or key in RESERVED_IDS:
            return (
                "RIPPLE_ADMIN_ID는 영문 소문자·숫자로 시작하는 3~32자(._- 가능)여야 합니다"
                "(첫 관리자를 만들지 않았습니다)"
            )
        if self.accounts.is_retired(key):
            return "RIPPLE_ADMIN_ID는 삭제한 계정의 아이디라 다시 사용할 수 없습니다(첫 관리자를 만들지 않았습니다)"
        problem = password_problem(admin_password, key)
        if problem:
            return f"RIPPLE_ADMIN_PASSWORD: {problem}(첫 관리자를 만들지 않았습니다)"
        account = StoredAccount(
            login_id=key,
            name="팀장",
            role=Role.ADMIN,
            password_hash=hash_password(admin_password),
            must_change_password=True,  # 배포 변수에 남은 비밀번호를 계속 쓰지 않게
            created_at=self._now(),
        )
        self.accounts.change(lambda accounts: accounts.__setitem__(key, account))
        return None

    def options(self) -> AuthOptions:
        """accounts_ready는 아이디·비밀번호로 들어갈 수 있는 켜진 팀장이 있나(빠른 로그인 고정 계정은 세지 않음)."""
        ready = any(a.role is Role.ADMIN and not a.disabled for a in self._people()) if self.required else True
        return AuthOptions(
            required=self.required,
            demo_login=self.demo_login,
            accounts_ready=ready,
            quick_login=self._quick_on,
        )

    # ---------- 로그인 ----------

    def login(self, login_id: str, password: str) -> tuple[Principal, str]:
        key = normalize_id(login_id)
        with self._attempt(key, "로그인을"):
            account = self._check_password(key, password)
        if account.disabled:
            raise _disabled()
        now = self._now()
        verified = account.password_hash

        def stamp(current: StoredAccount) -> StoredAccount:
            if current.password_hash != verified:  # 검증한 사이 비밀번호가 바뀜(초기화 등)
                raise _wrong_credentials()
            if current.disabled:
                raise _disabled()
            return current.model_copy(update={"last_login_at": now})

        stamped = mutate(self.accounts, key, stamp)
        token = self._session(key, now, stamped.session_version)
        return _principal(stamped, token), token

    def demo(self) -> tuple[Principal, str]:
        if not self.required or not self.demo_login:
            raise AuthError(404, "demo_unavailable", "체험 로그인이 꺼져 있습니다")
        now = self._now()
        token = self.sessions.create(DEMO_ID, demo=True, now=now, expires_at=now + timedelta(hours=DEMO_SESSION_HOURS))
        return _demo_principal(token), token

    def quick(self, role: QuickRole) -> tuple[Principal, str]:
        """빠른 로그인: 그 역할의 고정 계정(없으면 만들고 상수대로 되돌림)으로 로그인과 같은 세션 — 계정마다 최근
        QUICK_SESSION_LIMIT개만 남긴다. 꺼져 있거나 개발 모드면 404."""
        if not self._quick_on:
            raise AuthError(404, "quick_unavailable", "빠른 로그인이 꺼져 있습니다")
        now = self._now()
        account = quick_account(self.accounts, role, now=now, hash_slot=self._hash_slot)
        token = self._session(account.login_id, now, account.session_version, keep_latest=QUICK_SESSION_LIMIT)
        return _principal(account, token), token

    def resolve(self, token: str | None) -> Principal | None:
        """쿠키의 토큰 → 사람. 없거나 만료·폐기·꺼진 계정이면 None. 개발 모드는 늘 개발 관리자."""
        if not self.required:
            return DEV_PRINCIPAL
        if not token:
            return None
        session = self.sessions.resolve(token, self._now())
        if session is None or not self._still_on(session):
            return None
        if session.demo:
            return _demo_principal(token)
        account = self.accounts.get(session.login_id)
        if account is None or account.disabled or session.account_version != account.session_version:
            return None
        return _principal(account, token)

    def logout(self, token: str | None) -> None:
        if token and self.required:
            self.sessions.delete(token)

    def change_password(self, principal: Principal, current: str, new: str) -> tuple[Principal, str]:
        if principal.demo or principal.token is None or not principal.can(Permission.CHANGE_PASSWORD):
            raise AuthError(403, "forbidden", "이 계정은 비밀번호를 변경할 수 없습니다")
        key = principal.login_id
        guard = f"password:{key}"
        with self._attempt(guard, "현재 비밀번호를"):
            account = existing(self.accounts, key)
            with self._hash_slot():
                matched = verify_password(current, account.password_hash)
            if not matched:
                self._throttle.fail(guard, self._monotonic())
                # 401이 아니라 422: 화면은 401을 '로그인이 끝남'으로 보고 로그인 화면으로 보낸다
                raise AuthError(422, "invalid_credentials", "현재 비밀번호가 일치하지 않습니다")
            self._throttle.succeed(guard)
        problem = password_problem(new, key)
        if problem is None and new == current:
            problem = "현재 비밀번호와 다른 비밀번호를 정해 주십시오"
        if problem:
            raise AuthError(422, "weak_password", problem)
        with self._hash_slot():
            hashed = hash_password(new)
        verified = account.password_hash

        def replace(current: StoredAccount) -> StoredAccount:
            if current.password_hash != verified:  # 그사이 초기화됨 → 이 세션은 이미 무효
                raise AuthError(401, "unauthenticated", "비밀번호가 변경되었습니다. 다시 로그인해 주십시오")
            return current.model_copy(
                update={
                    "password_hash": hashed,
                    "must_change_password": False,
                    "session_version": current.session_version + 1,
                }
            )

        updated = mutate(self.accounts, key, replace)
        self.sessions.delete_for(key, below=updated.session_version)
        token = self._session(key, self._now(), updated.session_version)
        return _principal(updated, token), token

    # ---------- 구성원 관리(관리자, members.py) ----------

    def list_accounts(self) -> tuple[Account, ...]:
        return self._members.list_accounts()

    def create_account(self, body: AccountCreate) -> AccountCreated:
        return self._members.create_account(body)

    def reset_password(self, actor: Principal, login_id: str) -> PasswordIssued:
        return self._members.reset_password(actor, login_id)

    def update_account(self, actor: Principal, login_id: str, body: AccountUpdate) -> Account:
        return self._members.update_account(actor, login_id, body)

    def delete_account(self, actor: Principal, login_id: str) -> None:
        self._members.delete_account(actor, login_id)

    # ---------- 안쪽 ----------

    @property
    def _quick_on(self) -> bool:
        """빠른 로그인을 쓸 수 있나: 켜 두었고 개발 모드가 아님."""
        return self.required and self.quick_login

    def _still_on(self, session: StoredSession) -> bool:
        """체험·빠른 로그인 세션은 그 설정을 끄면 무효(끈 뒤 남은 세션으로 공용 계정을 계속 쓰지 않게)."""
        if session.demo:
            return self.demo_login
        return self._quick_on or not is_quick(session.login_id)

    def _check_password(self, key: str, password: str) -> StoredAccount:
        """아이디·비밀번호가 맞는 계정(실패 제한을 센다). 없는 아이디·틀린 비밀번호·빠른 로그인 고정 계정은 같은 계산·
        같은 실패 문구로 401 — 고정 계정은 아이디·비밀번호로 들어갈 수 없다."""
        account = self.accounts.get(key) if valid_login_id(key) and not is_quick(key) else None
        with self._hash_slot():
            if account is None:
                burn_time(password)
                matched = False
            else:
                matched = verify_password(password, account.password_hash)
        if account is None or not matched:
            self._throttle.fail(key, self._monotonic())
            raise _wrong_credentials()
        self._throttle.succeed(key)
        return account

    @contextmanager
    def _attempt(self, guard: str, what: str) -> Iterator[None]:
        """비밀번호 한 번 검사. 같은 대상으로 여러 번 틀려 막힌 동안은 429(몇 분 뒤에 다시 하면 되는지 알려 준다).
        확인과 자리 잡기가 한 번에 일어나 동시 요청이 함께 확인을 지나 실패 제한을 넘지 않는다(throttle.py)."""
        wait = self._throttle.reserve(guard, self._monotonic())
        if wait is not None:
            minutes = max(1, (wait + 59) // 60)
            message = f"{what} 여러 번 잘못 입력했습니다. {minutes}분 뒤 다시 시도해 주십시오"
            raise AuthError(429, "too_many_attempts", message, wait)
        try:
            yield
        finally:
            self._throttle.release(guard)

    def _session(self, key: str, now: datetime, version: int, *, keep_latest: int | None = None) -> str:
        """관리자·담당자 세션(SESSION_HOURS 절대 만료, 계정의 세션 판을 가진다). keep_latest = 그 계정 세션 상한."""
        expires = now + timedelta(hours=SESSION_HOURS)
        return self.sessions.create(
            key, demo=False, now=now, expires_at=expires, version=version, keep_latest=keep_latest
        )

    def _people(self) -> tuple[StoredAccount, ...]:
        """아이디·비밀번호로 들어가는 계정(빠른 로그인 고정 계정을 뺌): 첫 관리자·계정 준비 판단에 쓴다."""
        return tuple(a for a in self.accounts.all() if not is_quick(a.login_id))

    @contextmanager
    def _hash_slot(self) -> Iterator[None]:
        if not self._hashing.acquire(timeout=HASH_WAIT_S):
            raise AuthError(503, "busy", "로그인 요청이 많습니다. 잠시 뒤 다시 시도해 주십시오")
        try:
            yield
        finally:
            self._hashing.release()


def _principal(account: StoredAccount, token: str) -> Principal:
    return Principal(
        login_id=account.login_id,
        name=account.name,
        role=account.role,
        must_change_password=account.must_change_password,
        token=token,
    )


def _demo_principal(token: str) -> Principal:
    """체험 공용 계정(저장소 밖)."""
    return Principal(login_id=DEMO_ID, name=DEMO_NAME, role=Role.DEMO, demo=True, token=token)


def _wrong_credentials() -> AuthError:
    return AuthError(401, "invalid_credentials", "아이디 또는 비밀번호가 일치하지 않습니다")


def _disabled() -> AuthError:
    return AuthError(403, "account_disabled", "사용이 중지된 계정입니다. 팀장에게 문의해 주십시오")


__all__ = ["DEMO_SESSION_HOURS", "SESSION_HOURS", "AuthService"]
