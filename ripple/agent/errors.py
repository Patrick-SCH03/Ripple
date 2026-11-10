"""비서 대화의 오류. API는 메시지를 그대로 거절 이유로 돌려준다."""

from __future__ import annotations


class AssistantError(ValueError):
    """대화를 이어 갈 수 없는 요청(없는 대화, 지난 질문의 답 등). 메시지는 명사형."""
