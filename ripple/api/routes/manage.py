"""결재자(파트장·팀장·본부장) 결재·현황과 실적(docs/records.md(기록·결재) 11절).

- GET /manage/overview?days=(승인 권한 = 결재선의 파트장·팀장·본부장, 비우면 성과는 전체 기간):
  결재함(검토·보류 중 개정 가운데 보는 사람의 결재 단계 건 — 마감 급한 순, 미루면 늘어나는 금액, 결재선 진행) ·
  현황(상태별 건수·미결 금액·블록별) · 성과(기간 안 업무 결정의 처리 시간·마감 안 결재·대안 차액·담당자별 업무량) ·
  예측 대비 실적. 기록 저장소를 읽어 계산하고 저장하지 않는다. 팀장은 실데이터 기록도 본다(목록 API와 같은 규칙).
- GET /manage/export?days=(같은 권한): 같은 계산을 엑셀로 — 결재 대장(결재함 줄) · 현황 · 상태별 · 블록별.
- GET /ecns/{ecn_id}/outcome(보기): 그 ECN의 실적 지금 값(없으면 404). 체험에게 실데이터 ECN은 없는 것처럼.
- PUT /ecns/{ecn_id}/outcome(기록 권한 = 담당자): 실행을 시작했거나 끝낸 ECN에 실제 비용·구역 출구 지연을 넣는다
  (고치면 새 줄).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ripple.auth import AuthService, Principal
from ripple.contracts.manage import ManageOverview
from ripple.contracts.outcomes import OutcomeEntry, OutcomeInput
from ripple.contracts.records import EcnStatus, RecordProblem
from ripple.ingest.out_ledger import ledger_workbook
from ripple.records.flow import FlowError
from ripple.records.metrics import Inputs, overview
from ripple.store.outcomes import OutcomeLog, OutcomeLogError
from ripple.store.records import RecordStore

from ..deps import AppContext, get_context
from ..downloads import XLSX, exported_at, xlsx_response
from ..records import actor_of, inbox_steps, outcome_entry, proxy_steps
from ..security import AUTH_RESPONSES, ApprovePrincipal, RecordPrincipal, ViewPrincipal, get_auth
from .records import EcnIdPath, Records

router = APIRouter(tags=["manage"])
OVERVIEW_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_RESPONSES,
    500: {"description": "저장된 기록 본문이 ID와 맞지 않음(detail = RecordProblem integrity) → 감사 확인"},
}
OUTCOME_RESPONSES: dict[int | str, dict[str, object]] = {
    **OVERVIEW_RESPONSES,
    404: {"description": "기록이 없는 ECN · 실적이 아직 없음(detail = RecordProblem)"},
    409: {"description": "실행을 시작하지 않은 ECN(detail = RecordProblem invalid_transition)"},
}


def get_outcomes(request: Request) -> OutcomeLog:
    log = getattr(request.app.state, "outcomes", None)
    if not isinstance(log, OutcomeLog):
        raise RuntimeError("실적 기록 준비 안 됨")
    return log


Outcomes = Annotated[OutcomeLog, Depends(get_outcomes)]


def _problem(status: int, code: str, message: str) -> HTTPException:
    detail = RecordProblem.model_validate({"code": code, "message": message})
    return HTTPException(status_code=status, detail=detail.model_dump(mode="json"))


def _status(records: RecordStore, ecn_id: str, *, include_real: bool) -> EcnStatus:
    found = next(
        (item.status for item in records.listing(include_real=include_real).ecns if item.status.ecn_id == ecn_id), None
    )
    if found is None:
        raise _problem(404, "not_found", "기록 없는 설계변경")
    return found


Days = Annotated[int | None, Query(ge=1, le=3650, description="성과 기간(일). 비우면 전체")]


def _overview(
    principal: Principal,
    records: RecordStore,
    outcomes: OutcomeLog,
    context: AppContext,
    days: int | None,
    now: datetime,
    *,
    login_mode: bool,
) -> ManageOverview:
    try:
        items, audit, bodies = records.overview_inputs(include_real=not principal.demo)
    except FlowError as error:  # 본문 해시가 ID와 다름 등(integrity) → 감사 확인
        raise _problem(error.status, error.code, error.message) from None
    return overview(
        Inputs(
            items=items,
            audit=audit,
            bodies=bodies,
            now=now,
            days=days,
            outcomes=outcomes.latest(),
            live=context.settings.live_world,
            steps=inbox_steps(principal, login_mode=login_mode),
            proxy_steps=proxy_steps(principal, login_mode=login_mode),
        )
    )


@router.get("/manage/overview", responses=OVERVIEW_RESPONSES)
def manage_overview(
    principal: ApprovePrincipal,
    records: Records,
    outcomes: Outcomes,
    context: Annotated[AppContext, Depends(get_context)],
    auth: Annotated[AuthService, Depends(get_auth)],
    days: Days = None,
) -> ManageOverview:
    return _overview(principal, records, outcomes, context, days, datetime.now(UTC), login_mode=auth.required)


@router.get(
    "/manage/export",
    response_class=Response,
    responses={
        **OVERVIEW_RESPONSES,
        200: {"content": {XLSX: {}}, "description": "결재 대장 엑셀(결재 대장 · 현황 · 상태별 · 블록별)"},
    },
)
def export_manage(
    principal: ApprovePrincipal,
    records: Records,
    outcomes: Outcomes,
    context: Annotated[AppContext, Depends(get_context)],
    auth: Annotated[AuthService, Depends(get_auth)],
    days: Days = None,
) -> Response:
    """결재·현황을 엑셀로(결재함 줄 = 결재 대장). 숫자는 결재·현황 응답과 같은 계산 그대로다."""
    now = datetime.now(UTC)
    data = _overview(principal, records, outcomes, context, days, now, login_mode=auth.required)
    body = ledger_workbook(data, exported_at=exported_at(now))
    day = data.today.isoformat()
    return xlsx_response(body, name=f"Ripple_결재대장_{day}.xlsx", fallback=f"ripple-ledger-{day}.xlsx")


@router.get("/ecns/{ecn_id}/outcome", responses=OUTCOME_RESPONSES)
def get_outcome(ecn_id: EcnIdPath, principal: ViewPrincipal, records: Records, outcomes: Outcomes) -> OutcomeEntry:
    _status(records, ecn_id, include_real=not principal.demo)
    found = outcomes.get(ecn_id)
    if found is None:
        raise _problem(404, "not_found", "실적 미입력")
    return found


@router.put("/ecns/{ecn_id}/outcome", responses=OUTCOME_RESPONSES)
def put_outcome(
    ecn_id: EcnIdPath,
    body: OutcomeInput,
    principal: RecordPrincipal,
    records: Records,
    outcomes: Outcomes,
    auth: Annotated[AuthService, Depends(get_auth)],
) -> OutcomeEntry:
    try:
        entry = outcome_entry(records, ecn_id, body, actor_of(principal, login_mode=auth.required), datetime.now(UTC))
    except FlowError as error:
        raise _problem(error.status, error.code, error.message) from None
    try:
        outcomes.append(entry)
    except OutcomeLogError as error:
        raise _problem(500, "integrity", str(error)) from None
    return entry
