"""로그인·역할 권한의 API 성질(docs/operations.md(서비스) 2절). 순수 부품은 tests/checks/auth.py.

- 권한 행렬: 앱의 모든 /api 경로(OpenAPI) × 세션 없음·체험·담당자·비밀번호 바꾸기 전 관리자·관리자. 표에 없는 새 경로가
  생기면 실패하고, 금지된 요청 뒤에 계정·지도·활성 지도·가져오기 대기가 그대로인지 본다.
- 쿠키 속성, 출처(Origin) 검사, 비밀번호 바꾸기·초기화·끄기의 세션 폐기, 다시 켠 뒤 세션 유지.
- 체험은 실데이터를 어떤 경로로도 못 본다(목록·내려받기·업무 경로·체험 로그인), 검사한 세대로 처리한다.
- 빠른 로그인(1.30.0)은 같은 합성 지도 폴더로 tests/checks/auth_quick.py.
"""

from __future__ import annotations

import json
import logging
import tempfile
import threading
import warnings
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, HTTPException
from harness import Checker

from checks import auth_delete, auth_quick
from ripple.api.app import create_app
from ripple.api.security import origin_allowed
from ripple.api.workspace import Workspaces, get_workspace, info_of
from ripple.auth import DEV_PRINCIPAL, AuthError, Principal
from ripple.config.settings import Settings
from ripple.contracts.auth import AccountUpdate, Role
from ripple.contracts.domain import DataMode, GraphSnapshot
from ripple.contracts.identity import snapshot_id
from ripple.generator.build import generate
from ripple.generator.io import load_config, write_outputs
from ripple.store.accounts import AccountStoreError
from ripple.store.snapshots import SnapshotStore

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

BASE = "https://testserver"  # Secure 쿠키가 오가게 https로
FIRST = "first-pass-2026"  # 검사용 첫 관리자 비밀번호(배포 값 아님)
ADMIN_PW = "lead-pass-2026-x"
MEMBER_PW = "kim-pass-2026-x"
ADMIN_ENV = {"RIPPLE_ADMIN_ID": "lead", "RIPPLE_ADMIN_PASSWORD": FIRST}
ROLES = ("anon", "demo", "member", "admin_mc", "admin", "part_lead", "executive")
OPEN = "open"  # 누구나(로그인 전 포함): 401·403이 아니다
SESSION = "session"  # 세션을 바꾸는 경로: 행렬 대신 아래 전용 검사로 본다
VIEW = frozenset({"demo", "member", "admin", "part_lead", "executive"})
RECORD = frozenset({"member"})  # 관리자는 결재자 — 기록·검토 요청·상태 갱신은 담당자
ACT = frozenset({"member", "admin", "part_lead", "executive"})  # 결재 행동 입구: 담당자(요청·실행) 또는 결재자(결정)
ADMIN = frozenset({"admin"})  # 팀장만: 구성원 관리·지도 전환·가져오기·AI 호출 기록
# 결재자(승인 권한): 팀장 + 결재선의 파트장·본부장(docs/records.md(기록·결재) 14절) — 결재·현황·감사 확인·결정 도우미 등
APPROVER = frozenset({"admin", "part_lead", "executive"})
ME = frozenset({"demo", "member", "admin_mc", "admin", "part_lead", "executive"})
MATRIX: dict[tuple[str, str], str | frozenset[str]] = {
    ("GET", "/api/health"): OPEN,
    ("POST", "/api/auth/login"): SESSION,
    ("POST", "/api/auth/demo"): SESSION,
    ("POST", "/api/auth/quick"): SESSION,  # 1.30.0 빠른 로그인(auth_quick.py)
    ("POST", "/api/auth/logout"): SESSION,
    ("POST", "/api/auth/password"): SESSION,
    ("GET", "/api/auth/me"): ME,
    ("GET", "/api/accounts"): ADMIN,
    ("POST", "/api/accounts"): ADMIN,
    ("POST", "/api/accounts/{login_id}/reset-password"): ADMIN,
    ("PATCH", "/api/accounts/{login_id}"): ADMIN,
    ("DELETE", "/api/accounts/{login_id}"): ADMIN,  # 구성원 지우기(auth_delete.py)
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
    ("POST", "/api/analyses/export"): VIEW,  # 분석 결과 엑셀: 내려받기 권한(체험은 합성 작업 공간만)
    ("POST", "/api/analyses/notices"): VIEW,  # 1.37.0 상세 통보문 보기(분석과 같은 권한, 외부 AI 없음)
    ("POST", "/api/assistant/turns"): VIEW,
    ("GET", "/api/assistant/conversations/{conversation_id}"): VIEW,
    ("POST", "/api/records"): RECORD,
    ("GET", "/api/ecns"): VIEW,
    ("GET", "/api/ecns/{ecn_id}"): VIEW,
    ("GET", "/api/ecns/{ecn_id}/brief"): APPROVER,  # 1.31.0 결정 도우미: 결재하는 사람만(외부 AI를 부를 수 있음)
    ("GET", "/api/ncrs/summary"): APPROVER,  # 1.32.0 합성 NCR 요약: 비슷한 과거 사례와 같은 권한(결재자)
    ("GET", "/api/records/{record_id}"): VIEW,
    ("POST", "/api/ecns/{ecn_id}/actions"): ACT,
    ("POST", "/api/ecns/{ecn_id}/notices"): RECORD,  # 1.28.0 통보 기록은 담당자(기록과 같은 권한)
    ("GET", "/api/audit/verify"): APPROVER,
    ("GET", "/api/manage/overview"): APPROVER,
    ("GET", "/api/manage/export"): APPROVER,  # 결재 대장 엑셀(결재·현황과 같은 권한)
    ("GET", "/api/ecns/{ecn_id}/outcome"): VIEW,
    ("PUT", "/api/ecns/{ecn_id}/outcome"): RECORD,
    ("GET", "/api/llm/calls"): ADMIN,
    ("POST", "/api/updates/preview"): RECORD,  # 상태 갱신은 담당자도
    ("POST", "/api/updates"): RECORD,
    ("GET", "/api/updates"): APPROVER,
    ("DELETE", "/api/imports/mappings"): ADMIN,
    ("POST", "/api/status-imports"): RECORD,
    ("POST", "/api/status-imports/{import_id}/proposal"): RECORD,
    ("POST", "/api/status-imports/{import_id}/mapping"): RECORD,
    ("POST", "/api/status-imports/{import_id}/confirm"): RECORD,
    ("POST", "/api/intake/proposals"): VIEW,  # 1.27.0 문서 접수(비서·분석과 같은 보기 권한)
    ("POST", "/api/intake/proposals/xlsx"): VIEW,
    ("POST", "/api/intake/confirmations"): VIEW,
    ("GET", "/api/corrections/summary"): APPROVER,  # 수정 기록 요약은 결재·현황과 같은 승인 권한(결재자)
}
FILL = {
    "{login_id}": "nobody",
    "{snapshot_id}": "G-0000000000000000",
    "{import_id}": "I-none",
    "{conversation_id}": "C-none",
    "{ecn_id}": "ECN-NONE",
    "{record_id}": "R-0000000000000000",
}


def run(c: Checker) -> None:
    _origin(c)
    generated = generate(load_config())
    logger = logging.getLogger("ripple.auth")
    notes = _Notes()
    logger.addHandler(notes)
    logger.propagate = False  # 검사 출력에 경고가 섞이지 않게(내용은 notes로 확인)
    try:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_outputs(generated, root / "synthetic")
            _matrix(c, root)
            _flows(c, root)
            _demo_real(c, root, generated.snapshot)
            _restart(c, root)
            _bootstrap(c, root, notes)
            _dev_mode(c, root, notes)
            auth_quick.run(c, root)
            auth_delete.run(c, root)
    finally:
        logger.removeHandler(notes)
        logger.propagate = True
    _pinned(c)


class _Notes(logging.Handler):
    """ripple.auth 경고를 모아 둔다."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


# ---------- 순수 부품 ----------


def _origin(c: Checker) -> None:
    c.section("로그인: 출처(Origin) 검사")
    c.check(
        "같은 출처·기본 포트 허용, 다른 출처·'null'·이상한 스킴 거절, 읽기·Origin 없음은 허용",
        origin_allowed("POST", "https://ripple.up.railway.app", "ripple.up.railway.app")
        and origin_allowed("POST", "https://ripple.up.railway.app:443", "ripple.up.railway.app")
        and origin_allowed("POST", "http://localhost:5173", "localhost:5173")
        and not origin_allowed("POST", "https://evil.example", "ripple.up.railway.app")
        and not origin_allowed("POST", "http://localhost:5174", "localhost:5173")
        and not origin_allowed("PATCH", "null", "localhost:5173")
        and not origin_allowed("DELETE", "file://x", "localhost:5173")
        and origin_allowed("GET", "https://evil.example", "ripple.up.railway.app")
        and origin_allowed("POST", None, "ripple.up.railway.app"),
    )


# ---------- 앱 ----------


def _settings_for(root: Path, data: str, *, demo: bool = True, extra: dict[str, str] | None = None) -> Settings:
    env = {"RIPPLE_DEMO_LOGIN": "on" if demo else "off", **(extra or {})}
    return replace(Settings.from_env(env), snapshot_path=root / "synthetic" / "snapshot.json", data_dir=root / data)


def _app(root: Path, data: str, **kwargs: Any) -> FastAPI:
    environ = kwargs.pop("environ", ADMIN_ENV)
    return create_app(_settings_for(root, data, **kwargs), environ=environ)


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, base_url=BASE)


def _with(app: FastAPI, token: str) -> TestClient:
    """그 세션 토큰을 쿠키 머리글로 싣는 클라이언트(쿠키 저장소의 도메인 규칙과 무관하게)."""
    return TestClient(app, base_url=BASE, headers={"Cookie": f"ripple_session={token}"})


def _login(client: TestClient, login_id: str, password: str) -> Any:
    return client.post("/api/auth/login", json={"login_id": login_id, "password": password})


def _change(client: TestClient, current: str, new: str) -> Any:
    return client.post("/api/auth/password", json={"current_password": current, "new_password": new})


def _people(app: FastAPI) -> dict[str, TestClient]:
    """역할마다 로그인한 클라이언트: 관리자(비밀번호 바꿈) · 담당자 · 비밀번호 바꾸기 전 관리자 · 체험 · 세션 없음."""
    people = {name: _client(app) for name in ROLES}
    _login(people["admin"], "lead", FIRST)
    _change(people["admin"], FIRST, ADMIN_PW)
    member = people["admin"].post("/api/accounts", json={"login_id": "kim", "name": "김담당", "role": "member"})
    temporary = member.json()["temporary_password"]
    _login(people["member"], "kim", temporary)
    _change(people["member"], temporary, MEMBER_PW)
    second = people["admin"].post("/api/accounts", json={"login_id": "park", "name": "박관리", "role": "admin"})
    _login(people["admin_mc"], "park", second.json()["temporary_password"])
    for login_id, role in (("part", "part_lead"), ("boss", "executive")):  # 결재선의 파트장·본부장
        made = people["admin"].post("/api/accounts", json={"login_id": login_id, "name": login_id, "role": role})
        temporary = made.json()["temporary_password"]
        _login(people[role], login_id, temporary)
        _change(people[role], temporary, f"{login_id}-pass-2026-x")
    people["demo"].post("/api/auth/demo")
    return people


def _routes(app: FastAPI) -> set[tuple[str, str]]:
    paths = app.openapi()["paths"]
    return {(method.upper(), path) for path, ops in paths.items() for method in ops}


def _state(app: FastAPI, admin: TestClient) -> tuple[Any, ...]:
    holder = app.state.workspaces
    return (
        admin.get("/api/accounts").json(),
        admin.get("/api/snapshots").json(),
        len(holder._imports._pending),
    )


def _matrix(c: Checker, root: Path) -> None:
    c.section("로그인: 권한 행렬(모든 /api 경로 × 역할)")
    app = _app(root, "data-matrix")
    with _client(app) as main:
        people = _people(app)
        routes = _routes(app)
        c.check(
            "표에 없는 경로·없어진 경로가 없음(새 경로는 권한을 정해 표에 더하기)",
            routes == set(MATRIX),
            sorted(routes ^ set(MATRIX)),
        )
        before = _state(app, people["admin"])
        wrong: list[str] = []
        for (method, path), allowed in sorted(MATRIX.items()):
            if allowed == SESSION:
                continue
            url = path
            for key, value in FILL.items():
                url = url.replace(key, value)
            for role in ROLES:
                response = people[role].request(method, url, json={} if method in ("POST", "PATCH", "PUT") else None)
                code = (response.json().get("detail") or {}).get("code") if response.status_code in (401, 403) else None
                if allowed == OPEN or (isinstance(allowed, frozenset) and role in allowed):
                    ok = response.status_code not in (401, 403)
                elif role == "anon":
                    ok = response.status_code == 401 and code == "unauthenticated"
                elif role == "admin_mc":
                    ok = response.status_code == 403 and code == "password_change_required"
                else:
                    ok = response.status_code == 403 and code == "forbidden"
                if not ok:
                    wrong.append(f"{role} {method} {url} → {response.status_code} {code}")
        c.check("역할마다 허용·401·403(이유 코드까지)이 표대로", not wrong, wrong[:6])
        c.check(
            "금지된 요청 뒤 계정·지도 목록·활성 지도·가져오기 대기가 그대로", _state(app, people["admin"]) == before
        )
        main.get("/api/health")


def _flows(c: Checker, root: Path) -> None:
    c.section("로그인: 쿠키·출처·비밀번호·세션 폐기")
    app = _app(root, "data-flows")
    with _client(app) as main:
        first = _login(main, "lead", FIRST)
        cookie = first.headers.get("set-cookie", "")
        c.check(
            "로그인 쿠키: HttpOnly · Secure · SameSite=Strict · Path=/ · 12시간",
            first.status_code == 200
            and all(part in cookie for part in ("ripple_session=", "HttpOnly", "Secure", "Path=/", "Max-Age=43200"))
            and "samesite=strict" in cookie.lower(),
            cookie[:160],
        )
        c.check("첫 관리자는 비밀번호를 바꾸기 전", first.json()["must_change_password"] is True)
        c.check(
            "바꾸기 전 업무 API는 403(password_change_required), 내 정보는 200",
            main.get("/api/samples").status_code == 403 and main.get("/api/auth/me").status_code == 200,
        )
        wrong_current = _change(main, "not-the-pass-1", ADMIN_PW)
        c.check(
            "지금 비밀번호가 틀리면 401이 아니라 422(화면이 로그인 끝남으로 보지 않게)",
            wrong_current.status_code == 422 and wrong_current.json()["detail"]["code"] == "invalid_credentials",
        )
        weak = _change(main, FIRST, "lead")
        c.check(
            "규칙 위반은 422 weak_password",
            weak.status_code == 422 and weak.json()["detail"]["code"] == "weak_password",
        )
        old_token = main.cookies.get("ripple_session")
        changed = _change(main, FIRST, ADMIN_PW)
        c.check(
            "비밀번호 바꾸면 200 · 새 세션 · 업무 API 200",
            changed.status_code == 200
            and main.cookies.get("ripple_session") != old_token
            and main.get("/api/samples").status_code == 200,
        )
        fresh = main.cookies.get("ripple_session") or ""
        c.check(
            "바꾸기 전 세션은 폐기(401), 새 세션은 그대로(200) — 같은 방식으로 쿠키를 실어 비교",
            _with(app, old_token or "").get("/api/auth/me").status_code == 401
            and _with(app, fresh).get("/api/auth/me").status_code == 200,
        )

        c.check(
            "출처: 다른 사이트·'null'은 403 bad_origin, 같은 출처는 통과",
            main.post("/api/analyses", json={}, headers={"Origin": "https://evil.example"}).json()["detail"]["code"]
            == "bad_origin"
            and main.post("/api/analyses", json={}, headers={"Origin": "null"}).status_code == 403
            and main.post("/api/analyses", json={}, headers={"Origin": BASE}).status_code == 422,
        )

        created = main.post("/api/accounts", json={"login_id": "kim", "name": "김담당"}).json()
        temporary = created["temporary_password"]
        c.check(
            "구성원 추가: 기본 역할 담당자 · 첫 로그인 때 바꿈 · 응답에만 임시 비밀번호",
            created["account"]["role"] == "member"
            and created["account"]["must_change_password"]
            and temporary not in json.dumps(main.get("/api/accounts").json()),
        )
        c.check(
            "같은 아이디·예약된 아이디(demo·dev)는 409",
            main.post("/api/accounts", json={"login_id": "kim", "name": "다시"}).status_code == 409
            and main.post("/api/accounts", json={"login_id": "demo", "name": "체험"}).status_code == 409,
        )
        member = _client(app)
        _login(member, "kim", temporary)
        _change(member, temporary, MEMBER_PW)
        c.check("담당자 로그인 → 업무 API 200", member.get("/api/samples").status_code == 200)

        wrong = [_login(_client(app), "kim", f"bad-pass-{i}-x").status_code for i in range(5)]
        blocked = _login(_client(app), "kim", MEMBER_PW)
        c.check(
            "5번 틀리면 맞는 비밀번호도 429(Retry-After) · 없는 아이디도 같은 401 문구",
            wrong == [401] * 5
            and blocked.status_code == 429
            and int(blocked.headers.get("retry-after", "0")) > 0
            and _login(_client(app), "nobody", "whatever-1234").json()["detail"]["message"]
            == "아이디 또는 비밀번호가 일치하지 않습니다",
        )
        app.state.auth._throttle.succeed("kim")

        reset = main.post("/api/accounts/kim/reset-password")
        c.check(
            "초기화: 새 임시 비밀번호 · 담당자 세션 폐기 · 다시 로그인하면 바꾸기 전",
            reset.status_code == 200
            and member.get("/api/auth/me").status_code == 401
            and _login(_client(app), "kim", reset.json()["temporary_password"]).json()["must_change_password"],
        )
        c.check(
            "내 비밀번호는 초기화 대신 바꾸기(422)", main.post("/api/accounts/lead/reset-password").status_code == 422
        )

        again = _client(app)
        _login(again, "kim", reset.json()["temporary_password"])
        off = main.patch("/api/accounts/kim", json={"disabled": True})
        c.check(
            "끄기: 세션 폐기 · 맞는 비밀번호로도 403 account_disabled",
            off.status_code == 200
            and again.get("/api/auth/me").status_code == 401
            and _login(_client(app), "kim", reset.json()["temporary_password"]).json()["detail"]["code"]
            == "account_disabled",
        )
        own_role = main.patch("/api/accounts/lead", json={"role": "member"})
        own_off = main.patch("/api/accounts/lead", json={"disabled": True})
        c.check(
            "내 줄(역할·사용 여부)은 서버에서도 바꿀 수 없음(403 forbidden — 화면과 같은 규칙)",
            own_role.status_code == 403
            and own_off.json()["detail"]["code"] == "forbidden"
            and main.get("/api/auth/me").json()["role"] == "admin",
            (own_role.status_code, own_off.json()),
        )
        last: list[int] = []
        try:  # 내 줄을 못 바꾸니 API로는 닿지 않는 규칙 — 다른 사람(개발 모드 관리자)이 마지막 팀장을 끄는 경우로 본다
            app.state.auth.update_account(DEV_PRINCIPAL, "lead", AccountUpdate(disabled=True))
        except AuthError as error:
            last.append(error.status)
        c.check("사용 중인 관리자가 0명이 되는 변경은 409 last_admin", last == [409], last)

        results: list[int] = []

        def sign_in() -> None:
            results.append(_login(_client(app), "lead", ADMIN_PW).status_code)

        threads = [threading.Thread(target=sign_in) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        c.check("동시에 로그인해도 모두 성공(해시 동시 2개 + 대기)", results == [200, 200, 200], results)
        out = main.post("/api/auth/logout")
        c.check(
            "로그아웃: 204 · 쿠키 지움 · 그 세션 401",
            out.status_code == 204 and main.get("/api/auth/me").status_code == 401,
        )


def _real(snapshot: GraphSnapshot) -> GraphSnapshot:
    real = snapshot.model_copy(update={"origin": "excel_import", "data_mode": DataMode.REAL})
    return real.model_copy(update={"snapshot_id": snapshot_id(real)})


def _demo_real(c: Checker, root: Path, snapshot: GraphSnapshot) -> None:
    c.section("로그인: 체험은 실데이터를 못 본다")
    real = _real(snapshot)
    SnapshotStore(root / "data-demo").save(real, info_of(real, "협력사 발주대장.xlsx", imported_at=datetime.now(UTC)))
    app = _app(root, "data-demo")
    with _client(app):
        people = _people(app)
        admin, demo = people["admin"], people["demo"]
        listing = demo.get("/api/snapshots").json()
        c.check(
            "합성 지도가 활성: 체험 목록에는 합성 지도만(실데이터 파일 이름 없음), 관리자는 둘 다",
            [i["data_mode"] for i in listing["items"]] == ["synthetic"]
            and "협력사" not in json.dumps(listing, ensure_ascii=False)
            and len(admin.get("/api/snapshots").json()["items"]) == 2,
        )
        c.check(
            "체험 내려받기: 실데이터 지도 403, 합성 지도 200",
            demo.get(f"/api/snapshots/{real.snapshot_id}/export").status_code == 403
            and demo.get(f"/api/snapshots/{snapshot.snapshot_id}/export").status_code == 200,
        )
        token = admin.get("/api/snapshots").json()["workspace"]
        admin.post(f"/api/snapshots/{real.snapshot_id}/activate", headers={"X-Ripple-Workspace": token})
        codes = {
            "list": demo.get("/api/snapshots"),
            "samples": demo.get("/api/samples"),
            "graph": demo.get("/api/graph/view", params={"center": "S-001:B31P"}),
            "export": demo.post("/api/analyses/export", json={}),  # 분석 결과 엑셀도 실데이터 작업 공간이면 막힘
            "login": _client(app).post("/api/auth/demo"),
        }
        c.check(
            "실데이터가 활성: 체험 목록·업무 경로·새 체험 로그인 모두 403 demo_unavailable, 내 정보는 200",
            all(r.status_code == 403 and r.json()["detail"]["code"] == "demo_unavailable" for r in codes.values())
            and demo.get("/api/auth/me").status_code == 200
            and people["member"].get("/api/samples").status_code == 200,
            {k: r.status_code for k, r in codes.items()},
        )
        token = admin.get("/api/snapshots").json()["workspace"]
        admin.post(f"/api/snapshots/{snapshot.snapshot_id}/activate", headers={"X-Ripple-Workspace": token})
        c.check("합성 지도로 돌아오면 체험 다시 됨", demo.get("/api/samples").status_code == 200)


def _restart(c: Checker, root: Path) -> None:
    c.section("로그인: 다시 켜도 계정·세션 유지")
    first = _app(root, "data-restart")
    with _client(first) as client:
        _login(client, "lead", FIRST)
        _change(client, FIRST, ADMIN_PW)
        token = client.cookies.get("ripple_session") or ""
    second = _app(root, "data-restart", environ={"RIPPLE_ADMIN_ID": "other", "RIPPLE_ADMIN_PASSWORD": "another-pass-1"})
    with _client(second) as client:
        holder = _with(second, token)
        me = holder.get("/api/auth/me")
        c.check(
            "같은 데이터 폴더로 다시 켜면 세션 그대로(비밀번호 바꾼 관리자)",
            me.status_code == 200 and me.json()["must_change_password"] is False,
        )
        c.check(
            "계정이 있으면 첫 관리자 변수는 무시",
            [a["login_id"] for a in holder.get("/api/accounts").json()["items"]] == ["lead"],
        )


def _bootstrap(c: Checker, root: Path, notes: _Notes) -> None:
    c.section("로그인: 첫 관리자")
    weak = _app(root, "data-weak", environ={"RIPPLE_ADMIN_ID": "lead", "RIPPLE_ADMIN_PASSWORD": "short"})
    with _client(weak) as client:
        health = client.get("/api/health").json()
        c.check(
            "약한 첫 관리자 비밀번호는 만들지 않음 → 로그인 준비 안 됨, 이유를 경고로 남김",
            health["auth"]["accounts_ready"] is False
            and _login(client, "lead", "short").status_code == 401
            and any(m.startswith("RIPPLE_ADMIN_PASSWORD") for m in notes.messages),
        )
    empty = _app(root, "data-empty", environ={})
    with _client(empty) as client:
        c.check(
            "첫 관리자 변수 없음 → 계정 없음(로그인 화면이 안내)",
            client.get("/api/health").json()["auth"]
            == {"required": True, "demo_login": True, "accounts_ready": False, "quick_login": False},
        )
    (root / "data-broken").mkdir()
    (root / "data-broken" / "accounts.json").write_text("{깨짐", encoding="utf-8")
    broken = _app(root, "data-broken")

    def start() -> None:
        with _client(broken):
            pass

    c.check("계정 파일 손상이면 시작하지 않음(첫 관리자 변수로 새로 만들지 않음)", c.raises(start, AccountStoreError))
    built = _app(root, "data-build", extra={"RIPPLE_BUILD": "abc1234"})
    with _client(built) as client:
        c.check("상태 확인에 빌드 커밋", client.get("/api/health").json()["build"] == "abc1234")


def _dev_mode(c: Checker, root: Path, notes: _Notes) -> None:
    c.section("로그인: 개발 모드(RIPPLE_AUTH=off)")
    app = _app(root, "data-dev", extra={"RIPPLE_AUTH": "off"})
    with _client(app) as client:
        me = client.get("/api/auth/me").json()
        c.check(
            "모든 요청을 개발 관리자로, 상태 확인에 required=false",
            me["login_id"] == "dev"
            and me["role"] == "admin"
            and client.get("/api/samples").status_code == 200
            and client.get("/api/health").json()["auth"]["required"] is False,
        )
        c.check("개발 모드로 켜면 경고를 남김", any("RIPPLE_AUTH=off" in m for m in notes.messages))
        accounts = client.get("/api/accounts")
        c.check(
            "개발 모드에서도 구성원 목록을 열 수 있음(계정 파일만 읽고 첫 관리자는 만들지 않음)",
            accounts.status_code == 200 and accounts.json()["items"] == [],
            accounts.status_code,
        )


def _pinned(c: Checker) -> None:
    """검사한 세대 = 처리하는 세대.

    활성 세대를 읽을 때마다 합성↔실데이터가 바뀌어도 체험에게 실데이터 세대를 주지 않는다."""
    c.section("로그인: 체험 검사와 처리가 같은 세대")
    synthetic = SimpleNamespace(data_mode=DataMode.SYNTHETIC, token="w-syn")
    real = SimpleNamespace(data_mode=DataMode.REAL, token="w-real")

    class Flipping(Workspaces):
        def __init__(self) -> None:  # 부모 초기화 없이 활성 세대 읽기만 흉내 낸다
            self.reads = 0

        @property
        def current(self) -> Any:
            self.reads += 1
            return synthetic if self.reads % 2 else real

    demo = Principal(login_id="demo", name="체험", role=Role.DEMO, demo=True, token="t")
    handed: list[str] = []
    for flips in range(6):
        holder = Flipping()
        holder.reads = flips
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(workspaces=holder)))
        response = SimpleNamespace(headers={})
        try:
            workspace = get_workspace(request, response, demo, None)  # type: ignore[arg-type]
            handed.append(workspace.data_mode.value)
        except HTTPException as error:
            handed.append(f"blocked:{error.status_code}")
    c.check(
        "체험 요청에 실데이터 세대를 넘기는 경우가 없음(합성 세대를 받거나 403)",
        all(h in ("synthetic", "blocked:403") for h in handed),
        handed,
    )
