"""기록·승인 흐름의 성질(docs/records.md).

순수 상태 기계(독립 정답표와 대조) · 감사 사슬(변조·삭제·순서·끝 줄) · 저장소(재시도·끼어들기·되돌림·
본문 변조·동시 요청·형식 판·재시작) · API(역할·자기 결정·확인 목록·지도 대조·전환 잠금·체험 범위·감사 확인).
지도·데이터 폴더는 임시 폴더에 만든다.
"""

from __future__ import annotations

import itertools
import json
import random
import sqlite3
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from harness import Checker

from ripple.api.app import create_app
from ripple.api.records import checklist_of
from ripple.config.settings import Settings
from ripple.contracts.assistant import NotificationTarget
from ripple.contracts.auth import Role
from ripple.contracts.change import ChangeCause, ChangeIntent
from ripple.contracts.domain import DataMode, GraphSnapshot
from ripple.contracts.identity import snapshot_id
from ripple.contracts.ingest import ImportIssue, ImportSummary, IssueCode, IssueSeverity
from ripple.contracts.records import (
    ActionRequest,
    Actor,
    ApprovalStep,
    AuditDetail,
    AuditEntry,
    ChecklistItem,
    EcnAction,
    EcnState,
    EcnStatus,
    NoticeLog,
    NoticeStep,
    RecordBody,
    RecordSaved,
)
from ripple.contracts.result import (
    AnalysisResult,
    DeadlineKind,
    Determinacy,
    Unresolved,
    UnresolvedKind,
    VerdictLevel,
)
from ripple.contracts.workspace import SnapshotInfo
from ripple.generator.build import generate
from ripple.generator.io import load_config, write_outputs
from ripple.records import chain
from ripple.records.approval import (
    APPROVAL_LINE,
    DAYS_PER_STEP_LOW,
    approval_plan,
    no_cost,
    plus_workdays,
    submit_by_of,
)
from ripple.records.flow import Ask, FlowError, Projection, Who, act, record, replay
from ripple.store.records import (
    FILE_NAME,
    FORMAT_VERSION,
    SCHEMA,
    RecordStore,
    RecordStoreError,
    record_id_of,
    summary_of,
)
from ripple.store.reset import archive_records, done_scope

BASE = "https://testserver"
FIRST = "first-pass-2026"
ADMIN_PW = "lead-pass-2026-x"
SECOND_PW = "park-pass-2026-x"
MEMBER_PW = "kim-pass-2026-x"
ADMIN_ENV = {"RIPPLE_ADMIN_ID": "lead", "RIPPLE_ADMIN_PASSWORD": FIRST}

S = EcnState
A = EcnAction
# 독립 정답표(계획 v2 4절): (지금 상태, 행동) → 다음 상태. 코드의 TRANSITIONS를 보지 않고 적는다.
EXPECTED: dict[tuple[EcnState, EcnAction], EcnState] = {
    (S.ANALYZED, A.REQUEST_REVIEW): S.IN_REVIEW,
    (S.IN_REVIEW, A.WITHDRAW): S.ANALYZED,
    (S.IN_REVIEW, A.APPROVE): S.APPROVED,
    (S.ON_HOLD, A.APPROVE): S.APPROVED,
    (S.IN_REVIEW, A.REJECT): S.REJECTED,
    (S.ON_HOLD, A.REJECT): S.REJECTED,
    (S.IN_REVIEW, A.HOLD): S.ON_HOLD,
    (S.APPROVED, A.START): S.IN_PROGRESS,
    (S.IN_PROGRESS, A.CLOSE): S.CLOSED,
    (S.ANALYZED, A.SETTLE): S.APPROVED,  # 무비용 담당자 처리(무비용 개정만)
}
# 결재선 정답표(docs/records.md(기록·결재) 14절): (지금 단계, 행동) → (다음 상태, 다음 단계). 세 단계 결재선 기준.
LINE_EXPECTED: dict[tuple[int, EcnAction], tuple[EcnState, int | None]] = {
    (1, A.APPROVE): (S.IN_REVIEW, 2),
    (2, A.APPROVE): (S.IN_REVIEW, 3),
    (3, A.APPROVE): (S.APPROVED, None),
    (1, A.REJECT): (S.REJECTED, None),
    (2, A.REJECT): (S.REJECTED, None),
    (3, A.REJECT): (S.REJECTED, None),
    (1, A.HOLD): (S.ON_HOLD, 1),
    (2, A.HOLD): (S.ON_HOLD, 2),
    (3, A.HOLD): (S.ON_HOLD, 3),
}
STORED_STATES = [s for s in EcnState if s is not S.REQUESTED]
ACTS = [a for a in EcnAction if a not in (A.RECORD, A.NOTICE)]  # 기록 저장·통보 기록은 따로(행동 API 밖)
DECIDE = {A.APPROVE, A.REJECT, A.HOLD}


def run(c: Checker) -> None:
    _flow_table(c)
    _flow_rules(c)
    _flow_line(c)
    _flow_replay(c)
    _submit_rule(c)
    _plan_low(c)
    _chain(c)
    generated = generate(load_config())
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        write_outputs(generated, root / "synthetic")
        results = _results(root)
        _store(c, root, results)
        _store_tamper(c, root, results)
        _store_read(c, root, results)
        _store_race(c, root, results)
        _store_format(c, root)
        _store_notice(c, root, results)
        _checklist(c, results, generated.snapshot)
        _api(c, root, generated.snapshot)
        _api_line(c, root, generated)
        _api_dev(c, root)
        _api_real(c, root, generated.snapshot)
        _api_version(c, root)
        _reset(c, root)


# ---------- 순수 상태 기계 ----------


ST = ApprovalStep
LINE = (ST.PART_LEAD, ST.TEAM_LEAD, ST.EXECUTIVE)  # 정답표의 결재선(코드의 APPROVAL_LINE을 보지 않고 적음)


def _who(
    name: str = "kim",
    *,
    record_: bool = True,
    approve: bool = False,
    admin: bool = False,
    dev: bool = False,
    step: ApprovalStep | None = None,
) -> Who:
    """approve = 팀장(팀장 단계 + 파트장·본부장 전결), step = 그 단계만 결정하는 결재자(파트장·본부장),
    개발 모드 = 모든 단계."""
    if dev and (approve or step):
        steps, proxy = frozenset(ST), frozenset[ApprovalStep]()
    elif step is not None:
        steps, proxy = frozenset({step}), frozenset()
    elif approve:
        steps, proxy = frozenset({ST.TEAM_LEAD}), frozenset({ST.PART_LEAD, ST.EXECUTIVE})
    else:
        steps, proxy = frozenset(), frozenset()
    return Who(login_id=name, can_record=record_, steps=steps, proxy=proxy, admin=admin, dev=dev)


ADMIN_WHO = _who("lead", approve=True, admin=True)
OTHER_ADMIN = _who("park", approve=True, admin=True)
MEMBER_WHO = _who("kim")
NOBODY = _who("guest", record_=False)
PART_WHO = _who("part", record_=False, step=ST.PART_LEAD)
EXEC_WHO = _who("boss", record_=False, step=ST.EXECUTIVE)


def _proj(state: EcnState, **kw: Any) -> Projection:
    """정답표용 투영: 검토·보류면 옛 판처럼 팀장 한 단계(1/1단계) 검토."""
    reviewing = state in (S.IN_REVIEW, S.ON_HOLD)
    approved = state in (S.APPROVED, S.IN_PROGRESS, S.CLOSED)
    base = Projection(
        state=state,
        version=5,
        revision=2,
        record_id="R-00000000000000aa",
        review_seq=7 if reviewing else None,
        review_revision=2 if reviewing else None,
        review_by="kim" if reviewing else None,
        approved_revision=2 if approved else None,
        review_steps=(ST.TEAM_LEAD,) if reviewing else (),
        review_step=1 if reviewing else None,
    )
    return replace(base, **kw)


def _line_proj(state: EcnState, step: int) -> Projection:
    """결재선 세 단계 검토의 step단계 투영."""
    return _proj(state, review_steps=LINE, review_step=step)


def _ask(action: EcnAction, p: Projection, **kw: Any) -> Ask:
    base = Ask(
        action=action,
        expected_version=p.version,
        revision=p.revision,
        record_id=p.record_id,
        review_seq=p.review_seq if action in DECIDE or action is A.WITHDRAW else None,
        reason="사유" if action in DECIDE else None,
    )
    return replace(base, **kw)


def _try(fn: Any, *args: Any, **kwargs: Any) -> tuple[str, Any]:
    """fn(*args, **kwargs)를 불러 ('ok', 결과) 또는 (거절 코드, FlowError)."""
    try:
        return "ok", fn(*args, **kwargs)
    except FlowError as error:
        return error.code, error


def _flow_table(c: Checker) -> None:
    c.section("기록: 상태 기계 전이표(상태 × 행동, 정답표와 대조)")
    wrong: list[str] = []
    for state, action in itertools.product(STORED_STATES, ACTS):
        p = _proj(state)
        who = OTHER_ADMIN if action in DECIDE else ADMIN_WHO
        code, out = _try(
            act,
            p,
            _ask(action, p),
            who,
            checklist=frozenset(),
            same_map=True,
            same_version=True,
            login_mode=True,
            seq=9,
            no_cost=True,
        )
        expected = EXPECTED.get((state, action))
        if expected is None:
            if code != "invalid_transition":
                wrong.append(f"{state}+{action}: 거절이어야 하는데 {code}")
        elif code != "ok" or out.projection.state is not expected or out.projection.version != p.version + 1:
            wrong.append(f"{state}+{action}: {code}")
    c.check("허용 조합만 다음 상태로(버전 +1), 나머지는 invalid_transition", not wrong, wrong[:6])
    locked = [_try(record, _proj(s), 3, "R-00000000000000bb", MEMBER_WHO)[0] for s in (S.IN_PROGRESS, S.CLOSED)]
    others = [
        _try(record, _proj(s), 3, "R-00000000000000bb", MEMBER_WHO)
        for s in (S.ANALYZED, S.IN_REVIEW, S.ON_HOLD, S.REJECTED, S.APPROVED)
    ]
    c.check(
        "새 개정: 실행·종료는 locked, 나머지는 분석으로(진행 중 검토는 대체됨으로 남김)",
        locked == ["locked", "locked"]
        and all(code == "ok" and out.projection.state is S.ANALYZED for code, out in others)
        and others[1][1].detail.superseded_review_seq == 7
        and others[1][1].projection.review_seq is None,
    )
    first = record(None, 1, "R-00000000000000bb", MEMBER_WHO)
    c.check(
        "첫 기록: 요청 → 분석, 버전 1·개정 1. 개정 번호가 이어지지 않으면 ecn_changed, 기록 권한 없으면 forbidden",
        first.projection.version == 1
        and first.detail.from_state is S.REQUESTED
        and _try(record, None, 2, "R-00000000000000bb", MEMBER_WHO)[0] == "ecn_changed"
        and _try(record, None, 1, "R-00000000000000bb", NOBODY)[0] == "forbidden",
    )


def _flow_rules(c: Checker) -> None:
    c.section("기록: 상태 기계 규칙(기대값·권한·자기 결정·사유·확인 목록·지도·개발 모드)")
    review = _proj(S.IN_REVIEW)

    def go(p: Projection, ask: Ask, who: Who, **kw: Any) -> tuple[str, Any]:
        args = {"checklist": frozenset(), "same_map": True, "same_version": True, "login_mode": True, "seq": 9, **kw}
        return _try(act, p, ask, who, **args)

    stale = [
        go(review, _ask(A.APPROVE, review, expected_version=4), OTHER_ADMIN)[0],
        go(review, _ask(A.APPROVE, review, revision=1), OTHER_ADMIN)[0],
        go(review, _ask(A.APPROVE, review, record_id="R-00000000000000cc"), OTHER_ADMIN)[0],
        go(review, _ask(A.APPROVE, review, review_seq=6), OTHER_ADMIN)[0],
        go(review, _ask(A.WITHDRAW, review, review_seq=None), MEMBER_WHO)[0],
    ]
    c.check("기대 버전·개정·기록·검토 순번이 다르면 ecn_changed", stale == ["ecn_changed"] * 5, stale)
    c.check(
        "결정은 관리자만(담당자 forbidden), 요청자 본인의 결정은 self_decision(로그인 모드)",
        go(review, _ask(A.APPROVE, review), MEMBER_WHO)[0] == "forbidden"
        and go(review, _ask(A.APPROVE, review), _who("kim", approve=True, admin=True))[0] == "self_decision"
        and go(review, _ask(A.REJECT, review), _who("kim", approve=True, admin=True))[0] == "self_decision",
    )
    dev_self = go(review, _ask(A.APPROVE, review), _who("kim", approve=True, admin=True, dev=True), login_mode=False)
    c.check(
        "개발 모드에서는 자기 결정을 받되 감사 세부에 self_decision·승인 개발 모드 표시",
        dev_self[0] == "ok" and dev_self[1].detail.self_decision and dev_self[1].projection.approval_dev,
    )
    c.check(
        "검토 취소는 요청자·관리자만, 다른 담당자는 forbidden",
        go(review, _ask(A.WITHDRAW, review), MEMBER_WHO)[0] == "ok"
        and go(review, _ask(A.WITHDRAW, review), ADMIN_WHO)[0] == "ok"
        and go(review, _ask(A.WITHDRAW, review), _who("lee"))[0] == "forbidden",
    )
    c.check(
        "반려·보류는 사유 필수(reason_required)",
        go(review, _ask(A.REJECT, review, reason=None), OTHER_ADMIN)[0] == "reason_required"
        and go(review, _ask(A.HOLD, review, reason=None), OTHER_ADMIN)[0] == "reason_required",
    )
    items = frozenset({"analysis:1:delivery", "import:1:missing_sheet"})
    partial = go(
        review, _ask(A.APPROVE, review, acknowledged=frozenset({"analysis:1:delivery"})), OTHER_ADMIN, checklist=items
    )
    no_reason = go(review, _ask(A.APPROVE, review, acknowledged=items, reason=None), OTHER_ADMIN, checklist=items)
    full = go(review, _ask(A.APPROVE, review, acknowledged=items), OTHER_ADMIN, checklist=items)
    c.check(
        "확인 목록이 있으면 전부 체크 + 사유, 승인 감사 세부에 체크한 키(정렬)",
        partial[0] == "checklist_required"
        and no_reason[0] == "reason_required"
        and full[0] == "ok"
        and full[1].detail.acknowledged == tuple(sorted(items))
        and go(review, _ask(A.REJECT, review, acknowledged=items), OTHER_ADMIN, checklist=items)[0]
        == "invalid_transition",
    )
    c.check(
        "확인 목록에 없는 체크를 보내면 거절(목록이 비어도)",
        go(review, _ask(A.APPROVE, review, acknowledged=items), OTHER_ADMIN)[0] == "checklist_required",
    )
    analyzed = _proj(S.ANALYZED)
    approved = _proj(S.APPROVED)
    c.check(
        "지도: 검토 요청·승인은 같은 지도만(map_changed), 실행 시작은 허용하되 other_map 표시",
        go(analyzed, _ask(A.REQUEST_REVIEW, analyzed), MEMBER_WHO, same_map=False)[0] == "map_changed"
        and go(review, _ask(A.APPROVE, review), OTHER_ADMIN, same_map=False)[0] == "map_changed"
        and go(approved, _ask(A.START, approved), MEMBER_WHO, same_map=False)[1].detail.other_map,
    )
    held_old = _proj(S.ON_HOLD)
    dev_old = _proj(S.APPROVED, approval_dev=True)
    old = {"same_version": False}
    c.check(
        "계산 판: 검토 요청·승인(보류 뒤·개발 승인 다시 받기 포함)은 지금 판만(version_changed)",
        go(analyzed, _ask(A.REQUEST_REVIEW, analyzed), MEMBER_WHO, **old)[0] == "version_changed"
        and go(review, _ask(A.APPROVE, review), OTHER_ADMIN, **old)[0] == "version_changed"
        and go(held_old, _ask(A.APPROVE, held_old), OTHER_ADMIN, **old)[0] == "version_changed"
        and go(dev_old, _ask(A.REQUEST_REVIEW, dev_old), MEMBER_WHO, **old)[0] == "version_changed",
    )

    def flag(outcome: tuple[str, Any]) -> bool | None:
        """받았으면 감사 세부의 other_version, 거절이면 None(거절 코드는 다른 검사가 본다)."""
        code, out = outcome
        return bool(out.detail.other_version) if code == "ok" else None

    flags = [
        flag(go(review, _ask(A.REJECT, review), OTHER_ADMIN, **old)),
        flag(go(review, _ask(A.HOLD, review), OTHER_ADMIN, **old)),
        flag(go(held_old, _ask(A.REJECT, held_old), OTHER_ADMIN, **old)),
        flag(go(review, _ask(A.WITHDRAW, review), MEMBER_WHO, **old)),
        flag(go(approved, _ask(A.START, approved), MEMBER_WHO, **old)),
        flag(go(review, _ask(A.REJECT, review), OTHER_ADMIN)),
    ]
    c.check(
        "계산 판: 반려·보류는 받고 other_version 표시, 취소·실행·같은 판 결정은 표시 없음, 둘 다 다르면 map_changed",
        flags == [True, True, True, False, False, False]
        and go(review, _ask(A.APPROVE, review), OTHER_ADMIN, same_map=False, same_version=False)[0] == "map_changed",
    )
    dev_approved = _proj(S.APPROVED, approval_dev=True)
    rereview = go(dev_approved, _ask(A.REQUEST_REVIEW, dev_approved), MEMBER_WHO, seq=12)
    c.check(
        "개발 모드 승인: 로그인 모드 실행 dev_approval, 다시 검토 요청 → 검토(승인 지움), 개발 모드에서는 실행 가능",
        go(dev_approved, _ask(A.START, dev_approved), MEMBER_WHO)[0] == "dev_approval"
        and rereview[0] == "ok"
        and rereview[1].projection.state is S.IN_REVIEW
        and rereview[1].projection.approved_revision is None
        and rereview[1].projection.review_seq == 12
        and go(dev_approved, _ask(A.START, dev_approved), MEMBER_WHO, login_mode=False)[0] == "ok"
        and go(approved, _ask(A.REQUEST_REVIEW, approved), MEMBER_WHO)[0] == "invalid_transition",
    )
    held = go(review, _ask(A.HOLD, review), OTHER_ADMIN)[1].projection
    c.check(
        "보류는 같은 검토를 이어 감(순번·요청자 그대로) → 그 순번으로 승인",
        held.review_seq == 7
        and held.review_by == "kim"
        and go(held, _ask(A.APPROVE, held), OTHER_ADMIN)[1].projection.state is S.APPROVED,
    )
    in_progress = _proj(S.IN_PROGRESS)
    nobody = [
        go(analyzed, _ask(A.REQUEST_REVIEW, analyzed), NOBODY)[0],
        go(approved, _ask(A.START, approved), NOBODY)[0],
        go(in_progress, _ask(A.CLOSE, in_progress), NOBODY)[0],
    ]
    c.check("기록 권한이 없으면 검토 요청·실행 시작·종료도 forbidden", nobody == ["forbidden"] * 3, nobody)


def _flow_line(c: Checker) -> None:
    c.section("기록: 결재선(파트장 → 팀장 → 본부장) · 팀장 전결 · 무비용 담당자 처리(정답표와 대조)")

    def go(p: Projection, ask: Ask, who: Who, **kw: Any) -> tuple[str, Any]:
        args = {"checklist": frozenset(), "same_map": True, "same_version": True, "login_mode": True, "seq": 9, **kw}
        return _try(act, p, ask, who, **args)

    owner = {1: PART_WHO, 2: OTHER_ADMIN, 3: EXEC_WHO}
    wrong: list[str] = []
    for (step, action), (state, nxt) in LINE_EXPECTED.items():
        p = _line_proj(S.IN_REVIEW, step)
        code, out = go(p, _ask(action, p), owner[step])
        got = (out.projection.state, out.projection.review_step) if code == "ok" else code
        if got != (state, nxt) or (code == "ok" and out.projection.version != p.version + 1):
            wrong.append(f"{step}단계 {action}: {got}")
        elif out.detail.step is not LINE[step - 1] or out.detail.proxy:
            wrong.append(f"{step}단계 {action}: 감사 세부 단계 {out.detail.step}·전결 {out.detail.proxy}")
    c.check(
        "단계마다 승인 → 다음 단계(마지막은 승인)·반려 → 끝·보류 → 같은 단계, 감사 세부에 결정한 단계", not wrong, wrong
    )
    ask_p = _proj(S.ANALYZED)
    asked = go(ask_p, _ask(A.REQUEST_REVIEW, ask_p), MEMBER_WHO, line=LINE, seq=12)
    c.check(
        "검토 요청은 결재선을 그 검토에 고정(투영·감사 세부), 1단계부터",
        asked[0] == "ok"
        and asked[1].projection.review_steps == LINE
        and asked[1].projection.review_step == 1
        and asked[1].detail.steps == LINE,
    )
    blocked = {
        "파트장이 2단계": go(_line_proj(S.IN_REVIEW, 2), _ask(A.APPROVE, _line_proj(S.IN_REVIEW, 2)), PART_WHO)[0],
        "본부장이 1단계": go(_line_proj(S.IN_REVIEW, 1), _ask(A.REJECT, _line_proj(S.IN_REVIEW, 1)), EXEC_WHO)[0],
        "본부장이 2단계 보류": go(_line_proj(S.IN_REVIEW, 2), _ask(A.HOLD, _line_proj(S.IN_REVIEW, 2)), EXEC_WHO)[0],
        "담당자": go(_line_proj(S.IN_REVIEW, 1), _ask(A.APPROVE, _line_proj(S.IN_REVIEW, 1)), MEMBER_WHO)[0],
    }
    c.check("자기 단계가 아니면 forbidden(결재 권한이 있어도)", set(blocked.values()) == {"forbidden"}, blocked)
    proxied = {
        step: go(_line_proj(S.IN_REVIEW, step), _ask(A.APPROVE, _line_proj(S.IN_REVIEW, step)), OTHER_ADMIN)
        for step in (1, 3)
    }
    c.check(
        "팀장 전결: 파트장·본부장 단계를 팀장이 결정 — 감사 세부 proxy와 원래 단계, 상태는 그 단계 승인과 같음",
        all(code == "ok" for code, _ in proxied.values())
        and proxied[1][1].detail.proxy
        and proxied[1][1].detail.step is ST.PART_LEAD
        and proxied[1][1].projection.review_step == 2
        and proxied[3][1].detail.step is ST.EXECUTIVE
        and proxied[3][1].projection.state is S.APPROVED,
    )
    self_step = _replace_by(_line_proj(S.IN_REVIEW, 2), "lead")
    c.check(
        "결재선 어느 단계든 요청자 본인은 self_decision(전결로도)",
        go(self_step, _ask(A.APPROVE, self_step), ADMIN_WHO)[0] == "self_decision"
        and go(_replace_by(_line_proj(S.IN_REVIEW, 1), "lead"), _ask(A.HOLD, _line_proj(S.IN_REVIEW, 1)), ADMIN_WHO)[0]
        == "self_decision",
    )
    held = go(_line_proj(S.IN_REVIEW, 2), _ask(A.HOLD, _line_proj(S.IN_REVIEW, 2)), OTHER_ADMIN)[1].projection
    resumed = go(held, _ask(A.APPROVE, held), OTHER_ADMIN)
    items = frozenset({"analysis:1:delivery"})
    mid = _line_proj(S.IN_REVIEW, 1)
    c.check(
        "보류 뒤 승인은 다음 단계로(검토 순번 그대로), 단계마다 확인 목록·계산 판·지도 검사",
        resumed[0] == "ok"
        and resumed[1].projection.state is S.IN_REVIEW
        and resumed[1].projection.review_step == 3
        and resumed[1].projection.review_seq == 7
        and go(mid, _ask(A.APPROVE, mid), PART_WHO, checklist=items)[0] == "checklist_required"
        and go(mid, _ask(A.APPROVE, mid), PART_WHO, same_version=False)[0] == "version_changed"
        and go(mid, _ask(A.APPROVE, mid), PART_WHO, same_map=False)[0] == "map_changed",
    )
    analyzed = _proj(S.ANALYZED)
    settle = _ask(A.SETTLE, analyzed)
    settled = go(analyzed, settle, MEMBER_WHO, no_cost=True)
    c.check(
        "무비용 담당자 처리: 담당자가 분석 → 승인(감사 세부 no_cost, 승인 개정), 추가 비용 개정은 invalid_transition",
        settled[0] == "ok"
        and settled[1].projection.state is S.APPROVED
        and settled[1].projection.approved_revision == analyzed.revision
        and settled[1].detail.no_cost
        and go(analyzed, settle, MEMBER_WHO, no_cost=False)[0] == "invalid_transition",
    )
    c.check(
        "무비용 담당자 처리 규칙: 기록 권한만(팀장 forbidden) · 확인 목록 전부 체크 + 사유 · "
        "지금 지도·판만 · 분석 상태만",
        go(analyzed, settle, _who("lead", record_=False, approve=True, admin=True), no_cost=True)[0] == "forbidden"
        and go(analyzed, settle, MEMBER_WHO, no_cost=True, checklist=items)[0] == "checklist_required"
        and go(analyzed, _ask(A.SETTLE, analyzed, acknowledged=items), MEMBER_WHO, no_cost=True, checklist=items)[0]
        == "reason_required"
        and go(analyzed, settle, MEMBER_WHO, no_cost=True, same_map=False)[0] == "map_changed"
        and go(analyzed, settle, MEMBER_WHO, no_cost=True, same_version=False)[0] == "version_changed"
        and go(_proj(S.REJECTED), _ask(A.SETTLE, _proj(S.REJECTED)), MEMBER_WHO, no_cost=True)[0]
        == "invalid_transition",
    )
    legacy = _proj(S.IN_REVIEW)
    c.check(
        "옛 판 검토(결재선 없음 = 팀장 한 단계): 팀장 승인 한 번에 승인, 파트장은 forbidden",
        go(legacy, _ask(A.APPROVE, legacy), OTHER_ADMIN)[1].projection.state is S.APPROVED
        and go(legacy, _ask(A.APPROVE, legacy), PART_WHO)[0] == "forbidden",
    )


def _replace_by(p: Projection, login_id: str) -> Projection:
    return replace(p, review_by=login_id)


def _entry(seq: int, action: EcnAction, out_detail: AuditDetail, who: Who, revision: int, record_id: str) -> AuditEntry:
    actor = Actor(login_id=who.login_id, name=who.login_id, role=Role.ADMIN if who.admin else Role.MEMBER, dev=who.dev)
    return AuditEntry(
        seq=seq,
        at=datetime(2026, 10, 9, tzinfo=UTC) + timedelta(minutes=seq),
        actor=actor,
        action=action,
        ecn_id="ECN-T-1",
        revision=revision,
        record_id=record_id,
        detail=out_detail,
        prev="0" * 64,
        digest="0" * 64,
    )


def _flow_replay(c: Checker) -> None:
    c.section("기록: 감사 줄을 다시 돌린 상태 = 투영(무작위 흐름 300개)")
    rng = random.Random(20261009)
    people = [
        MEMBER_WHO,
        _who("lee"),
        ADMIN_WHO,
        OTHER_ADMIN,
        PART_WHO,
        EXEC_WHO,
        _who("dev", approve=True, admin=True, dev=True),
    ]
    bad: list[str] = []
    advanced = 0  # 중간 단계 승인이 실제로 일어난 수(결재선을 걷는지 확인)
    for walk in range(300):
        p: Projection | None = None
        entries: list[AuditEntry] = []
        for _step in range(rng.randint(1, 14)):
            seq = len(entries) + 1
            if p is None or rng.random() < 0.18:
                rid = f"R-{rng.randrange(16**16):016x}"
                revision = 1 if p is None else p.revision + 1
                code, out = _try(record, p, revision, rid, rng.choice(people))
                if code == "ok":
                    entries.append(_entry(seq, A.RECORD, out.detail, MEMBER_WHO, revision, rid))
                    p = out.projection
                continue
            # 검토 중이면 절반은 승인을 골라 결재선을 실제로 걷게 한다(나머지는 아무 행동)
            reviewing = p.state in (S.IN_REVIEW, S.ON_HOLD)
            action = A.APPROVE if reviewing and rng.random() < 0.5 else rng.choice(ACTS)
            who = rng.choice(people)
            login = not who.dev
            items = frozenset({"analysis:1:delivery"}) if rng.random() < 0.3 else frozenset()
            checked = action in (A.APPROVE, A.SETTLE)
            reason = "사유" if checked or action in DECIDE else None
            ask = _ask(action, p, acknowledged=items if checked else frozenset(), reason=reason)
            here = p
            same = rng.random() < 0.9
            edition = rng.random() < 0.9
            free = rng.random() < 0.4
            code, out = _try(
                act,
                here,
                ask,
                who,
                checklist=items,
                same_map=same,
                same_version=edition,
                login_mode=login,
                seq=seq,
                no_cost=free,
                line=LINE,
            )
            if code == "ok":
                entries.append(_entry(seq, action, out.detail, who, here.revision, here.record_id))
                advanced += action is A.APPROVE and out.projection.state is S.IN_REVIEW
                p = out.projection
        if replay(entries) != p:
            bad.append(f"walk {walk}")
    c.check(
        "어떤 흐름이든(결재선 단계·전결·무비용 담당자 처리 포함) replay(감사 줄) = 마지막 투영",
        not bad and advanced > 30,
        (bad[:5], advanced),
    )


# ---------- 감사 사슬 ----------


def _links(n: int) -> list[chain.ChainLink]:
    out: list[chain.ChainLink] = []
    prev = chain.GENESIS
    for seq in range(1, n + 1):
        entry = {"seq": seq, "action": "record", "note": f"줄 {seq}"}
        digest = chain.entry_hash(prev, entry)
        out.append(chain.ChainLink(seq=seq, prev=prev, digest=digest, entry=entry))
        prev = digest
    return out


def _chain(c: Checker) -> None:
    c.section("기록: 감사 사슬(변조·삭제·순서·끝 줄)")
    links = _links(6)
    head = chain.ChainHead(seq=6, digest=links[-1].digest)
    ok = chain.verify(links, head)
    tampered = [*links]
    tampered[2] = replace(tampered[2], entry={**tampered[2].entry, "note": "바꿈"})
    deleted = [*links[:3], *links[4:]]
    swapped = [links[0], links[2], links[1], *links[3:]]
    tail = links[:5]
    c.check("정상 사슬: ok, 줄 수·머리 해시", ok.ok and ok.entries == 6 and ok.head == links[-1].digest)
    c.check("가운데 줄 내용 변조 → 3번째에서 어긋남", chain.verify(tampered, head).broken_at == 3)
    c.check("가운데 줄 삭제 → 4번째에서 어긋남(순번 끊김)", chain.verify(deleted, head).broken_at == 4)
    c.check("순서 바꿈 → 2번째에서 어긋남", chain.verify(swapped, head).broken_at == 2)
    c.check("끝 줄 삭제 → 머리와 달라 어긋남(사슬만으로는 정상처럼 보임)", not chain.verify(tail, head).ok)
    c.check("빈 사슬 + 빈 머리 = 정상", chain.verify([], chain.ChainHead(seq=0, digest=chain.GENESIS)).ok)
    # 고친 줄의 해시까지 다시 계산한 변조: 그 줄은 맞아 보여도 다음 줄의 앞 해시가 어긋난다
    third = {**links[2].entry, "note": "바꾸고 해시도 다시"}
    rehashed = [*links[:2], replace(links[2], entry=third, digest=chain.entry_hash(links[2].prev, third)), *links[3:]]
    last = {**links[5].entry, "note": "끝 줄 바꿈"}
    rehashed_tail = [*links[:5], replace(links[5], entry=last, digest=chain.entry_hash(links[5].prev, last))]
    c.check(
        "줄을 고치고 그 줄 해시까지 다시 계산 → 다음 줄의 앞 해시가 어긋나 4번째에서 잡힘",
        chain.verify(rehashed, head).broken_at == 4,
    )
    c.check(
        "끝 줄을 고치고 해시도 다시 계산(순번 같음) → 머리 해시와 달라 어긋남",
        not chain.verify(rehashed_tail, head).ok,
    )


# ---------- 저장소 ----------


def _settings_for(root: Path, data: str, *, extra: dict[str, str] | None = None) -> Settings:
    env = {"RIPPLE_DEMO_LOGIN": "on", **(extra or {})}
    return replace(Settings.from_env(env), snapshot_path=root / "synthetic" / "snapshot.json", data_dir=root / data)


def _app(root: Path, data: str, **kwargs: Any) -> FastAPI:
    environ = kwargs.pop("environ", ADMIN_ENV)
    return create_app(_settings_for(root, data, **kwargs), environ=environ)


def _results(root: Path) -> list[AnalysisResult]:
    """샘플 요청으로 분석 결과 몇 개(저장소 검사용 본문 재료)."""
    app = create_app(_settings_for(root, "data-results", extra={"RIPPLE_AUTH": "off"}))
    with TestClient(app, base_url=BASE) as client:
        samples = client.get("/api/samples").json()
        results = [
            AnalysisResult.model_validate(client.post("/api/analyses", json=s["request"]).json()) for s in samples[:4]
        ]
    return results


def _body(
    result: AnalysisResult, *, ecn: str | None = None, mode: DataMode = DataMode.SYNTHETIC, checklist: int = 0
) -> RecordBody:
    if ecn is not None:
        change = result.request.change.model_copy(update={"ecn_id": ecn})
        request = result.request.model_copy(update={"change": change})
        result = result.model_copy(update={"request": request})
    items = tuple(
        ChecklistItem(key=f"analysis:{n}:delivery", source="analysis", text=f"확인 {n}")
        for n in range(1, checklist + 1)
    )
    return RecordBody(
        ecn_id=result.request.change.ecn_id,
        snapshot_id=result.versions.snapshot_id,
        data_mode=mode,
        result=result,
        checklist=items,
    )


def _actor(who: Who) -> Actor:
    return Actor(login_id=who.login_id, name=who.login_id, role=Role.ADMIN if who.admin else Role.MEMBER, dev=who.dev)


def _same(_body: RecordBody) -> bool:
    """저장소 검사의 판 대조: 같은 코드로 만든 기록이라 늘 지금 판(판이 다른 경우는 판 호환·API 검사)."""
    return True


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 9, 3, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


def _save(store: RecordStore, body: RecordBody, who: Who, version: int, request_id: str | None = None) -> Any:
    return store.save(
        body,
        _actor(who),
        who,
        request_id=request_id or str(uuid.uuid4()),
        analysis_id=body.result.analysis_id,
        expected_version=version,
    )


def _do(
    store: RecordStore, ecn: str, action: EcnAction, who: Who, *, snapshot: str, login: bool = True, **kw: Any
) -> Any:
    status = store.listing(include_real=True)
    current = next(item.status for item in status.ecns if item.status.ecn_id == ecn)
    ask = Ask(
        action=action,
        expected_version=kw.pop("version", current.version),
        revision=current.revision,
        record_id=current.record_id,
        review_seq=current.review.seq if current.review else None,
        reason=kw.pop("reason", "사유" if action in DECIDE else None),
        acknowledged=kw.pop("acknowledged", frozenset()),
    )
    same_version = kw.pop("same_version", _same)
    return store.act(
        ecn, ask, _actor(who), who, active_snapshot_id=snapshot, same_version=same_version, login_mode=login
    )


def _do_line(store: RecordStore, ecn: str, who: Who, *, snapshot: str, login: bool = True, **kw: Any) -> Any:
    """결재선 끝까지 승인(팀장이면 파트장·본부장 단계는 전결, 개발 모드는 모든 단계). 마지막 상태를 돌려준다."""
    status = None
    for _step in range(4):
        status = _do(store, ecn, A.APPROVE, who, snapshot=snapshot, login=login, **dict(kw))
        if status.state is not S.IN_REVIEW:
            break
    return status


@contextmanager
def _raw(path: Path) -> Iterator[sqlite3.Connection]:
    """저장소 밖에서 파일을 직접 고치는 연결(변조 검사용). 끝나면 커밋하고 닫는다(Windows는 열린 파일을 못 지움)."""
    with closing(sqlite3.connect(path)) as db:
        yield db
        db.commit()


def _store(c: Checker, root: Path, results: list[AnalysisResult]) -> None:
    c.section("기록: 저장소(개정·재시도·끼어들기·되돌림·본문 변조·검증)")
    store = RecordStore(root / "store-a", clock=_Clock())
    store.start()
    one, two = results[0], results[1]
    ecn = one.request.change.ecn_id
    snap = one.versions.snapshot_id
    first = _save(store, _body(one), MEMBER_WHO, 0, "11111111-1111-4111-8111-111111111111")
    retry = _save(store, _body(one), MEMBER_WHO, 0, "11111111-1111-4111-8111-111111111111")
    same = _save(store, _body(one), MEMBER_WHO, 1)
    c.check(
        "첫 기록 = 개정 1·버전 1, 같은 요청 ID 재시도 = 처음 결과 그대로, 같은 본문 새 요청 = 새 개정 없음",
        first.created
        and first.revision.revision == 1
        and first.status.version == 1
        and retry == first
        and not same.created
        and same.revision.revision == 1
        and same.status.version == 1,
    )
    other_ecn = _save(store, _body(one, ecn="ECN-X-0001"), MEMBER_WHO, 0)
    c.check(
        "다른 ECN 같은 계산 = 다른 기록 ID·같은 분석 ID",
        other_ecn.revision.record_id != first.revision.record_id
        and other_ecn.revision.analysis_id == first.revision.analysis_id,
    )
    c.check(
        "유효 데이터 모드가 다르면 기록 ID가 다름(본문 전체 해시)",
        record_id_of(_body(one)) != record_id_of(_body(one, mode=DataMode.REAL)),
    )
    reused = _try(
        lambda: _save(store, _body(one, ecn="ECN-X-0002"), MEMBER_WHO, 0, "11111111-1111-4111-8111-111111111111")
    )
    c.check("같은 저장 요청 ID를 다른 ECN에 쓰면 request_reused", reused[0] == "request_reused")
    # 끼어들기: 갑 저장(응답 유실) → 을 새 개정 + 검토 요청 → 갑 재시도 = 처음 결과, 상태는 을의 검토 그대로
    lee = _who("lee")
    b2 = _body(two, ecn=ecn)
    rev2 = _save(store, b2, lee, 1)
    _do(store, ecn, A.REQUEST_REVIEW, lee, snapshot=snap)
    again = _save(store, _body(one), MEMBER_WHO, 0, "11111111-1111-4111-8111-111111111111")
    now = next(item.status for item in store.listing(include_real=True).ecns if item.status.ecn_id == ecn)
    stale = _try(lambda: _save(store, _body(one), MEMBER_WHO, 1))
    c.check(
        "응답 유실 뒤 재시도는 처음 결과(새 개정 없음), 을의 검토 유지 · 옛 버전 새 요청은 ecn_changed",
        again == first
        and rev2.revision.revision == 2
        and now.state is S.IN_REVIEW
        and now.revision == 2
        and stale[0] == "ecn_changed",
    )
    back = _save(store, _body(one), MEMBER_WHO, now.version)
    c.check(
        "옛 내용으로 되돌림(새 요청) = 새 개정 3이 옛 기록 ID를 가리킴, 진행 중 검토는 대체됨",
        back.created
        and back.revision.revision == 3
        and back.revision.record_id == first.revision.record_id
        and back.status.state is S.ANALYZED
        and back.status.review is None,
    )
    detail = store.detail(ecn, include_real=True, same_version=_same)
    assert detail is not None
    actions = [e.action for e in detail.audit]
    c.check(
        "상세: 개정 3개(오래된 순)·감사 줄(기록·기록·검토 요청·기록)·최신 개정의 확인 목록",
        [r.revision for r in detail.revisions] == [1, 2, 3]
        and actions == [A.RECORD, A.RECORD, A.REQUEST_REVIEW, A.RECORD]
        and detail.audit[-1].detail.superseded_review_seq == detail.audit[2].seq,
    )
    # 승인 흐름 + 확인 목록
    third = _save(store, _body(results[2], ecn="ECN-X-0003", checklist=2), MEMBER_WHO, 0)
    snap3 = results[2].versions.snapshot_id
    _do(store, "ECN-X-0003", A.REQUEST_REVIEW, MEMBER_WHO, snapshot=snap3)
    missing = _try(lambda: _do(store, "ECN-X-0003", A.APPROVE, ADMIN_WHO, snapshot=snap3))
    keys = frozenset(item.key for item in _body(results[2], checklist=2).checklist)
    part = _do(store, "ECN-X-0003", A.APPROVE, PART_WHO, snapshot=snap3, acknowledged=keys)
    lead_step = _try(lambda: _do(store, "ECN-X-0003", A.APPROVE, EXEC_WHO, snapshot=snap3, acknowledged=keys))
    team = _do(store, "ECN-X-0003", A.APPROVE, ADMIN_WHO, snapshot=snap3, acknowledged=keys)
    approved = _do(store, "ECN-X-0003", A.APPROVE, ADMIN_WHO, snapshot=snap3, acknowledged=keys)  # 본부장 전결
    signs = store.detail("ECN-X-0003", include_real=True, same_version=_same)
    assert signs is not None
    c.check(
        "결재선 저장: 파트장 승인 → 2/3단계(검토 그대로) · 본부장은 2단계 forbidden · 팀장 승인 → 3/3 · "
        "팀장 전결 → 승인, "
        "감사 줄에 단계·전결",
        part.state is S.IN_REVIEW
        and part.review is not None
        and (part.review.step, part.review.steps) == (2, LINE)
        and lead_step[0] == "forbidden"
        and team.review is not None
        and team.review.step == 3
        and [(e.detail.step, e.detail.proxy) for e in signs.audit if e.action is A.APPROVE]
        == [(ST.PART_LEAD, False), (ST.TEAM_LEAD, False), (ST.EXECUTIVE, True)]
        and signs.audit[[e.action for e in signs.audit].index(A.REQUEST_REVIEW)].detail.steps == LINE,
        (part.review, lead_step[0]),
    )
    started = _do(store, "ECN-X-0003", A.START, MEMBER_WHO, snapshot="G-0000000000000000")
    closed = _do(store, "ECN-X-0003", A.CLOSE, MEMBER_WHO, snapshot=snap3)
    locked = _try(lambda: _save(store, _body(results[3], ecn="ECN-X-0003"), MEMBER_WHO, closed.version))
    same_locked = _try(
        lambda: _save(store, _body(results[2], ecn="ECN-X-0003", checklist=2), MEMBER_WHO, closed.version)
    )
    audit3 = store.detail("ECN-X-0003", include_real=True, same_version=_same)
    assert audit3 is not None
    c.check(
        "확인 목록 미체크 거절 → 전부 체크 승인 → 다른 지도에서 실행 시작(표시) → 종료 → 새 개정·같은 본문 모두 locked",
        third.created
        and missing[0] == "checklist_required"
        and approved.state is S.APPROVED
        and approved.approved_revision == 1
        and started.state is S.IN_PROGRESS
        and audit3.audit[-2].detail.other_map
        and closed.state is S.CLOSED
        and locked[0] == "locked"
        and same_locked[0] == "locked",
        same_locked,
    )
    verified = store.verify()
    c.check(
        "검증: 사슬·본문 해시·개정 연결·투영 = 재생 모두 정상", verified.ok and verified.entries > 8, verified.problems
    )
    # 본문만 변조(감사 줄은 그대로) → 조회 거부·검증 실패
    with _raw(store.path) as db:
        text = db.execute("SELECT body FROM records WHERE record_id = ?", (first.revision.record_id,)).fetchone()[0]
        data = json.loads(text)
        data["result"]["total"]["value"] = data["result"]["total"]["value"] + 1
        db.execute("UPDATE records SET body = ? WHERE record_id = ?", (json.dumps(data), first.revision.record_id))
    c.check(
        "본문만 변조 → 기록 조회 integrity, 검증 실패(본문 해시)",
        _try(lambda: store.record(first.revision.record_id, include_real=True))[0] == "integrity"
        and not store.verify().ok,
    )
    with _raw(store.path) as db:
        db.execute("UPDATE records SET body = ? WHERE record_id = ?", (text, first.revision.record_id))
        db.execute("DELETE FROM audit WHERE seq = (SELECT MAX(seq) FROM audit)")
    c.check("끝 감사 줄 삭제 → 머리와 달라 검증 실패", not store.verify().ok)
    store2 = RecordStore(root / "store-b", clock=_Clock())
    store2.start()
    _save(store2, _body(one), MEMBER_WHO, 0)
    # 선주 요청은 1.29.0부터 분석 ID가 달라(허용 지연) 계산에 쓰지 않는 원인으로 본다
    caused_change = one.request.change.model_copy(update={"cause": ChangeCause.DESIGN_ERROR})
    caused = one.model_copy(update={"request": one.request.model_copy(update={"change": caused_change})})
    recaused = _save(store2, _body(caused), MEMBER_WHO, 1)
    detail2 = store2.detail(one.request.change.ecn_id, include_real=True, same_version=_same)
    c.check(
        "계산에 쓰지 않는 원인만 바꿔 저장하면 새 개정(분석 ID 같음), 상세의 최신 원인 = 설계 오류(계약 1.28.0)",
        recaused.created
        and detail2 is not None
        and detail2.latest_cause is ChangeCause.DESIGN_ERROR
        and len({r.analysis_id for r in detail2.revisions}) == 1,
        detail2.latest_cause if detail2 else None,
    )
    with _raw(store2.path) as db:
        status = json.loads(db.execute("SELECT status FROM ecns").fetchone()[0])
        status["version"] = 9
        db.execute("UPDATE ecns SET status = ?", (json.dumps(status),))
    c.check("투영만 고침 → 감사 재생과 달라 검증 실패", not store2.verify().ok)
    store4 = RecordStore(root / "store-d", clock=_Clock())
    store4.start()
    listed = _save(store4, _body(one), MEMBER_WHO, 0)
    item = store4.listing(include_real=True).ecns[0]
    c.check(
        "목록 줄 = 상태 + 최신 개정 요약(판정·총액·마감일), 저장한 요약 = 본문에서 다시 만든 요약",
        item.status == listed.status and item.latest == listed.revision and store4.verify().ok,
    )
    with _raw(store4.path) as db:
        summary = json.loads(db.execute("SELECT summary FROM revisions").fetchone()[0])
        summary["total"]["value"] = summary["total"]["value"] + 1000
        db.execute("UPDATE revisions SET summary = ?", (json.dumps(summary),))
    c.check("개정 요약만 고침 → 본문과 달라 검증 실패", not store4.verify().ok)
    broken_json: dict[str, object] = {}
    for table, column in (("audit", "entry"), ("ecns", "status"), ("revisions", "summary"), ("records", "body")):
        damaged = RecordStore(root / f"store-json-{table}", clock=_Clock())
        damaged.start()
        _save(damaged, _body(one), MEMBER_WHO, 0)
        with _raw(damaged.path) as db:
            db.execute(f"UPDATE {table} SET {column} = ?", ("{깨진 JSON",))
        try:
            found = damaged.verify()
            broken_json[table] = found.problems if not found.ok and found.problems else "문제 없음으로 보고"
        except Exception as error:  # 검증이 예외로 끝나면 그 자체가 실패
            broken_json[table] = f"예외 {type(error).__name__}"
    c.check(
        "JSON이 깨진 칸(감사 줄·상태·개정 요약·기록 본문)은 예외(500) 대신 검증 실패 + 문제 목록",
        all(isinstance(v, tuple) for v in broken_json.values()),
        broken_json,
    )
    store3 = RecordStore(root / "store-c", clock=_Clock())
    store3.start()
    real = _save(store3, _body(one, mode=DataMode.REAL), MEMBER_WHO, 0)
    c.check(
        "실데이터 기록: 체험 범위(목록·상세·기록 조회)에서 안 보임, 관리자 범위에서는 보임",
        store3.listing(include_real=False).ecns == ()
        and store3.detail(ecn, include_real=False, same_version=_same) is None
        and store3.record(real.revision.record_id, include_real=False) is None
        and len(store3.listing(include_real=True).ecns) == 1
        and real.status.real,
    )


def _fresh(root: Path, name: str) -> RecordStore:
    store = RecordStore(root / name, clock=_Clock())
    store.start()
    return store


def _rows(store: RecordStore) -> tuple[int, ...]:
    with _raw(store.path) as db:
        return tuple(
            db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("records", "revisions", "audit", "requests")
        )


def _store_tamper(c: Checker, root: Path, results: list[AnalysisResult]) -> None:
    c.section("기록: 저장소 변조·실패(본문·개정 표·감사 색인·머리·되돌림·실데이터 표시)")
    one, two, three = results[0], results[1], results[2]
    ecn = one.request.change.ecn_id
    snap = one.versions.snapshot_id
    # 같은 기록 ID에 다른 본문이 저장돼 있으면 같은 내용을 다시 저장해도 거절(최신 개정과 같다고 넘기지 않음)
    same_id = _fresh(root, "tamper-a")
    rid = _save(same_id, _body(one), MEMBER_WHO, 0).revision.record_id
    with _raw(same_id.path) as db:
        data = json.loads(db.execute("SELECT body FROM records WHERE record_id = ?", (rid,)).fetchone()[0])
        data["result"]["total"]["value"] += 1
        db.execute("UPDATE records SET body = ? WHERE record_id = ?", (json.dumps(data), rid))
    again = _try(_save, same_id, _body(one), MEMBER_WHO, 1)
    c.check(
        "같은 기록 ID에 다른 본문이 저장돼 있으면 같은 내용 저장도 integrity(새 개정 없음)",
        again[0] == "integrity" and _rows(same_id)[1] == 1,
        again[0],
    )
    # 실데이터 표시는 그 ECN에서 풀리지 않는다
    sticky = _fresh(root, "tamper-b")
    _save(sticky, _body(one, mode=DataMode.REAL), MEMBER_WHO, 0)
    later = _save(sticky, _body(two, ecn=ecn), MEMBER_WHO, 1)
    c.check(
        "실데이터 기록 뒤 합성 개정을 남겨도 그 ECN은 계속 실데이터(체험 목록·그 합성 개정 직접 조회 없음)",
        later.status.real
        and sticky.listing(include_real=False).ecns == ()
        and sticky.record(later.revision.record_id, include_real=False) is None
        and sticky.record(later.revision.record_id, include_real=True) is not None,
    )
    # 개정 표의 기록한 사람·시각만 바꾸고(요약도 맞춤) 감사 사슬은 그대로 → 감사 줄과 달라 검증 실패
    author = _fresh(root, "tamper-k")
    first = _save(author, _body(one), MEMBER_WHO, 0)
    forged = Actor(login_id="lead", name="바꾼 사람", role=Role.ADMIN, dev=False)
    at2 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    with _raw(author.path) as db:
        db.execute(
            "UPDATE revisions SET actor = ?, recorded_at = ?, summary = ?",
            (
                forged.model_dump_json(),
                at2.isoformat(),
                summary_of(1, first.revision.record_id, at2, forged, _body(one)).model_dump_json(),
            ),
        )
    authored = author.verify()
    c.check(
        "개정의 기록한 사람·시각만 바꿈(요약 맞춤, 사슬 그대로) → 감사 줄과 달라 검증 실패",
        not authored.ok and any("기록한 사람·시각" in p for p in authored.problems),
        authored.problems,
    )
    # 개정 표만 고친 변조(요약까지 본문에 맞춰 다시 만듦)
    table = _fresh(root, "tamper-c")
    _save(table, _body(one), MEMBER_WHO, 0)
    _save(table, _body(two, ecn=ecn), MEMBER_WHO, 1)
    other_body = _body(three, ecn="ECN-X-0009")
    other_id = _save(table, other_body, MEMBER_WHO, 0).revision.record_id
    clean = table.verify().ok
    actor = _actor(MEMBER_WHO)
    at = datetime(2026, 10, 9, 5, 0, tzinfo=UTC)
    smuggled = summary_of(3, other_id, at, actor, other_body)
    with _raw(table.path) as db:
        db.execute(
            "INSERT INTO revisions (ecn_id, revision, record_id, recorded_at, actor, summary) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ecn, 3, other_id, at.isoformat(), actor.model_dump_json(), smuggled.model_dump_json()),
        )
    inserted = table.verify()
    c.check(
        "감사 줄 없이 개정 표에 끼워 넣은 개정(번호 이어짐·요약 맞춤) → 검증 실패",
        clean and not inserted.ok and any("개정 3" in p for p in inserted.problems),
        inserted.problems,
    )
    with _raw(table.path) as db:
        db.execute("DELETE FROM revisions WHERE ecn_id = ? AND revision = 3", (ecn,))
        recorded_at, actor_text = db.execute(
            "SELECT recorded_at, actor FROM revisions WHERE ecn_id = ? AND revision = 1", (ecn,)
        ).fetchone()
        rewired = summary_of(
            1, other_id, datetime.fromisoformat(recorded_at), Actor.model_validate_json(actor_text), other_body
        )
        db.execute(
            "UPDATE revisions SET record_id = ?, summary = ? WHERE ecn_id = ? AND revision = 1",
            (other_id, rewired.model_dump_json(), ecn),
        )
    c.check(
        "개정이 가리키는 기록을 다른 기록으로 바꿈(요약 맞춤) → 감사 줄의 기록과 달라 검증 실패",
        not table.verify().ok,
    )
    # 감사 줄 내용의 시각만 고침(재생·참조에는 영향 없음) → 사슬이 잡는다
    when = _fresh(root, "tamper-d")
    _save(when, _body(one), MEMBER_WHO, 0)
    _do(when, ecn, A.REQUEST_REVIEW, MEMBER_WHO, snapshot=snap)
    with _raw(when.path) as db:
        entry = json.loads(db.execute("SELECT entry FROM audit WHERE seq = 1").fetchone()[0])
        entry["at"] = "2026-10-09T09:00:00Z"
        db.execute("UPDATE audit SET entry = ? WHERE seq = 1", (json.dumps(entry, ensure_ascii=False),))
    retimed = when.verify()
    c.check("감사 줄의 시각만 고침 → 사슬이 1번째 줄에서 어긋나 검증 실패", not retimed.ok and retimed.broken_at == 1)
    # 끝 감사 줄을 지운 파일에는 새 줄을 덧붙이지 않는다(머리와 마지막 줄이 다름)
    tail = _fresh(root, "tamper-e")
    _save(tail, _body(one), MEMBER_WHO, 0)
    _do(tail, ecn, A.REQUEST_REVIEW, MEMBER_WHO, snapshot=snap)
    with _raw(tail.path) as db:
        db.execute("DELETE FROM audit WHERE seq = (SELECT MAX(seq) FROM audit)")
    refused = _try(_do, tail, ecn, A.WITHDRAW, MEMBER_WHO, snapshot=snap)
    c.check(
        "끝 감사 줄을 지운 파일에는 새 줄을 덧붙이지 않음(integrity, 줄 수 그대로)",
        refused[0] == "integrity" and _rows(tail)[2] == 1,
        refused[0],
    )
    # 쓰는 중 실패 → 한 트랜잭션 전부 되돌림
    broken = _fresh(root, "tamper-f")
    _save(broken, _body(one), MEMBER_WHO, 0)

    def boom(*_args: Any) -> None:
        raise RuntimeError("상태를 쓰다 실패(시험)")

    patched = cast(Any, broken)
    patched._put_status = boom
    failed = Checker.raises(lambda: _save(broken, _body(two, ecn=ecn), MEMBER_WHO, 1), RuntimeError)
    del patched._put_status
    c.check(
        "저장 중 실패 → 기록·개정·감사 줄·요청 결과 모두 되돌림(검증 정상)",
        failed and _rows(broken) == (1, 1, 1, 1) and broken.verify().ok,
        _rows(broken),
    )
    # 색인 칸만 고친 변조: 기록의 데이터 모드 칸 · 감사 줄의 ECN 칸 · 감사 줄의 순번 칸
    index = _fresh(root, "tamper-g")
    _save(index, _body(one), MEMBER_WHO, 0)
    _save(index, _body(two, ecn="ECN-X-0010"), MEMBER_WHO, 0)
    with _raw(index.path) as db:
        db.execute("UPDATE records SET data_mode = 'real' WHERE record_id = (SELECT MIN(record_id) FROM records)")
    c.check("기록의 데이터 모드 칸만 고침 → 본문과 달라 검증 실패", not index.verify().ok)
    moved = _fresh(root, "tamper-h")
    _save(moved, _body(one), MEMBER_WHO, 0)
    _save(moved, _body(two, ecn="ECN-X-0010"), MEMBER_WHO, 0)
    with _raw(moved.path) as db:
        db.execute("UPDATE audit SET ecn_id = ? WHERE seq = 2", (ecn,))
    c.check(
        "감사 줄의 ECN 칸만 옮김 → 그 ECN 상세 조회 integrity, 검증 실패",
        _try(moved.detail, ecn, include_real=True, same_version=_same)[0] == "integrity" and not moved.verify().ok,
    )
    renumbered = _fresh(root, "tamper-i")
    _save(renumbered, _body(one), MEMBER_WHO, 0)
    with _raw(renumbered.path) as db:
        db.execute("UPDATE audit SET seq = 7 WHERE seq = 1")
    c.check(
        "감사 줄의 순번 칸만 고침 → 상세 조회 integrity, 검증 실패",
        _try(renumbered.detail, ecn, include_real=True, same_version=_same)[0] == "integrity"
        and not renumbered.verify().ok,
    )
    # 상태 칸 중 투영 밖의 것(실데이터 표시·지도·제목)만 고친 변조
    fields = {"real": False, "snapshot_id": "G-00000000000000ff", "title": "바꾼 제목"}
    caught: list[str] = []
    for name, value in fields.items():
        status_store = _fresh(root, f"tamper-status-{name}")
        _save(status_store, _body(one, mode=DataMode.REAL), MEMBER_WHO, 0)
        clean = status_store.verify().ok
        with _raw(status_store.path) as db:
            status = json.loads(db.execute("SELECT status FROM ecns").fetchone()[0])
            status[name] = value
            db.execute("UPDATE ecns SET status = ?", (json.dumps(status),))
        if clean and not status_store.verify().ok:
            caught.append(name)
    c.check("상태의 실데이터 표시·지도·제목만 고침 → 기록 본문과 달라 검증 실패", caught == list(fields), caught)
    # 같은 계산(분석 ID 같음)이라도 변경 사유가 다르면 다른 기록 → 새 개정, 요약에 사유
    reason = _fresh(root, "tamper-j")
    base = _save(reason, _body(one), MEMBER_WHO, 0)
    other = next(i for i in ChangeIntent if i is not one.request.change.intent)
    change = one.request.change.model_copy(update={"intent": other})
    with_intent = one.model_copy(update={"request": one.request.model_copy(update={"change": change})})
    second = _save(reason, _body(with_intent), MEMBER_WHO, 1)
    c.check(
        "변경 사유만 바꿔 기록 → 새 개정(분석 ID 같음), 개정 요약에 사유",
        not one.request.include_alternatives
        and second.created
        and second.revision.revision == 2
        and second.revision.analysis_id == base.revision.analysis_id
        and second.revision.intent is other
        and base.revision.intent == one.request.change.intent,
        (other, base.revision.intent, second.revision.intent),
    )


def _store_read(c: Checker, root: Path, results: list[AnalysisResult]) -> None:
    c.section("기록: 읽기는 한 시점(상세를 읽는 사이 들어온 실데이터 개정이 체험 응답에 섞이지 않음)")
    one, two = results[0], results[1]
    ecn = one.request.change.ecn_id
    store = _fresh(root, "read-a")
    _save(store, _body(one), MEMBER_WHO, 0)
    writer = RecordStore(store.path.parent, clock=_Clock())
    original = RecordStore._status
    injected: list[str] = []

    def status_then_commit(db: sqlite3.Connection, ecn_id: str) -> EcnStatus | None:
        found = original(db, ecn_id)
        if not injected:  # 상태를 읽은 바로 뒤, 다른 연결이 같은 ECN에 실데이터 개정을 커밋
            injected.append(_save(writer, _body(two, ecn=ecn, mode=DataMode.REAL), MEMBER_WHO, 1).revision.record_id)
        return found

    patched = cast(Any, store)
    patched._status = status_then_commit
    seen = store.detail(ecn, include_real=False, same_version=_same)
    del patched._status
    after = store.detail(ecn, include_real=False, same_version=_same)
    c.check(
        "상태를 읽은 직후 실데이터 개정이 커밋돼도 그 응답은 커밋 전 시점만(개정 1개), 다음 조회부터는 체험에게 없음",
        len(injected) == 1
        and seen is not None
        and [r.revision for r in seen.revisions] == [1]
        and all(r.data_mode is DataMode.SYNTHETIC for r in seen.revisions)
        and after is None,
        (injected, None if seen is None else [r.revision for r in seen.revisions]),
    )


def _store_race(c: Checker, root: Path, results: list[AnalysisResult]) -> None:
    c.section("기록: 동시 요청(승인 vs 새 개정) — 하나만 반영, 투영 = 재생")
    outcomes: list[str] = []
    for round_ in range(6):
        store = RecordStore(root / f"race-{round_}", clock=_Clock())
        store.start()
        one = results[0]
        ecn = one.request.change.ecn_id
        snap = one.versions.snapshot_id
        _save(store, _body(one), MEMBER_WHO, 0)
        _do(store, ecn, A.REQUEST_REVIEW, MEMBER_WHO, snapshot=snap)
        status = store.listing(include_real=True).ecns[0].status
        gate = threading.Barrier(2)
        codes: list[str] = []

        ask = Ask(
            action=A.APPROVE,
            expected_version=status.version,
            revision=status.revision,
            record_id=status.record_id,
            review_seq=status.review.seq if status.review else None,
            reason="사유",
        )
        approve_args = (ecn, ask, _actor(ADMIN_WHO), ADMIN_WHO)
        revise_args = (store, _body(results[1], ecn=ecn), MEMBER_WHO, status.version)

        def approve(
            gate: Any = gate,
            codes: list[str] = codes,
            store: RecordStore = store,
            args: Any = approve_args,
            snap: str = snap,
        ) -> None:
            gate.wait()
            codes.append(_try(store.act, *args, active_snapshot_id=snap, same_version=_same, login_mode=True)[0])

        def revise(gate: Any = gate, codes: list[str] = codes, args: Any = revise_args) -> None:
            gate.wait()
            codes.append(_try(_save, *args)[0])

        threads = [threading.Thread(target=approve), threading.Thread(target=revise)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        final = store.listing(include_real=True).ecns[0].status
        ok = sorted(codes) == ["ecn_changed", "ok"] and store.verify().ok
        # 승인이 이기면 1단계를 넘긴 검토(2/3단계), 새 개정이 이기면 분석
        passed = final.state is S.IN_REVIEW and final.review is not None and final.review.step == 2
        ok = ok and (passed or final.state is S.ANALYZED)
        outcomes.append("ok" if ok else f"{codes} {final.state}")
    c.check("6번 모두: 하나는 성공·하나는 ecn_changed, 검증 정상", all(o == "ok" for o in outcomes), outcomes)


def _store_format(c: Checker, root: Path) -> None:
    c.section("기록: 형식 판(판 1 올림 · 모르는 판·판 없는 표는 시작 거부)")
    store = RecordStore(root / "fmt-a")
    store.start()
    store.start()  # 다시 열어도 그대로
    with _raw(store.path) as db:
        db.execute("PRAGMA user_version = 99")
    c.check("모르는 형식 판 → RecordStoreError", Checker.raises(store.start, RecordStoreError))
    folder = root / "fmt-b"
    folder.mkdir()
    with _raw(folder / FILE_NAME) as db:
        db.execute("CREATE TABLE something (x INTEGER)")
    c.check("판 없는 기존 표 → RecordStoreError", Checker.raises(RecordStore(folder).start, RecordStoreError))
    junk = root / "fmt-c"
    junk.mkdir()
    (junk / FILE_NAME).write_bytes(b"not a database at all" * 50)
    c.check("손상 파일 → RecordStoreError", Checker.raises(RecordStore(junk).start, RecordStoreError))
    old = root / "fmt-v1"
    old.mkdir()
    with _raw(old / FILE_NAME) as db:
        db.executescript(f"{SCHEMA}PRAGMA user_version = 1;")  # 계약 1.17.0 코드가 만든 파일(표는 같음)
    two = root / "fmt-v2"
    two.mkdir()
    with _raw(two / FILE_NAME) as db:
        db.executescript(f"{SCHEMA}PRAGMA user_version = 2;")  # 계약 1.18.0~1.27.0 코드가 만든 파일(표는 같음)
    three = root / "fmt-v3"
    three.mkdir()
    with _raw(three / FILE_NAME) as db:
        db.executescript(f"{SCHEMA}PRAGMA user_version = 3;")  # 결재선 전(1.28.0~1.32.0) 코드가 만든 파일(표는 같음)
    versions = []
    for folder in (old, old, two, two, three, three):
        RecordStore(folder).start()
        with _raw(folder / FILE_NAME) as db:
            versions.append(db.execute("PRAGMA user_version").fetchone()[0])
    old_code_accepts = {1, 2, 3}  # 계약 1.17.0·1.27.0·1.32.0(결재선 전) 코드의 FORMAT_VERSION — 그 밖이면 시작을 멈춘다
    c.check(
        "판 1·2·3 파일은 시작 때 판 4로 올림(다시 열어도 4) — 옛 판만 받는 옛 코드는 이 파일로 시작하지 않음",
        FORMAT_VERSION == 4 and versions == [4] * 6 and not set(versions) & old_code_accepts,
        versions,
    )


def _store_notice(c: Checker, root: Path, results: list[AnalysisResult]) -> None:
    c.section("기록: 통보 기록(계약 1.28.0)")
    store = RecordStore(root / "store-notice", clock=_Clock())  # 시계: 2026-10-09 KST
    store.start()
    one = results[0]
    ecn = one.request.change.ecn_id
    saved = _save(store, _body(one), MEMBER_WHO, 0)
    record_id = saved.status.record_id
    sent = NoticeLog(
        target=NotificationTarget.SUPPLIER, recipient_id="SUP-VL1", step=NoticeStep.SENT, on=date(2026, 10, 9)
    )
    entry = store.notice(ecn, record_id, sent, _actor(MEMBER_WHO), MEMBER_WHO)
    replied = sent.model_copy(update={"step": NoticeStep.REPLIED, "note": "다음 단계 중지 확인"})
    store.notice(ecn, record_id, replied, _actor(MEMBER_WHO), MEMBER_WHO)
    detail = store.detail(ecn, include_real=True, same_version=_same)
    assert detail is not None
    c.check(
        "통보 기록은 감사 줄로 남고 상태·버전은 그대로(결재 중인 다른 화면을 막지 않음), 검증 정상",
        entry.action is A.NOTICE
        and entry.detail.notice == sent
        and entry.revision == saved.status.revision
        and detail.status.version == saved.status.version
        and detail.status.state is saved.status.state
        and [e.detail.notice.step for e in detail.audit if e.detail.notice] == [NoticeStep.SENT, NoticeStep.REPLIED]
        and store.verify().ok,
        store.verify().problems,
    )
    review = _do(store, ecn, A.REQUEST_REVIEW, MEMBER_WHO, snapshot=saved.status.snapshot_id)
    c.check("통보 기록 뒤에도 그 전 버전으로 바로 검토 요청 가능", review.state is S.IN_REVIEW, review.state)
    viewer = _who("view", record_=False)
    codes = [
        _try(store.notice, ecn, "R-0000000000000000", sent, _actor(MEMBER_WHO), MEMBER_WHO)[0],
        _try(
            store.notice,
            ecn,
            record_id,
            sent.model_copy(update={"on": date(2026, 10, 10)}),
            _actor(MEMBER_WHO),
            MEMBER_WHO,
        )[0],
        _try(store.notice, ecn, record_id, sent, _actor(viewer), viewer)[0],
        _try(store.notice, "ECN-NONE", record_id, sent, _actor(MEMBER_WHO), MEMBER_WHO)[0],
    ]
    c.check(
        "다른 개정 → ecn_changed, 앞날 → 거절, 보기 권한 → forbidden, 기록 없는 설계변경 → not_found",
        codes == ["ecn_changed", "invalid_transition", "forbidden", "not_found"],
        codes,
    )
    p = _proj(S.ANALYZED)
    ask = Ask(action=A.NOTICE, expected_version=p.version, revision=p.revision, record_id=p.record_id)
    c.check(
        "행동 API로 통보를 보내면 거절(통보는 전용 경로)",
        _try(act, p, ask, MEMBER_WHO, checklist=frozenset(), same_map=True, same_version=True, login_mode=True, seq=9)[
            0
        ]
        == "invalid_transition",
    )


def _checklist(c: Checker, results: list[AnalysisResult], snapshot: GraphSnapshot) -> None:
    c.section("기록: 확인 목록(계산하지 못한 항목 + 가져온 지도의 경고)")
    item = Unresolved(kind=UnresolvedKind.PO_STATE, reason="발주 단계를 알 수 없어요", entity_id="PO-0001")
    result = results[0].model_copy(update={"unresolved": (item,)})
    base = _info(snapshot)
    issues = (
        ImportIssue(
            severity=IssueSeverity.WARNING,
            code=IssueCode.IGNORED_COLUMN,
            sheet="부재",
            file_column="비고",
            message="양식에 없는 열이라 읽지 않았어요",
        ),
        ImportIssue(
            severity=IssueSeverity.ERROR, code=IssueCode.BAD_VALUE, sheet="부재", row=7, message="숫자가 아니에요"
        ),
    )
    summary = ImportSummary(template_version="excel-v1", file="plant.xlsx", snapshot_id=base.snapshot_id, issues=issues)
    imported = SnapshotInfo.model_validate(
        {**base.model_dump(), "origin": "excel_import", "data_mode": "real", "summary": summary.model_dump()}
    )
    items = checklist_of(result, imported)
    plain = checklist_of(result, base)
    c.check(
        "확인 목록 = 계산하지 못한 항목(현장 이름·대상) + 가져온 지도의 경고(오류 제외), 기본 지도는 앞의 것만",
        [i.key for i in items] == ["analysis:1:po_state", "import:1:ignored_column"]
        and items[0].text == "발주 상태 · PO-0001: 발주 단계를 알 수 없어요"
        and items[1].source == "import"
        and "부재" in items[1].text
        and "비고" in items[1].text
        and [i.key for i in plain] == ["analysis:1:po_state"],
        [i.model_dump() for i in items],
    )
    # 같은 종류가 많으면 한 항목으로: 미계산 10개(같은 이유) + 2개, 같은 시트 메모 행 경고 201개 + 열 경고 2개
    many = [
        Unresolved(kind=UnresolvedKind.PO_STATE, reason="발주 단계를 알 수 없어요", entity_id=f"PO-{n:04d}")
        for n in range(1, 11)
    ]
    many += [
        Unresolved(kind=UnresolvedKind.DELIVERY, reason="인도 조건이 없어요", entity_id=None),
        Unresolved(kind=UnresolvedKind.DELIVERY, reason="인도 조건이 없어요", entity_id=None),
    ]
    memo = [
        ImportIssue(
            severity=IssueSeverity.WARNING, code=IssueCode.IGNORED_ROW, sheet="부재", row=r, message="메모 행이에요"
        )
        for r in range(12, 213)
    ]
    cols = [
        ImportIssue(severity=IssueSeverity.WARNING, code=IssueCode.IGNORED_COLUMN, sheet="발주", message=f"열 {n}")
        for n in (1, 2)
    ]
    big_summary = summary.model_copy(update={"issues": (*memo, *cols)})
    big_info = imported.model_copy(update={"summary": big_summary})
    grouped = checklist_of(results[0].model_copy(update={"unresolved": tuple(many)}), big_info)
    keys = [i.key for i in grouped]
    c.check(
        "같은 종류가 많으면 묶음: 미계산 10개 → 1항목(이름 5개 외 5건), 메모 행 201개 → 1항목, 적은 것은 그대로",
        keys
        == [
            "analysis:1:po_state",
            "analysis:2:delivery",
            "analysis:3:delivery",
            "import:1:ignored_row",
            "import:2:ignored_column",
            "import:3:ignored_column",
        ]
        and "10건" in grouped[0].text
        and "외 5건" in grouped[0].text
        and "201건" in grouped[3].text
        and len(keys) == len(set(keys)),
        [i.text for i in grouped],
    )
    ask = ActionRequest.model_validate(
        {
            "action": "approve",
            "expected_version": 1,
            "revision": 1,
            "record_id": "R-0000000000000000",
            "review_seq": 1,
            "acknowledged": [f"import:{n}:x" for n in range(300)],
        }
    )
    c.check("승인 요청은 확인 체크 300개도 받음(묶은 목록보다 넉넉히)", len(ask.acknowledged) == 300)


# ---------- API ----------


class _SpyStore(RecordStore):
    """기록 저장·행동이 지도 전환 잠금(Workspaces._switch)을 잡은 채 저장소에 들어오는지 적는다."""

    def __init__(self, base: RecordStore, holder: Any) -> None:
        super().__init__(base.path.parent)
        self.holder = holder
        self.seen: list[tuple[str, bool]] = []

    def save(self, body: RecordBody, actor: Actor, who: Who, **kwargs: Any) -> RecordSaved:
        self.seen.append(("save", self.holder._switch.locked()))
        return super().save(body, actor, who, **kwargs)

    def act(self, ecn_id: str, ask: Ask, actor: Actor, who: Who, **kwargs: Any) -> EcnStatus:
        self.seen.append(("act", self.holder._switch.locked()))
        return super().act(ecn_id, ask, actor, who, **kwargs)


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, base_url=BASE)


def _login(client: TestClient, login_id: str, password: str) -> Any:
    return client.post("/api/auth/login", json={"login_id": login_id, "password": password})


PART_PW = "part-pass-2026-x"
EXEC_PW = "boss-pass-2026-x"


def _people(app: FastAPI) -> dict[str, TestClient]:
    """팀장 둘(lead·park) · 담당자(kim) · 파트장(part) · 본부장(boss) · 체험."""
    people = {name: _client(app) for name in ("lead", "park", "kim", "demo")}
    _login(people["lead"], "lead", FIRST)
    people["lead"].post("/api/auth/password", json={"current_password": FIRST, "new_password": ADMIN_PW})
    staff = (
        ("park", "admin", SECOND_PW),
        ("kim", "member", MEMBER_PW),
        ("part", "part_lead", PART_PW),
        ("boss", "executive", EXEC_PW),
    )
    for login_id, role, password in staff:
        people[login_id] = _staff(app, people["lead"], login_id, role, password)
    people["demo"].post("/api/auth/demo")
    return people


def _approve_line(client: TestClient, ecn: str, token: str, **extra: Any) -> Any:
    """결재선 끝까지 한 사람이 승인(팀장이면 전결, 개발 모드면 모든 단계): 마지막 응답."""
    response = None
    for _step in range(4):
        response = _action(client, ecn, "approve", token, **extra)
        if response.status_code != 200 or response.json()["state"] != "in_review":
            break
    return response


def _staff(app: FastAPI, lead: TestClient, login_id: str, role: str, password: str) -> TestClient:
    """팀장(lead)이 만든 구성원으로 로그인한 손님."""
    client = _client(app)
    body: dict[str, Any] = {"login_id": login_id, "name": login_id, "role": role}
    temporary = lead.post("/api/accounts", json=body).json()["temporary_password"]
    _login(client, login_id, temporary)
    client.post("/api/auth/password", json={"current_password": temporary, "new_password": password})
    return client


def _reset(c: Checker, root: Path) -> None:
    c.section("기록 비우기(RIPPLE_RESET_RECORDS): 기록·실적만 보관 폴더로, 같은 표지로는 한 번")
    data = root / "data-reset"
    dev = {"RIPPLE_AUTH": "off"}

    def record(index: int) -> None:
        with TestClient(_app(root, "data-reset", extra=dev), base_url=BASE) as client:
            request, result, token = _analysis(client, index)
            _record(client, request, result["analysis_id"], token, 0)

    def ecns(extra: dict[str, str]) -> list[str]:
        with TestClient(_app(root, "data-reset", extra={**dev, **extra}), base_url=BASE) as client:
            return [item["status"]["ecn_id"] for item in client.get("/api/ecns").json()["ecns"]]

    record(0)
    (data / "accounts.json").write_text('{"version": 3, "accounts": []}', encoding="utf-8")  # 건드리지 않아야 할 파일
    before = ecns({})
    emptied = ecns({"RIPPLE_RESET_RECORDS": "t1"})
    folder = data / "archive" / "records-t1"
    record(1)
    again = ecns({"RIPPLE_RESET_RECORDS": "t1"})
    c.check(
        "표지를 켜면 시작할 때 기록이 비고(보관 폴더에 원래 파일·DONE), 계정 파일은 그대로, 같은 표지로 다시 시작하면 "
        "새 기록을 비우지 않음",
        len(before) == 1
        and emptied == []
        and (folder / FILE_NAME).exists()
        and (folder / "DONE").exists()
        and (data / "accounts.json").exists()
        and len(again) == 1,
        (before, emptied, again, sorted(p.name for p in folder.iterdir()) if folder.exists() else None),
    )
    c.check(
        "표지 꼴(영문·숫자·_·- 1~40자)이 아니면 설정 오류로 시작하지 않음",
        c.raises(lambda: Settings.from_env({"RIPPLE_RESET_RECORDS": "../x"}), ValueError)
        and Settings.from_env({"RIPPLE_RESET_RECORDS": " "}).reset_records is None,
    )
    workspace = ("updates.sqlite3", "active.json", "mappings.json")
    for name in workspace:
        (data / name).write_text("{}", encoding="utf-8")  # 범위 records에서는 남아야 하고 all에서는 옮겨져야 할 파일
    (data / "snapshots").mkdir(exist_ok=True)
    (data / "snapshots" / "G-0000000000000000.info.json").write_text("{}", encoding="utf-8")
    kept = archive_records(data, "t2")
    left = all((data / name).exists() for name in workspace) and (data / "snapshots").exists()
    swept = archive_records(data, "t3", scope="all")
    folder3 = data / "archive" / "records-t3"
    c.check(
        "범위 all(RIPPLE_RESET_SCOPE)이면 지도 폴더·활성 지도·상태 갱신·열 매핑 기억까지 보관 폴더로, "
        "기본 범위는 그대로 둠 — 계정 파일은 어느 범위에서도 그대로",
        kept is not None
        and left
        and swept is not None
        and set(workspace) | {"snapshots"} <= set(swept)
        and (folder3 / "snapshots" / "G-0000000000000000.info.json").exists()
        and not any((data / name).exists() for name in workspace)
        and (data / "accounts.json").exists()
        and json.loads((folder3 / "DONE").read_text(encoding="utf-8"))["scope"] == "all",
        (kept, swept),
    )
    label = {"RIPPLE_RESET_RECORDS": "t9"}
    c.check(
        "범위 꼴: 표지가 있을 때만 읽음 — 비우면 records, records·all(대소문자 무시)만 받고 그 밖은 설정 오류, "
        "표지가 없으면 남은 범위 변수(오타 포함)는 무시",
        Settings.from_env(label).reset_scope == "records"
        and Settings.from_env({**label, "RIPPLE_RESET_SCOPE": "ALL"}).reset_scope == "all"
        and c.raises(lambda: Settings.from_env({**label, "RIPPLE_RESET_SCOPE": "everything"}), ValueError)
        and Settings.from_env({"RIPPLE_RESET_SCOPE": "everything"}).reset_scope == "records"
        and Settings.from_env({"RIPPLE_RESET_SCOPE": "all"}).reset_scope == "records",
    )
    c.check(
        "이미 쓴 표지의 범위를 읽음(경고용): all로 쓴 표지는 all, 기록만 쓴 표지는 records, 안 쓴 표지는 None",
        done_scope(data, "t3") == "all" and done_scope(data, "t2") == "records" and done_scope(data, "t8") is None,
    )


def _analysis(client: TestClient, index: int = 0) -> tuple[dict[str, Any], dict[str, Any], str]:
    samples = client.get("/api/samples")
    token = samples.headers["X-Ripple-Workspace"]
    request = samples.json()[index]["request"]
    result = client.post("/api/analyses", json=request, headers={"X-Ripple-Workspace": token}).json()
    return request, result, token


def _record(
    client: TestClient, request: dict[str, Any], analysis_id: str, token: str, version: int, rid: str | None = None
) -> Any:
    body = {
        "request": request,
        "analysis_id": analysis_id,
        "request_id": rid or str(uuid.uuid4()),
        "expected_version": version,
    }
    return client.post("/api/records", json=body, headers={"X-Ripple-Workspace": token})


def _action(client: TestClient, ecn: str, action: str, token: str, **extra: Any) -> Any:
    status = client.get(f"/api/ecns/{ecn}").json()["status"]
    body = {
        "action": action,
        "expected_version": status["version"],
        "revision": status["revision"],
        "record_id": status["record_id"],
        "review_seq": (status.get("review") or {}).get("seq"),
        **extra,
    }
    return client.post(f"/api/ecns/{ecn}/actions", json=body, headers={"X-Ripple-Workspace": token})


def _code(response: Any) -> str | None:
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


def _api(c: Checker, root: Path, snapshot: GraphSnapshot) -> None:
    c.section("기록: API(역할·자기 결정·분석 대조·지도 대조·전환 잠금·재시작·감사 확인)")
    app = _app(root, "api-a")
    with _client(app) as main:
        people = _people(app)
        kim, lead, park, demo = people["kim"], people["lead"], people["park"], people["demo"]
        request, result, token = _analysis(kim)
        ecn = request["change"]["ecn_id"]
        wrong = _record(kim, request, "A-0000000000000000", token, 0)
        saved = _record(kim, request, result["analysis_id"], token, 0, "22222222-2222-4222-8222-222222222222")
        retry = _record(kim, request, result["analysis_id"], token, 0, "22222222-2222-4222-8222-222222222222")
        c.check(
            "분석 ID가 다시 계산한 값과 다르면 409 analysis_changed, 기록 → 개정 1, 같은 요청 ID 재시도 = 같은 응답",
            wrong.status_code == 409
            and _code(wrong) == "analysis_changed"
            and saved.status_code == 200
            and saved.json()["revision"]["revision"] == 1
            and retry.json() == saved.json(),
        )
        demo_record = _record(demo, request, result["analysis_id"], token, 1)
        c.check("체험은 기록 불가(403)", demo_record.status_code == 403)
        review = _action(kim, ecn, "request_review", token)
        kim_approve = _action(kim, ecn, "approve", token, reason="ok")
        c.check(
            "담당자 검토 요청 → 검토, 담당자의 승인은 403 forbidden",
            review.status_code == 200 and review.json()["state"] == "in_review" and kim_approve.status_code == 403,
        )
        no_reason = _action(lead, ecn, "reject", token)
        part, boss = people["part"], people["boss"]
        boss_early = _action(boss, ecn, "approve", token, reason="확인함")
        part_ok = _action(part, ecn, "approve", token, reason="파트장 확인")
        part_again = _action(part, ecn, "approve", token, reason="확인함")
        lead_ok = _action(lead, ecn, "approve", token, reason="확인함")
        approved = _action(boss, ecn, "approve", token, reason="본부장 확인")
        signs = [e["detail"] for e in kim.get(f"/api/ecns/{ecn}").json()["audit"] if e["action"] == "approve"]
        c.check(
            "반려 사유 없음 422 reason_required → 파트장 → 팀장 → 본부장 승인(단계 밖 결재자는 403), 감사 줄에 단계",
            no_reason.status_code == 422
            and _code(no_reason) == "reason_required"
            and boss_early.status_code == 403
            and part_ok.json()["state"] == "in_review"
            and part_ok.json()["review"]["step"] == 2
            and part_ok.json()["review"]["steps"] == ["part_lead", "team_lead", "executive"]
            and part_again.status_code == 403
            and lead_ok.json()["review"]["step"] == 3
            and approved.status_code == 200
            and approved.json()["state"] == "approved"
            and [(d["step"], d["proxy"]) for d in signs]
            == [("part_lead", False), ("team_lead", False), ("executive", False)],
            (boss_early.status_code, part_again.status_code, signs),
        )
        # 통보 기록(1.28.0) — API 경로 그대로(권한·검증·거절 이유·응답 직렬화)
        current = kim.get(f"/api/ecns/{ecn}").json()["status"]
        today = (datetime.now(UTC) + timedelta(hours=9)).date()
        log = {"target": "supplier", "recipient_id": "SUP-VL1", "step": "sent", "on": today.isoformat()}

        def notice(client: TestClient, **change: Any) -> Any:
            body = {"record_id": current["record_id"], "notice": log} | change
            return client.post(f"/api/ecns/{ecn}/notices", json=body)

        sent = notice(kim)
        after = kim.get(f"/api/ecns/{ecn}").json()
        refused = [
            notice(kim, record_id="R-0000000000000000"),
            notice(kim, notice=log | {"on": (today + timedelta(days=1)).isoformat()}),
            notice(kim, notice=log | {"recipient_id": "   "}),
            notice(lead),
            notice(demo),
        ]
        c.check(
            "통보 기록 API: 담당자 200(감사 줄·날짜 왕복, 상태 버전 그대로) · 다른 개정 409 · 앞날 422 · 공백 ID 422 · "
            "팀장·체험 403",
            sent.status_code == 200
            and sent.json()["action"] == "notice"
            and sent.json()["detail"]["notice"]["on"] == today.isoformat()
            and after["status"]["version"] == current["version"]
            and after["audit"][-1]["action"] == "notice"
            and [r.status_code for r in refused] == [409, 422, 422, 403, 403]
            and _code(refused[0]) == "ecn_changed",
            [(r.status_code, _code(r)) for r in refused],
        )
        # 관리자는 결재자: 기록·검토 요청은 403. 담당자가 요청한 검토는 관리자가 결정
        # (자기 결정 금지 규칙은 흐름 검사에서 — 로그인 모드의 관리자는 이제 검토를 요청할 수 없다)
        request2, result2, token = _analysis(kim, 1)
        ecn2 = request2["change"]["ecn_id"]
        lead_record = _record(lead, request2, result2["analysis_id"], token, 0)
        _record(kim, request2, result2["analysis_id"], token, 0)
        lead_review = _action(lead, ecn2, "request_review", token)
        _action(kim, ecn2, "request_review", token)
        other = _action(park, ecn2, "hold", token, reason="자료 더 필요")
        c.check(
            "관리자의 기록·검토 요청은 403 forbidden, 담당자가 요청한 검토는 관리자가 보류 가능",
            lead_record.status_code == 403
            and lead_review.status_code == 403
            and _code(lead_review) == "forbidden"
            and other.json()["state"] == "on_hold",
        )
        # 지도 대조: 다른 지도로 바꾼 뒤 그 개정의 검토 요청·승인은 map_changed
        request3, result3, token = _analysis(kim, 2)
        ecn3 = request3["change"]["ecn_id"]
        _record(kim, request3, result3["analysis_id"], token, 0)
        holder = app.state.workspaces
        renamed = snapshot.blocks[0].model_copy(update={"name": "바뀐 블록 이름"})
        alt = snapshot.model_copy(update={"blocks": (renamed, *snapshot.blocks[1:])})
        alt = alt.model_copy(update={"snapshot_id": snapshot_id(alt)})
        assert alt.snapshot_id != snapshot.snapshot_id
        holder._store.save(alt, _info(alt))
        listing = lead.post(f"/api/snapshots/{alt.snapshot_id}/activate", headers={"X-Ripple-Workspace": token})
        token = listing.json()["workspace"]
        moved = _action(kim, ecn3, "request_review", token)
        stale_token = _action(kim, ecn3, "request_review", "G-0.old.1")
        c.check(
            "지도를 바꾼 뒤 옛 지도 개정의 검토 요청은 409 map_changed, 옛 토큰은 409 workspace_changed",
            listing.status_code == 200
            and moved.status_code == 409
            and _code(moved) == "map_changed"
            and stale_token.status_code == 409,
        )
        start_other = _action(kim, ecn, "start", token)
        c.check(
            "승인한 건은 지도가 바뀌어도 실행 시작 허용(감사 세부 other_map)",
            start_other.status_code == 200
            and kim.get(f"/api/ecns/{ecn}").json()["audit"][-1]["detail"]["other_map"] is True,
        )
        # 전환 잠금: 커밋 중(pinned)에는 지도 전환이 기다린다
        order: list[str] = []

        def switch() -> None:
            order.append("switch-start")
            lead.post(f"/api/snapshots/{snapshot.snapshot_id}/activate")
            order.append("switch-done")

        with holder.pinned(token):
            switcher = threading.Thread(target=switch)
            switcher.start()
            time.sleep(0.4)
            order.append("commit-done")
        switcher.join()
        c.check(
            "기록·결정 커밋 중 지도 전환은 커밋이 끝난 뒤에 됨",
            order == ["switch-start", "commit-done", "switch-done"],
            order,
        )
        original = app.state.records
        spy = _SpyStore(original, holder)
        app.state.records = spy
        request4, result4, token = _analysis(kim, 3)
        spied = _record(kim, request4, result4["analysis_id"], token, 0)
        spied_review = _action(kim, request4["change"]["ecn_id"], "request_review", token)
        app.state.records = original
        c.check(
            "기록 저장·검토 요청은 지도 전환 잠금을 잡은 채 저장소에 커밋",
            spied.status_code == 200
            and spied_review.status_code == 200
            and spy.seen == [("save", True), ("act", True)],
            spy.seen,
        )
        verify = lead.get("/api/audit/verify")
        c.check(
            "감사 확인: 관리자 200 정상, 담당자 403",
            verify.status_code == 200 and verify.json()["ok"] and kim.get("/api/audit/verify").status_code == 403,
            verify.json(),
        )
        listing_before = kim.get("/api/ecns").json()
        main.get("/api/health")
    app2 = _app(root, "api-a")
    with _client(app2) as again:
        _login(again, "kim", MEMBER_PW)
        c.check(
            "서버를 다시 켜도 상태·개정·감사 그대로(볼륨)",
            again.get("/api/ecns").json() == listing_before,
        )


def _after_workdays(day: date, count: int) -> date:
    """정답용: day에서 근무일(월~금) count개가 지난 날(코드의 approval.plus_workdays를 보지 않고 센다)."""
    seen = 0
    while seen < count:
        day += timedelta(days=1)
        seen += day.isoweekday() <= 5
    return day


def _submit_by(deadline: date, count: int) -> date:
    """정답: 결재 올릴 기한 = 그날부터 근무일 count개가 지나도 결정 기한을 넘지 않는 마지막 근무일(불변식을 기한부터
    하루씩 거꾸로 찾음 — 코드의 '마지막 근무일로 내린 뒤 빼기' 셈을 보지 않는다)."""
    day = deadline
    while not (day.isoweekday() <= 5 and _after_workdays(day, count) <= deadline):
        day -= timedelta(days=1)
    return day


def _submit_rule(c: Checker) -> None:
    c.section("기록: 결재 올릴 기한 불변식(주말 기한 포함, docs/records.md(기록·결재) 14절)")
    start = date(2026, 1, 5)  # 월요일부터 400일(토·일 기한 114개 포함)
    bad = [
        (deadline.isoformat(), n, got.isoformat())
        for deadline in (start + timedelta(days=i) for i in range(400))
        for n in range(9)
        if (got := submit_by_of(deadline, n)) != _submit_by(deadline, n)
        or _after_workdays(got, n) > deadline
        or got.isoweekday() > 5
        or plus_workdays(got, n) > deadline
    ]
    saturday = date(2026, 11, 7)
    c.check(
        "400일 × 근무일 0~8: plus_workdays(결재 올릴 기한, n) ≤ 결정 기한, 기한은 근무일, 그다음 근무일은 기한을 넘김"
        "(독립 셈과 같음) · 토요일(11-07) 기한 6근무일 = 10-29(목)(10-30이면 결재가 11-09 월요일에 끝나 기한을 넘김)",
        not bad
        and submit_by_of(saturday, 6) == date(2026, 10, 29)
        and plus_workdays(date(2026, 10, 29), 6) == date(2026, 11, 6)
        and plus_workdays(date(2026, 10, 30), 6) > saturday,
        bad[:5],
    )


def _plan_stub(deadline: date, kind: DeadlineKind = DeadlineKind.BY_DATE) -> AnalysisResult:
    """결재 계획 계산에 쓰는 칸만 있는 분석 결과(추가 비용 건 — 결재선 3단계): 결정 기한·곡선·보류 권고 없음."""
    line = SimpleNamespace(rule_id="C-01", determinacy=Determinacy.KNOWN)
    return cast(
        AnalysisResult,
        SimpleNamespace(
            cost_lines=(line,),
            schedule=SimpleNamespace(delivery=None, risk=None),
            verdict=SimpleNamespace(level=VerdictLevel.APPROVE),
            timing=SimpleNamespace(deadline=SimpleNamespace(kind=kind, last_day=deadline), curve=(), holds=()),
            request=SimpleNamespace(as_of=deadline),
        ),
    )


def _last_weekday(day: date) -> date:
    """정답용: day 이하 마지막 근무일(코드의 approval.last_workday를 보지 않고 센다)."""
    while day.isoweekday() > 5:
        day -= timedelta(days=1)
    return day


def _plan_low(c: Checker) -> None:
    c.section("기록: 단계당 1일 결재 올릴 기한·지남·결정 기한의 근무일(결재 계획 1.33.0)")
    start = date(2026, 1, 5)
    bad = []
    in_review = cast(Any, SimpleNamespace(steps=APPROVAL_LINE, step=2))  # 파트장 승인 뒤 팀장 차례(남은 2단계)
    for deadline in (start + timedelta(days=i) for i in range(400)):
        for today in (deadline - timedelta(days=gap) for gap in range(12)):  # 업무상 오늘 = 모든 요일(토·일 포함)
            for review in (None, in_review):
                plan = approval_plan(_plan_stub(deadline), today, review)
                n = len(plan.steps) * DAYS_PER_STEP_LOW
                low, workday = plan.submit_by_low, plan.decide_by_workday
                expected_workday = _last_weekday(deadline) if _last_weekday(deadline) >= today else None
                if (
                    low is None
                    or plan.submit_by is None
                    or low != _submit_by(deadline, n)
                    or plus_workdays(low, n) > deadline
                    or low.isoweekday() > 5
                    or low < plan.submit_by
                    or plan.late_low != (_after_workdays(today, n) > deadline)
                    or plan.late != (_after_workdays(today, plan.workdays) > deadline)
                    or (today.isoweekday() <= 5 and plan.late != (plan.submit_by < today))
                    or (today.isoweekday() <= 5 and plan.late_low != (low < today))
                    or (plan.late_low and not plan.late)
                    or workday != expected_workday
                    or (workday is not None and (workday.isoweekday() > 5 or _after_workdays(workday, 1) <= deadline))
                ):
                    bad.append((deadline.isoformat(), today.isoformat(), review is None, low, plan.late, workday))
    empty = approval_plan(_plan_stub(start, DeadlineKind.NONE_IN_HORIZON), start, None)
    sunday = approval_plan(_plan_stub(date(2026, 11, 8)), date(2026, 10, 28), None)
    c.check(
        "400일 × 업무상 오늘 12가지(토·일 포함) × 검토 전·검토 중: 단계당 1일 기한 = 남은 단계 × 1근무일 뒤가 "
        "결정 기한을 넘지 않는 마지막 근무일(독립 셈·최대성), 대표 기한 이후 · 지남 = 오늘 올려도 결재가 "
        "결정 기한 안에 끝나지 않음(대표·단계당 1일 모두, 오늘이 평일이면 '기한 < 오늘'과 같음, "
        "단계당 1일이 지났으면 대표도 지남) · "
        "결정 기한의 근무일 = 기한 이하 마지막 근무일(다음 근무일은 기한을 넘김, 업무상 오늘보다 앞이면 없음) · "
        "손실 없음이면 둘 다 없음 · 일요일(11-08) 기한 → 금요일(11-06)",
        not bad
        and (empty.submit_by_low, empty.late_low, empty.decide_by_workday) == (None, False, None)
        and sunday.decide_by_workday == date(2026, 11, 6)
        and sunday.submit_by_low == date(2026, 11, 3),
        bad[:5],
    )
    _weekend_late(c)


def _weekend_late(c: Checker) -> None:
    """업무상 오늘이 토·일(실시간 세계·실데이터 = KST 오늘)이고 결재 올릴 기한이 바로 앞 금요일이면
    오늘 올려도 결정이 결정 기한 당일이라 '지났어요'가 아니다(월요일부터 진짜 지남). S-제안3: 업무상 오늘 토요일 ·
    결정 기한 일요일이면 결정 기한의 근무일(금요일)이 오늘보다 앞이라 없음."""
    monday = date(2026, 11, 9)
    plans = {
        today: approval_plan(_plan_stub(monday), today, None)
        for today in (date(2026, 10, 30), date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 2))
    }
    weekend = [plans[date(2026, 10, 31)], plans[date(2026, 11, 1)]]
    friday, monday_after = plans[date(2026, 10, 30)], plans[date(2026, 11, 2)]
    saturday = approval_plan(_plan_stub(date(2026, 10, 25)), date(2026, 10, 24), None)
    c.check(
        "결정 기한 11-09(월) · 결재 올릴 기한 10-30(금): 금·토·일에 올리면 결정 11-09 = 기한 안(지남 아님), "
        "월(11-02)부터 지남(빨라야 11-10) · 업무상 오늘 10-24(토)·결정 기한 10-25(일)이면 결정 기한의 근무일 없음",
        all(p.submit_by == date(2026, 10, 30) for p in plans.values())
        and all(not p.late and not p.late_low and p.earliest is None for p in (friday, *weekend))
        and all(plus_workdays(t, 6) == monday for t in (date(2026, 10, 30), date(2026, 10, 31), date(2026, 11, 1)))
        and monday_after.late
        and monday_after.earliest == date(2026, 11, 10)
        and saturday.decide_by_workday is None
        and approval_plan(_plan_stub(date(2026, 10, 25)), date(2026, 10, 23), None).decide_by_workday
        == date(2026, 10, 23),
        {str(t): (p.late, p.late_low, p.earliest) for t, p in plans.items()},
    )


def _api_line(c: Checker, root: Path, generated: Any) -> None:
    c.section("기록: API 결재선 — 결재 계획(결재 올릴 기한)·무비용 담당자 처리·팀장 전결")
    app = _app(root, "api-line")
    free = next(e for e in generated.ecns if e.change.ecn_id == "ECN-D-0007")  # 비용 줄이 도면 개정뿐(무비용)
    with _client(app):
        people = _people(app)
        kim, lead, part = people["kim"], people["lead"], people["part"]
        request, result, token = _analysis(kim, 0)
        ecn = request["change"]["ecn_id"]
        _record(kim, request, result["analysis_id"], token, 0)
        plan = kim.get(f"/api/ecns/{ecn}").json()["approval_plan"]
        deadline = result["timing"]["deadline"]
        expected = (
            None if deadline["kind"] == "none_in_horizon" else _submit_by(date.fromisoformat(deadline["last_day"]), 6)
        )
        refused = _action(kim, ecn, "settle", token, reason="무비용")
        c.check(
            "추가 비용 건: 결재 계획 = 결재선(line) 3단계 × 2근무일(1~2일), 결재 올릴 기한 = 6근무일 뒤가 결정 기한을 "
            "넘지 않는 마지막 근무일(독립 셈), 기록 전 분석 응답과 같은 값, "
            "담당자 처리는 409",
            plan["no_cost"] is False
            and plan["line"] == ["part_lead", "team_lead", "executive"]
            and plan["steps"] == ["part_lead", "team_lead", "executive"]
            and (plan["days_per_step_low"], plan["days_per_step"], plan["workdays"]) == (1, 2, 6)
            and plan["submit_by"] == (expected.isoformat() if expected else None)
            and result.get("approval_plan") == plan  # 기록 전 분석 응답의 결재 계획 = 기록 뒤 상세(서버 한 곳 규칙)
            and refused.status_code == 409
            and _code(refused) == "invalid_transition",
            (plan, expected, refused.status_code),
        )
        _action(kim, ecn, "request_review", token)
        proxied = _action(lead, ecn, "approve", token, reason="파트장 부재로 전결")
        after = kim.get(f"/api/ecns/{ecn}").json()
        looked = kim.get(f"/api/records/{after['status']['record_id']}").json()
        c.check(
            "검토 중 기록 조회(판단 리포트)의 결재 계획 = 상세(남은 2단계 · 넘길 기한 같음)",
            looked["approval_plan"] == after["approval_plan"] and looked["approval_plan"]["workdays"] == 4,
            (looked["approval_plan"], after["approval_plan"]),
        )
        c.check(
            "팀장 전결: 파트장 단계를 팀장이 승인 → 2/3단계, 감사 세부 proxy·원래 단계, 남은 결재 2단계 계획",
            proxied.status_code == 200
            and after["status"]["review"]["step"] == 2
            and after["audit"][-1]["detail"]["proxy"] is True
            and after["audit"][-1]["detail"]["step"] == "part_lead"
            and after["approval_plan"]["steps"] == ["team_lead", "executive"]
            and after["approval_plan"]["line"] == ["part_lead", "team_lead", "executive"]
            and after["approval_plan"]["workdays"] == 4
            and _action(part, ecn, "approve", token, reason="늦게 확인").status_code == 403,
            after["approval_plan"],
        )
        body = {"change": free.change.model_dump(mode="json"), "as_of": free.as_of.isoformat()}
        free_result = kim.post("/api/analyses", json=body, headers={"X-Ripple-Workspace": token}).json()
        _no_cost_rule(c, AnalysisResult.model_validate(free_result))
        _record(kim, free_result["request"], free_result["analysis_id"], token, 0)
        free_plan = kim.get(f"/api/ecns/{free.change.ecn_id}").json()["approval_plan"]
        record_plan = kim.get(
            f"/api/records/{kim.get(f'/api/ecns/{free.change.ecn_id}').json()['status']['record_id']}"
        )
        _free_review(c, kim, free.change.ecn_id, token)
        lead_settle = _action(lead, free.change.ecn_id, "settle", token, reason="무비용")
        settled = _action(kim, free.change.ecn_id, "settle", token, reason="도면 개정만 있어 담당자 처리")
        last = kim.get(f"/api/ecns/{free.change.ecn_id}").json()["audit"][-1]
        c.check(
            "무비용 건(비용 줄이 도면 개정뿐): 계획 no_cost·결재 단계 없음·결재 올릴 기한 없음 → 팀장 403, "
            "담당자 처리 200 승인(감사 세부 no_cost) → 실행 가능",
            free_plan["no_cost"] is True
            and free_plan["steps"] == []
            and free_plan["line"] == ["part_lead", "team_lead", "executive"]  # 검토를 올리면 고정될 결재선
            and free_plan["line_steps"] == 0
            and free_plan["submit_by"] is None
            and free_result.get("approval_plan") == free_plan
            and record_plan.json().get("approval_plan") == free_plan
            and lead_settle.status_code == 403
            and settled.status_code == 200
            and settled.json()["state"] == "approved"
            and last["action"] == "settle"
            and last["detail"]["no_cost"] is True
            and _action(kim, free.change.ecn_id, "start", token).json()["state"] == "in_progress",
            (free_plan, lead_settle.status_code, settled.status_code),
        )
        verify = lead.get("/api/audit/verify").json()
        c.check("결재선·전결·담당자 처리 뒤 감사 확인 ok", verify["ok"] is True, verify["problems"])


def _no_cost_rule(c: Checker, free: AnalysisResult) -> None:
    """무비용 = 비용 줄이 도면 개정뿐 + 판정 '승인 가능'(경고·검토 필요면 결재선, docs/records.md(기록·결재) 14절)."""
    verdicts = {
        level: free.model_copy(update={"verdict": free.verdict.model_copy(update={"level": level})})
        for level in VerdictLevel
    }
    c.check(
        "무비용 판정: 도면 개정 줄뿐 + 승인 가능이면 무비용, 같은 줄이라도 판정이 검토 필요·경고면 결재선(무비용 아님)",
        {f.rule_id for f in free.cost_lines} <= {"R-D01"}
        and free.verdict.level is VerdictLevel.APPROVE
        and {level: no_cost(r) for level, r in verdicts.items()}
        == {VerdictLevel.APPROVE: True, VerdictLevel.REVIEW: False, VerdictLevel.WARN: False},
    )


def _free_review(c: Checker, kim: TestClient, ecn: str, token: str) -> None:
    """무비용 개정을 검토 요청하면 결재 계획도 결재선 기준(남은 단계·결재 기간 모두 3단계) → 취소하면 다시 무비용."""
    review = _action(kim, ecn, "request_review", token)
    plan = kim.get(f"/api/ecns/{ecn}").json()["approval_plan"]
    withdrawn = _action(kim, ecn, "withdraw", token)
    back = kim.get(f"/api/ecns/{ecn}").json()["approval_plan"]
    c.check(
        "검토 중인 무비용 개정: 계획 = 결재선 3단계(남은 단계·line_steps 3, 보류 권고 문구도 결재 기간) · 검토 취소 뒤 "
        "다시 무비용(남은 단계 없음)",
        review.status_code == 200
        and plan["no_cost"] is True
        and plan["steps"] == plan["line"] == ["part_lead", "team_lead", "executive"]
        and plan["line_steps"] == 3
        and plan["workdays"] == 6
        and all(h["text"] != "담당자 처리 — 결재 없음" for h in plan["holds"])
        and withdrawn.status_code == 200
        and back["steps"] == []
        and back["line_steps"] == 0,
        (plan, back),
    )


RETRY_ID = "33333333-3333-4333-8333-333333333333"


def _api_version(c: Checker, root: Path) -> None:
    c.section("기록: API 계산 판(판이 바뀐 진행 중 검토 — 반려·보류만, 다시 기록하면 검토 요청)")
    app = _app(root, "api-v")
    with _client(app):
        people = _people(app)
        kim, lead = people["kim"], people["lead"]
        ecns: list[str] = []
        for index in (0, 1, 2):
            request, result, token = _analysis(kim, index)
            ecn = request["change"]["ecn_id"]
            ecns.append(ecn)
            _record(kim, request, result["analysis_id"], token, 0)
        first, second, third = ecns
        first_request, first_result, _token = _analysis(kim, 0)
        replayed = _record(
            kim, first_request, first_result["analysis_id"], token, 1, RETRY_ID
        )  # 같은 본문 → 새 개정 없음
        for ecn in (first, third):
            _action(kim, ecn, "request_review", token)
        before = kim.get(f"/api/ecns/{first}").json()["same_version"]
        context = app.state.context
        # 파라미터 판만 올린 앱(현업 답으로 파라미터를 고친 배포와 같은 상황): 지도는 그대로
        app.state.context = replace(context, params=context.params.model_copy(update={"version": "next-params"}))
        after = kim.get(f"/api/ecns/{first}").json()["same_version"]
        c.check("상세의 same_version: 같은 판 True → 파라미터 판이 바뀐 뒤 False", before is True and after is False)
        retry = _record(kim, first_request, first_result["analysis_id"], token, 1, RETRY_ID)
        c.check(
            "판이 바뀐 뒤 같은 저장 요청 재시도 = 다시 계산하지 않고 처음 응답(개정 수 그대로)",
            retry.status_code == 200
            and retry.json() == replayed.json()
            and len(kim.get(f"/api/ecns/{first}").json()["revisions"]) == 1,
            (retry.status_code, _code(retry)),
        )
        approve = _action(lead, first, "approve", token, reason="확인함")
        reject = _action(lead, first, "reject", token, reason="이전 판 기록이라 다시 검토")
        audit = lead.get(f"/api/ecns/{first}").json()["audit"]
        c.check(
            "판이 바뀐 검토의 승인은 409 version_changed, 반려는 200 + 감사 세부 other_version",
            approve.status_code == 409
            and _code(approve) == "version_changed"
            and reject.status_code == 200
            and reject.json()["state"] == "rejected"
            and audit[-1]["action"] == "reject"
            and audit[-1]["detail"]["other_version"] is True,
        )
        hold = _action(lead, third, "hold", token, reason="이전 판 기록이라 보류")
        held_approve = _action(lead, third, "approve", token, reason="확인함")
        c.check(
            "판이 바뀐 검토의 보류는 200(other_version), 보류 뒤 승인도 409 version_changed",
            hold.status_code == 200
            and lead.get(f"/api/ecns/{third}").json()["audit"][-1]["detail"]["other_version"] is True
            and _code(held_approve) == "version_changed",
        )
        stale_review = _action(kim, second, "request_review", token)
        request, result, token = _analysis(kim, 1)
        version = kim.get(f"/api/ecns/{second}").json()["status"]["version"]
        again = _record(kim, request, result["analysis_id"], token, version)
        fresh_review = _action(kim, second, "request_review", token)
        c.check(
            "이전 판 개정의 검토 요청은 409 version_changed → 지금 판으로 다시 기록(개정 2)하면 검토 요청 200",
            _code(stale_review) == "version_changed"
            and again.status_code == 200
            and again.json()["revision"]["revision"] == 2
            and kim.get(f"/api/ecns/{second}").json()["same_version"] is True
            and fresh_review.status_code == 200,
        )
        verify = lead.get("/api/audit/verify").json()
        c.check("판이 바뀐 결정·다시 기록 뒤에도 감사 확인 ok", verify["ok"] is True, verify["problems"])


def _api_dev(c: Checker, root: Path) -> None:
    c.section("기록: 개발 모드(로그인 끔) — 자기 결정은 받되 표시, 그 승인으로는 로그인 모드에서 실행 불가")
    app = _app(root, "api-dev", extra={"RIPPLE_AUTH": "off"})
    with _client(app) as dev:
        request, result, token = _analysis(dev)
        ecn = request["change"]["ecn_id"]
        _record(dev, request, result["analysis_id"], token, 0)
        _action(dev, ecn, "request_review", token)
        approved = _approve_line(dev, ecn, token, reason="개발 모드 확인")  # 개발 모드는 모든 단계를 자기 단계로
        last = dev.get(f"/api/ecns/{ecn}").json()["audit"][-1]
        c.check(
            "개발 모드: 요청자가 직접 승인 200, 감사 줄에 개발 모드·자기 결정, 상태에 개발 모드 승인",
            approved.status_code == 200
            and approved.json()["approval_dev"] is True
            and last["detail"]["self_decision"] is True
            and last["actor"]["dev"] is True,
            approved.json(),
        )
    app2 = _app(root, "api-dev")  # 같은 볼륨, 로그인 켬
    with _client(app2):
        lead = _client(app2)
        _login(lead, "lead", FIRST)
        lead.post("/api/auth/password", json={"current_password": FIRST, "new_password": ADMIN_PW})
        kim = _staff(app2, lead, "kim", "member", MEMBER_PW)  # 실행·검토 요청은 담당자 일
        _, _, token = _analysis(kim)
        start = _action(kim, ecn, "start", token)
        again = _action(kim, ecn, "request_review", token)
        c.check(
            "로그인 모드: 개발 모드 승인으로 실행 시작은 409 dev_approval, 다시 검토 요청은 됨",
            start.status_code == 409 and _code(start) == "dev_approval" and again.json().get("state") == "in_review",
            (start.status_code, again.status_code),
        )


def _info(snapshot: GraphSnapshot) -> Any:
    from ripple.api.workspace import info_of

    return info_of(snapshot, "시험 지도")


def _api_real(c: Checker, root: Path, snapshot: GraphSnapshot) -> None:
    c.section("기록: 실데이터 기록은 체험에게 보이지 않음(목록·상세·기록 조회)")
    app = _app(root, "api-real", extra={"RIPPLE_DATA_MODE": "real"})
    with _client(app):
        lead = _client(app)
        _login(lead, "lead", FIRST)
        lead.post("/api/auth/password", json={"current_password": FIRST, "new_password": ADMIN_PW})
        kim = _staff(app, lead, "kim", "member", MEMBER_PW)  # 기록은 담당자 일(관리자는 결재자)
        request, result, token = _analysis(kim)
        saved = _record(kim, request, result["analysis_id"], token, 0)
        record_id = saved.json()["revision"]["record_id"]
    app2 = _app(root, "api-real")  # 같은 볼륨, 합성 설정으로 다시 켬 → 체험 로그인 가능
    with _client(app2):
        demo = _client(app2)
        demo.post("/api/auth/demo")
        ecn = request["change"]["ecn_id"]
        c.check(
            "실데이터 설정에서 남긴 기록: 체험 목록에 없음, 상세·기록 조회 404",
            saved.json()["status"]["real"]
            and demo.get("/api/ecns").json()["ecns"] == []
            and demo.get(f"/api/ecns/{ecn}").status_code == 404
            and demo.get(f"/api/records/{record_id}").status_code == 404,
        )
