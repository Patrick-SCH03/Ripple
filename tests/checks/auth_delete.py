"""구성원 계정 지우기의 성질(DELETE /api/accounts/{id}, docs/operations.md(서비스) 2절). 묶음 auth_api가 만든 합성
지도 폴더로 부른다(권한 행렬 — 관리자만 — 은 auth_api의 MATRIX).

- 지우면 목록에서 빠지고 그 계정의 세션이 모두 끊기며, 맞는 비밀번호로도 없는 아이디와 같은 401.
- 거절: 내 계정 403 · 빠른 로그인 고정 계정 403(잠금과 같은 문구) · 사용 중인 팀장이 0명이 되면 409 · 없는 계정 404.
- 기록·결재·감사 줄에 남은 그 사람의 아이디·이름은 그대로(기록은 고칠 수 없는 사슬), 사슬 검증도 그대로.
- 지운 아이디는 다시 쓰지 않는다(구성원 추가 409 · 다시 켜도 · 첫 관리자 변수도).
- 계정 파일은 지운 계정이 없으면 판 3 그대로(옛 코드도 읽음), 하나라도 지우면 판 4(지운 아이디 목록).
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from harness import Checker

from checks.records import ADMIN_PW, FIRST, _action, _analysis, _app, _approve_line, _client, _login, _record
from ripple.auth import DEV_PRINCIPAL, AuthError
from ripple.contracts.auth import Role
from ripple.store.accounts import AccountStore, RetiredIdError, StoredAccount, account_file_text

LOCKED = "시연용 고정 계정 변경 불가"
GONE_PW = "gone-pass-2026-x"
STAY_PW = "stay-pass-2026-x"


def run(c: Checker, root: Path) -> None:
    _store(c)
    _api(c, root)
    _restart(c, root)


def _detail(response: Any) -> dict[str, Any]:
    detail = response.json().get("detail")
    return detail if isinstance(detail, dict) else {}


def _staff(app: FastAPI, lead: TestClient, login_id: str, name: str, role: str, password: str) -> TestClient:
    """팀장(lead)이 만든 구성원으로 로그인하고 비밀번호를 정한 손님."""
    client = _client(app)
    temporary = lead.post("/api/accounts", json={"login_id": login_id, "name": name, "role": role}).json()
    _login(client, login_id, temporary["temporary_password"])
    client.post(
        "/api/auth/password", json={"current_password": temporary["temporary_password"], "new_password": password}
    )
    return client


def _account(login_id: str, role: Role = Role.MEMBER) -> StoredAccount:
    return StoredAccount(
        login_id=login_id, name=login_id, role=role, password_hash="x", created_at=datetime(2026, 10, 1, tzinfo=UTC)
    )


def _store(c: Checker) -> None:
    c.section("구성원 지우기: 계정 파일(지운 아이디 목록 · 형식 판)")
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        store = AccountStore(root)
        store.load()
        store.change(lambda stored: stored.update({"lead": _account("lead", Role.ADMIN), "kim": _account("kim")}))
        plain = json.loads(store.path.read_text(encoding="utf-8"))
        c.check(
            "지운 계정이 없으면 판 3 그대로이고 지운 아이디 칸이 없음(옛 코드로 되돌려도 읽힘)",
            plain["version"] == 3
            and "retired_ids" not in plain
            and store.path.read_text(encoding="utf-8")
            == account_file_text([_account("lead", Role.ADMIN), _account("kim")], ()),
            plain,
        )
        refused = store.path.read_bytes()
        checked: list[list[str]] = []

        def refuse(_removed: Any, remaining: Any) -> None:
            checked.append(sorted(remaining))
            raise AuthError(409, "last_admin", "사용 중인 팀장이 한 명은 있어야 해요")

        c.check(
            "check가 거절하면 아무것도 쓰지 않음(계정·파일 그대로), check는 지운 뒤의 계정을 봄",
            c.raises(lambda: store.delete("kim", refuse), AuthError)
            and checked == [["lead"]]
            and store.get("kim") is not None
            and store.path.read_bytes() == refused,
        )
        missing = store.delete("nobody", lambda *_: None)
        removed = store.delete("kim", lambda *_: None)
        written = json.loads(store.path.read_text(encoding="utf-8"))
        c.check(
            "지우면 판 4 · 지운 아이디 목록 · 계정에서 빠짐, 없는 아이디를 지우면 None",
            missing is None
            and removed is not None
            and removed.login_id == "kim"
            and store.get("kim") is None
            and store.is_retired("kim")
            and not store.is_retired("lead")
            and written["version"] == 4
            and written["retired_ids"] == ["kim"]
            and [a["login_id"] for a in written["accounts"]] == ["lead"],
            written,
        )
        before = store.path.read_bytes()
        c.check(
            "지운 아이디로 계정을 새로 넣으면 RetiredIdError(아무것도 쓰지 않음), 다른 아이디는 됨",
            c.raises(lambda: store.change(lambda stored: stored.update({"kim": _account("kim")})), RetiredIdError)
            and store.path.read_bytes() == before
            and store.get("kim") is None,
        )
        store.change(lambda stored: stored.update({"lee": _account("lee")}))
        again = AccountStore(root)
        again.load()
        c.check(
            "다시 읽어도 지운 아이디는 그대로, 판 4 파일을 고쳐 써도 지운 아이디 목록이 남음",
            again.is_retired("kim")
            and again.get("lee") is not None
            and json.loads(store.path.read_text(encoding="utf-8"))["retired_ids"] == ["kim"],
        )


def _api(c: Checker, root: Path) -> None:
    c.section("구성원 지우기: 관리자만 · 세션 끊김 · 로그인 불가 · 거절 세 가지 · 기록 이름 유지")
    app = _app(root, "data-delete")
    with _client(app) as lead:
        _login(lead, "lead", FIRST)
        lead.post("/api/auth/password", json={"current_password": FIRST, "new_password": ADMIN_PW})
        gone = _staff(app, lead, "gone", "이지움", "member", GONE_PW)
        also = _client(app)
        _login(also, "gone", GONE_PW)  # 같은 사람의 두 번째 세션
        stay = _staff(app, lead, "stay", "남음", "member", STAY_PW)
        request, result, token = _analysis(gone)
        ecn = request["change"]["ecn_id"]
        _record(gone, request, result["analysis_id"], token, 0)
        _action(gone, ecn, "request_review", token)
        before = lead.get(f"/api/ecns/{ecn}").json()

        by_member = stay.delete("/api/accounts/gone")
        by_anon = _client(app).delete("/api/accounts/gone")
        deleted = lead.delete("/api/accounts/gone")
        listed = [a["login_id"] for a in lead.get("/api/accounts").json()["items"]]
        c.check(
            "담당자 403 · 로그인 전 401 → 팀장은 204(본문 없음), 목록에서 빠지고 다른 구성원은 그대로",
            by_member.status_code == 403
            and _detail(by_member).get("code") == "forbidden"
            and by_anon.status_code == 401
            and deleted.status_code == 204
            and deleted.content == b""
            and "gone" not in listed
            and {"lead", "stay"} <= set(listed),
            (by_member.status_code, by_anon.status_code, deleted.status_code, listed),
        )
        sessions = app.state.auth.sessions
        c.check(
            "지운 계정의 세션은 모두 끊김(두 세션 다 401, 세션 파일에도 없음), 다른 사람의 세션은 그대로",
            gone.get("/api/auth/me").status_code == 401
            and also.get("/api/auth/me").status_code == 401
            and sessions.count_for("gone") == 0
            and stay.get("/api/auth/me").status_code == 200
            and lead.get("/api/auth/me").status_code == 200,
        )
        tried = _login(_client(app), "gone", GONE_PW)
        nobody = _login(_client(app), "nobody-here", GONE_PW)
        c.check(
            "지운 계정은 맞는 비밀번호로도 로그인 401 — 없는 아이디와 같은 문구",
            tried.status_code == 401 and _detail(tried) == _detail(nobody),
            tried.json(),
        )
        _names_kept(c, lead, ecn, token, before)
        _refusals(c, app, lead)
        reused = lead.post("/api/accounts", json={"login_id": "gone", "name": "새 사람"})
        c.check(
            "지운 아이디로 구성원 추가 409 account_exists '지운 계정의 아이디 재사용 불가…'",
            reused.status_code == 409
            and _detail(reused).get("code") == "account_exists"
            and "지운 계정의 아이디" in _detail(reused).get("message", ""),
            reused.json(),
        )
        written = json.loads((root / "data-delete" / "accounts.json").read_text(encoding="utf-8"))
        c.check(
            "계정 파일은 판 4 · 지운 아이디 목록에 gone",
            written["version"] == 4 and "gone" in written["retired_ids"],
            written.get("retired_ids"),
        )


def _names_kept(c: Checker, lead: TestClient, ecn: str, token: str, before: dict[str, Any]) -> None:
    """기록·결재·감사 줄의 사람(아이디·이름)은 지운 뒤에도 그대로, 지운 사람이 올린 검토도 팀장이 결정할 수 있다."""
    after = lead.get(f"/api/ecns/{ecn}").json()
    people = [(entry["actor"]["login_id"], entry["actor"]["name"]) for entry in after["audit"]]
    c.check(
        "지운 뒤에도 상세(개정의 기록한 사람·검토 요청자·감사 줄의 사람 gone 이지움)가 그대로, 기록 본문도 읽힘",
        after == before
        and after["revisions"][0]["recorded_by"]["name"] == "이지움"
        and after["status"]["review"]["requested_by"]["name"] == "이지움"
        and ("gone", "이지움") in people
        and lead.get(f"/api/records/{after['status']['record_id']}").status_code == 200,
        people,
    )
    approved = _approve_line(lead, ecn, token, reason="확인함")  # 결재선 끝까지(팀장 전결)
    verify = lead.get("/api/audit/verify").json()
    c.check(
        "지운 사람이 올린 검토도 팀장이 승인 200, 감사 사슬 검증 ok(지우기는 기록을 건드리지 않음)",
        approved.status_code == 200 and approved.json()["state"] == "approved" and verify["ok"] is True,
        (approved.status_code, verify),
    )


def _refusals(c: Checker, app: FastAPI, lead: TestClient) -> None:
    own = lead.delete("/api/accounts/lead")
    fixed = [lead.delete(f"/api/accounts/{key}") for key in ("quick-lead", "quick-member")]
    missing = lead.delete("/api/accounts/nobody-here")
    c.check(
        "내 계정 403 '내 계정 삭제 불가' · 고정 계정 403(잠금과 같은 문구) · 없는 계정 404",
        own.status_code == 403
        and (_detail(own).get("code"), _detail(own).get("message")) == ("forbidden", "내 계정 삭제 불가")
        and all(r.status_code == 403 and _detail(r).get("message") == LOCKED for r in fixed)
        and missing.status_code == 404,
        (own.json(), [r.json() for r in fixed], missing.status_code),
    )
    last: list[tuple[int, str]] = []
    try:  # 내 계정을 못 지우니 API로는 닿지 않는 규칙 — 개발 모드 관리자가 마지막 팀장을 지우는 경우로 본다
        app.state.auth.delete_account(DEV_PRINCIPAL, "lead")
    except AuthError as error:
        last.append((error.status, error.code))
    c.check(
        "사용 중인 팀장이 0명이 되면 409 last_admin(계정·세션 그대로)",
        last == [(409, "last_admin")]
        and app.state.auth.accounts.get("lead") is not None
        and lead.get("/api/auth/me").status_code == 200,
        last,
    )
    boss = lead.post("/api/accounts", json={"login_id": "boss", "name": "다른 팀장", "role": "admin"})
    c.check(
        "다른 팀장은 지울 수 있음(사용 중인 팀장이 남음)",
        boss.status_code == 201 and lead.delete("/api/accounts/boss").status_code == 204,
    )


def _restart(c: Checker, root: Path) -> None:
    c.section("구성원 지우기: 다시 켜기 · 첫 관리자 변수")
    app = _app(root, "data-delete")  # 같은 폴더(지운 아이디가 있는 판 4 파일)
    with _client(app) as client:
        signed = _login(client, "lead", ADMIN_PW)
        c.check(
            "다시 켜도 판 4 파일을 읽고, 지운 계정은 로그인 401 · 그 아이디로 추가 409",
            signed.status_code == 200
            and _login(_client(app), "gone", GONE_PW).status_code == 401
            and client.post("/api/accounts", json={"login_id": "gone", "name": "다시"}).status_code == 409,
        )
    folder = root / "data-delete-first"
    folder.mkdir()
    (folder / "accounts.json").write_text(
        json.dumps({"version": 4, "accounts": [], "retired_ids": ["lead"]}), encoding="utf-8"
    )
    fresh = _app(root, "data-delete-first")  # 첫 관리자 변수 lead = 지운 아이디
    with _client(fresh) as client:
        health = client.get("/api/health").json()["auth"]
        c.check(
            "첫 관리자 변수가 지운 아이디면 만들지 않음(accounts_ready=false, 로그인 401)",
            health["accounts_ready"] is False
            and fresh.state.auth.accounts.get("lead") is None
            and _login(_client(fresh), "lead", FIRST).status_code == 401,
            health,
        )
