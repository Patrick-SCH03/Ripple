"""AI 비서 대화: 자연어 요청 → 되묻기 → 분석 → 설명·알림 초안(docs/input.md(판단 계층) 7절, docs/input.md(외부 AI))."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ripple.agent.flow import AssistantError
from ripple.contracts.assistant import AssistantTurn, AssistantTurnRequest, Conversation
from ripple.llm.quota import acting_as

from ..security import ViewPrincipal
from ..workspace import Workspace, get_workspace

router = APIRouter(tags=["assistant"])


@router.post(
    "/assistant/turns",
    responses={status.HTTP_409_CONFLICT: {"description": "이어 갈 수 없는 대화(없는 대화, 지난 질문의 답 등)"}},
)
def take_turn(
    request: AssistantTurnRequest,
    principal: ViewPrincipal,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> AssistantTurn:
    """새 문장이면 대화를 시작하거나 다시 해석하고, 답이면 지난 질문에 반영해 다음 차례를 낸다.
    외부 AI 호출은 이 계정의 하루 몫으로 센다."""
    try:
        with acting_as(principal.login_id):
            return workspace.assistant.turn(request)
    except AssistantError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None


@router.get(
    "/assistant/conversations/{conversation_id}",
    responses={status.HTTP_404_NOT_FOUND: {"description": "없거나 만료된 대화"}},
)
def get_conversation(conversation_id: str, workspace: Annotated[Workspace, Depends(get_workspace)]) -> Conversation:
    try:
        return workspace.assistant.conversation(conversation_id)
    except AssistantError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None
