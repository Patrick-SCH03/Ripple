"""팀장(관리자) 결재·현황 · 역할 분리 검사(docs/records.md(기록·결재) 11절, 계약 1.25.0).

- 역할 분리: 팀장(관리자)은 결재자(기록·검토 요청·실행은 403), 개발 모드는 모든 권한.
- 역할 통일(1.25.0): 금액별 결재 단계(전결)는 없다 — 옛 계정 파일의 결재 단계 칸은 읽을 때 버림. 결재선(파트장 → 팀장 →
  본부장, docs/records.md(기록·결재) 14절)은 금액과 무관하게 추가 비용 건 모두 — 결재함은 보는 사람의 단계 건만.
- 지표: 날짜 기준(실데이터 = 실제 날짜, 합성 = 기준일 + 지난 날수) · 기간 안 손실 없음 ·
  개발 모드 결정 제외 · 결재·현황 API · 실적.
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from harness import Checker

from checks.records import (
    ADMIN_PW,
    FIRST,
    MEMBER_PW,
    PART_PW,
    PART_WHO,
    SECOND_PW,
    _action,
    _analysis,
    _app,
    _approve_line,
    _body,
    _client,
    _do,
    _do_line,
    _login,
    _record,
    _results,
    _save,
    _staff,
    _who,
)
from ripple.auth import DEV_PRINCIPAL, AuthService, Principal
from ripple.contracts.auth import AccountUpdate, Permission, Role
from ripple.contracts.domain import DataMode
from ripple.contracts.records import ApprovalStep, EcnAction, EcnState, RecordBody
from ripple.contracts.result import AnalysisResult, DeadlineKind, ZeroLossDeadline
from ripple.generator.build import generate
from ripple.generator.io import load_config, write_outputs
from ripple.records.metrics import Inputs, business_today, decided_on, delay_cost, overview
from ripple.store.accounts import AccountStore, SessionStore
from ripple.store.records import RecordStore

A = EcnAction
S = EcnState


def run(c: Checker) -> None:
    generated = generate(load_config())
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        write_outputs(generated, root / "synthetic")
        results = _results(root)
        _dates(c, results)
        _dev_excluded(c, root, results)
        _accounts(c, root)
        _api(c, root)


# ---------- 지표 날짜 기준(순수) ----------


def _dates(c: Checker, results: list[AnalysisResult]) -> None:
    c.section("결재·현황: 날짜 기준(실데이터 = 실제 날짜, 합성 = 기준일 + 지난 날수)")
    base = results[0]
    request = base.request.model_copy(update={"as_of": date(2026, 10, 1), "confirm_on": date(2026, 10, 1)})
    moved = base.model_copy(update={"request": request})
    # 기준일만 바꾼 본문(분석 ID 검증을 건너뜀 — 날짜 규칙은 데이터 모드와 기준일만 읽는다)
    real = RecordBody.model_construct(**{**dict(_body(base, mode=DataMode.REAL)), "result": moved})
    synthetic = RecordBody.model_construct(**{**dict(_body(base)), "result": moved})
    recorded = datetime(2026, 10, 10, 1, 0, tzinfo=UTC)  # KST 10-10
    decided = datetime(2026, 10, 12, 1, 0, tzinfo=UTC)  # KST 10-12
    c.check(
        "결정 날짜: 실데이터는 실제 KST 날짜(10-12), 합성은 기준일 + 기록 뒤 2일(10-03) — 재검토 반례",
        decided_on(real, decided, recorded) == date(2026, 10, 12)
        and decided_on(synthetic, decided, recorded) == date(2026, 10, 3),
    )
    c.check(
        "업무상 오늘: 실데이터 = KST 오늘, 합성 = 분석 기준일(업무 화면 D-n과 같은 기준)",
        business_today(real, date(2026, 10, 12)) == date(2026, 10, 12)
        and business_today(synthetic, date(2026, 10, 12)) == date(2026, 10, 1),
    )
    c.check(
        "실시간 시연 세계면 합성 기록도 KST 오늘·실제 결정 날짜로 센다",
        business_today(synthetic, date(2026, 10, 12), live=True) == date(2026, 10, 12)
        and decided_on(synthetic, decided, recorded, live=True) == date(2026, 10, 12),
    )
    by_date = next((r for r in results if r.timing.deadline.kind is DeadlineKind.BY_DATE), None)
    none = base.model_copy(
        update={
            "timing": base.timing.model_copy(
                update={
                    "deadline": ZeroLossDeadline(
                        kind=DeadlineKind.NONE_IN_HORIZON, last_day=base.timing.curve[-1].confirm_on
                    )
                }
            )
        }
    )
    late = delay_cost(by_date) if by_date is not None else None
    expected = (
        next(p for p in by_date.timing.curve if p.confirm_on == by_date.timing.deadline.last_day + timedelta(days=1))
        if by_date is not None
        else None
    )
    c.check(
        "미루면 = 마감 다음 날 곡선 값(대표), 기간 안 손실이 없으면 계산하지 않음(None)",
        by_date is not None
        and late is not None
        and expected is not None
        and late == (expected.additional_loss.value, expected.confirm_on)
        and delay_cost(none) is None,
    )


def _dev_excluded(c: Checker, root: Path, results: list[AnalysisResult]) -> None:
    c.section("결재·현황: 개발 모드 요청·결정은 성과·담당자 집계에서 뺌")
    store = RecordStore(root / "metrics-dev")
    store.start()
    dev = _who("dev", approve=True, admin=True, dev=True)
    member = _who("kim")
    lead = _who("lead", record_=False, approve=True, admin=True)
    snapshot = results[0].versions.snapshot_id
    _save(store, _body(results[0], ecn="ECN-M-0001"), dev, 0)
    _do(store, "ECN-M-0001", A.REQUEST_REVIEW, dev, snapshot=snapshot, login=False)
    _do_line(store, "ECN-M-0001", dev, snapshot=snapshot, login=False)
    _save(store, _body(results[1], ecn="ECN-M-0002"), member, 0)
    _do(store, "ECN-M-0002", A.REQUEST_REVIEW, member, snapshot=snapshot)
    _do_line(store, "ECN-M-0002", lead, snapshot=snapshot)
    _save(store, _body(results[2], ecn="ECN-M-0003"), member, 0)
    _do(store, "ECN-M-0003", A.REQUEST_REVIEW, member, snapshot=snapshot)
    items, audit, bodies = store.overview_inputs(include_real=True)
    now = max(e.at for e in audit) + timedelta(hours=1)
    found = overview(Inputs(items=items, audit=audit, bodies=bodies, now=now, days=None))
    people = {p.actor.login_id: p for p in found.performance.people}
    states = {s.state: s.count for s in found.states}
    c.check(
        "성과: 업무 승인 1건만(개발 모드 승인 제외), 담당자별에 개발 모드 없음, 상태 건수에는 둘 다",
        found.performance.approved == 1
        and found.performance.decided == 1
        and "dev" not in people
        and people["kim"].recorded == 2
        and people["kim"].requested == 2
        and states[S.APPROVED] == 2,
        (found.performance, states),
    )
    inbox = found.inbox
    c.check(
        "결재함: 검토 중 1건, 기다린 시간·미루면(또는 기간 끝)이 붙음",
        len(inbox) == 1
        and inbox[0].ecn_id == "ECN-M-0003"
        and inbox[0].waiting_hours >= 1
        and (inbox[0].delay_cost is not None or inbox[0].deadline_kind is DeadlineKind.NONE_IN_HORIZON)
        and inbox[0].days_left == (inbox[0].deadline - inbox[0].as_of).days,
        inbox,
    )
    waiting = next(i for i in items if i.status.ecn_id == "ECN-M-0003")

    def urgent_with(kind: DeadlineKind) -> int:
        deadline = ZeroLossDeadline(kind=kind, last_day=waiting.latest.as_of)
        moved = waiting.model_copy(update={"latest": waiting.latest.model_copy(update={"deadline": deadline})})
        swapped = [moved if i is waiting else i for i in items]
        return overview(Inputs(items=swapped, audit=audit, bodies=bodies, now=now, days=None)).kpis.urgent

    urgent = {kind: urgent_with(kind) for kind in (DeadlineKind.BY_DATE, DeadlineKind.NONE_IN_HORIZON)}
    c.check(
        "현황 '마감 3일 이내'는 손실 없음(탐색 기간 끝까지 0)을 세지 않음 — 결재함 거르기와 같게",
        urgent[DeadlineKind.BY_DATE] == 1 and urgent[DeadlineKind.NONE_IN_HORIZON] == 0,
        urgent,
    )
    _steps(c, store, results, member, lead)


def _steps(c: Checker, store: RecordStore, results: list[AnalysisResult], member: Any, lead: Any) -> None:
    c.section("결재·현황: 결재선 — 결재함은 보는 사람의 단계 건만 · 앞 단계 승인 · 단계별 처리 시간")
    snapshot = results[0].versions.snapshot_id
    _save(store, _body(results[3], ecn="ECN-M-0004"), member, 0)
    _do(store, "ECN-M-0004", A.REQUEST_REVIEW, member, snapshot=snapshot)
    _do(store, "ECN-M-0004", A.APPROVE, PART_WHO, snapshot=snapshot)  # 파트장 승인 → 팀장 단계
    items, audit, bodies = store.overview_inputs(include_real=True)
    now = max(e.at for e in audit) + timedelta(hours=2)

    def inbox(steps: frozenset[ApprovalStep] | None) -> list[str]:
        found = overview(Inputs(items=items, audit=audit, bodies=bodies, now=now, days=None, steps=steps))
        return [i.ecn_id for i in found.inbox]

    found = overview(Inputs(items=items, audit=audit, bodies=bodies, now=now, days=None))
    row = next(i for i in found.inbox if i.ecn_id == "ECN-M-0004")
    c.check(
        "파트장 결재함 = 파트장 단계 건(M-0003) · 팀장 결재함 = 팀장 단계 건(M-0004) · 본부장 = 없음 · "
        "모두(None) = 둘 다",
        inbox(frozenset({ApprovalStep.PART_LEAD})) == ["ECN-M-0003"]
        and inbox(frozenset({ApprovalStep.TEAM_LEAD})) == ["ECN-M-0004"]
        and inbox(frozenset({ApprovalStep.EXECUTIVE})) == []
        and sorted(inbox(None)) == ["ECN-M-0003", "ECN-M-0004"],
    )
    c.check(
        "결재함 줄: 지금 단계·결재선·앞 단계 승인(파트장, 전결 아님)·남은 결재 2단계 계획",
        row.step is ApprovalStep.TEAM_LEAD
        and row.steps == (ApprovalStep.PART_LEAD, ApprovalStep.TEAM_LEAD, ApprovalStep.EXECUTIVE)
        and [(s.step, s.actor.login_id, s.proxy) for s in row.signed] == [(ApprovalStep.PART_LEAD, "part", False)]
        and row.approval_plan is not None
        and row.approval_plan.steps == (ApprovalStep.TEAM_LEAD, ApprovalStep.EXECUTIVE)
        and row.approval_plan.workdays == 4,
        row,
    )
    lead_view = overview(
        Inputs(
            items=items,
            audit=audit,
            bodies=bodies,
            now=now,
            days=None,
            steps=frozenset({ApprovalStep.TEAM_LEAD}),
            proxy_steps=frozenset({ApprovalStep.PART_LEAD, ApprovalStep.EXECUTIVE}),
        )
    )
    part_view = overview(
        Inputs(items=items, audit=audit, bodies=bodies, now=now, days=None, steps=frozenset({ApprovalStep.PART_LEAD}))
    )
    c.check(
        "팀장 결재함 = 팀장 단계 건, 전결 묶음 = 파트장·본부장 단계 건(M-0003) · 파트장은 전결 묶음 없음 · "
        "지금 단계가 시작된 때 = 앞 단계 승인 시각(없으면 검토 요청)",
        [i.ecn_id for i in lead_view.inbox] == ["ECN-M-0004"]
        and [i.ecn_id for i in lead_view.proxy] == ["ECN-M-0003"]
        and lead_view.proxy[0].step is ApprovalStep.PART_LEAD
        and part_view.proxy == ()
        and row.step_since == row.signed[-1].at
        and lead_view.proxy[0].step_since == lead_view.proxy[0].requested_at,
        ([i.ecn_id for i in lead_view.proxy], row.step_since),
    )
    perf = found.performance
    steps = {s.step: s for s in perf.steps}
    c.check(
        "성과: 결정 수는 마지막 단계 승인만(M-0002 하나), 단계별 처리 시간은 파트장·팀장·본부장 모두",
        perf.approved == 1
        and perf.decided == 1
        and set(steps) == set(ApprovalStep)
        and steps[ApprovalStep.PART_LEAD].decisions == 2  # M-0002(팀장 전결) + M-0004(파트장)
        and all(s.median_hours is not None for s in steps.values()),
        perf.steps,
    )


# ---------- 계정(역할 통일, 계약 1.25.0) ----------


def _accounts(c: Checker, root: Path) -> None:
    c.section("계정: 팀장(관리자) 한 역할 — 옛 결재 단계 칸은 읽을 때 버림")
    folder = root / "accounts-v3"
    folder.mkdir()
    old = {
        "version": 3,
        "accounts": [
            {
                "login_id": login,
                "name": name,
                "role": "admin",
                "password_hash": "x",
                "created_at": "2026-10-01T00:00:00Z",
                "approval_level": level,
            }
            for login, name, level in (("boss", "옛 부장", 2), ("lead2", "옛 팀장", 1))
        ],
    }
    (folder / "accounts.json").write_text(json.dumps(old), encoding="utf-8")
    store = AccountStore(folder)
    store.load()
    service = AuthService(store, SessionStore(folder))
    lead2 = Principal(login_id="lead2", name="옛 팀장", role=Role.ADMIN)
    reset = service.reset_password(lead2, "boss")  # 1.24.0에서는 결재 단계 2만 할 수 있던 일
    renamed = service.update_account(lead2, "boss", AccountUpdate(name="팀장"))
    written = json.loads((folder / "accounts.json").read_text(encoding="utf-8"))
    c.check(
        "판 3 파일(결재 단계 칸 있음)을 읽고, 팀장끼리 비밀번호 초기화·이름 바꾸기가 되며, "
        "다시 쓴 파일은 판 3 그대로 그 칸이 없음",
        bool(reset.temporary_password)
        and renamed.name == "팀장"
        and written["version"] == 3
        and all("approval_level" not in account for account in written["accounts"]),
        written,
    )
    me_lead = lead2.me()
    me_dev = DEV_PRINCIPAL.me()
    c.check(
        "팀장 Me: 기록 권한 없음 · 승인 권한 · 결재 단계 칸 없음, 개발 모드는 모든 권한",
        Permission.RECORD not in me_lead.permissions
        and Permission.APPROVE in me_lead.permissions
        and "approval_level" not in me_lead.model_dump()
        and Permission.RECORD in me_dev.permissions,
    )


# ---------- API ----------


def _sample_over(client: TestClient, won: int) -> int:
    """총변경비용 대표값이 won 이상인 샘플 번호(1.24.0에서 부장 결재 대상이던 금액 — 분석해서 찾음)."""
    samples = client.get("/api/samples")
    token = samples.headers["X-Ripple-Workspace"]
    for index, sample in enumerate(samples.json()):
        result = client.post("/api/analyses", json=sample["request"], headers={"X-Ripple-Workspace": token}).json()
        if result["total"]["value"] >= won:
            return index
    raise AssertionError(f"총변경비용 {won:,}원 이상 샘플이 없어요")


def _api(c: Checker, root: Path) -> None:
    c.section("결재·현황 API: 역할 분리 · 금액과 무관한 팀장 승인 · 결재함·성과")
    app = _app(root, "api-manage")
    with _client(app):
        lead = _client(app)
        _login(lead, "lead", FIRST)
        lead.post("/api/auth/password", json={"current_password": FIRST, "new_password": ADMIN_PW})
        kim = _staff(app, lead, "kim", "member", MEMBER_PW)
        tl = _client(app)
        made = lead.post("/api/accounts", json={"login_id": "teamlead", "name": "팀장", "role": "admin"})
        temporary = made.json()["temporary_password"]
        _login(tl, "teamlead", temporary)
        tl.post("/api/auth/password", json={"current_password": temporary, "new_password": SECOND_PW})
        me = lead.get("/api/auth/me").json()
        leveled_body = {"login_id": "boss9", "name": "b", "role": "admin", "approval_level": 2}
        leveled = lead.post("/api/accounts", json=leveled_body)
        c.check(
            "팀장 내 정보: 기록 권한 없음 · 승인 권한 · 결재 단계 칸 없음, 결재 단계를 보내면 422(계약에서 뺌)",
            "record" not in me["permissions"]
            and "approve" in me["permissions"]
            and "approval_level" not in me
            and leveled.status_code == 422,
            (me, leveled.status_code),
        )
        big = _sample_over(kim, 10_000_000)
        request, result, token = _analysis(kim, big)
        ecn = request["change"]["ecn_id"]
        _record(kim, request, result["analysis_id"], token, 0)
        _action(kim, ecn, "request_review", token)
        detail = lead.get(f"/api/ecns/{ecn}").json()
        approved = _approve_line(tl, ecn, token, reason="팀장 승인")  # 파트장·본부장 단계는 팀장 전결
        started_by_admin = _action(lead, ecn, "start", token)
        c.check(
            "1,000만원 이상 설계변경도 새로 만든 팀장이 승인 200(결재 단계 없음), 상세에 결재 단계 칸 없음, "
            "팀장의 실행 시작은 403",
            "approval_need" not in detail and approved.status_code == 200 and started_by_admin.status_code == 403,
            (approved.json(), started_by_admin.status_code),
        )
        small = next(i for i in range(8) if i != big)
        request2, result2, token = _analysis(kim, small)
        ecn2 = request2["change"]["ecn_id"]
        _record(kim, request2, result2["analysis_id"], token, 0)
        _action(kim, ecn2, "request_review", token)
        team_ok = _approve_line(lead, ecn2, token, reason="팀장 승인")
        c.check("다른 팀장도 승인 200", team_ok.status_code == 200, team_ok.json())
        pending = next(i for i in range(8) if i not in (big, small))
        request3, result3, token = _analysis(kim, pending)
        ecn3 = request3["change"]["ecn_id"]
        _record(kim, request3, result3["analysis_id"], token, 0)
        _action(kim, ecn3, "request_review", token)
        part = _staff(app, lead, "part", "part_lead", PART_PW)
        part_view = part.get("/api/manage/overview").json()
        part_inbox = [i["ecn_id"] for i in part_view["inbox"]]
        lead_view = lead.get("/api/manage/overview").json()
        lead_inbox = [i["ecn_id"] for i in lead_view["inbox"]]
        lead_proxy = [(i["ecn_id"], i["step"]) for i in lead_view["proxy"]]
        _action(part, ecn3, "approve", token, reason="파트장 확인")
        overview_ = lead.get("/api/manage/overview", params={"days": 30})
        body = overview_.json()
        people = {p["actor"]["login_id"]: p for p in body["performance"]["people"]}
        whole = lead.get("/api/manage/overview").json()["performance"]
        c.check(
            "결재함은 내 단계 건만: 검토 요청 직후 파트장 결재함 = [그 건] · 팀장 결재함 = []·전결 묶음 = [그 건] → "
            "파트장 승인 뒤 팀장 결재함",
            part_inbox == [ecn3]
            and lead_inbox == []
            and lead_proxy == [(ecn3, "part_lead")]
            and part_view["proxy"] == []
            and body["inbox"][0]["signed"][0]["step"] == "part_lead"
            and body["proxy"] == [],
            (part_inbox, lead_inbox, lead_proxy),
        )
        c.check(
            "결재·현황: 팀장 200(결재함 1건 · 승인 2건 · 담당자 kim 기록 3·요청 3), 기간을 비우면 전체, "
            "담당자·체험은 403",
            overview_.status_code == 200
            and [i["ecn_id"] for i in body["inbox"]] == [ecn3]
            and body["performance"]["approved"] == 2
            and body["performance"]["days"] == 30
            and whole["days"] is None
            and whole["approved"] == 2
            and people["kim"]["recorded"] == 3
            and people["kim"]["requested"] == 3
            and "rule" not in body
            and kim.get("/api/manage/overview").status_code == 403,
            (body.get("performance"), whole.get("days")),
        )
        demo = _client(app)
        demo.post("/api/auth/demo")
        c.check("체험은 결재·현황 403", demo.get("/api/manage/overview").status_code == 403)
        _outcomes(c, lead=lead, kim=kim, executed=ecn, approved_only=ecn2, token=token, predicted=result["total"])


def _outcomes(
    c: Checker,
    *,
    lead: TestClient,
    kim: TestClient,
    executed: str,
    approved_only: str,
    token: str,
    predicted: dict[str, int],
) -> None:
    c.section("실적: 실행한 설계변경의 실제 비용·지연 → 예측 대비(결재·현황)")
    started = _action(kim, executed, "start", token)
    not_yet = kim.put(f"/api/ecns/{approved_only}/outcome", json={"cost_krw": 100})
    by_admin = lead.put(f"/api/ecns/{executed}/outcome", json={"cost_krw": 100})
    missing = kim.get(f"/api/ecns/{executed}/outcome")
    actual = predicted["value"] + predicted["value"] // 10  # 예측보다 10% 많이
    first = kim.put(f"/api/ecns/{executed}/outcome", json={"cost_krw": 1, "exit_delay_days": 3, "note": "처음 값"})
    fixed = kim.put(
        f"/api/ecns/{executed}/outcome", json={"cost_krw": actual, "exit_delay_days": 9, "note": " 고친 값 "}
    )
    got = kim.get(f"/api/ecns/{executed}/outcome").json()
    c.check(
        "실행 전은 409, 관리자는 403, 없으면 404, 담당자가 넣고 고치면 마지막 값(앞뒤 공백 정리)",
        started.status_code == 200
        and not_yet.status_code == 409
        and by_admin.status_code == 403
        and missing.status_code == 404
        and first.status_code == 200
        and fixed.status_code == 200
        and got["cost_krw"] == actual
        and got["exit_delay_days"] == 9
        and got["note"] == "고친 값"
        and got["entered_by"]["login_id"] == "kim",
        (started.status_code, not_yet.status_code, by_admin.status_code, missing.status_code, got),
    )
    rows = lead.get("/api/manage/overview").json()["outcomes"]
    row = rows["rows"][0] if rows["rows"] else {}
    c.check(
        "결재·현황 실적: 승인한 개정의 예측 대비 오차율(+10%)·범위 안 여부·출구 지연",
        rows["count"] == 1
        and row.get("ecn_id") == executed
        and abs(row.get("error_rate", 0) - (actual - predicted["value"]) / predicted["value"]) < 1e-3
        and row.get("in_range") == (predicted["low"] <= actual <= predicted["high"])
        and row.get("actual_delay_days") == 9
        and rows["median_abs_error"] is not None,
        rows,
    )
