"""문서 접수(계약 1.27.0, docs/input.md(문서 접수))와 수정 기록 요약.

- POST /intake/proposals(보기): 붙여 넣은 문서 → 확인표 제안(항목·문제·후보). 외부 AI 호출은 이 계정의 몫으로 센다.
- POST /intake/proposals/xlsx?ship_ids=(보기): 변경 리스트 엑셀 → 같은 제안.
- POST /intake/confirmations(보기): 항목별 맞음·고침·뺌 → 서버 확정 검증 → 분석 결과. 확정하지 못하면 422(항목별 이유),
  제안이 없거나 지도가 바뀌었으면 409. 사람 결정은 수정 기록에 남긴다(실패해도 분석 응답은 그대로).
- GET /corrections/summary(승인(결재자)): 칸·채움 방식별 사람이 고친 비율(체험·개발 모드 행은 빼고 개수만).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from starlette.concurrency import run_in_threadpool

from ripple.agent.intake import Actor, ExistingLookup, IntakeError, IntakeProblems
from ripple.auth import Principal
from ripple.contracts.corrections import CorrectionSummary
from ripple.contracts.intake import (
    ExistingEcn,
    IntakeConfirmation,
    IntakeProposal,
    IntakeResult,
    IntakeTextInput,
)
from ripple.contracts.records import EcnState
from ripple.ingest.workbook import read_workbook
from ripple.llm.quota import acting_as
from ripple.store.corrections import CorrectionLog, CorrectionLogError, summarize
from ripple.store.records import RecordStore

from ..security import AUTH_RESPONSES, ApprovePrincipal, ViewPrincipal
from ..workspace import Workspace, get_workspace
from .snapshots import upload_bytes

router = APIRouter(tags=["intake"])
log = logging.getLogger("ripple.intake")
LOCKED = (EcnState.IN_PROGRESS, EcnState.CLOSED)
INTAKE_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_RESPONSES,
    409: {"description": "제안이 없거나(지도가 바뀌었거나 2시간이 지남) 이어 갈 수 없는 설계변경"},
    422: {"description": "문서 형식·상한 문제, 또는 확정할 수 없는 항목(detail = message + problems '항목 ID: 이유')"},
}


def get_corrections(request: Request) -> CorrectionLog:
    return request.app.state.corrections  # type: ignore[no-any-return]


Corrections = Annotated[CorrectionLog, Depends(get_corrections)]
WorkspaceDep = Annotated[Workspace, Depends(get_workspace)]


def _existing(request: Request, principal: Principal) -> ExistingLookup:
    records: RecordStore = request.app.state.records

    def lookup(ecn_id: str) -> ExistingEcn | None:
        for item in records.listing(include_real=not principal.demo).ecns:
            if item.status.ecn_id == ecn_id:
                state = item.status.state
                return ExistingEcn(
                    ecn_id=ecn_id, title=item.status.title, state=state.value, can_continue=state not in LOCKED
                )
        return None

    return lookup


def _fail(error: IntakeError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=str(error))


@router.post("/intake/proposals", responses=INTAKE_RESPONSES)
def propose_text(
    body: IntakeTextInput, request: Request, principal: ViewPrincipal, workspace: WorkspaceDep
) -> IntakeProposal:
    """문서 → 확인표 제안. 자동 진행은 없다(항상 사람 확인)."""
    try:
        with acting_as(principal.login_id):
            return workspace.intake.propose(body.text, body.ship_ids, _existing(request, principal))
    except IntakeError as error:
        raise _fail(error) from None


@router.post("/intake/proposals/xlsx", responses=INTAKE_RESPONSES)
async def propose_xlsx(
    request: Request,
    principal: ViewPrincipal,
    workspace: WorkspaceDep,
    ship_ids: Annotated[list[str], Query(min_length=1)],
) -> IntakeProposal:
    """변경 리스트 엑셀(첫 시트, 첫 행 = 머리글) → 확인표 제안."""
    data = await upload_bytes(request)
    lookup = _existing(request, principal)

    def propose() -> IntakeProposal:  # 엑셀 읽기·AI 호출(최대 45초)은 작업 스레드에서 — 이벤트 루프를 막지 않게
        try:
            sheets = read_workbook(data)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
        sheet = next((s for s in sheets.values() if len(s.rows) >= 2), None)
        if sheet is None:
            raise HTTPException(status_code=422, detail="머리글과 행이 있는 시트 없음")
        try:
            with acting_as(principal.login_id):
                return workspace.intake.propose_rows([cells for _, cells in sheet.rows], tuple(ship_ids), lookup)
        except IntakeError as error:
            raise _fail(error) from None

    return await run_in_threadpool(propose)


@router.post("/intake/confirmations", responses=INTAKE_RESPONSES)
def confirm_intake(
    body: IntakeConfirmation, principal: ViewPrincipal, workspace: WorkspaceDep, corrections: Corrections
) -> IntakeResult:
    actor = Actor(login_id=principal.login_id, demo=principal.demo, dev=principal.dev)
    try:
        result, events = workspace.intake.confirm(body, actor)
    except IntakeError as error:
        raise _fail(error) from None
    except IntakeProblems as error:  # 화면 오류 꼴(message + problems 글): 항목 문제는 '항목 ID: 이유'
        problems = [f"{p.item_id}: {p.message}" if p.item_id else p.message for p in error.problems]
        detail = {"message": "확정 불가 항목 있음", "problems": problems}
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail) from None
    try:
        corrections.append(events)
    except CorrectionLogError as error:  # 수정 기록 실패가 분석을 깨지 않는다
        log.warning("수정 기록 저장 실패: %s", error)
    return result


@router.get("/corrections/summary", responses=AUTH_RESPONSES)
def correction_summary(
    principal: ApprovePrincipal, corrections: Corrections, days: Annotated[int | None, Query(ge=1, le=3650)] = None
) -> CorrectionSummary:
    since = None if days is None else datetime.now(UTC) - timedelta(days=days)
    try:
        events = corrections.events(since=since, include_real=not principal.demo)
    except CorrectionLogError as error:
        raise HTTPException(status_code=500, detail=str(error)) from None
    return summarize(events, since)
