"""영향 탐색: 변경 요청 → 영향 범위·근거 경로·영향 그래프(docs/engine.md(전파))."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.base import Frozen
from ripple.contracts.result import ImpactReport
from ripple.engine.propagate import RequestError, impact_report

from ..deps import AppContext, get_context
from ..workspace import Workspace, get_workspace

router = APIRouter(tags=["impacts"])


class RequestProblems(Frozen):
    """요청이 지도와 맞지 않을 때(422)의 응답 본문 detail."""

    message: str
    problems: tuple[str, ...]


@router.post(
    "/impacts",
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "계약 위반 또는 지도와 맞지 않는 요청(이유 목록)"}
    },
)
def create_impacts(
    request: AnalysisRequest,
    context: Annotated[AppContext, Depends(get_context)],
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> ImpactReport:
    try:
        return impact_report(workspace.index, request, context.rulebook, context.params.version)
    except RequestError as error:
        detail = RequestProblems(message="요청이 연결 지도와 불일치", problems=error.problems)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail.model_dump(mode="json")
        ) from None
