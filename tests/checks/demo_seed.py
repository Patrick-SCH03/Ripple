"""합성 시연 기록 시드(RIPPLE_DEMO_SEED, docs/operations.md(서비스) 7절) — 서버·키 없이.

- 꺼짐(기본)이면 아무것도 안 함 · 실데이터면 켜져 있어도 안 함(경고) · 같은 날 다시 시작하면 그대로 · 다음 날
  시작하면 옛 기록을 자동 보관하고 그날 기준으로 다시 채움(날마다 새로 채우기의 나머지는 demo_daily.py).
- 만든 기록이 진짜 흐름을 거쳤나: 감사 사슬 검증 통과 · 결재 규칙(역할 · 자기 결정 금지 · 개발 모드 없음) ·
  시각이 순번 순이고 지금보다 앞 · 시연용 설계변경(ECN-D-0043·0119·0045·0130) 없음.
- 숫자는 엔진·숨긴 모델 값: 개정마다 그날 세계로 다시 분석하면 본문 그대로 · 실적은 같은 세계 숨긴 모델 값 그대로.
- 결재·현황(순수 overview와 GET /api/manage/overview)의 결재함·현황·성과·실적이 비어 있지 않음,
  날이 바뀌면 D-n이 하루 준다.
- 가상 담당자 계정은 구성원에 보이고 아이디·비밀번호로는 들어갈 수 없음. 날짜에 멈춘 세계(fixed)도 채운다.
- 결재선 가상 계정(part-lead·executive)은 빠른 로그인 고정 계정: 예전 시드가 비밀번호(RIPPLE_DEMO_PASSWORD)로 만든
  계정이 남은 폴더(라이브)에서 시작해도 깨지지 않고, 그 해시·세션은 지우며, 파트장·본부장 단추로 자기 단계 결재함.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from harness import Checker

from checks.demo_daily import _counts, _settings
from ripple.api.app import create_app
from ripple.api.demo_daily import seed_demo
from ripple.api.demo_plan import APPROVERS, EXTRA, PLAN, RESERVED, SEED_PEOPLE
from ripple.api.demo_seed import KST, SeedResult, sync_approvers
from ripple.api.deps import AppContext
from ripple.api.ncr import ncr_counts
from ripple.api.workspace import Workspaces
from ripple.auth import AuthError, AuthService
from ripple.auth.passwords import hash_password
from ripple.config.settings import Settings
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.auth import Role
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.domain import DataMode
from ripple.contracts.records import ApprovalStep, EcnAction, EcnState, RecordBody
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.generator.actuals import HiddenModel
from ripple.generator.build import Generated, generate
from ripple.generator.io import load_config, write_outputs
from ripple.graph.memory import MemoryGraphStore
from ripple.records.metrics import Inputs, overview
from ripple.store.accounts import AccountStore, SessionStore, StoredAccount
from ripple.store.outcomes import OutcomeLog
from ripple.store.records import RecordStore
from ripple.store.snapshots import SnapshotStore

DAY = date(2026, 11, 9)  # 시연 날
NOW = datetime(2026, 11, 9, 6, 0, tzinfo=UTC)  # KST 15:00
BASE = "https://testserver"
DECIDE = (EcnAction.APPROVE, EcnAction.REJECT, EcnAction.HOLD)
MEMBER_ACTS = (EcnAction.RECORD, EcnAction.REQUEST_REVIEW, EcnAction.SETTLE, EcnAction.START, EcnAction.CLOSE)
STEP_ROLE = {
    ApprovalStep.PART_LEAD: Role.PART_LEAD,
    ApprovalStep.TEAM_LEAD: Role.ADMIN,
    ApprovalStep.EXECUTIVE: Role.EXECUTIVE,
}
PASSWORD = "demo-pass-2026-x"  # 예전 시드의 RIPPLE_DEMO_PASSWORD 흉내(배포 값 아님) — 이제는 쓰지 않는다
ON = {"RIPPLE_DEMO_SEED": "on"}


def run(c: Checker) -> None:
    c.section("시연 기록 시드: 설정·꺼짐·실데이터")
    c.check(
        "RIPPLE_DEMO_SEED: 기본 off · on/off(대소문자 무관) · 그 밖의 값은 시작 오류",
        not Settings.from_env({}).demo_seed
        and Settings.from_env({"RIPPLE_DEMO_SEED": "ON"}).demo_seed
        and c.raises(lambda: Settings.from_env({"RIPPLE_DEMO_SEED": "yes"})),
    )
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        _off_and_real(c, root)
        _live(c, root)
        _api(c, root)
        _fixed(c, root)


# ---------- 준비 ----------


def _desk(settings: Settings, today: date = DAY) -> tuple[AppContext, Workspaces, AccountStore, OutcomeLog]:
    context = AppContext.load(settings)
    holder = Workspaces(context, MemoryGraphStore(), None, SnapshotStore(settings.data_dir), today=lambda: today)
    holder.start()
    accounts = AccountStore(settings.data_dir)
    accounts.load()
    RecordStore(settings.data_dir).start()  # 앱 시작 순서 그대로(기록 저장소 → 계정 → 작업 공간 → 시드)
    return context, holder, accounts, OutcomeLog(settings.data_dir)


@contextmanager
def _warnings() -> Iterator[list[str]]:
    seen: list[str] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    logger = logging.getLogger("ripple.seed")
    handler = Keep(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        yield seen
    finally:
        logger.removeHandler(handler)


def _world(day: date | None) -> Generated:
    config = load_config()
    return generate(config if day is None else config.model_copy(update={"scenario_date": day}))


# ---------- 꺼짐 · 실데이터 ----------


def _off_and_real(c: Checker, root: Path) -> None:
    live = {"RIPPLE_SYNTHETIC_CLOCK": "live"}
    off = _desk(_settings(root, "off", live))
    c.check(
        "꺼짐(기본): 아무것도 만들지 않음", seed_demo(*off[:3], now=NOW) is None and _counts(root / "off") == (0, 0, 0)
    )
    context, holder, accounts, _outcomes = _desk(_settings(root, "real", {**live, **ON}))
    real = AppContext.load(replace(context.settings, data_mode=DataMode.REAL))
    with _warnings() as seen:
        result = seed_demo(real, holder, accounts, now=NOW)
    c.check(
        "실데이터 모드면 켜져 있어도 만들지 않고 경고(계정도 그대로)",
        result is None
        and _counts(root / "real") == (0, 0, 0)
        and any("실데이터" in message for message in seen)
        and not any(a.login_id.startswith("seed-") for a in accounts.all()),
        seen,
    )


# ---------- 실시간 시연 세계(배포 기본) ----------


def _live(c: Checker, root: Path) -> None:
    c.section("시연 기록 시드: 실시간 시연 세계 — 진짜 흐름 · 한 번만 · 숫자 근거")
    settings = _settings(root, "live", {"RIPPLE_SYNTHETIC_CLOCK": "live", **ON})
    desk = _desk(settings)
    result = seed_demo(*desk[:3], now=NOW)
    outcome_steps = sum(1 for case in PLAN for step in case.steps if step.action is None)
    c.check(
        "각본대로 채움: 설계변경 수 · 실적 수 · 가상 담당자 2명",
        result == SeedResult(ecns=len(PLAN), audit=result.audit if result else -1, outcomes=outcome_steps, people=2),
        result,
    )
    store = RecordStore(settings.data_dir)
    _chain_and_rules(c, store)
    _numbers(c, store, settings, live=True)
    _screens(c, store, desk[3])
    before = _counts(settings.data_dir)
    again = seed_demo(*_desk(settings)[:3], now=NOW + timedelta(hours=1))
    same = _counts(settings.data_dir)
    with _warnings() as seen:
        next_day = _desk(settings, DAY + timedelta(days=1))
        later = seed_demo(*next_day[:3], now=NOW + timedelta(days=1))
    archives = sorted(p.name for p in (settings.data_dir / "archive").glob("records-auto-*"))
    c.check(
        "같은 날 다시 시작하면 그대로(같은 수) · 다음 날 시작하면 옛 기록을 자동 보관하고 그날 기준으로 다시 채움"
        "(같은 수, 로그에 '날 바뀜')",
        again is None
        and same == before
        and later is not None
        and _counts(settings.data_dir) == before
        and len(archives) == 1
        and any("날 바뀜" in message and "옛 기록 보관" in message for message in seen),
        (before, same, _counts(settings.data_dir), archives, seen),
    )
    _people(c, settings.data_dir)


def _chain_and_rules(c: Checker, store: RecordStore) -> None:
    check = store.verify()
    c.check("감사 사슬·참조·투영 검증 통과", check.ok and not check.problems, check.problems)
    items, audit, _ = store.overview_inputs(include_real=True)
    by_seq = {e.seq: e for e in audit}
    decisions = [e for e in audit if e.action in DECIDE]
    c.check(
        "결재 규칙: 결정은 그 단계의 결재자(파트장·팀장·본부장) 또는 팀장 전결 · 요청자 ≠ 결정자 · 기록·검토 요청·"
        "담당자 처리(무비용)·실행·종료는 담당자 · 개발 모드 표시 없음",
        all(
            e.detail.step is not None
            and (e.actor.role is STEP_ROLE[e.detail.step]) != e.detail.proxy
            and (not e.detail.proxy or e.actor.role is Role.ADMIN)
            for e in decisions
        )
        and all(e.detail.no_cost for e in audit if e.action is EcnAction.SETTLE)
        and all(
            e.detail.review_seq in by_seq and by_seq[e.detail.review_seq].actor.login_id != e.actor.login_id
            for e in decisions
        )
        and all(e.actor.role is Role.MEMBER for e in audit if e.action in MEMBER_ACTS)
        and not any(e.actor.dev or e.detail.self_decision or e.detail.other_version for e in audit),
    )
    ids = {item.status.ecn_id for item in items}
    c.check(
        "시연용 설계변경(ECN-D-0043·0119·0045·0130)은 기록 없음 · 각본의 설계변경만",
        not ids & set(RESERVED) and ids == {case.ecn_id for case in PLAN} and set(EXTRA) <= ids,
        sorted(ids),
    )
    times = [e.at for e in sorted(audit, key=lambda e: e.seq)]
    c.check(
        "감사 줄 시각은 순번 순이고 시드한 '지금'보다 앞",
        times == sorted(times) and times[-1] <= NOW,
    )
    states = {item.status.state for item in items}
    stored = set(EcnState) - {EcnState.REQUESTED}
    c.check("현황: 분석·검토·보류·승인·실행·종료·반려가 모두 있음", states == stored, states)
    waiting = {item.status.review.current for item in items if item.status.review is not None}
    c.check(
        "결재선이 섞임: 지금 걸린 건이 파트장·팀장·본부장 단계에 모두 있음 · 팀장 전결 · 무비용 담당자 처리가 있음",
        waiting == set(ApprovalStep)
        and any(e.detail.proxy for e in decisions)
        and any(e.action is EcnAction.SETTLE for e in audit),
        waiting,
    )


def _bodies(store: RecordStore) -> list[RecordBody]:
    bodies: list[RecordBody] = []
    for item in store.listing(include_real=True).ecns:
        detail = store.detail(item.status.ecn_id, include_real=True, same_version=lambda _body: True)
        assert detail is not None
        for revision in detail.revisions:
            found = store.record(revision.record_id, include_real=True)
            assert found is not None
            bodies.append(found.body)
    return bodies


def _numbers(c: Checker, store: RecordStore, settings: Settings, *, live: bool) -> None:
    context = AppContext.load(settings)
    worlds: dict[date | None, Generated] = {}

    def world(day: date) -> Generated:
        key = day if live else None
        if key not in worlds:
            worlds[key] = _world(key)
        return worlds[key]

    same: list[bool] = []
    for body in _bodies(store):
        request = body.result.request
        generated = world(request.as_of)
        # 기록 본문 계산(api/records.py record_body)과 같게 사전 점검의 합성 NCR 건수를 넘긴다
        fresh = analyze(
            GraphIndex(generated.snapshot),
            request,
            context.rulebook,
            context.params,
            context.strength,
            ncr_counts=ncr_counts(body.data_mode),
        )
        same.append(generated.snapshot.snapshot_id == body.snapshot_id and fresh == body.result)
    c.check(f"개정 {len(same)}개: 그날 세계로 다시 분석하면 기록 본문 그대로(엔진 값)", bool(same) and all(same))
    truth: list[bool] = []
    for entry in OutcomeLog(settings.data_dir).latest().values():
        found = store.record(entry.record_id, include_real=True)
        assert found is not None
        approved: AnalysisRequest = found.body.result.request
        generated = world(approved.as_of)
        holds = {hold.po_id: hold.hold_days for hold in approved.holds}
        actual = HiddenModel(generated, settings.params_path).outcome(
            approved.change, approved.as_of, approved.effective_confirm_on, holds
        )
        delay = entry.exit_delay_days
        truth.append(entry.cost_krw == actual.total_krw and delay in (None, actual.max_exit_delay_days))
    c.check(f"실적 {len(truth)}건: 같은 세계 숨긴 모델의 실제 비용·출구 지연 그대로", len(truth) >= 5 and all(truth))
    if live:
        recorded = [
            (r.as_of, r.recorded_at.astimezone(KST).date())
            for item in store.listing(include_real=True).ecns
            for r in [item.latest]
        ]
        c.check("실시간 세계: 개정의 기준일 = 기록한 날(KST, 그날 세계로 계산)", all(a == b for a, b in recorded))


def _screens(c: Checker, store: RecordStore, outcomes: OutcomeLog) -> None:
    items, audit, bodies = store.overview_inputs(include_real=True)
    latest = outcomes.latest()
    found = overview(Inputs(items=items, audit=audit, bodies=bodies, now=NOW, days=30, outcomes=latest, live=True))
    inbox, perf = found.inbox, found.performance
    c.check(
        "결재함: 검토 3건 이상 · 보류 1건 · 마감 3일 이내 · 더 저렴한 대안 · 요청자 2명 이상",
        sum(i.state is EcnState.IN_REVIEW for i in inbox) >= 3
        and sum(i.state is EcnState.ON_HOLD for i in inbox) == 1
        and any(0 <= i.days_left <= 3 for i in inbox)
        and any(i.cheaper_by for i in inbox)
        and len({i.requested_by.login_id for i in inbox}) >= 2,
        [(i.ecn_id, i.state, i.days_left, i.cheaper_by) for i in inbox],
    )
    c.check(
        "성과(30일): 승인·반려·보류 · 처리 시간 · 마감 안 비율 · 지킨 금액 · 담당자 3명 · 블록 3개 이상",
        perf.approved >= 5
        and perf.rejected >= 1
        and perf.held >= 1
        and perf.request_to_decision_hours is not None
        and perf.on_time_rate is not None
        and perf.protected > 0
        and len(perf.people) == 3
        and len(found.blocks) >= 3,
        perf,
    )
    c.check(
        "예측 대비 실적 5건 이상(실행·종료 건) · 오차 중앙값 계산됨",
        found.outcomes.count >= 5 and found.outcomes.median_abs_error is not None,
        found.outcomes,
    )
    later = NOW + timedelta(days=1)
    tomorrow = overview(Inputs(items=items, audit=audit, bodies=bodies, now=later, days=30, live=True))
    c.check(
        "날이 바뀌면 결재함 D-n이 하루씩 준다(실시간 세계 = KST 오늘 기준), 줄 수는 그대로",
        [i.days_left - 1 for i in inbox] == [i.days_left for i in tomorrow.inbox],
    )


def _people(c: Checker, data_dir: Path) -> None:
    accounts = AccountStore(data_dir)
    accounts.load()
    seeded = {a.login_id: a for a in accounts.all() if a.login_id.startswith("seed-")}
    auth = AuthService(accounts, SessionStore(data_dir))
    refused: list[bool] = []
    for person in SEED_PEOPLE:
        try:
            auth.login(person.login_id, "seed-pass-2026-x")
            refused.append(False)
        except AuthError as error:
            refused.append(error.status == 401)
    c.check(
        "가상 담당자: 구성원(담당자)으로 보이고 아이디·비밀번호로는 못 들어감",
        set(seeded) == {p.login_id for p in SEED_PEOPLE}
        and all(a.role is Role.MEMBER and not a.disabled for a in seeded.values())
        and all(refused),
        refused,
    )
    _approvers(c, accounts, data_dir)


def _legacy(accounts: AccountStore) -> None:
    """라이브처럼: 예전 시드가 RIPPLE_DEMO_PASSWORD로 만든 결재선 계정(비밀번호 해시 · 세션 판 2)."""
    hashed = hash_password(PASSWORD)

    def put(stored: dict[str, StoredAccount]) -> None:
        for person in APPROVERS:
            stored[person.login_id] = StoredAccount(
                login_id=person.login_id,
                name=person.name,
                role=person.role,
                password_hash=hashed,
                created_at=NOW - timedelta(days=3),
                session_version=2,
            )

    accounts.change(put)


def _approvers(c: Checker, accounts: AccountStore, data_dir: Path) -> None:
    """결재선 가상 계정(이파트장·최본부장) = 빠른 로그인 고정 계정: 예전 비밀번호 해시가 있어도 아이디·비밀번호로는 401,
    다음 시작(sync_approvers)에 해시를 지우고 그 비밀번호 시절 세션을 끊으며, 빠른 로그인으로는 그 역할."""
    seeded = {p.login_id: accounts.get(p.login_id) for p in APPROVERS}
    _legacy(accounts)
    sessions = SessionStore(data_dir)
    sessions.load(NOW)
    auth = AuthService(accounts, sessions, quick_login=True, now=lambda: NOW)

    def login(person_id: str) -> str:
        try:
            principal, _token = auth.login(person_id, PASSWORD)
        except AuthError as error:
            return str(error.status)
        return principal.role.value

    def old_session(login_id: str) -> str:
        version = accounts.get(login_id).session_version  # type: ignore[union-attr]
        expires = NOW + timedelta(hours=12)
        return sessions.create(login_id, demo=False, now=NOW, expires_at=expires, version=version)

    old = [old_session(p.login_id) for p in APPROVERS]
    alive_before = [auth.resolve(token) is not None for token in old]
    with_pw = [login(p.login_id) for p in APPROVERS]
    synced = sync_approvers(accounts, NOW)
    once = {p.login_id: accounts.get(p.login_id) for p in APPROVERS}
    again = sync_approvers(accounts, NOW)  # 다시 시작: 그대로(세션 판도)
    kept = all(once[p.login_id] == accounts.get(p.login_id) for p in APPROVERS)
    quick = [auth.quick(p.role)[0] for p in APPROVERS]
    files = (accounts.path.read_text(encoding="utf-8"),)
    c.check(
        "결재선 가상 계정: 시드가 파트장·본부장 역할로 넣음 · 예전 비밀번호 해시가 있어도 아이디·비밀번호 로그인 401 · "
        "다음 시작에 해시를 지우고 세션 판을 한 번 올려 그 시절 세션 무효(다시 시작해도 그대로) · "
        "빠른 로그인은 그 아이디·이름·역할(비밀번호 바꾸기 요구 없음) · 파일에 비밀번호 원문 없음",
        all(a is not None and a.role is p.role for p, a in zip(APPROVERS, seeded.values(), strict=True))
        and alive_before == [True, True]
        and with_pw == ["401", "401"]
        and synced is True
        and again is True
        and kept
        and all(a is not None and a.session_version == 3 for a in once.values())
        and all(auth.resolve(token) is None for token in old)
        and [(q.login_id, q.name, q.role) for q in quick] == [(p.login_id, p.name, p.role) for p in APPROVERS]
        and not any(q.must_change_password for q in quick)
        and not any(PASSWORD in text for text in files),
        (alive_before, with_pw, [a.session_version if a else None for a in once.values()]),
    )


# ---------- 앱으로(빠른 로그인 · GET /api/manage/overview) ----------


def _api(c: Checker, root: Path) -> None:
    c.section("시연 기록 시드: 앱 시작 → 팀장 결재·현황 API")
    settings = _settings(root, "app", {"RIPPLE_SYNTHETIC_CLOCK": "live", "RIPPLE_QUICK_LOGIN": "on", **ON})
    settings.data_dir.mkdir(parents=True)
    legacy = AccountStore(settings.data_dir)
    legacy.load()
    _legacy(legacy)  # 라이브처럼 예전 비밀번호 해시가 있는 결재선 계정 + 남은 변수
    with TestClient(create_app(settings, environ={"RIPPLE_DEMO_PASSWORD": PASSWORD}), base_url=BASE) as client:
        client.post("/api/auth/quick", json={"role": "admin"})
        data = client.get("/api/manage/overview").json()
        verify = client.get("/api/audit/verify").json()
        boxes = {role: _approver_box(client, role) for role in ("part_lead", "executive")}
        typed = [
            client.post("/api/auth/login", json={"login_id": p.login_id, "password": PASSWORD}).status_code
            for p in APPROVERS
        ]
    counts = _counts(settings.data_dir)
    c.check(
        "팀장 overview: 결재함·현황·성과·실적이 비어 있지 않음 · 감사 확인 정상",
        len(data.get("inbox", [])) >= 3
        and sum(s["count"] for s in data.get("states", [])) == len(PLAN)
        and data["performance"]["decided"] > 0
        and data["outcomes"]["count"] >= 5
        and verify.get("ok") is True,
        data.get("kpis"),
    )
    c.check(
        "예전 비밀번호 계정이 남은 폴더로 시작해도 파트장·본부장 빠른 로그인 200 · 그 사람(이파트장·최본부장) · "
        "결재함은 자기 단계 건만 1건 이상 · 예전 비밀번호로 아이디 로그인 401",
        all(
            box["status"] == 200
            and box["name"] == person.name
            and box["inbox"]
            and all(step == role for step in box["inbox"])
            for (role, box), person in zip(boxes.items(), APPROVERS, strict=True)
        )
        and typed == [401, 401],
        (boxes, typed),
    )
    with TestClient(create_app(settings, environ={}), base_url=BASE) as client:
        client.post("/api/auth/quick", json={"role": "member"})
        listed = {item["status"]["ecn_id"] for item in client.get("/api/ecns").json()["ecns"]}
    c.check(
        "다시 시작해도 같은 수 · 담당자 목록에 시연용 설계변경 없음",
        _counts(settings.data_dir) == counts and len(listed) == len(PLAN) and not listed & set(RESERVED),
        (counts, _counts(settings.data_dir)),
    )


def _approver_box(client: TestClient, role: str) -> dict[str, Any]:
    """그 역할 단추로 들어가 결재함 줄의 지금 단계를 모은다(쿠키는 다음 단추가 바꾼다)."""
    entered = client.post("/api/auth/quick", json={"role": role})
    inbox = client.get("/api/manage/overview").json().get("inbox", [])
    return {"status": entered.status_code, "name": entered.json().get("name"), "inbox": [i["step"] for i in inbox]}


# ---------- 날짜에 멈춘 세계 ----------


def _fixed(c: Checker, root: Path) -> None:
    c.section("시연 기록 시드: 날짜에 멈춘 세계(fixed) — 기본 지도 하나")
    write_outputs(_world(None), root / "synthetic")
    settings = replace(_settings(root, "fixed", ON), snapshot_path=root / "synthetic" / "snapshot.json")
    desk = _desk(settings)
    result = seed_demo(*desk[:3], now=NOW)
    store = RecordStore(settings.data_dir)
    items, audit, bodies = store.overview_inputs(include_real=True)
    found = overview(Inputs(items=items, audit=audit, bodies=bodies, now=NOW, days=None, outcomes=desk[3].latest()))
    c.check(
        "같은 각본으로 채움 · 감사 확인 정상 · 결재함 D-n은 지도 기준일 기준",
        result is not None
        and result.ecns == len(PLAN)
        and store.verify().ok
        and len(found.inbox) >= 3
        and all(i.days_left == (i.deadline - i.as_of).days for i in found.inbox),
        result,
    )
    _numbers(c, store, settings, live=False)
    dev_ids = {e.change.ecn_id for e in _world(None).ecns if e.split is EcnSplit.DEV}
    c.check("쓰는 설계변경은 모두 같은 세계의 개발 분할", {case.ecn_id for case in PLAN} <= dev_ids)
