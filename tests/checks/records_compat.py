"""옛 판 기록 저장소 호환(docs/records.md(기록·결재) 4절): 계약 1.17.0·엔진 0.4.1 코드로 만든 저장소 고정 파일
(tests/compat/records_contract_1.17.0.sql — 합성 지도 표본 요청, 상태가 다른 ECN 8개)을 지금 코드로 열어 본다.

저장되는 모델(개정 요약·상태·저장 응답·감사 줄·기록 본문)이 옛 판 그대로 읽히고 감사 확인이 통과하는지,
판이 바뀐 개정에 계산 판 규칙(검토 요청·승인 409 version_changed, 반려·보류 허용)이 걸리는지 본다.
고정 파일은 옛 판의 증거라 다시 만들지 않는다.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

from harness import Checker

from ripple.api.deps import AppContext
from ripple.api.records import same_version_of
from ripple.contracts.base import CONTRACT_VERSION
from ripple.contracts.records import ApprovalStep, EcnAction, EcnState, RecordBody, RecordSaved
from ripple.contracts.result import AnalysisResult
from ripple.generator.build import generate
from ripple.generator.io import load_config, write_outputs
from ripple.records.flow import FlowError, Who
from ripple.store.records import FILE_NAME, FORMAT_VERSION, RecordStore

from .records import (
    ADMIN_WHO,
    MEMBER_WHO,
    OTHER_ADMIN,
    _actor,
    _app,
    _body,
    _client,
    _Clock,
    _code,
    _do,
    _people,
    _record,
    _results,
    _settings_for,
)

FIXTURE = Path(__file__).resolve().parents[1] / "compat" / "records_contract_1.17.0.sql"
OLD_CONTRACT = "1.17.0"
STATES = {
    "OLD-ANALYZED": EcnState.ANALYZED,
    "OLD-APPROVED": EcnState.APPROVED,
    "OLD-CLOSED": EcnState.CLOSED,
    "OLD-DEV": EcnState.APPROVED,
    "OLD-HOLD": EcnState.ON_HOLD,
    "OLD-REJECTED": EcnState.REJECTED,
    "OLD-REVIEW": EcnState.IN_REVIEW,
    "OLD-REVISED": EcnState.ANALYZED,
}
A = EcnAction
Same = Callable[[RecordBody], bool]


def run(c: Checker) -> None:
    c.section("기록: 옛 판 저장소 호환(계약 1.17.0 고정 파일을 지금 코드로 — 읽기·감사·재시도·결정)")
    generated = generate(load_config())
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        write_outputs(generated, root / "synthetic")
        context = AppContext.load(_settings_for(root, "ctx"))
        same = same_version_of(context)
        _api_retry(c, root)
        store = _open(root / "old")
        _reads(c, store, same)
        _retries(c, store)
        _decisions(c, store, same)
        _after(c, store, same, _results(root)[0])


def _unpack(folder: Path) -> None:
    folder.mkdir()
    with closing(sqlite3.connect(folder / FILE_NAME)) as db:
        db.executescript(FIXTURE.read_text(encoding="utf-8"))


def _version(folder: Path) -> int:
    with closing(sqlite3.connect(folder / FILE_NAME)) as db:
        return int(db.execute("PRAGMA user_version").fetchone()[0])


def _open(folder: Path) -> RecordStore:
    _unpack(folder)
    store = RecordStore(folder, clock=_Clock())
    store.start()  # 형식 판 1 → 4(표·본문·감사 사슬은 그대로)
    return store


def _api_retry(c: Checker, root: Path) -> None:
    """옛 판 저장소로 앱을 띄워 그때 커밋된 저장 요청을 지금 작업 공간 토큰으로 다시 보낸다(계산 전에 처음 응답)."""
    _unpack(root / "api-old")
    before = _version(root / "api-old")
    rows = _raw_rows(root / "api-old")
    app = _app(root, "api-old")
    with _client(app):
        after = _version(root / "api-old")
        kim = _people(app)["kim"]
        token = kim.get("/api/samples").headers["X-Ripple-Workspace"]
        same: list[bool] = []
        for request_id, _ecn, analysis_id, response in rows:
            stored = json.loads(response)
            body = kim.get(f"/api/records/{stored['revision']['record_id']}").json()["body"]
            again = _record(kim, body["result"]["request"], analysis_id, token, 0, request_id)
            same.append(again.status_code == 200 and again.json() == stored)
        revisions = sum(len(kim.get(f"/api/ecns/{e}").json()["revisions"]) for e in {r[1] for r in rows})
        request = kim.get(f"/api/records/{json.loads(rows[0][3])['revision']['record_id']}").json()["body"]["result"]
        reused = _record(kim, request["request"], "A-0000000000000000", token, 0, rows[0][0])
        fresh = _record(kim, request["request"], rows[0][2], token, 0, "44444444-4444-4444-8444-444444444444")
    c.check(
        f"앱 시작이 옛 저장소 형식 판을 {before} → {after}로 올림(옛 코드는 시작을 멈춤)",
        before == 1 and after == FORMAT_VERSION == 4,
        (before, after),
    )
    c.check(
        "API 재시도: 옛 판의 저장 요청 9건을 같은 ID로 다시 보내면 처음 응답 그대로(다시 계산 안 함), 개정 수 9 그대로",
        len(rows) == 9 and all(same) and revisions == 9,
        (same, revisions),
    )
    c.check(
        "같은 요청 ID에 다른 분석 ID면 422 request_reused, 새 요청 ID에 옛 분석 ID면 다시 계산해 409 analysis_changed",
        reused.status_code == 422
        and _code(reused) == "request_reused"
        and fresh.status_code == 409
        and _code(fresh) == "analysis_changed",
        (reused.status_code, _code(reused), fresh.status_code, _code(fresh)),
    )


def _raw_rows(folder: Path) -> list[tuple[str, str, str, str]]:
    with closing(sqlite3.connect(folder / FILE_NAME)) as db:
        return [
            (str(a), str(b), str(c_), str(d))
            for a, b, c_, d in db.execute(
                "SELECT request_id, ecn_id, analysis_id, response FROM requests ORDER BY request_id"
            )
        ]


def _raw(store: RecordStore, sql: str) -> list[tuple[str, ...]]:
    with closing(sqlite3.connect(store.path)) as db:
        return [tuple(row) for row in db.execute(sql)]


def _reads(c: Checker, store: RecordStore, same: Same) -> None:
    bodies = [store.record(rid, include_real=True) for (rid,) in _raw(store, "SELECT record_id FROM records")]
    contracts = {found.body.result.versions.contract for found in bodies if found is not None}
    risks = {found.body.result.schedule.risk for found in bodies if found is not None}
    c.check(
        "고정 파일은 옛 계약 판(1.17.0)이고 지금 판은 다름 — 기록 본문 9개가 모두 지금 계약으로 읽힘(일정 위험 없음)",
        contracts == {OLD_CONTRACT}
        and CONTRACT_VERSION != OLD_CONTRACT
        and len(bodies) == 9
        and None not in bodies
        and risks == {None},
        (contracts, CONTRACT_VERSION, len(bodies), len(risks)),
    )
    c.check(
        f"저장소를 열면 형식 판 {FORMAT_VERSION}(판 1에서 올림)", _version(store.path.parent) == FORMAT_VERSION == 4
    )
    listing = store.listing(include_real=True)
    states = {item.status.ecn_id: item.status.state for item in listing.ecns}
    c.check("목록: 8개 ECN이 저장된 상태 그대로(개정 요약 포함)", states == STATES, states)
    details = {ecn: store.detail(ecn, include_real=True, same_version=same) for ecn in STATES}
    c.check(
        "상세: 모두 읽히고 계산 판은 이전 판(same_version False), 개정·감사 줄 수가 저장 그대로",
        all(d is not None and d.same_version is False for d in details.values())
        and [len(d.revisions) for d in details.values() if d] == [1, 1, 1, 1, 1, 1, 1, 2]
        and sum(len(d.audit) for d in details.values() if d) == 23,
    )
    reviews = {ecn: d.status.review for ecn, d in details.items() if d is not None and d.status.review is not None}
    c.check(
        "결재선 전 검토(검토·보류)는 팀장 한 단계로 읽힘(1/1단계, 형식 판 4의 결재선 칸 없음)",
        set(reviews) == {"OLD-REVIEW", "OLD-HOLD"}
        and all(
            (r.steps, r.step, r.current) == ((ApprovalStep.TEAM_LEAD,), 1, ApprovalStep.TEAM_LEAD)
            for r in reviews.values()
        ),
        reviews,
    )
    check = store.verify()
    c.check(
        "감사 확인: 사슬·본문 해시·개정 요약 = 본문·투영 = 재생 모두 통과(문제 0)",
        check.ok and not check.problems and check.entries == 23 and check.records == 9,
        check.problems,
    )


def _retries(c: Checker, store: RecordStore) -> None:
    rows = _raw(store, "SELECT request_id, ecn_id, analysis_id, response FROM requests ORDER BY request_id")
    same_answer: list[bool] = []
    for request_id, _ecn, analysis_id, response in rows:
        saved = RecordSaved.model_validate_json(response)
        found = store.record(saved.revision.record_id, include_real=True)
        assert found is not None
        again = store.save(
            found.body,
            _actor(MEMBER_WHO),
            MEMBER_WHO,
            request_id=request_id,
            analysis_id=analysis_id,
            expected_version=0,  # 재시도는 기대 버전과 상관없이 처음 응답을 받는다
        )
        same_answer.append(again.model_dump(mode="json") == json.loads(response))
    c.check(
        "같은 저장 요청 재시도: 옛 저장 응답 9개를 그대로 돌려줌(저장 모델에 새 필드 없음)",
        len(rows) == 9 and all(same_answer),
        (len(rows), same_answer),
    )


def _try(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    try:
        fn(*args, **kwargs)
    except FlowError as error:
        return error.code
    return "ok"


def _snapshot(store: RecordStore, ecn: str) -> str:
    status = next(item.status for item in store.listing(include_real=True).ecns if item.status.ecn_id == ecn)
    found = store.record(status.record_id, include_real=True)
    assert found is not None
    return found.body.snapshot_id


def _decisions(c: Checker, store: RecordStore, same: Same) -> None:
    def do(ecn: str, action: EcnAction, who: Who, **kw: Any) -> str:
        return _try(_do, store, ecn, action, who, snapshot=_snapshot(store, ecn), same_version=same, **kw)

    keys = frozenset({"analysis:1:delivery", "analysis:2:delivery"})
    blocked = [
        do("OLD-REVIEW", A.APPROVE, ADMIN_WHO, acknowledged=keys, reason="확인함"),
        do("OLD-HOLD", A.APPROVE, ADMIN_WHO),
        do("OLD-ANALYZED", A.REQUEST_REVIEW, MEMBER_WHO),
        do("OLD-DEV", A.REQUEST_REVIEW, MEMBER_WHO),  # 개발 모드 승인을 업무 계정으로 다시 받기
    ]
    c.check(
        "이전 판 개정: 승인(검토·보류)·검토 요청(분석·개발 승인 다시 받기)은 409 version_changed",
        blocked == ["version_changed"] * 4,
        blocked,
    )
    allowed = [
        do("OLD-REVIEW", A.REJECT, OTHER_ADMIN, reason="이전 판 기록"),
        do("OLD-HOLD", A.REJECT, OTHER_ADMIN, reason="이전 판 기록"),
        do("OLD-APPROVED", A.START, MEMBER_WHO),
    ]
    flags = {
        ecn: (detail.audit[-1].detail.other_version if detail else None)
        for ecn in ("OLD-REVIEW", "OLD-HOLD", "OLD-APPROVED")
        for detail in [store.detail(ecn, include_real=True, same_version=same)]
    }
    c.check(
        "이전 판 개정: 반려(검토·보류)는 받고 other_version, 승인된 개정의 실행 시작은 표시 없이 받음",
        allowed == ["ok"] * 3 and flags == {"OLD-REVIEW": True, "OLD-HOLD": True, "OLD-APPROVED": False},
        (allowed, flags),
    )


def _after(c: Checker, store: RecordStore, same: Same, fresh: AnalysisResult) -> None:
    body = _body(fresh, ecn="OLD-REVISED")
    status = next(i.status for i in store.listing(include_real=True).ecns if i.status.ecn_id == "OLD-REVISED")
    saved = store.save(
        body,
        _actor(MEMBER_WHO),
        MEMBER_WHO,
        request_id="00000000-0000-4000-8000-000000000099",
        analysis_id=body.result.analysis_id,
        expected_version=status.version,
    )
    review = _try(_do, store, "OLD-REVISED", A.REQUEST_REVIEW, MEMBER_WHO, snapshot=body.snapshot_id, same_version=same)
    detail = store.detail("OLD-REVISED", include_real=True, same_version=same)
    check = store.verify()
    c.check(
        "옛 저장소에 지금 판 개정(3)을 더하면 같은 판 → 검토 요청 받음, 그 뒤에도 감사 확인 통과",
        saved.created
        and saved.revision.revision == 3
        and review == "ok"
        and detail is not None
        and detail.same_version is True
        and detail.status.state is EcnState.IN_REVIEW
        and check.ok
        and not check.problems,
        (review, check.problems),
    )
