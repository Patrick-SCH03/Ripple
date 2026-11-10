"""로그인 부품의 성질(docs/operations.md(서비스) 2절).

비밀번호 해시·규칙·임시 비밀번호, 실패 제한, 계정·세션 파일(손상·재시작·해시만), 설정.

API·권한 행렬·흐름은 tests/checks/auth_api.py.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from harness import Checker

from ripple.auth import AuthError, AuthService, Principal
from ripple.auth.passwords import hash_password, password_problem, temporary_password, verify_password
from ripple.auth.throttle import LoginThrottle
from ripple.config.settings import Settings
from ripple.contracts.auth import AccountCreate, AccountUpdate, Role
from ripple.store.accounts import AccountStore, AccountStoreError, SessionStore, StoredAccount

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")

BASE = "https://testserver"  # Secure 쿠키가 오가게 https로
FIRST = "first-pass-2026"  # 검사용 첫 관리자 비밀번호(배포 값 아님)
ADMIN_PW = "lead-pass-2026-x"
MEMBER_PW = "kim-pass-2026-x"
ADMIN_ENV = {"RIPPLE_ADMIN_ID": "lead", "RIPPLE_ADMIN_PASSWORD": FIRST}
ROLES = ("anon", "demo", "member", "admin_mc", "admin")
OPEN = "open"  # 누구나(로그인 전 포함): 401·403이 아니다
SESSION = "session"  # 세션을 바꾸는 경로: 행렬 대신 아래 전용 검사로 본다
VIEW = frozenset({"demo", "member", "admin"})
ADMIN = frozenset({"admin"})
ME = frozenset({"demo", "member", "admin_mc", "admin"})
MATRIX: dict[tuple[str, str], str | frozenset[str]] = {
    ("GET", "/api/health"): OPEN,
    ("POST", "/api/auth/login"): SESSION,
    ("POST", "/api/auth/demo"): SESSION,
    ("POST", "/api/auth/logout"): SESSION,
    ("POST", "/api/auth/password"): SESSION,
    ("GET", "/api/auth/me"): ME,
    ("GET", "/api/accounts"): ADMIN,
    ("POST", "/api/accounts"): ADMIN,
    ("POST", "/api/accounts/{login_id}/reset-password"): ADMIN,
    ("PATCH", "/api/accounts/{login_id}"): ADMIN,
    ("GET", "/api/snapshots"): VIEW,
    ("POST", "/api/snapshots/{snapshot_id}/activate"): ADMIN,
    ("GET", "/api/snapshots/{snapshot_id}/export"): VIEW,
    ("POST", "/api/imports"): ADMIN,
    ("POST", "/api/imports/{import_id}/proposal"): ADMIN,
    ("POST", "/api/imports/{import_id}/mapping"): ADMIN,
    ("POST", "/api/imports/{import_id}/confirm"): ADMIN,
    ("POST", "/api/impacts"): VIEW,
    ("GET", "/api/graph/view"): VIEW,
    ("GET", "/api/samples"): VIEW,
    ("POST", "/api/analyses"): VIEW,
    ("POST", "/api/assistant/turns"): VIEW,
    ("GET", "/api/assistant/conversations/{conversation_id}"): VIEW,
}
FILL = {
    "{login_id}": "nobody",
    "{snapshot_id}": "G-0000000000000000",
    "{import_id}": "I-none",
    "{conversation_id}": "C-none",
}


def run(c: Checker) -> None:
    _passwords(c)
    _throttle(c)
    _stores(c)
    _settings(c)
    _races(c)


def _passwords(c: Checker) -> None:
    c.section("로그인: 비밀번호 해시·규칙·임시 비밀번호")
    encoded = hash_password("correct horse 42")
    c.check(
        "해시 → 같은 비밀번호는 맞음, 다른 비밀번호는 틀림",
        verify_password("correct horse 42", encoded) and not verify_password("correct horse 43", encoded),
    )
    c.check("해시에 매개변수가 함께 적힘(scrypt$N$r$p$솔트$해시)", encoded.startswith("scrypt$32768$8$1$"))
    c.check("같은 비밀번호도 솔트가 달라 해시가 다름", hash_password("correct horse 42") != encoded)
    parts = encoded.split("$")
    tampered = "$".join([*parts[:5], parts[5][:-4] + "AAA="])
    c.check(
        "손상·형식이 틀린 해시는 예외 없이 틀림",
        not verify_password("correct horse 42", tampered)
        and not verify_password("x", "plain")
        and not verify_password("x", "scrypt$1$8$1$!!$!!")
        and not verify_password("correct horse 42", encoded.replace("scrypt$32768", "scrypt$16384")),
    )
    c.check(
        "규칙: 10자 미만·아이디 포함·같은 글자 반복·흔한 비밀번호·앞뒤 공백은 거절, 좋은 비밀번호는 통과",
        password_problem("short1", "kim") is not None
        and password_problem("kim12345", "kim") is not None
        and password_problem("kimkim-01", "kimkim") is not None
        and password_problem("aaaaaaaaaaab", "lee") is not None
        and password_problem("password123", "lee") is not None
        and password_problem(" spaced-pass-1", "lee") is not None
        and password_problem("ship-design-2026", "kim") is None,
    )
    temps = [temporary_password() for _ in range(50)]
    c.check(
        "임시 비밀번호: 12자, 헷갈리는 글자 없음, 숫자·글자 섞임, 서로 다름",
        all(len(t) == 12 and not set(t) & set("0Oo1lI") for t in temps)
        and all(any(ch.isdigit() for ch in t) and any(ch.isalpha() for ch in t) for t in temps)
        and len(set(temps)) == 50,
    )


def _throttle(c: Checker) -> None:
    c.section("로그인: 실패 제한")
    throttle = LoginThrottle(window_s=900, limit=5)
    for second in range(5):
        throttle.fail("kim", float(second))
    blocked = throttle.retry_after("kim", 10.0)
    c.check("15분 안 5번 틀리면 막힘(남은 초 = 첫 실패 + 15분 − 지금)", blocked == 890, blocked)
    c.check("다른 아이디는 막히지 않음", throttle.retry_after("lee", 10.0) is None)
    c.check("첫 실패가 창 밖으로 나가면 다시 됨", throttle.retry_after("kim", 900.5) is None)
    throttle.fail("lee", 1.0)
    throttle.succeed("lee")
    c.check("성공하면 그 아이디의 실패 기록을 비움", throttle.retry_after("lee", 2.0) is None)
    _concurrent_failures(c)


def _concurrent_failures(c: Checker) -> None:
    """동시에 들어온 틀린 로그인 10건: 잠금 확인과 실패 기록 사이에 해시 대기가 끼어도 비밀번호 검사는 5번까지."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        service = AuthService(AccountStore(root), SessionStore(root))
        service.start("lead", FIRST)
        opened = threading.Event()
        checked: list[int] = []

        @contextmanager
        def slow_slot() -> Iterator[None]:
            opened.wait(5.0)  # 모든 요청이 잠금 확인을 지난 뒤에야 해시 자리가 열림
            checked.append(1)
            yield

        setattr(service, "_hash_slot", slow_slot)  # noqa: B010
        statuses: list[int] = []

        def attempt() -> None:
            try:
                service.login("lead", "wrong-pass-2026")
            except AuthError as error:
                statuses.append(error.status)

        threads = [threading.Thread(target=attempt) for _ in range(10)]
        for thread in threads:
            thread.start()
        time.sleep(0.5)
        opened.set()
        for thread in threads:
            thread.join(30.0)
        c.check(
            "동시 실패 10건 중 비밀번호 검사는 실패 제한(5번)까지, 나머지는 429",
            len(checked) == 5 and sorted(statuses) == [401] * 5 + [429] * 5,
            (len(checked), sorted(statuses)),
        )


def _stores(c: Checker) -> None:
    c.section("로그인: 계정·세션 파일")
    now = datetime(2026, 10, 9, 9, 0, tzinfo=UTC)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        sessions = SessionStore(root)
        sessions.load(now)
        token = sessions.create("kim", demo=False, now=now, expires_at=now + timedelta(hours=12))
        text = (root / "sessions.json").read_text(encoding="utf-8")
        c.check("세션 파일에는 토큰이 아니라 해시만", token not in text and len(json.loads(text)["sessions"]) == 1)
        again = SessionStore(root)
        again.load(now)
        c.check("다시 읽어도 세션 유지", again.resolve(token, now) is not None)
        c.check("만료 뒤에는 없음", again.resolve(token, now + timedelta(hours=12)) is None)
        other = again.create("kim", demo=False, now=now, expires_at=now + timedelta(hours=12))
        again.delete_for("kim", keep=other)
        c.check(
            "계정 세션 지우기(하나 남기기)", again.resolve(token, now) is None and again.resolve(other, now) is not None
        )
        (root / "sessions.json").write_text("{깨짐", encoding="utf-8")
        broken = SessionStore(root)
        broken.load(now)
        c.check(
            "세션 파일 손상 → 세션 없이 시작하고 이유를 남김",
            broken.load_problem is not None and broken.resolve(other, now) is None,
        )
        (root / "accounts.json").write_text('{"version": 1, "accounts": [{"login_id": "X"}]}', encoding="utf-8")
        c.check(
            "계정 파일 손상 → 읽기 오류(시작을 멈춤)", c.raises(lambda: AccountStore(root).load(), AccountStoreError)
        )


def _settings(c: Checker) -> None:
    c.section("로그인: 설정")
    c.check(
        "기본값: 로그인 켬 · 체험 끔 · 빠른 로그인 끔 · Secure 쿠키 켬",
        (s := Settings.from_env({})).auth_required and not s.demo_login and not s.quick_login and s.cookie_secure,
    )
    c.check(
        "on/off 오타는 시작할 때 거부(빠른 로그인 포함), 빠른 로그인은 on일 때만 켬",
        c.raises(lambda: Settings.from_env({"RIPPLE_AUTH": "of"}))
        and c.raises(lambda: Settings.from_env({"RIPPLE_QUICK_LOGIN": "yes"}))
        and Settings.from_env({"RIPPLE_QUICK_LOGIN": "ON"}).quick_login,
    )
    c.check(
        "빌드 커밋: RIPPLE_BUILD 먼저, 없으면 RAILWAY_GIT_COMMIT_SHA, 형식이 아니면 버림",
        Settings.from_env({"RIPPLE_BUILD": "abc1234"}).build == "abc1234"
        and Settings.from_env({"RAILWAY_GIT_COMMIT_SHA": "f" * 40}).build == "f" * 40
        and Settings.from_env({"RIPPLE_BUILD": "<script>"}).build is None,
    )


def _races(c: Checker) -> None:
    """검증하려고 먼저 읽은 계정 사본과 그사이 관리자 변경이 엇갈릴 때(잠금 밖 읽기 → 잠금 안 쓰기)."""
    c.section("로그인: 계정 쓰기 경합·세션 판")
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        accounts = AccountStore(root)
        sessions = SessionStore(root)
        service = AuthService(accounts, sessions)
        service.start("lead", "first-pass-2026")
        created = service.create_account(AccountCreate(login_id="kim", name="김담당", role=Role.MEMBER))
        real_get = accounts.get

        def stale_reads(snapshot: StoredAccount | None) -> None:
            """kim을 읽으면 먼저 읽어 둔 사본을 돌려준다(잠금 밖 읽기 흉내). 메서드를 인스턴스 속성으로 잠깐 가린다."""
            setattr(accounts, "get", lambda key: snapshot if key == "kim" else real_get(key))  # noqa: B010

        # ① 로그인이 옛 사본(담당자)을 읽은 뒤 관리자가 역할을 바꿈 → 로그인이 역할을 되돌리지 않음
        stale = real_get("kim")
        service.update_account(
            Principal(login_id="lead", name="관리자", role=Role.ADMIN), "kim", AccountUpdate(role=Role.ADMIN)
        )
        stale_reads(stale)
        try:
            service.login("kim", created.temporary_password)
        finally:
            delattr(accounts, "get")
        kept = real_get("kim")
        c.check(
            "로그인이 먼저 읽은 옛 사본으로 역할 변경을 되돌리지 않음", kept is not None and kept.role is Role.ADMIN
        )

        # ② 로그인 검증 뒤 관리자가 초기화 → 옛 비밀번호로는 세션이 생기지 않음
        stale = real_get("kim")
        issued = service.reset_password(Principal(login_id="lead", name="관리자", role=Role.ADMIN), "kim")
        stale_reads(stale)
        try:
            refused = c.raises(lambda: service.login("kim", created.temporary_password), AuthError)
        finally:
            delattr(accounts, "get")
        c.check("검증한 사이 초기화되면 옛 비밀번호 로그인은 실패", refused and sessions.count_for("kim") == 0)

        # ③ 세션 지우기와 엇갈려 옛 판으로 만든 세션이 남아도 무효(세션 판)
        now = datetime.now(UTC)
        leftover = sessions.create("kim", demo=False, now=now, expires_at=now + timedelta(hours=1), version=0)
        current = real_get("kim")
        c.check(
            "계정 세션 판이 오른 뒤 옛 판의 세션은 무효",
            current is not None and current.session_version >= 1 and service.resolve(leftover) is None,
        )

        # ④ 비밀번호를 바꾸는 사이 초기화 → 401(그 세션은 이미 무효)
        _, token = service.login("kim", issued.temporary_password)
        member = service.resolve(token)
        stale = real_get("kim")
        service.reset_password(Principal(login_id="lead", name="관리자", role=Role.ADMIN), "kim")
        stale_reads(stale)
        try:
            raised: list[AuthError] = []
            try:
                if member is not None:
                    service.change_password(member, issued.temporary_password, "kim-new-pass-2026")
            except AuthError as error:
                raised.append(error)
        finally:
            delattr(accounts, "get")
        c.check(
            "비밀번호를 바꾸는 사이 초기화되면 401(새 비밀번호로 덮지 않음)",
            member is not None and [e.status for e in raised] == [401] and service.resolve(token) is None,
        )

        # ⑤ 계정은 바뀌었는데 세션 파일 쓰기(세션 지우기)가 실패 → 옛 세션은 세션 판으로 무효
        lee = service.create_account(AccountCreate(login_id="lee", name="이담당", role=Role.MEMBER))
        _, old_token = service.login("lee", lee.temporary_password)
        principal = service.resolve(old_token)
        assert principal is not None

        def broken(login_id: str, **_: object) -> None:
            raise OSError("디스크가 가득 찼어요")

        setattr(sessions, "delete_for", broken)  # noqa: B010
        try:
            failed = c.raises(
                lambda: service.change_password(principal, lee.temporary_password, "lee-new-pass-2026"), OSError
            )
        finally:
            delattr(sessions, "delete_for")
        c.check(
            "세션 지우기가 실패해도(파일 쓰기 오류) 비밀번호를 바꾼 계정의 옛 세션은 무효",
            failed and service.resolve(old_token) is None,
        )

        # ⑥ 계정 변경과 정리 사이에 새 판으로 로그인한 정상 세션은 늦은 정리가 지우지 않음(재검토 medium)
        now = datetime.now(UTC)
        fresh = real_get("lee")
        assert fresh is not None
        newer = sessions.create(
            "lee", demo=False, now=now, expires_at=now + timedelta(hours=1), version=fresh.session_version
        )
        older = sessions.create(
            "lee", demo=False, now=now, expires_at=now + timedelta(hours=1), version=max(0, fresh.session_version - 1)
        )
        sessions.delete_for("lee", below=fresh.session_version)
        c.check(
            "늦은 정리는 무효로 만든 판보다 오래된 세션만 지움(새 판의 세션은 남음)",
            sessions.resolve(newer, now) is not None and sessions.resolve(older, now) is None,
        )

        # ⑥-2 지우기가 먼저 읽은 대상 사본(담당자)이 그사이 유일한 팀장이 됨 → 마지막 팀장 지우기는 409
        lead = Principal(login_id="lead", name="관리자", role=Role.ADMIN)
        service.create_account(AccountCreate(login_id="park", name="박담당", role=Role.MEMBER))
        stale = real_get("park")
        service.update_account(lead, "park", AccountUpdate(role=Role.ADMIN))
        boss = Principal(login_id="park", name="박팀장", role=Role.ADMIN)
        for other in ("lead", "kim"):  # park만 사용 중 팀장으로 남김
            if (found := real_get(other)) is not None and found.role is Role.ADMIN:
                service.update_account(boss, other, AccountUpdate(disabled=True))
        setattr(accounts, "get", lambda key: stale if key == "park" else real_get(key))  # noqa: B010
        try:
            refused = c.raises(lambda: service.delete_account(lead, "park"), AuthError)
        finally:
            delattr(accounts, "get")
        c.check(
            "지우기는 잠금 안의 지금 계정으로 마지막 팀장을 판단(먼저 읽은 옛 사본이 담당자여도 409, 지우지 않음)",
            refused and real_get("park") is not None,
        )

    # ⑦ 파일 형식 판: 1(세션 판 없음)은 0으로 읽고, 모르는 판은 읽기 오류(시작 멈춤)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        old = {
            "version": 1,
            "accounts": [
                {
                    "login_id": "lead",
                    "name": "관리자",
                    "role": "admin",
                    "password_hash": hash_password("first-pass-2026"),
                    "created_at": "2026-10-09T00:00:00Z",
                }
            ],
        }
        (root / "accounts.json").write_text(json.dumps(old), encoding="utf-8")
        store = AccountStore(root)
        store.load()
        legacy = store.get("lead")
        c.check("형식 판 1 계정 파일은 세션 판 0으로 읽음", legacy is not None and legacy.session_version == 0)
        # 판 4(지운 아이디 목록)까지 아는 판 — 그다음 판이 모르는 판
        (root / "accounts.json").write_text(json.dumps({**old, "version": 5}), encoding="utf-8")
        c.check("모르는(더 새) 형식 판이면 읽기 오류", c.raises(lambda: AccountStore(root).load(), AccountStoreError))
