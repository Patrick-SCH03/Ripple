"""배포 이미지 스모크 검사(CI image 작업, docs/operations.md(배포)): 실제 컨테이너(compose: neo4j·api·web)를 띄워
화면·API·로그인·
볼륨·재시작을 확인한다. 표준 라이브러리만 쓴다.

실행: python scripts/smoke_compose.py [--build <커밋>]
(Docker와 docker compose v2 필요, 끝나면 컨테이너·볼륨을 지운다)

- 데이터 볼륨을 root 소유로 먼저 만들어 Railway 볼륨처럼 붙인다 → API가 ripple 사용자로 돌고 계정 파일을 쓰는지.
- 화면: /, /app, /login(되돌림), 자산 캐시 머리글, CSP, version.json의 빌드 커밋.
- 로그인: 첫 관리자 → 비밀번호 바꾸기 전 403 → 바꾸면 200, 담당자는 관리자 API 403·상태 그대로, 다른 출처·null 출처 403.
- 기록·승인: 담당자 기록 → 검토 요청 → 관리자가 결재선(파트장 → 팀장 → 본부장) 끝까지 승인
  (전결 포함, docs/records.md 14절).
- API 컨테이너를 같은 볼륨으로 다시 만들기 → 세션 유지, 폐기한 세션 401, 기다리던 가져오기는 정해진 404,
  옛 작업 공간 토큰 409, 기록·승인 상태 그대로 · 감사 확인 정상.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WEB = "http://127.0.0.1:8080"
PROJECT = "ripple"
VOLUME = f"{PROJECT}_ripple-data"
RIPPLE_UID = 10001


@dataclass
class Reply:
    status: int
    headers: Mapping[str, str]
    body: bytes
    cookies: list[str] = field(default_factory=list)

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    def code(self) -> str | None:
        try:
            detail = self.json().get("detail")
        except (ValueError, AttributeError):
            return None
        return detail.get("code") if isinstance(detail, dict) else None


def request(
    method: str,
    path: str,
    *,
    body: Any = None,
    raw: bytes | None = None,
    cookie: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> Reply:
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode("utf-8"))
    sent = {"Content-Type": "application/octet-stream" if raw is not None else "application/json", **(headers or {})}
    if cookie:
        sent["Cookie"] = f"ripple_session={cookie}"
    req = urllib.request.Request(f"{WEB}{path}", data=data, method=method, headers=sent)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return Reply(
                response.status,
                {k.lower(): v for k, v in response.headers.items()},
                response.read(),
                response.headers.get_all("Set-Cookie") or [],
            )
    except urllib.error.HTTPError as error:
        return Reply(
            error.code,
            {k.lower(): v for k, v in error.headers.items()},
            error.read(),
            error.headers.get_all("Set-Cookie") or [],
        )


def session_of(reply: Reply) -> str:
    for line in reply.cookies:
        match = re.match(r"ripple_session=([^;]+)", line)
        if match:
            return match.group(1)
    raise AssertionError(f"세션 쿠키가 없어요: {reply.status} {reply.body[:200]!r}")


def compose(*args: str, env: Mapping[str, str], check: bool = True) -> str:
    result = subprocess.run(
        ["docker", "compose", "-p", PROJECT, *args], cwd=ROOT, env=env, capture_output=True, text=True, check=False
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"docker compose {' '.join(args)} 실패:\n{result.stdout}\n{result.stderr}")
    return result.stdout


class Smoke:
    def __init__(self) -> None:
        self.failed: list[str] = []

    def check(self, name: str, ok: bool, detail: object = "") -> None:
        print(f"{'✓' if ok else '✗'} {name}{'' if ok else f'  {str(detail)[:400]}'}", flush=True)
        if not ok:
            self.failed.append(name)


def wait_for(probe: Callable[[], bool], seconds: float, what: str) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if probe():
                return
        except OSError:
            pass
        time.sleep(2)
    raise RuntimeError(f"{what}을(를) 기다리다 시간이 지났어요")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", default="smoke")
    args = parser.parse_args()
    first = "Sm-" + secrets.token_urlsafe(12)
    changed = "Sm-" + secrets.token_urlsafe(12)
    env = {
        **os.environ,
        "NEO4J_PASSWORD": "Sm-" + secrets.token_urlsafe(16),
        "RIPPLE_ADMIN_ID": "lead",
        "RIPPLE_ADMIN_PASSWORD": first,
        "RIPPLE_DEMO_LOGIN": "on",
        "RIPPLE_BUILD": args.build,
    }
    smoke = Smoke()
    try:
        run(smoke, env, first, changed, args.build)
    except Exception as error:  # 진행을 못 하면 실패로 남기고 로그를 보인다
        smoke.check(f"진행 중 오류: {error}", False)
    if smoke.failed:
        print(compose("logs", "--no-color", "--tail", "200", env=env, check=False))
    compose("down", "-v", "--remove-orphans", env=env, check=False)
    print(f"\n스모크 {'통과' if not smoke.failed else f'실패 {len(smoke.failed)}건'}")
    return 1 if smoke.failed else 0


def run(smoke: Smoke, env: dict[str, str], first: str, changed: str, build: str) -> None:
    # 데이터 볼륨: root 소유 폴더 + root 소유 파일(Railway 볼륨처럼).
    # 비워 두면 compose가 이미지 폴더의 소유권으로 채우므로 파일을 하나 둔다
    subprocess.run(["docker", "volume", "rm", "-f", VOLUME], capture_output=True, check=False)
    subprocess.run(["docker", "volume", "create", VOLUME], capture_output=True, check=True)
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{VOLUME}:/data",
            "alpine:3.22",
            "sh",
            "-c",
            "touch /data/root-owned && chown -R root:root /data && chmod 755 /data",
        ],
        capture_output=True,
        check=True,
    )
    compose("up", "-d", "--wait", "--wait-timeout", "300", env=env)

    # ---------- 화면 ----------
    home = request("GET", "/")
    smoke.check("화면 /: 200 HTML", home.status == 200 and b'<div id="root">' in home.body)
    for path in ("/app", "/login", "/app/whatever"):
        reply = request("GET", path)
        smoke.check(f"화면 {path}: index.html로 되돌림", reply.status == 200 and b'<div id="root">' in reply.body)
    csp = home.headers.get("content-security-policy", "")
    smoke.check(
        "보안 머리글: CSP(script-src 'self', frame-ancestors 'none')·nosniff, 문서는 no-cache",
        "script-src 'self'" in csp
        and "frame-ancestors 'none'" in csp
        and home.headers.get("x-content-type-options") == "nosniff"
        and home.headers.get("cache-control") == "no-cache",
        dict(home.headers),
    )
    asset = re.search(rb'src="(/assets/[^"]+\.js)"', home.body)
    cached = request("GET", asset.group(1).decode()) if asset else None
    smoke.check(
        "자산: 1년 immutable",
        cached is not None and cached.status == 200 and "immutable" in cached.headers.get("cache-control", ""),
    )
    gone = request("GET", "/assets/no-such-chunk-0000.js")
    smoke.check(
        "없는 자산은 404(index.html로 돌리지 않고 오래 캐시하지 않음)",
        gone.status == 404
        and b'<div id="root">' not in gone.body
        and "immutable" not in gone.headers.get("cache-control", ""),
        (gone.status, dict(gone.headers)),
    )
    version = request("GET", "/version.json")
    smoke.check(
        "version.json의 빌드 = 커밋", version.status == 200 and version.json().get("build") == build, version.body
    )

    # ---------- API·로그인 ----------
    health = request("GET", "/api/health").json()
    smoke.check(
        "상태 확인: 빌드 = 커밋, 로그인 켬, 첫 관리자 준비, 빠른 로그인 끔(기본)",
        health.get("build") == build
        and health["auth"] == {"required": True, "demo_login": True, "accounts_ready": True, "quick_login": False},
        health,
    )
    uid = compose("exec", "-T", "api", "sh", "-c", "grep '^Uid:' /proc/1/status", env=env)
    smoke.check(f"API 프로세스는 ripple 사용자({RIPPLE_UID})", uid.split()[1:2] == [str(RIPPLE_UID)], uid)
    owners = compose("exec", "-T", "api", "sh", "-c", "stat -c '%u %n' /app/.data /app/.data/*", env=env)
    smoke.check(
        "root 소유로 붙인 볼륨의 폴더·파일이 ripple 소유로 바뀌고 계정·기록 파일이 생김",
        all(line.startswith(f"{RIPPLE_UID} ") for line in owners.strip().splitlines())
        and "accounts.json" in owners
        and "records.sqlite3" in owners,
        owners,
    )
    smoke.check("세션 없이 업무 API 401", request("GET", "/api/samples").status == 401)
    login = request("POST", "/api/auth/login", body={"login_id": "lead", "password": first})
    cookie_line = next((c for c in login.cookies if c.startswith("ripple_session=")), "")
    smoke.check(
        "첫 관리자 로그인: HttpOnly·SameSite=Strict·Path=/ 쿠키",
        login.status == 200 and "HttpOnly" in cookie_line and "samesite=strict" in cookie_line.lower(),
        cookie_line,
    )
    first_session = session_of(login)
    blocked = request("GET", "/api/samples", cookie=first_session)
    smoke.check(
        "비밀번호 바꾸기 전 업무 API 403", blocked.status == 403 and blocked.code() == "password_change_required"
    )
    change = request(
        "POST", "/api/auth/password", body={"current_password": first, "new_password": changed}, cookie=first_session
    )
    admin = session_of(change)
    smoke.check("비밀번호 바꾸면 업무 API 200", request("GET", "/api/samples", cookie=admin).status == 200)
    smoke.check("바꾸기 전 세션은 폐기", request("GET", "/api/auth/me", cookie=first_session).status == 401)

    created = request("POST", "/api/accounts", body={"login_id": "kim", "name": "김담당"}, cookie=admin).json()
    temporary = created["temporary_password"]
    member_first = session_of(request("POST", "/api/auth/login", body={"login_id": "kim", "password": temporary}))
    member = session_of(
        request(
            "POST",
            "/api/auth/password",
            body={"current_password": temporary, "new_password": changed + "-m"},
            cookie=member_first,
        )
    )
    listing = request("GET", "/api/snapshots", cookie=admin).json()
    default_id = listing["active_snapshot_id"]
    before = (request("GET", "/api/accounts", cookie=admin).body, request("GET", "/api/snapshots", cookie=admin).body)
    forbidden = [
        request("GET", "/api/accounts", cookie=member),
        request("POST", "/api/accounts", body={"login_id": "park", "name": "박"}, cookie=member),
        request("POST", f"/api/snapshots/{default_id}/activate", cookie=member),
        request("POST", "/api/imports?file_name=x.xlsx", raw=b"x", cookie=member),
    ]
    after = (request("GET", "/api/accounts", cookie=admin).body, request("GET", "/api/snapshots", cookie=admin).body)
    smoke.check(
        "담당자의 관리자 API 403 · 계정·지도 그대로",
        all(r.status == 403 and r.code() == "forbidden" for r in forbidden) and before == after,
        [r.status for r in forbidden],
    )
    evil = request("POST", "/api/analyses", body={}, cookie=member, headers={"Origin": "https://evil.example"})
    null = request("POST", "/api/analyses", body={}, cookie=member, headers={"Origin": "null"})
    same = request("POST", "/api/analyses", body={}, cookie=member, headers={"Origin": WEB})
    smoke.check(
        "출처: 다른 사이트·null은 403 bad_origin, 같은 출처는 통과(본문 검사 422)",
        evil.code() == "bad_origin" and null.code() == "bad_origin" and same.status == 422,
        (evil.status, null.status, same.status),
    )

    # ---------- 기록·승인(볼륨에 남는지는 다시 만든 뒤에 본다) ----------
    samples = request("GET", "/api/samples", cookie=member)
    bound = {"X-Ripple-Workspace": samples.headers.get("x-ripple-workspace", "")}
    sample = samples.json()[0]
    ecn = sample["ecn_id"]
    analysis = request("POST", "/api/analyses", body=sample["request"], cookie=member, headers=bound).json()
    saved = request(
        "POST",
        "/api/records",
        body={
            "request": sample["request"],
            "analysis_id": analysis.get("analysis_id"),
            "request_id": str(uuid.uuid4()),
            "expected_version": 0,
        },
        cookie=member,
        headers=bound,
    )
    status = saved.json().get("status", {}) if saved.status == 200 else {}
    review = request(
        "POST",
        f"/api/ecns/{ecn}/actions",
        body={
            "action": "request_review",
            "expected_version": status.get("version"),
            "revision": status.get("revision"),
            "record_id": status.get("record_id"),
        },
        cookie=member,
        headers=bound,
    )
    reviewed = review.json() if review.status == 200 else {}
    checklist = request("GET", f"/api/ecns/{ecn}", cookie=admin).json().get("checklist", [])
    line = len((reviewed.get("review") or {}).get("steps") or ())
    # 결재선(docs/records.md 14절): 관리자(팀장)가 파트장·본부장 단계는 전결로, 팀장 단계는 자기 단계로 끝까지 승인
    current, approvals = reviewed, []
    for _ in range(line):
        approved = request(
            "POST",
            f"/api/ecns/{ecn}/actions",
            body={
                "action": "approve",
                "expected_version": current.get("version"),
                "revision": current.get("revision"),
                "record_id": current.get("record_id"),
                "review_seq": (current.get("review") or {}).get("seq"),
                "reason": "스모크 승인",
                "acknowledged": [item["key"] for item in checklist],
            },
            cookie=admin,
            headers=bound,
        )
        approvals.append(approved.status)
        if approved.status != 200:
            break
        current = approved.json()
    smoke.check(
        "기록·승인: 담당자 기록 → 검토 요청 → 관리자가 결재선 끝까지 승인(전결 포함)",
        saved.status == 200
        and review.status == 200
        and line == 3
        and approvals == [200] * line
        and current.get("state") == "approved",
        (saved.status, review.status, line, approvals, str(current)[:300]),
    )
    records_before = request("GET", "/api/ecns", cookie=admin).body

    exported = request("GET", f"/api/snapshots/{default_id}/export", cookie=admin)
    staged = request("POST", "/api/imports?file_name=smoke.xlsx", raw=exported.body, cookie=admin)
    import_id = staged.json().get("import_id") if staged.status == 200 else None
    smoke.check("관리자 엑셀 올림(열 확인 대기)", import_id is not None, (exported.status, staged.status))
    old_token = request("GET", "/api/snapshots", cookie=admin).json()["workspace"]

    # ---------- 같은 볼륨으로 API 다시 만들기 ----------
    compose("up", "-d", "--force-recreate", "--no-deps", "--wait", "--wait-timeout", "300", "api", env=env)
    wait_for(lambda: request("GET", "/api/health").status == 200, 120, "다시 만든 API")
    smoke.check(
        "다시 만든 뒤에도 관리자·담당자 세션 유지",
        request("GET", "/api/auth/me", cookie=admin).status == 200
        and request("GET", "/api/auth/me", cookie=member).status == 200,
    )
    smoke.check(
        "폐기한 세션은 다시 만든 뒤에도 401", request("GET", "/api/auth/me", cookie=first_session).status == 401
    )
    gone = request("POST", f"/api/imports/{import_id}/confirm", body={"version": 1}, cookie=admin)
    smoke.check(
        "기다리던 가져오기 확정은 404(다시 올려 달라는 안내)", gone.status == 404, (gone.status, gone.body[:200])
    )
    stale = request("GET", "/api/samples", cookie=admin, headers={"X-Ripple-Workspace": old_token})
    smoke.check(
        "옛 작업 공간 토큰은 409 workspace_changed", stale.status == 409 and stale.code() == "workspace_changed"
    )
    audit = request("GET", "/api/audit/verify", cookie=admin)
    smoke.check(
        "다시 만든 뒤에도 기록·승인 상태 그대로, 감사 확인 정상(기록·검토 요청·단계 승인 줄)",
        request("GET", "/api/ecns", cookie=admin).body == records_before
        and audit.status == 200
        and audit.json().get("ok") is True
        and audit.json().get("entries") == 2 + line,
        audit.body[:300],
    )
    out = request("POST", "/api/auth/logout", cookie=admin)
    smoke.check(
        "로그아웃 204 → 그 세션 401", out.status == 204 and request("GET", "/api/auth/me", cookie=admin).status == 401
    )
    stats = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    print("메모리:", " | ".join(line for line in stats.stdout.splitlines() if line.startswith(PROJECT)))


if __name__ == "__main__":
    sys.exit(main())
