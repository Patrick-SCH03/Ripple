"""상태 갱신 API(docs/domain.md 12절): 분석 화면의 확인·수정과 엑셀 '상태 올리기'가 지금 지도에 상태·날짜만 덮어쓴다.

- POST /updates/preview(기록 권한): 적용하면 무엇이 바뀌는지와 거부 항목(지도는 그대로).
- POST /updates(기록 권한, 요청 머리글 X-Ripple-Workspace 필수): 거부가 없으면 새 지도·새 작업 공간 세대로
  바꾸고 갱신 기록을 남긴다. 거부가 하나라도 있으면 422(UpdatePreview, 아무것도 바꾸지 않음),
  그사이 지도가 바뀌었으면 409.
- GET /updates(승인(결재자)): 최근 갱신 기록(누가·언제·무엇을).
담당자도 상태를 바꿀 수 있다. 부재·블록·공정 구조는 바꾸지 못하고,
전체 엑셀 가져오기는 관리자만이다.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from ripple.contracts.ingest import ImportVersion, MappingOverrides, MappingProposal, MappingSubmission
from ripple.contracts.updates import StatusImportPreview, StatusUpdate, UpdateApplied, UpdateEvent, UpdatePreview
from ripple.contracts.workspace import WORKSPACE_HEADER
from ripple.engine.updates import date_problems
from ripple.store.updates import UpdateLog, UpdateLogError

from ..records import actor_of
from ..security import AUTH_RESPONSES, RecordPrincipal, get_auth, require_approve
from ..status_imports import StatusImports
from ..workspace import (
    Busy,
    ImportChanged,
    NotFound,
    StaleWorkspace,
    UpdateRejected,
    Workspaces,
    conflict,
    get_workspaces,
)
from ..workspace_errors import import_step_errors
from .snapshots import upload_bytes

router = APIRouter(tags=["updates"], responses=AUTH_RESPONSES)
RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {"description": "기대 작업 공간이 지금 것과 다름(detail = WorkspaceConflict)"},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "거부 항목이 있음(detail = UpdatePreview)"},
}


def get_update_log(request: Request) -> UpdateLog:
    log = getattr(request.app.state, "updates", None)
    if not isinstance(log, UpdateLog):
        raise RuntimeError("상태 갱신 기록 준비 안 됨")
    return log


def _rejected(preview: UpdatePreview) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=preview.model_dump(mode="json"))


@router.post("/updates/preview", responses=RESPONSES)
def preview_update(
    body: StatusUpdate, _: RecordPrincipal, holder: Annotated[Workspaces, Depends(get_workspaces)]
) -> UpdatePreview:
    preview = holder.preview_update(body)
    dated = date_problems(body, holder.today())
    if dated:
        preview = preview.model_copy(update={"snapshot_id": None, "problems": (*dated, *preview.problems)})
    return preview


@router.post("/updates", responses=RESPONSES)
def apply_status_update(
    body: StatusUpdate,
    principal: RecordPrincipal,
    holder: Annotated[Workspaces, Depends(get_workspaces)],
    log: Annotated[UpdateLog, Depends(get_update_log)],
    request: Request,
    expected: Annotated[str, Header(alias=WORKSPACE_HEADER, description="화면이 아는 작업 공간 토큰(필수)")],
) -> UpdateApplied:
    dated = date_problems(body, holder.today())
    if dated:
        raise _rejected(holder.preview_update(body).model_copy(update={"snapshot_id": None, "problems": dated}))
    actor = actor_of(principal, login_mode=get_auth(request).required)
    try:
        _, event = holder.apply_update(body, expected, actor, log)
    except StaleWorkspace as error:
        raise conflict(error) from None
    except UpdateRejected as error:
        raise _rejected(error.preview) from None
    except UpdateLogError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    return UpdateApplied(event=event, snapshots=holder.listing())


@router.get("/updates", dependencies=[Depends(require_approve)])
def recent_updates(
    log: Annotated[UpdateLog, Depends(get_update_log)], limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> tuple[UpdateEvent, ...]:
    return log.recent(limit)


# ---------- 상태 올리기(바뀌는 시트만, docs/input.md(엑셀 양식) 5절) ----------


def get_status_imports(request: Request) -> StatusImports:
    imports = getattr(request.app.state, "status_imports", None)
    if not isinstance(imports, StatusImports):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="연결 지도 준비 중")
    return imports


Imports = Annotated[StatusImports, Depends(get_status_imports)]
IMPORT_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"description": "없거나 만료된 상태 올리기"},
    status.HTTP_409_CONFLICT: {"description": "상태 버전이 다름(ImportConflict) 또는 기대 작업 공간이 다름"},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "다른 엑셀을 읽는 중"},
}


@router.post(
    "/status-imports",
    openapi_extra={
        "requestBody": {
            "required": True,
            "description": "발주·발주 관측·공정·공정 확인 시트가 든 엑셀(xlsx) 파일 그대로",
            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
    responses={**IMPORT_RESPONSES, status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "빈 파일·엑셀 아님"}},
)
async def stage_status_import(
    request: Request,
    _: RecordPrincipal,
    imports: Imports,
    file_name: Annotated[str, Query(min_length=1, max_length=200, description="올린 파일 이름")],
) -> MappingProposal:
    """상태 시트만 고르는 매핑 제안. 같은 모양의 파일로 전에 확정한 매핑이 있으면 함께 싣는다."""
    data = await upload_bytes(request)
    try:
        return await run_in_threadpool(imports.stage, file_name.strip() or "엑셀", data)
    except Busy as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except ValidationError:
        raise
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None


@router.post("/status-imports/{import_id}/proposal", responses=IMPORT_RESPONSES)
def propose_status_import(
    import_id: str, body: MappingOverrides, _: RecordPrincipal, imports: Imports
) -> MappingProposal:
    with import_step_errors(invalid=True):
        return imports.propose(import_id, body)


@router.post("/status-imports/{import_id}/mapping", responses=IMPORT_RESPONSES)
def submit_status_import(
    import_id: str, body: MappingSubmission, _: RecordPrincipal, imports: Imports
) -> StatusImportPreview:
    """확정 매핑으로 읽어 품질 리포트와 적용 미리보기(바뀌는 것·거부 항목)를 낸다. 지도는 아직 그대로."""
    with import_step_errors(invalid=False):
        return imports.submit(import_id, body)


@router.post("/status-imports/{import_id}/confirm", responses={**IMPORT_RESPONSES, **RESPONSES})
def confirm_status_import(
    import_id: str,
    body: ImportVersion,
    principal: RecordPrincipal,
    imports: Imports,
    holder: Annotated[Workspaces, Depends(get_workspaces)],
    log: Annotated[UpdateLog, Depends(get_update_log)],
    request: Request,
    expected: Annotated[str, Header(alias=WORKSPACE_HEADER, description="화면이 아는 작업 공간 토큰(필수)")],
) -> UpdateApplied:
    """그 버전의 읽기 결과를 지금 지도에 적용한다(새 작업 공간 세대, 갱신 기록)."""
    actor = actor_of(principal, login_mode=get_auth(request).required)
    try:
        _, event = imports.confirm(import_id, body.version, expected, actor, log)
    except (StaleWorkspace, ImportChanged) as error:
        raise conflict(error) from None
    except NotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None
    except UpdateRejected as error:
        raise _rejected(error.preview) from None
    except UpdateLogError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    return UpdateApplied(event=event, snapshots=holder.listing())
