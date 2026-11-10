"""대화 차례 계약: 화면 맥락·질문과 답·차례 요청과 응답·알림 초안(화면 카드·공식 메일)·대화."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from ..analysis import AnalysisRequest
from ..base import Frozen
from ..contacts import Contact
from ..decision import DecisionAnswer, Route
from ..explain import RenderedText
from ..result import AnalysisResult
from ..translation import MailTranslation
from .draft import OP_SLOTS, ChangeDraft, SlotFill, SourceSpan, check_value


class TurnContext(Frozen):
    """화면 맥락: 분석 결과가 기준일·확정일에 달려 있으므로 화면이 정한다."""

    ship_ids: tuple[str, ...] = Field(min_length=1)
    as_of: date
    confirm_on: date | None = None
    horizon_days: int = Field(default=60, ge=1, le=365)

    @model_validator(mode="after")
    def _dates(self) -> TurnContext:
        if self.confirm_on is not None and self.confirm_on < self.as_of:
            raise ValueError("확정일이 기준일보다 앞섬")
        return self


class QuestionKind(StrEnum):
    CONFIRM = "confirm"  # 제안 하나가 맞는지
    CHOOSE = "choose"  # 후보 중 고르기
    RESTATE = "restate"  # 다시 설명(자유 입력)
    VALUE = "value"  # 값 확인·입력


YES = "__yes__"
"""확인 질문에서 제안을 받아들이는 선택지 ID. 거절은 decision.NONE_OPTION('해당 없음')."""


class QuestionOption(Frozen):
    option_id: str = Field(min_length=1)
    label: str
    detail: str | None = None  # 보조 정보(블록·지금 두께 등)


class Question(Frozen):
    question_id: str
    kind: QuestionKind
    target: str  # 채울 것: "op" | "intent" | 슬롯 이름 | "<슬롯>#<번호>"(대상 여럿 중 하나)
    prompt: str  # 명사형 질문
    mention: SourceSpan | None = None
    options: tuple[QuestionOption, ...] = ()
    proposal: str | None = None  # 확인할 제안(사람이 읽는 형태)
    reason: str | None = None  # 왜 묻는지(예: 지도에는 14.5mm)
    route: Route | None = None  # 판단 계층 질문이면 그 경로


class Answer(Frozen):
    question_id: str
    option_id: str | None = None  # 고른 선택지. 확인은 YES, '해당 없음'은 NONE_OPTION
    text: str | None = Field(default=None, min_length=1, max_length=300)  # 다시 설명·직접 입력

    @model_validator(mode="after")
    def _one(self) -> Answer:
        if (self.option_id is None) == (self.text is None):
            raise ValueError("답은 선택지나 입력 중 하나만")
        return self


class AssistantSeed(Frozen):
    """1.27.0 문서 접수 항목을 비서로 넘길 때 이미 정한 것: 연산과 슬롯 값(대상 질문 순번이 아니라 슬롯 이름으로)."""

    fixed_op: str | None = None
    overrides: dict[str, SlotFill] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _known(self) -> AssistantSeed:
        if self.fixed_op is not None and self.fixed_op not in OP_SLOTS:
            raise ValueError(f"없는 변경 연산 · {self.fixed_op}")
        if self.overrides and self.fixed_op is None:
            raise ValueError("슬롯 값은 연산을 정했을 때만 가능")
        if self.fixed_op is not None:
            specs = {s.name: s for s in OP_SLOTS[self.fixed_op]}
            for name, fill in self.overrides.items():
                if name not in specs:
                    raise ValueError(f"이 연산에 없는 슬롯 · {name}")
                check_value(specs[name], fill.value)
        return self


class AssistantTurnRequest(Frozen):
    conversation_id: str | None = None  # 없으면 새 대화
    context: TurnContext
    message: str | None = Field(default=None, min_length=1, max_length=1000)
    answer: Answer | None = None
    draft_only: bool = False  # 1.27.0 분석하지 않고 완성한 초안만(문서 접수 확인표로 돌려보냄)
    seed: AssistantSeed | None = None  # 1.27.0 새 대화에서 이미 정한 연산·슬롯 값

    @model_validator(mode="after")
    def _one(self) -> AssistantTurnRequest:
        if (self.message is None) == (self.answer is None):
            raise ValueError("차례 요청은 새 문장이나 질문의 답 중 하나만")
        if self.answer is not None and self.conversation_id is None:
            raise ValueError("질문의 답은 이어 가는 대화에만 가능")
        if (self.draft_only or self.seed is not None) and (self.message is None or self.conversation_id):
            raise ValueError("초안만·미리 정한 값은 새 대화를 시작하는 문장에만 가능")
        return self


class TurnState(StrEnum):
    ASKING = "asking"  # 확인·선택·입력을 기다림
    ANALYZED = "analyzed"  # 분석과 설명·알림 초안까지 끝남
    DRAFTED = "drafted"  # 1.27.0 초안만 완성(분석하지 않음 — 문서 접수 확인표로 돌려보냄)


class NotificationTarget(StrEnum):
    SUPPLIER = "supplier"  # 발주 변경이 생긴 협력사
    FABRICATOR = "fabricator"  # 재작업 블록 담당(사외 제작 협력사 또는 사내 생산)
    DRAWING = "drawing"  # 도면 담당(분야)
    CREW = "crew"  # 1.32.0 사내 협력사 작업반(이미 착수·완료한 공정을 수행한 작업반)


class EmailDraft(Frozen):
    """공식 메일 초안(합니다체, docs/records.md(통보)). 앱은 보내지 않고 사용자의 메일 도구에 채워 연다.

    본문 문단의 숫자는 수치 블록에서만 나온다(E4 검출기 대상). 제목·관련 건 줄은 요청 데이터(호선·ECN 번호·제목)로
    만든다(계산값이 아니다). 받는 사람이 비면(실데이터 지도·연락처 없음) 사용자가 채운다. 서명 이름은 화면이 로그인한
    사람으로 붙인다.
    """

    to: tuple[Contact, ...] = ()
    cc: tuple[Contact, ...] = ()
    subject: str = Field(min_length=1, max_length=200)
    salutation: str = Field(min_length=1, max_length=120)  # '한결밸브 최유진 과장님께'
    reference: str = Field(min_length=1, max_length=300)  # 관련 건 줄: 'S-001 호선 · ECN-D-0038 …'
    paragraphs: tuple[RenderedText, ...] = Field(min_length=1, max_length=20)
    sender: str | None = None  # 보내는 조직·부서(가상 연락처가 있을 때만)
    fictional: bool = False  # 받는 사람·참조가 시연용 가상 연락처인가
    # 1.36.0 번역 초안(사내 협력사 작업반 통보만, 언어마다 하나 — 고정 문장·용어집, 외부 AI 없음). 비면 한국어만
    translations: tuple[MailTranslation, ...] = ()


class Notification(Frozen):
    target: NotificationTarget
    recipient_id: str  # 협력사 ID·블록 ID·도면 ID
    recipient: str  # 받는 쪽 이름
    body: RenderedText  # 화면 카드의 짧은 요약(명사형)
    email: EmailDraft | None = None  # 공식 메일 초안(계약 1.21.0부터 비서가 항상 채운다)


class AnalysisNotices(Frozen):
    """1.37.0 분석 하나의 알림 초안(상세 사전 점검 '통보문 보기', POST /api/analyses/notices).

    같은 요청을 다시 분석한 결과로 AI 비서 분석 차례와 같은 규칙(ripple/explain/compose.py notifications)으로 만든다 —
    외부 AI 없이 결정적. analysis_id는 다시 분석한 결과의 ID(화면이 보던 분석과 다르면 화면이 알린다).
    """

    analysis_id: str = Field(min_length=1, max_length=64)
    notifications: tuple[Notification, ...] = ()


class AssistantTurn(Frozen):
    conversation_id: str
    turn: int = Field(ge=1)
    state: TurnState
    message: str  # 비서 안내 한 줄(명사형)
    interpreter: Literal["rule", "rule+llm"]
    draft: ChangeDraft | None = None
    summary: str | None = None  # 이해한 변경 한 줄(연산이 정해졌을 때, 화면 표시용)
    questions: tuple[Question, ...] = ()
    decisions: tuple[DecisionAnswer, ...] = ()  # 근거 패널용 보정 확률(화면 첫 줄에는 안 보임)
    request: AnalysisRequest | None = None
    result: AnalysisResult | None = None
    explanation: RenderedText | None = None
    notifications: tuple[Notification, ...] = ()
    follow_ups: tuple[Question, ...] = ()  # 분석 뒤 질문: 변경 사유 기록·바꾸기(분석한 차례에만)
    reason_recorded: bool = False  # 앞 분석에 변경 사유만 기록한 차례(결과·분석 ID가 앞 분석과 같다)
    llm_limited: bool = False  # 이 차례에 하루 사용 한도 때문에 외부 AI를 부르지 못한 호출이 있었는가

    @model_validator(mode="after")
    def _state(self) -> AssistantTurn:
        if self.state is TurnState.DRAFTED:
            if self.draft is None or self.draft.missing():
                raise ValueError("초안만 낸 차례에는 다 채운 초안 필요")
            if self.questions or self.result is not None or self.request is not None or self.follow_ups:
                raise ValueError("초안만 낸 차례에는 질문·분석 없음")
            return self
        analyzed = self.state is TurnState.ANALYZED
        if analyzed != (self.result is not None) or analyzed != (self.request is not None):
            raise ValueError("요청과 결과는 분석을 마친 차례에만 가능")
        if analyzed and (self.questions or self.explanation is None):
            raise ValueError("분석을 마친 차례에는 질문 없이 설명 필요")
        if not analyzed and not self.questions:
            raise ValueError("묻는 차례에는 질문 하나 이상 필요")
        if (self.follow_ups or self.reason_recorded) and not analyzed:
            raise ValueError("분석 뒤 질문·사유 기록은 분석한 차례에만 가능")
        return self


class Conversation(Frozen):
    conversation_id: str
    turns: tuple[AssistantTurn, ...] = Field(min_length=1)
