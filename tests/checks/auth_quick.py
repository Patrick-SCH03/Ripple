"""빠른 로그인의 API 성질(계약 1.30.0, docs/operations.md(서비스) 2절). 묶음 auth_api가 만든 합성 지도 폴더로 부른다.

- 꺼짐(기본)·개발 모드는 404 quick_unavailable, 상태 확인의 auth.quick_login이 설정을 따른다. 출처 검사도 그대로.
- 켜면 역할마다 고정 계정(담당자 quick-member 김설계 · 파트장 part-lead 이파트장 · 팀장 quick-lead 박팀장 · 본부장
  executive 최본부장)으로 로그인과 같은 세션·쿠키.
- 계정은 한 번만 생기고 다시 눌러도 같은 계정. 자기 결정 금지 그대로(담당자 검토 요청 → 팀장 승인 200), 네 계정이
  서로 다른 사람이라 결재선(파트장 → 팀장 → 본부장)을 전결 없이 차례로 승인.
- 고정 계정이 다음 방문자의 단추를 망가뜨리지 않게:
  1. 구성원 관리(이름·역할·끄기·초기화)는 고정 계정을 403으로 거절, 내 줄도 403,
     손으로 고친 계정은 빠른 로그인이 상수로 복구.
  2. 고정 계정마다 세션은 최근 200개만 — 인증 없이 반복해도 다른 계정 세션이 밀려나지 않음.
  3. 설정을 끄면 남은 고정 계정 세션은 무효.
  4. 아이디·비밀번호로는 고정 계정에 못 들어감(없는 아이디와 같은 실패 문구).
  5. 첫 관리자 만들기·accounts_ready는 고정 계정을 세지 않음.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from harness import Checker

from checks.records import (
    ADMIN_ENV,
    ADMIN_PW,
    BASE,
    FIRST,
    _action,
    _analysis,
    _app,
    _approve_line,
    _client,
    _code,
    _login,
    _record,
)
from ripple.auth.passwords import hash_password
from ripple.auth.principal import RESERVED_IDS
from ripple.auth.quick import QUICK_ACCOUNTS, QUICK_SESSION_LIMIT, is_quick, restored
from ripple.contracts.auth import Role
from ripple.store.accounts import (
    MAX_SESSIONS,
    SessionStore,
    StoredAccount,
    StoredSession,
    over_cap,
    stale_own,
    token_hash,
)

QUICK_ON = {"RIPPLE_QUICK_LOGIN": "on"}
LOCKED = "시연용 고정 계정 변경 불가"


def run(c: Checker, root: Path) -> None:
    _pure(c)
    _off(c, root)
    _dev(c, root)
    _on(c, root)
    _race(c, root)
    _limit(c, root)
    _evict_own_first(c, root)
    _restart(c, root)


def _quick(client: TestClient, role: str, **kwargs: Any) -> Any:
    return client.post("/api/auth/quick", json={"role": role}, **kwargs)


def _message(response: Any) -> str | None:
    detail = response.json().get("detail")
    return detail.get("message") if isinstance(detail, dict) else None


def _with(app: FastAPI, token: str) -> TestClient:
    return TestClient(app, base_url=BASE, headers={"Cookie": f"ripple_session={token}"})


def _tamper(app: FastAPI, login_id: str, **changes: Any) -> None:
    """계정 파일을 손으로 고친 것처럼 저장소의 계정을 바로 바꾼다(구성원 관리 API를 거치지 않음)."""

    def edit(stored: dict[str, Any]) -> None:
        stored[login_id] = stored[login_id].model_copy(update=changes)

    app.state.auth.accounts.change(edit)


def _pure(c: Checker) -> None:
    """서버 없이 도는 순수 부분: 고정 계정 술어 · 자가 복구 사본 · 세션 상한 고르기."""
    c.section("빠른 로그인: 순수 함수(고정 계정 술어 · 자가 복구 · 세션 상한)")
    ids = [login_id for login_id, _ in QUICK_ACCOUNTS.values()]
    c.check(
        "is_quick: 네 고정 계정 아이디(담당자·파트장·팀장·본부장)만 참(예약 아이디 demo·dev, 비슷한 아이디, 대문자는 "
        "거짓 — 정규화한 아이디로)",
        sorted(ids) == ["executive", "part-lead", "quick-lead", "quick-member"]
        and all(is_quick(login_id) for login_id in ids)
        and {i for i in RESERVED_IDS if is_quick(i)} == set(ids)
        and not any(
            is_quick(other)
            for other in ("quick", "quick-lead2", "QUICK-LEAD", " quick-lead", "lead", "part", "Executive", "exec")
        ),
        ids,
    )
    c.check(
        "고정 계정 세션 상한 합(계정 수 × QUICK_SESSION_LIMIT)이 전역 상한 MAX_SESSIONS보다 작음",
        QUICK_SESSION_LIMIT * len(QUICK_ACCOUNTS) < MAX_SESSIONS,
        (QUICK_SESSION_LIMIT, len(QUICK_ACCOUNTS), MAX_SESSIONS),
    )
    start = datetime(2026, 10, 1, tzinfo=UTC)
    broken = StoredAccount(
        login_id="quick-lead",
        name="망가짐",
        role=Role.MEMBER,
        password_hash="x",
        disabled=True,
        must_change_password=True,
        created_at=start,
        session_version=3,
    )
    later = start + timedelta(days=1)
    back = restored(broken, Role.ADMIN, later)
    c.check(
        "restored: 이름·역할·사용 중·비밀번호 정하기 없음을 상수로, 로그인 시각을 찍고 "
        "해시·만든 시각·세션 판은 그대로(원본 불변)",
        (back.name, back.role, back.disabled, back.must_change_password, back.last_login_at)
        == ("박팀장", Role.ADMIN, False, False, later)
        and (back.password_hash, back.created_at, back.session_version) == ("x", start, 3)
        and (broken.name, broken.disabled) == ("망가짐", True),
        back,
    )

    def session(login_id: str, minute: int) -> StoredSession:
        at = start + timedelta(minutes=minute)
        return StoredSession(
            token_hash=token_hash(f"{login_id}-{minute}"),
            login_id=login_id,
            created_at=at,
            expires_at=at + timedelta(hours=12),
        )

    mine = [session("quick-lead", minute) for minute in (5, 1, 3)]
    others = [session("kim", minute) for minute in (0, 2)]
    tied = [session("quick-lead", 9), session("quick-lead", 9)]
    tied[1] = tied[1].model_copy(update={"token_hash": token_hash("tied-later")})
    c.check(
        "stale_own: 그 계정 세션만, 최근 keep개를 넘는 오래된 것부터(같은 시각이면 먼저 들어온 것), "
        "넘지 않으면 빈 목록",
        [s.created_at.minute for s in stale_own(mine + others, "quick-lead", 1)] == [1, 3]
        and stale_own(mine + others, "quick-lead", 3) == []
        and stale_own(others, "quick-lead", 0) == []
        and stale_own(tied, "quick-lead", 1) == [tied[0]],
    )
    fresh = session("quick-lead", 30)
    pool = [*others, *mine, fresh]
    c.check(
        "over_cap: 상한 안이면 빈 목록 · 상한 있는 계정(owner)은 자기 오래된 세션부터(방금 만든 것은 빼고) · "
        "owner가 없으면 전체에서 오래된 순",
        over_cap(pool, owner="quick-lead", fresh=fresh, cap=len(pool)) == []
        and [s.created_at.minute for s in over_cap(pool, owner="quick-lead", fresh=fresh, cap=3)] == [1, 3, 5]
        and over_cap(pool, owner="quick-lead", fresh=fresh, cap=0)[-1] is fresh
        and [s.created_at.minute for s in over_cap(pool, owner=None, fresh=fresh, cap=3)] == [0, 1, 2],
    )


def _off(c: Checker, root: Path) -> None:
    c.section("빠른 로그인: 꺼짐(기본) — 404 · 예약 아이디")
    app = _app(root, "data-quick-off")
    with _client(app) as client:
        refused = _quick(client, "member")
        c.check(
            "꺼져 있으면 404 quick_unavailable · 상태 확인 quick_login=false · 고정 계정을 만들지 않음",
            refused.status_code == 404
            and _code(refused) == "quick_unavailable"
            and client.get("/api/health").json()["auth"]["quick_login"] is False
            and app.state.auth.accounts.get("quick-member") is None,
            refused.json(),
        )
        _login(client, "lead", FIRST)
        client.post("/api/auth/password", json={"current_password": FIRST, "new_password": ADMIN_PW})
        made = [
            client.post("/api/accounts", json={"login_id": key, "name": "가짜"})
            for key in ("quick-member", "quick-lead", "part-lead", "executive")
        ]
        c.check(
            "구성원 추가로 고정 계정 아이디를 만들 수 없음(409, 사용 불가 아이디)",
            all(r.status_code == 409 and "사용 불가 아이디" in r.json()["detail"]["message"] for r in made),
            [r.status_code for r in made],
        )


def _dev(c: Checker, root: Path) -> None:
    c.section("빠른 로그인: 개발 모드(RIPPLE_AUTH=off)에서는 의미 없음")
    app = _app(root, "data-quick-dev", extra={**QUICK_ON, "RIPPLE_AUTH": "off"})
    with _client(app) as client:
        refused = _quick(client, "admin")
        c.check(
            "켜 두어도 개발 모드면 404 quick_unavailable · 상태 확인 quick_login=false",
            refused.status_code == 404
            and _code(refused) == "quick_unavailable"
            and client.get("/api/health").json()["auth"]["quick_login"] is False,
            refused.json(),
        )


def _on(c: Checker, root: Path) -> None:
    c.section("빠른 로그인: 켜짐 — 역할별 고정 계정 · 같은 계정 · 출처 · 결재")
    app = _app(root, "data-quick", extra=QUICK_ON, environ={})
    with _client(app) as main:
        ready = main.get("/api/health").json()["auth"]
        c.check(
            "켜면 상태 확인 quick_login=true(첫 관리자 변수가 없어 아직 팀장 계정 없음)",
            ready["quick_login"] is True and ready["accounts_ready"] is False,
            ready,
        )
        c.check(
            "역할은 담당자·파트장·팀장·본부장 넷(체험·모르는 값은 422)",
            _quick(_client(app), "demo").status_code == 422 and _quick(_client(app), "boss").status_code == 422,
        )
        member, lead = _client(app), _client(app)
        joined, led = _quick(member, "member"), _quick(lead, "admin")
        me, boss = joined.json(), led.json()
        c.check(
            "담당자 = quick-member 김설계(기록 권한) · 팀장 = quick-lead 박팀장(승인 권한), 둘 다 비밀번호 정하기 없음",
            joined.status_code == 200
            and (me["login_id"], me["name"], me["role"]) == ("quick-member", "김설계", "member")
            and "record" in me["permissions"]
            and led.status_code == 200
            and (boss["login_id"], boss["name"], boss["role"]) == ("quick-lead", "박팀장", "admin")
            and "approve" in boss["permissions"]
            and not me["must_change_password"]
            and not boss["must_change_password"],
            (me, boss),
        )
        cookie = joined.headers.get("set-cookie", "")
        c.check(
            "쿠키는 로그인과 같음: HttpOnly · Secure · SameSite=Strict · Path=/ · 12시간 · 업무 API 200",
            all(part in cookie for part in ("ripple_session=", "HttpOnly", "Secure", "Path=/", "Max-Age=43200"))
            and "samesite=strict" in cookie.lower()
            and member.get("/api/samples").status_code == 200,
            cookie[:160],
        )
        c.check(
            "고정 팀장 계정은 계정 준비로 세지 않음(accounts_ready 그대로 false — 비밀번호로 들어갈 팀장 없음)",
            main.get("/api/health").json()["auth"]["accounts_ready"] is False,
        )
        evil = _client(app)
        c.check(
            "출처 검사: 다른 사이트에서 보낸 빠른 로그인은 403 bad_origin(세션 없음), 같은 출처는 200",
            _code(_quick(evil, "admin", headers={"Origin": "https://evil.example"})) == "bad_origin"
            and "ripple_session" not in evil.cookies
            and _quick(_client(app), "admin", headers={"Origin": BASE}).status_code == 200,
        )
        _same_account(c, app, member, lead)
        _password(c, app)
        _approval(c, member, lead)
        _line(c, app, member, lead)
        _locked(c, app, lead)
        _last_admin(c, lead)
        _healed(c, app)


def _same_account(c: Checker, app: FastAPI, member: TestClient, lead: TestClient) -> None:
    stored = app.state.auth.accounts.get("quick-member")
    before = member.cookies.get("ripple_session") or ""
    again = _quick(member, "member")
    after = app.state.auth.accounts.get("quick-member")
    rows = [a["login_id"] for a in lead.get("/api/accounts").json()["items"]]
    c.check(
        "두 번째 빠른 로그인도 같은 계정(다시 만들지 않음 — 해시·만든 시각 그대로), 계정 목록에 하나씩, "
        "같은 브라우저의 이전 세션은 정리(401)",
        again.json()["login_id"] == "quick-member"
        and (stored.password_hash, stored.created_at) == (after.password_hash, after.created_at)
        and sorted(rows) == ["quick-lead", "quick-member"]
        and _with(app, before).get("/api/auth/me").status_code == 401,
        rows,
    )


def _password(c: Checker, app: FastAPI) -> None:
    """4. 비밀번호를 아는 상태(예전 초기화·손으로 고친 해시)여도 아이디·비밀번호 로그인은 거절."""
    known = "known-pass-2026-x"
    _tamper(app, "quick-member", password_hash=hash_password(known))
    tried = _login(_client(app), "quick-member", known)
    nobody = _login(_client(app), "nobody-here", known)
    c.check(
        "고정 계정은 맞는 비밀번호로도 아이디·비밀번호 로그인 401 — 없는 아이디와 같은 문구",
        tried.status_code == 401 and _message(tried) == _message(nobody) and _code(tried) == "invalid_credentials",
        tried.json(),
    )


def _approval(c: Checker, member: TestClient, lead: TestClient) -> None:
    request, result, token = _analysis(member)
    ecn = request["change"]["ecn_id"]
    saved = _record(member, request, result["analysis_id"], token, 0)
    review = _action(member, ecn, "request_review", token)
    own = _action(member, ecn, "approve", token, reason="확인함")
    approved = _approve_line(lead, ecn, token, reason="확인함")  # 파트장·본부장 단계는 팀장 전결
    c.check(
        "담당자 계정 기록·검토 요청 → 담당자 승인 403 → 팀장 계정 승인(전결로 결재선 끝까지) 200 — 서로 다른 사람",
        saved.status_code == 200
        and review.status_code == 200
        and own.status_code == 403
        and approved.status_code == 200
        and approved.json()["state"] == "approved",
        (saved.status_code, review.status_code, own.status_code, approved.json()),
    )


def _line(c: Checker, app: FastAPI, member: TestClient, lead: TestClient) -> None:
    """파트장·본부장 단추: 결재선 가상 계정과 같은 아이디(part-lead·executive)로 들어가 자기 단계만 결재한다."""
    part, boss = _client(app), _client(app)
    entered = {"part_lead": _quick(part, "part_lead").json(), "executive": _quick(boss, "executive").json()}
    c.check(
        "파트장 = part-lead 이파트장 · 본부장 = executive 최본부장"
        "(승인 권한, 기록·구성원 관리 없음, 비밀번호 정하기 없음)",
        [(m["login_id"], m["name"], m["role"]) for m in entered.values()]
        == [("part-lead", "이파트장", "part_lead"), ("executive", "최본부장", "executive")]
        and all(
            "approve" in m["permissions"]
            and "record" not in m["permissions"]
            and "manage_accounts" not in m["permissions"]
            and not m["must_change_password"]
            for m in entered.values()
        ),
        entered,
    )
    request, result, token = _analysis(member, 1)
    ecn = request["change"]["ecn_id"]
    _record(member, request, result["analysis_id"], token, 0)
    review = _action(member, ecn, "request_review", token)
    early = _action(boss, ecn, "approve", token, reason="확인함")  # 본부장 차례가 아님
    signed = [_action(who, ecn, "approve", token, reason="확인함") for who in (part, lead, boss)]
    c.check(
        "담당자 검토 요청 → 본부장이 먼저 승인하면 403 → 파트장 → 팀장 → 본부장 빠른 로그인 계정이 차례로 승인 "
        "(전결 없이 결재선 끝, 감사 이름이 각 계정)",
        review.status_code == 200
        and review.json()["review"]["steps"] == ["part_lead", "team_lead", "executive"]
        and early.status_code == 403
        and [r.status_code for r in signed] == [200, 200, 200]
        and [r.json()["review"]["step"] for r in signed[:2]] == [2, 3]
        and signed[2].json()["state"] == "approved",
        (review.status_code, early.status_code, [r.status_code for r in signed]),
    )
    rows = sorted(a["login_id"] for a in lead.get("/api/accounts").json()["items"])
    c.check(
        "구성원 목록에 네 고정 계정이 하나씩",
        rows == ["executive", "part-lead", "quick-lead", "quick-member"],
        rows,
    )


def _locked(c: Checker, app: FastAPI, lead: TestClient) -> None:
    """1. 팀장 단추로 들어온 방문자·그가 만든 다른 팀장 모두 고정 계정을 못 바꾼다(다음 방문자의 단추가 그대로)."""
    made = lead.post("/api/accounts", json={"login_id": "visitor", "name": "방문 팀장", "role": "admin"}).json()
    other = _client(app)
    _login(other, "visitor", made["temporary_password"])
    other.post("/api/auth/password", json={"current_password": made["temporary_password"], "new_password": ADMIN_PW})
    tries = {
        "자기 줄 이름·역할": lead.patch("/api/accounts/quick-lead", json={"name": "ㅋㅋ", "role": "member"}),
        "담당자 끄기": lead.patch("/api/accounts/quick-member", json={"disabled": True}),
        "담당자 초기화": lead.post("/api/accounts/quick-member/reset-password"),
        "다른 팀장이 팀장 끄기": other.patch("/api/accounts/quick-lead", json={"disabled": True}),
        "다른 팀장이 팀장 초기화": other.post("/api/accounts/quick-lead/reset-password"),
        "다른 팀장이 담당자 역할": other.patch("/api/accounts/quick-member", json={"role": "admin"}),
        "파트장 끄기": lead.patch("/api/accounts/part-lead", json={"disabled": True}),
        "본부장 초기화": other.post("/api/accounts/executive/reset-password"),
        "본부장 지우기": other.delete("/api/accounts/executive"),
    }
    c.check(
        f"구성원 관리로 고정 계정을 바꾸면 모두 403 forbidden '{LOCKED}'",
        all(r.status_code == 403 and _message(r) == LOCKED for r in tries.values()),
        {k: (r.status_code, _message(r)) for k, r in tries.items()},
    )
    own = other.patch("/api/accounts/visitor", json={"role": "member"})
    c.check(
        "내 줄 변경도 서버에서 403(화면과 같은 규칙) — 고정 계정이 아닌 팀장도",
        own.status_code == 403 and _code(own) == "forbidden" and other.get("/api/auth/me").json()["role"] == "admin",
        own.json(),
    )
    nxt, nxt_member = _quick(_client(app), "admin"), _quick(_client(app), "member")
    c.check(
        "다음 방문자의 '팀장으로'·'담당자로'는 그대로 박팀장(팀장)·김설계(담당자)",
        (nxt.json()["name"], nxt.json()["role"]) == ("박팀장", "admin")
        and (nxt_member.json()["name"], nxt_member.json()["role"]) == ("김설계", "member"),
        (nxt.json(), nxt_member.json()),
    )


def _last_admin(c: Checker, lead: TestClient) -> None:
    """마지막 팀장 보호(점검 E-5): 빠른 로그인 고정 팀장은 세지 않는다 — 유일한 실제 팀장(visitor, _locked가 만듦)을
    고정 팀장으로 멈추거나 지우면 409. 실제 팀장이 아닌 계정을 바꾸는 일은 그대로 된다."""
    tries = {
        "멈추기": lead.patch("/api/accounts/visitor", json={"disabled": True}),
        "담당자로": lead.patch("/api/accounts/visitor", json={"role": "member"}),
        "지우기": lead.delete("/api/accounts/visitor"),
    }
    made = lead.post("/api/accounts", json={"login_id": "helper", "name": "도우미", "role": "member"})
    renamed = lead.patch("/api/accounts/helper", json={"name": "도우미 2"})
    c.check(
        "고정 팀장(quick-lead)으로 유일한 실제 팀장을 멈추기·역할 바꾸기·지우기 → 409 last_admin"
        "(고정 팀장은 세지 않음), 실제 팀장이 아닌 계정 바꾸기는 200",
        all(r.status_code == 409 and _code(r) == "last_admin" for r in tries.values())
        and made.status_code == 201
        and renamed.status_code == 200,
        {k: (r.status_code, _code(r)) for k, r in tries.items()},
    )


def _healed(c: Checker, app: FastAPI) -> None:
    """1. 계정 파일을 손으로 고쳐도(이름·역할·끄기·비밀번호 바꾸기 전) 빠른 로그인 때 상수로 되돌린다."""
    _tamper(app, "quick-lead", name="망가짐", role=Role.MEMBER, disabled=True, must_change_password=True)
    back = _quick(_client(app), "admin")
    stored = app.state.auth.accounts.get("quick-lead")
    c.check(
        "손으로 고친 고정 팀장 계정: 빠른 로그인 200 · 박팀장 · 팀장 · 사용 중 · 비밀번호 정하기 없음으로 복구",
        back.status_code == 200
        and (back.json()["name"], back.json()["role"], back.json()["must_change_password"])
        == ("박팀장", "admin", False)
        and (stored.name, stored.role.value, stored.disabled) == ("박팀장", "admin", False),
        back.json(),
    )


def _race(c: Checker, root: Path) -> None:
    c.section("빠른 로그인: 처음 누르는 사람이 동시에 여럿")
    app = _app(root, "data-quick-race", extra=QUICK_ON, environ={})
    with _client(app):
        results: list[tuple[int, str]] = []

        def press() -> None:
            response = _quick(_client(app), "admin")
            results.append((response.status_code, response.json().get("login_id", "")))

        threads = [threading.Thread(target=press) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        accounts = [a.login_id for a in app.state.auth.accounts.all()]
        c.check(
            "동시에 눌러도 모두 200 · 같은 팀장 계정 · 계정은 하나",
            results == [(200, "quick-lead")] * 3 and accounts == ["quick-lead"],
            (results, accounts),
        )


def _limit(c: Checker, root: Path) -> None:
    """2. 쿠키 없이 빠른 로그인을 반복해도 그 고정 계정 세션만 최근 상한개 — 다른 사람의 세션은 그대로."""
    c.section("빠른 로그인: 고정 계정마다 세션 상한")
    app = _app(root, "data-quick-limit", extra=QUICK_ON)  # 첫 관리자(lead)도 있는 폴더
    with _client(app):
        lead, member = _client(app), _client(app)
        _login(lead, "lead", FIRST)
        _quick(member, "member")
        first = _client(app)
        _quick(first, "admin")
        oldest = first.cookies.get("ripple_session") or ""
        spam = _client(app)
        for _ in range(QUICK_SESSION_LIMIT + 5):
            spam.cookies.clear()  # 쿠키 없이(이전 세션 정리 없이) 반복
            _quick(spam, "admin")
        sessions = app.state.auth.sessions
        c.check(
            f"팀장 단추를 {QUICK_SESSION_LIMIT + 6}번 눌러도 quick-lead 세션은 최근 {QUICK_SESSION_LIMIT}개, "
            "가장 오래된 것부터 무효 · 첫 관리자·담당자 세션은 그대로",
            sessions.count_for("quick-lead") == QUICK_SESSION_LIMIT
            and _with(app, oldest).get("/api/auth/me").status_code == 401
            and lead.get("/api/auth/me").status_code == 200
            and member.get("/api/auth/me").status_code == 200
            and spam.get("/api/auth/me").status_code == 200,
            sessions.count_for("quick-lead"),
        )


def _evict_own_first(c: Checker, root: Path) -> None:
    """2. 전역 상한(MAX_SESSIONS)을 넘으면 상한 있는 세션(빠른 로그인)은 자기 계정의 오래된 것부터 지운다."""
    folder = root / "data-quick-evict"
    store = SessionStore(folder)
    store.load(datetime.now(UTC))
    start = datetime.now(UTC)

    def make(login_id: str, minute: int, keep: int | None = None) -> str:
        now = start + timedelta(minutes=minute)
        return store.create(login_id, demo=False, now=now, expires_at=now + timedelta(hours=12), keep_latest=keep)

    with mock.patch("ripple.store.accounts.MAX_SESSIONS", 5):
        people = [
            make("kim", minute) for minute in range(3)
        ]  # 가장 오래된 세션은 다른 계정(전체 오래된 순이면 지워질 것)
        quick_old = [make("quick-lead", 10 + minute, QUICK_SESSION_LIMIT) for minute in range(2)]
        newest = make("quick-lead", 20, QUICK_SESSION_LIMIT)  # 6개째: 상한 5를 넘김
        later = make("quick-lead", 21, QUICK_SESSION_LIMIT)
        kim_more = make("kim", 22)  # 상한 없는 세션은 전과 같이 전체에서 오래된 순
        now = start + timedelta(minutes=30)
        c.check(
            "전역 상한을 넘겨도 빠른 로그인 세션은 자기 계정의 오래된 것부터 지움(다른 계정 세션은 그대로), "
            "상한 없는 세션은 전과 같이 전체에서 오래된 순",
            all(store.resolve(token, now) is not None for token in people[1:])
            and all(store.resolve(token, now) is None for token in quick_old)
            and store.resolve(newest, now) is not None
            and store.resolve(later, now) is not None
            and store.resolve(kim_more, now) is not None
            and store.resolve(people[0], now) is None,
            (store.count_for("kim"), store.count_for("quick-lead")),
        )


def _restart(c: Checker, root: Path) -> None:
    """3·5. 시연 뒤 같은 폴더를 빠른 로그인 없이 다시 켤 때."""
    c.section("빠른 로그인: 끈 뒤 다시 켜기 — 세션 무효 · 첫 관리자")
    first = _app(root, "data-quick-restart", extra=QUICK_ON, environ={})
    with _client(first) as client:
        _quick(client, "admin")
        token = client.cookies.get("ripple_session") or ""
        c.check(
            "켜진 동안 고정 팀장 세션은 구성원 목록 200", _with(first, token).get("/api/accounts").status_code == 200
        )
    off = _app(root, "data-quick-restart", environ=ADMIN_ENV)  # 빠른 로그인 끔 + 첫 관리자 변수
    with _client(off) as client:
        holder = _with(off, token)
        c.check(
            "끈 뒤에는 남은 고정 계정 세션이 무효(내 정보·구성원 목록 401)",
            holder.get("/api/auth/me").status_code == 401 and holder.get("/api/accounts").status_code == 401,
        )
        health = client.get("/api/health").json()["auth"]
        signed = _login(_client(off), "lead", FIRST)
        c.check(
            "고정 계정만 있는 폴더면 첫 관리자 변수로 팀장을 만들고 accounts_ready=true, 그 아이디로 로그인 200",
            health["accounts_ready"] is True and health["quick_login"] is False and signed.status_code == 200,
            (health, signed.status_code),
        )
