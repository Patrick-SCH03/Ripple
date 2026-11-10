"""기록·승인 흐름 API(docs/records.md(기록·결재) 7절). 경로마다 권한을 정한다.

- POST /records(기록 권한): 화면이 본 분석을 불변 기록(개정)으로. 서버가 같은 요청을 다시 계산해 대조한다.
- GET /ecns · /ecns/{ecn_id} · /records/{record_id}(보기 권한): 체험은 실데이터 기록을 보지 못한다(없는 것처럼 404).
- POST /ecns/{ecn_id}/actions(기록 또는 승인 권한 — 행동마다의 권한은 결재 규칙이 봄):
  검토 요청·취소·무비용 담당자 처리·실행·종료는 담당자,
  승인·반려·보류는 결재선의 지금 단계 결재자(파트장·팀장·본부장, 팀장은 파트장·본부장 단계를 전결),
  검토 취소는 요청한 사람이나 팀장.
- GET /ecns/{ecn_id} · /records/{record_id}: 결재 계획(approval_plan — 결재 소요·결재 올릴 기한)을 읽을 때 계산해
  싣는다(최신 개정이 검토 중이면 둘 다 남은 단계로, 같은 값).
- POST /ecns/{ecn_id}/notices(기록 권한, 1.28.0): 통보 기록(보냄·수령 확인·회신)을 감사 줄로.
- GET /audit/verify(승인(결재자)): 감사 사슬 + 참조 무결성.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status

from ripple.auth import AuthService
from ripple.contracts.records import (
    ECN_ID_PATTERN,
    RECORD_ID_PATTERN,
    ActionRequest,
    AuditCheck,
    AuditEntry,
    EcnDetail,
    EcnList,
    EcnRecord,
    EcnStatus,
    NoticeRequest,
    RecordProblem,
    RecordRequest,
    RecordSaved,
)
from ripple.engine.propagate import RequestError
from ripple.records.flow import FlowError
from ripple.store.records import RecordStore

from ..deps import AppContext, get_context
from ..records import act_on, actor_of, plan_of, same_version_of, save_record, who_of
from ..security import AUTH_RESPONSES, ActPrincipal, RecordPrincipal, ViewPrincipal, get_auth, require_approve
from ..workspace import StaleWorkspace, Workspace, Workspaces, conflict, get_workspace, get_workspaces
from .impacts import RequestProblems

router = APIRouter(tags=["records"])

PROBLEMS: dict[int | str, dict[str, object]] = {
    **AUTH_RESPONSES,
    404: {"description": "기록이 없음(체험에게는 실데이터 기록도 없는 것처럼, detail = RecordProblem)"},
    409: {
        "description": "그사이 상태·분석·지도·계산 판이 바뀜 또는 지금 상태에서 할 수 없는 일(detail = RecordProblem)"
    },
    422: {"description": "사유·확인 목록이 빠짐 또는 요청 형식 오류(detail = RecordProblem 또는 검증 오류)"},
}
EcnIdPath = Annotated[str, Path(pattern=ECN_ID_PATTERN)]
RecordIdPath = Annotated[str, Path(pattern=RECORD_ID_PATTERN)]


def get_records(request: Request) -> RecordStore:
    store = getattr(request.app.state, "records", None)
    if not isinstance(store, RecordStore):
        raise RuntimeError("기록 저장소 준비 안 됨")
    return store


Records = Annotated[RecordStore, Depends(get_records)]
Auth = Annotated[AuthService, Depends(get_auth)]


def flow_problem(error: FlowError) -> HTTPException:
    detail = RecordProblem.model_validate({"code": error.code, "message": error.message})
    return HTTPException(status_code=error.status, detail=detail.model_dump(mode="json"))


def record_not_found() -> HTTPException:
    return flow_problem(FlowError(404, "not_found", "기록 없는 설계변경"))


@router.post("/records", responses=PROBLEMS)
def create_record(
    body: RecordRequest,
    principal: RecordPrincipal,
    context: Annotated[AppContext, Depends(get_context)],
    workspace: Annotated[Workspace, Depends(get_workspace)],
    workspaces: Annotated[Workspaces, Depends(get_workspaces)],
    records: Records,
    auth: Auth,
) -> RecordSaved:
    try:
        return save_record(context, workspaces, workspace, records, principal, body, login_mode=auth.required)
    except RequestError as error:
        detail = RequestProblems(message="요청이 연결 지도와 불일치", problems=error.problems)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail.model_dump(mode="json")
        ) from None
    except FlowError as error:
        raise flow_problem(error) from None
    except StaleWorkspace as error:
        raise conflict(error) from None


@router.get("/ecns", responses=AUTH_RESPONSES)
def list_ecns(principal: ViewPrincipal, records: Records) -> EcnList:
    return records.listing(include_real=not principal.demo)


@router.get("/ecns/{ecn_id}", responses=PROBLEMS)
def ecn_detail(
    ecn_id: EcnIdPath,
    principal: ViewPrincipal,
    context: Annotated[AppContext, Depends(get_context)],
    records: Records,
) -> EcnDetail:
    try:
        detail = records.detail(
            ecn_id,
            include_real=not principal.demo,
            same_version=same_version_of(context),
            plan=plan_of(context, datetime.now(UTC)),
        )
    except FlowError as error:
        raise flow_problem(error) from None
    if detail is None:
        raise record_not_found()
    return detail


@router.get("/records/{record_id}", responses=PROBLEMS)
def get_record(
    record_id: RecordIdPath,
    principal: ViewPrincipal,
    context: Annotated[AppContext, Depends(get_context)],
    records: Records,
) -> EcnRecord:
    """기록 본문 + 읽을 때 계산한 결재 계획(1.33.0, 판단 리포트의 보류 권고 결재 기간 문구). 그 기록이 최신 개정이고
    검토 중이면 상세와 같은 남은 단계로 센다."""
    try:
        found = records.record(record_id, include_real=not principal.demo, plan=plan_of(context, datetime.now(UTC)))
    except FlowError as error:
        raise flow_problem(error) from None
    if found is None:
        raise flow_problem(FlowError(404, "not_found", "없는 기록"))
    return found


@router.post("/ecns/{ecn_id}/actions", responses=PROBLEMS)
def act(
    ecn_id: EcnIdPath,
    body: ActionRequest,
    principal: ActPrincipal,
    context: Annotated[AppContext, Depends(get_context)],
    workspace: Annotated[Workspace, Depends(get_workspace)],
    workspaces: Annotated[Workspaces, Depends(get_workspaces)],
    records: Records,
    auth: Auth,
) -> EcnStatus:
    try:
        return act_on(context, workspaces, workspace, records, principal, ecn_id, body, login_mode=auth.required)
    except FlowError as error:
        raise flow_problem(error) from None
    except StaleWorkspace as error:
        raise conflict(error) from None


@router.post("/ecns/{ecn_id}/notices", responses=PROBLEMS)
def add_notice(
    ecn_id: EcnIdPath, body: NoticeRequest, principal: RecordPrincipal, records: Records, auth: Auth
) -> AuditEntry:
    """1.28.0 통보 기록(보냄·수령 확인·회신): 감사 사슬에 한 줄. 상태·버전은 바꾸지 않는다."""
    try:
        return records.notice(
            ecn_id,
            body.record_id,
            body.notice,
            actor_of(principal, login_mode=auth.required),
            who_of(principal, login_mode=auth.required),
        )
    except FlowError as error:
        raise flow_problem(error) from None


@router.get("/audit/verify", responses=AUTH_RESPONSES, dependencies=[Depends(require_approve)])
def verify_audit(records: Records) -> AuditCheck:
    return records.verify()
