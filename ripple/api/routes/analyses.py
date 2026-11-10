"""비용·일정 분석: 변경 요청 → 영향·비용 줄·일정·추가손실 곡선·보류 권고·요약 판정(docs/engine.md(비용·일정)).

include_alternatives면 강도형 요청의 대안·판정·권고·날짜별 최저 비용 대안을 더한다(docs/engine.md(대안)).

POST /analyses/export: 같은 요청을 다시 분석해(같은 요청이면 같은 결과 — 분석 ID) 엑셀로 내려받는다. 대안 비교 시트는
같은 요청을 대안 포함으로 한 번 더 계산한 것(대안 탭과 같음)이고, 대안이 없는 요청이면 시트가 없다.
권한은 지도 내려받기와 같다(내려받기 권한, 체험은 합성 데이터 작업 공간만 — get_workspace가 막는다).

POST /analyses/notices(1.37.0): 같은 요청을 다시 분석해 AI 비서와 같은 규칙으로 알림 초안(공식 메일·작업반 번역 초안)을
만든다 — 상세 사전 점검의 '통보문 보기'. 외부 AI 없이 결정적(docs/records.md(통보) 7절).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.assistant import AnalysisNotices, NotificationTarget
from ripple.contracts.domain import DataMode
from ripple.contracts.result import AnalysisResult
from ripple.engine.analyze import analyze
from ripple.engine.propagate import RequestError
from ripple.explain.compose import notifications
from ripple.ingest.out_analysis import analysis_workbook

from ..deps import AppContext, get_context
from ..downloads import XLSX, exported_at, safe_part, xlsx_response
from ..ncr import ncr_counts
from ..records import with_plan
from ..security import require_export
from ..workspace import Workspace, get_workspace
from .impacts import RequestProblems

router = APIRouter(tags=["analyses"])
UNPROCESSABLE = {"description": "계약 위반 또는 지도와 맞지 않는 요청(이유 목록)"}


def _run(context: AppContext, workspace: Workspace, request: AnalysisRequest) -> AnalysisResult:
    """사전 점검 항목의 같은 유형 합성 NCR 건수는 합성 작업 공간에서만 싣는다(api/ncr.py). 응답에는 결재 계획을
    덧붙인다(1.33.0 — 기록 전 분석에서도 결재 올릴 기한·보류 권고의 결재 기간이 기록 뒤와 같은 값,
    api/records.with_plan)."""
    counts = ncr_counts(workspace.data_mode)
    try:
        index, rulebook = workspace.index, context.rulebook
        result = analyze(index, request, rulebook, context.params, context.strength, ncr_counts=counts)
    except RequestError as error:
        detail = RequestProblems(message="요청이 연결 지도와 불일치", problems=error.problems)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail.model_dump(mode="json")
        ) from None
    return with_plan(context, result, real=workspace.data_mode is DataMode.REAL, now=datetime.now(UTC))


@router.post("/analyses", responses={status.HTTP_422_UNPROCESSABLE_CONTENT: UNPROCESSABLE})
def create_analysis(
    request: AnalysisRequest,
    context: Annotated[AppContext, Depends(get_context)],
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> AnalysisResult:
    return _run(context, workspace, request)


@router.post(
    "/analyses/export",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {
            "content": {XLSX: {}},
            "description": "분석 결과 엑셀(요약 · 영향 목록 · 비용 근거 · 가정값 · 확정 시점 곡선 · 대안 비교)",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: UNPROCESSABLE,
    },
    dependencies=[Depends(require_export)],
)
def export_analysis(
    request: AnalysisRequest,
    context: Annotated[AppContext, Depends(get_context)],
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Response:
    """화면이 보던 분석의 요청 그대로 → 엑셀. 숫자는 분석 결과 필드 그대로다."""
    result = _run(context, workspace, request)
    wide = result if request.include_alternatives else _alternatives(context, workspace, request)
    stamp = exported_at(datetime.now(UTC))
    body = analysis_workbook(result, alternatives=wide, exported_at=stamp, data_mode=workspace.data_mode)
    ecn = safe_part(request.change.ecn_id or "ECN")
    day = request.as_of.isoformat()
    return xlsx_response(body, name=f"Ripple_분석_{ecn}_{day}.xlsx", fallback=f"ripple-analysis-{ecn}-{day}.xlsx")


@router.post("/analyses/notices", responses={status.HTTP_422_UNPROCESSABLE_CONTENT: UNPROCESSABLE})
def analysis_notices(
    request: AnalysisRequest,
    context: Annotated[AppContext, Depends(get_context)],
    workspace: Annotated[Workspace, Depends(get_workspace)],
    target: NotificationTarget | None = None,
) -> AnalysisNotices:
    """1.37.0 상세 '통보문 보기': 보던 분석의 요청 그대로 다시 분석해 AI 비서와 같은 규칙으로 알림 초안을 만든다
    (작업반 통보의 번역 초안 포함, 외부 AI 없음 — real 모드도 같다). target을 주면 그 받는 쪽 초안만."""
    result = _run(context, workspace, request)
    found = notifications(result, workspace.assistant.resources.directory)
    if target is not None:
        found = tuple(n for n in found if n.target is target)
    return AnalysisNotices(analysis_id=result.analysis_id, notifications=found)


def _alternatives(context: AppContext, workspace: Workspace, request: AnalysisRequest) -> AnalysisResult | None:
    """같은 요청을 대안 포함으로(대안 탭과 같은 계산). 대안을 만들 수 없는 요청이면 None."""
    try:
        wide = _run(context, workspace, request.model_copy(update={"include_alternatives": True}))
    except HTTPException:
        return None
    return wide if wide.alternatives else None
