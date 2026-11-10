"""외부 AI 호출 기록(관리자): 최근 호출의 시각·작업·모델·성공 여부·걸린 시간만.

문장·응답·키는 담지 않고, 서버를 다시 켜면 비워진다."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ripple.contracts.system import LlmCalls
from ripple.llm.route import Router

from ..security import AUTH_RESPONSES, require_manage
from ..workspace import current_workspace, workspaces_of

router = APIRouter(tags=["system"], responses=AUTH_RESPONSES)


@router.get("/llm/calls", dependencies=[Depends(require_manage)])
def read_llm_calls(request: Request) -> LlmCalls:
    """지금 외부 AI를 부를 수 있는지와 최근 호출(최근 것부터). 관리자만."""
    holder = workspaces_of(request)
    model = None if holder is None else holder.model
    workspace = current_workspace(request)
    return LlmCalls(
        external=workspace is not None and workspace.llm_external,
        calls=model.recent_calls() if isinstance(model, Router) else (),
    )
