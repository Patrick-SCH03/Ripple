"""AI 비서 계약: 변경 초안(연산별 슬롯)·질문·대화 차례(docs/input.md(판단 계층) 7절).

자연어 요청은 변경 초안(ChangeDraft)이 된다. 연산마다 채울 슬롯이 정해져 있고(OP_SLOTS, 이름은
변경 연산 필드 그대로) 슬롯마다 어떻게 채웠는지(FillMethod)와 원문 근거(SourceSpan)를 남긴다.
필수 슬롯이 모두 채워지면 ChangeRequest로 조립한다.

자동 진행 자격(ChangeDraft.ready)은 보정 자료의 단위와 실행 라우터가 함께 쓰는 정의 하나다:
연산·의도·필수 슬롯이 모두 결정적 일치·판단 계층·지도·화면 맥락·사용자로 채워졌을 때.
추정(모호한 값 표현, 지도와 다른 변경 전 값)이나 LLM이 채운 슬롯이 하나라도 있으면 자격이 없다.

주제별 모듈:
- draft: 변경 초안(슬롯 정의·채움·초안 조립)
- turn: 대화 차례(화면 맥락·질문과 답·차례 요청과 응답·알림 초안·대화). draft를 import한다
"""

from .draft import (
    ANY_OF,
    INTENT_LABELS,
    LIST_KINDS,
    NUMBER_KINDS,
    OP_LABELS,
    OP_SLOTS,
    READY_METHODS,
    ChangeDraft,
    FillMethod,
    SlotFill,
    SlotKind,
    SlotSpec,
    SlotValue,
    SourceSpan,
    op_types,
)
from .turn import (
    YES,
    AnalysisNotices,
    Answer,
    AssistantSeed,
    AssistantTurn,
    AssistantTurnRequest,
    Conversation,
    EmailDraft,
    Notification,
    NotificationTarget,
    Question,
    QuestionKind,
    QuestionOption,
    TurnContext,
    TurnState,
)

__all__ = [
    "ANY_OF",
    "INTENT_LABELS",
    "LIST_KINDS",
    "NUMBER_KINDS",
    "OP_LABELS",
    "OP_SLOTS",
    "READY_METHODS",
    "YES",
    "AnalysisNotices",
    "Answer",
    "AssistantSeed",
    "AssistantTurn",
    "AssistantTurnRequest",
    "ChangeDraft",
    "Conversation",
    "EmailDraft",
    "FillMethod",
    "Notification",
    "NotificationTarget",
    "Question",
    "QuestionKind",
    "QuestionOption",
    "SlotFill",
    "SlotKind",
    "SlotSpec",
    "SlotValue",
    "SourceSpan",
    "TurnContext",
    "TurnState",
    "op_types",
]
