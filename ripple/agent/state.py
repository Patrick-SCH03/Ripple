"""대화 상태와 보관소(서버 메모리). 대화마다 원문, 사용자가 정한 것, 지난 질문, 차례 기록을 둔다.

API는 요청을 스레드에서 처리하므로 보관소는 자기 목록을, 대화는 차례 하나(답 확인 → 반영 → 다음 질문)를
잠금으로 지킨다. 같은 질문에 답이 두 번 와도 하나만 반영된다.
"""

from __future__ import annotations

import copy
import secrets
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.assistant import (
    AssistantTurn,
    ChangeDraft,
    Notification,
    Question,
    SlotFill,
    SlotValue,
    TurnContext,
)
from ripple.contracts.decision import DecisionAnswer
from ripple.contracts.explain import RenderedText
from ripple.contracts.result import AnalysisResult


@dataclass(frozen=True, slots=True)
class Asked:
    """지난 차례에 한 질문과, 답을 슬롯 값으로 바꿀 때 필요한 것."""

    question: Question
    proposal_value: SlotValue | None = None  # 추정 값 확인에서 '맞음'의 값


@dataclass(frozen=True, slots=True)
class Analysis:
    """마지막으로 분석한 것. 변경 사유 답은 이것에 묶는다(다시 해석·분석하지 않고 사유만 바꾼다)."""

    draft: ChangeDraft
    request: AnalysisRequest
    result: AnalysisResult
    explanation: RenderedText
    notifications: tuple[Notification, ...]
    intent: DecisionAnswer  # 사유 문 판단(분석 뒤 질문의 선택지 순서)


@dataclass
class ConversationState:
    conversation_id: str
    context: TurnContext
    text: str  # 지금 해석하는 원문(다시 설명하면 바뀐다)
    fixed_op: str | None = None
    fixed_intent: str | None = None
    fixed_targets: dict[int, str] = field(default_factory=dict)  # 대상 질문 번호 → 부재
    target_choices: dict[int, tuple[str, ...]] = field(default_factory=dict)  # 다시 설명한 대상의 후보
    restate_targets: set[int] = field(default_factory=set)  # '해당 없음'을 고른 대상: 다시 설명받기
    expanded: set[str] = field(default_factory=set)  # 'op'·'intent': 전체 선택지로 다시 묻기
    overrides: dict[str, SlotFill] = field(default_factory=dict)  # 사용자가 정한 슬롯 값
    value_checks: dict[str, tuple[float, str]] = field(default_factory=dict)  # 확인할 수치 답(슬롯 → 값·이유)
    confirmed: bool = False  # 요약 확인을 받음
    detail: bool = False  # 요약 확인에서 '고치기': 하나씩 묻기
    llm_used: bool = False
    llm_text: str | None = None  # 외부 모델이 다시 쓴 정규 문장(이 해석은 항상 확인받는다)
    rewrite_tried: bool = False
    draft_only: bool = False  # 1.27.0 분석하지 않고 완성한 초안만 돌려준다(대화 내내 같음)
    asked: dict[str, Asked] = field(default_factory=dict)  # 지난 차례 질문(키 → 질문)
    analysis: Analysis | None = None  # 마지막 분석(변경 사유 기록에 쓴다)
    turns: list[AssistantTurn] = field(default_factory=list)
    touched: datetime = field(default_factory=datetime.now)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def save(self) -> dict[str, object]:
        """차례를 처리하다 실패하면 되돌릴 결정 상태의 사본(담긴 값은 모두 불변이라 얕은 복사로 충분)."""
        return {name: copy.copy(getattr(self, name)) for name in _DECISIONS}

    def restore(self, saved: dict[str, object]) -> None:
        for name, value in saved.items():
            setattr(self, name, value)

    def restart(self, text: str) -> None:
        """새 문장(전체 다시 설명): 원문을 바꾸고 문장에 묶인 결정을 지운다(화면 맥락은 유지)."""
        self.text = text
        self.fixed_op = self.fixed_intent = None
        self.fixed_targets.clear()
        self.target_choices.clear()
        self.restate_targets.clear()
        self.expanded.clear()
        self.overrides.clear()
        self.value_checks.clear()
        self.confirmed = self.detail = False
        self.asked.clear()
        self.analysis = None
        self.llm_text = None
        self.rewrite_tried = False


_DECISIONS = (
    "context",
    "text",
    "fixed_op",
    "fixed_intent",
    "fixed_targets",
    "target_choices",
    "restate_targets",
    "expanded",
    "overrides",
    "value_checks",
    "confirmed",
    "detail",
    "llm_used",
    "llm_text",
    "rewrite_tried",
    "asked",
    "analysis",
)
"""차례마다 바뀔 수 있는 상태(차례 기록·잠금·시각은 빼고)."""


class ConversationStore:
    """최근 대화 limit개를 ttl 동안 둔다(가장 오래 쓰지 않은 것부터 지움)."""

    def __init__(
        self,
        limit: int = 200,
        ttl: timedelta = timedelta(hours=2),
        now: Callable[[], datetime] = datetime.now,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self._items: OrderedDict[str, ConversationState] = OrderedDict()
        self._guard = threading.Lock()
        self._limit = limit
        self._ttl = ttl
        self._now = now
        self._new_id = new_id or (lambda: f"C-{secrets.token_hex(6)}")

    def new_id(self) -> str:
        return self._new_id()

    def get(self, conversation_id: str) -> ConversationState | None:
        with self._guard:
            self._expire()
            state = self._items.get(conversation_id)
            if state is not None:
                self._items.move_to_end(conversation_id)
                state.touched = self._now()
            return state

    def put(self, state: ConversationState) -> None:
        with self._guard:
            state.touched = self._now()
            self._items[state.conversation_id] = state
            self._items.move_to_end(state.conversation_id)
            while len(self._items) > self._limit:
                self._items.popitem(last=False)

    def _expire(self) -> None:
        cutoff = self._now() - self._ttl
        for key in [k for k, v in self._items.items() if v.touched < cutoff]:
            del self._items[key]
