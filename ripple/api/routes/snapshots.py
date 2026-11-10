"""지도 목록·전환·내보내기와 엑셀 가져오기(docs/operations.md(서비스) 6절, docs/input.md(엑셀 양식) 4절).

가져오기: 올리기(매핑 제안 — 아직 지도를 만들지 않음) → 열 확인(덮어쓰기는 다시 제안) → 확정 매핑으로 읽기(품질
리포트) → 확정(저장하고 그 지도로 전환). 가져오기 상태 버전이 지금 것이 아니면 409(import_changed), 전환·확정은 요청
머리글의 기대 작업 공간 토큰이 지금 것과 다르면 409(workspace_changed)로 거절한다.

권한(docs/operations.md(서비스) 2절): 목록은 로그인한 누구나(체험은 합성 지도만 — 실데이터 지도의 파일 이름·호선·규모가
보이지
않게, 활성 지도가 실데이터면 403) · 전환과 가져오기는 관리자 · 내려받기는 체험이면 그 지도가 합성 데이터일 때만.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from ripple.auth import Principal
from ripple.contracts.domain import DataMode
from ripple.contracts.ingest import ImportVersion, MappingOverrides, MappingProposal, MappingSubmission
from ripple.contracts.workspace import ImportPreview, SnapshotList
from ripple.ingest.export import to_bytes
from ripple.store.snapshots import SnapshotStoreError

from ..security import (
    AUTH_RESPONSES,
    ViewPrincipal,
    demo_blocked,
    problem,
    require_export,
    require_import,
    require_switch,
)
from ..workspace import (
    Busy,
    ExpectedWorkspace,
    ImportChanged,
    NotFound,
    StaleWorkspace,
    Workspaces,
    conflict,
    get_workspaces,
)
from ..workspace_errors import import_step_errors

router = APIRouter(tags=["snapshots"], responses=AUTH_RESPONSES)
Switcher = Annotated[Principal, Depends(require_switch)]
Importer = Annotated[Principal, Depends(require_import)]

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CONFLICT: dict[int | str, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {"description": "기대 작업 공간이 지금 것과 다름(detail = WorkspaceConflict)"}
}
IMPORT_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"description": "없거나 만료된 가져오기"},
    status.HTTP_409_CONFLICT: {"description": "가져오기 상태 버전이 지금 것과 다름(detail = ImportConflict)"},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "다른 엑셀을 읽는 중"},
}


@router.get("/snapshots")
def list_snapshots(principal: ViewPrincipal, holder: Annotated[Workspaces, Depends(get_workspaces)]) -> SnapshotList:
    """지도 목록(기본 지도가 맨 앞)과 지금 활성 작업 공간(세대·유효 데이터 모드·외부 모델 사용 가능 여부).

    체험에게는 지도마다 자기 데이터 모드로 걸러 합성 지도만 보인다(활성 지도가 실데이터면 목록 자체가 403)."""
    listing = holder.listing()
    if not principal.demo:
        return listing
    if listing.data_mode is not DataMode.SYNTHETIC:
        raise demo_blocked()
    items = tuple(i for i in listing.items if i.data_mode is DataMode.SYNTHETIC)
    return listing.model_copy(update={"items": items, "restore_problem": None})


@router.post(
    "/snapshots/{snapshot_id}/activate",
    responses={
        **CONFLICT,
        status.HTTP_404_NOT_FOUND: {"description": "목록에 없는 지도"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "저장된 지도가 손상돼 열 수 없음"},
    },
)
def activate_snapshot(
    snapshot_id: str,
    _: Switcher,
    holder: Annotated[Workspaces, Depends(get_workspaces)],
    expected: ExpectedWorkspace = None,
) -> SnapshotList:
    """그 지도로 전환한다(새 작업 공간 세대: 샘플·AI 비서 대화가 새로 시작)."""
    try:
        holder.activate(snapshot_id, expected)
    except StaleWorkspace as error:
        raise conflict(error) from None
    except NotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None
    except SnapshotStoreError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
    return holder.listing()


@router.get(
    "/snapshots/{snapshot_id}/export",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {"content": {XLSX: {}}, "description": "지정 양식 엑셀"},
        status.HTTP_404_NOT_FOUND: {"description": "목록에 없는 지도"},
    },
)
def export_snapshot(
    snapshot_id: str,
    principal: Annotated[Principal, Depends(require_export)],
    holder: Annotated[Workspaces, Depends(get_workspaces)],
) -> Response:
    """지도를 지정 양식 엑셀로 내려받는다(기본 지도 = 양식 예시). 체험은 요청한 그 지도가 합성 데이터일 때만."""
    try:
        snapshot = holder.snapshot(snapshot_id)
    except NotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None
    except SnapshotStoreError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
    if principal.demo and snapshot.data_mode is not DataMode.SYNTHETIC:
        raise problem(403, "forbidden", "권한 없음 — 체험 계정은 합성 데이터 지도만 내려받기 가능")
    name = f"ripple-map-{snapshot.snapshot_id}.xlsx"
    return Response(
        content=to_bytes(snapshot), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )


@router.post(
    "/imports",
    openapi_extra={
        "requestBody": {
            "required": True,
            "description": "지정 양식 엑셀(xlsx) 파일 그대로",
            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
    responses={
        status.HTTP_413_CONTENT_TOO_LARGE: {"description": f"파일이 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB를 넘음"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "빈 파일, 엑셀(xlsx)이 아님, 또는 크기 상한 초과"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "다른 엑셀을 읽는 중"},
    },
)
async def stage_import(
    request: Request,
    _: Importer,
    holder: Annotated[Workspaces, Depends(get_workspaces)],
    file_name: Annotated[str, Query(min_length=1, max_length=200, description="올린 파일 이름(리포트·지도 이름)")],
) -> MappingProposal:
    """엑셀을 읽어 매핑 제안(시트마다 양식 시트·머리글 행, 열마다 양식 항목·원본 단위·경로)을 낸다. 지도는 아직
    만들지 않는다 — 열 확인 뒤 확정 매핑으로 읽는다. 외부 AI를 부르지 않는다(로컬 판단 계층만)."""
    data = await upload_bytes(request)
    try:
        return await run_in_threadpool(holder.stage, file_name.strip() or "엑셀", data)
    except Busy as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except ValidationError:
        raise
    except ValueError as error:  # 엑셀(xlsx)로 읽지 못함·크기 상한 초과
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None


@router.post(
    "/imports/{import_id}/proposal",
    responses={**IMPORT_RESPONSES, status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "모르는 시트·빈 머리글 행"}},
)
def propose_import(
    import_id: str, body: MappingOverrides, _: Importer, holder: Annotated[Workspaces, Depends(get_workspaces)]
) -> MappingProposal:
    """사람이 정한 시트 상태(양식 시트·읽지 않음)·머리글 행으로 다시 제안한다. 상태 버전이 오르고 이전 읽기 결과는
    무효가 된다."""
    with import_step_errors(invalid=True):
        return holder.propose(import_id, body)


@router.post("/imports/{import_id}/mapping", responses=IMPORT_RESPONSES)
def submit_mapping(
    import_id: str, body: MappingSubmission, _: Importer, holder: Annotated[Workspaces, Depends(get_workspaces)]
) -> ImportPreview:
    """확정 매핑(열 확인 화면의 '이대로 읽기')으로 읽어 품질 리포트를 낸다. 상태 버전이 오르고, 오류가 없으면 그
    버전으로 확정할 수 있다."""
    with import_step_errors(invalid=False):
        return holder.submit(import_id, body)


@router.post(
    "/imports/{import_id}/confirm",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "없거나 만료된 가져오기"},
        status.HTTP_409_CONFLICT: {
            "description": "기대 작업 공간이 다름(WorkspaceConflict) 또는 가져오기 상태 버전이 다름(ImportConflict)"
        },
    },
)
def confirm_import(
    import_id: str,
    body: ImportVersion,
    _: Importer,
    holder: Annotated[Workspaces, Depends(get_workspaces)],
    expected: ExpectedWorkspace = None,
) -> SnapshotList:
    """그 버전의 읽기 결과로 만든 지도를 저장하고 그 지도로 전환한다."""
    try:
        holder.confirm(import_id, body.version, expected)
    except (StaleWorkspace, ImportChanged) as error:
        raise conflict(error) from None
    except NotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None
    return holder.listing()


async def upload_bytes(request: Request) -> bytes:
    """올린 파일 본문(크기 상한·빈 파일 검사). 상태 올리기도 같은 규칙을 쓴다."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise _too_large()
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_UPLOAD_BYTES:
            raise _too_large()
    if not data:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="빈 파일")
    return bytes(data)


def _too_large() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=f"파일 크기 초과 · {MAX_UPLOAD_BYTES // (1024 * 1024)}MB까지 올리기 가능",
    )


@router.delete("/imports/mappings", status_code=status.HTTP_204_NO_CONTENT)
def forget_mappings(_: Importer, holder: Annotated[Workspaces, Depends(get_workspaces)]) -> None:
    """기억한 열 매핑을 모두 지운다(다음 가져오기부터 열 확인을 처음부터)."""
    holder.forget_mappings()
