"""문서 접수 계약(계약 1.27.0, docs/input.md(문서 접수)): 설계변경 문서 하나 → 변경 항목 여러 개 → 사람 확인 → 분석.

AI(합성 모드의 외부 LLM)나 규칙이 문서에서 항목을 뽑고, 항목마다 기존 해석기로 초안(ChangeDraft)을 만들어
지도와 대조한 문제를 붙인다. 사람이 항목마다 맞음·고침·뺌을 정하면 서버가 다시 검증해 연산 여러 개짜리
변경 요청 하나를 만든다. 자동 진행은 없다 — 접수는 항상 사람 확인을 거친다.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from .analysis import AnalysisRequest
from .assistant import ChangeDraft, SlotSpec, SourceSpan, TurnContext
from .base import Frozen
from .change import SourceKind
from .domain import DataMode
from .result import AnalysisResult

MAX_DOCUMENT_CHARS = 12_000
"""문서 원문 상한(글자). 넘으면 접수하지 않는다(나눠서 넣게 안내)."""
MAX_ITEMS = 30
"""문서 하나에서 보일 항목 상한. 넘는 항목은 문서 문제로 알리고 뒤는 보이지 않는다."""
MAX_FRAGMENT_CHARS = 600
"""항목 조각 상한. 해석기 원문 상한(ChangeDraft.text 1,000자) 안에 들도록 넘으면 자르고 '잘림' 문제를 붙인다."""
CANDIDATES_SHOWN = 3
"""확인표에 보이는 대상 후보 수(되묻기 집합 크기와 같은 정책)."""


class Extractor(StrEnum):
    RULE = "rule"  # 규칙 분할 + 기존 해석기
    LLM = "llm"  # 외부 LLM이 뽑은 항목(합성 모드만) + 기존 해석기로 다시 읽음


class IntakeIssueCode(StrEnum):
    UNSUPPORTED_OP = "unsupported_op"  # 연산 8종 밖(용접 각장·케이블·도장 등)
    UNREADABLE = "unreadable"  # 연산을 읽지 못함
    NOT_EXTRACTED = "not_extracted"  # AI가 항목으로 뽑지 않은 줄(규칙으로 보임)
    EXTRACT_UNVERIFIED = "extract_unverified"  # AI가 뽑은 값이 원문 조각에 없음
    TRUNCATED = "truncated"  # 조각이 길어 앞부분만 읽음
    TARGET_UNRESOLVED = "target_unresolved"  # 대상을 지도에서 찾지 못함
    TARGET_AMBIGUOUS = "target_ambiguous"  # 대상 후보가 여럿
    FROM_MISMATCH = "from_mismatch"  # 문서의 지금 값이 지도와 다름
    REVISION_MISMATCH = "revision_mismatch"  # 문서 개정이 지도 도면 개정과 다름(정보)
    VALUE_MISSING = "value_missing"  # 필요한 값이 없음
    VALUE_UNCERTAIN = "value_uncertain"  # 값 표현이 모호·범위 밖(추정 값)
    LLM_RULE_DISAGREE = "llm_rule_disagree"  # AI와 규칙이 다른 값을 읽음
    TEXT_LEFTOVER = "text_leftover"  # 조각에 어디에도 안 쓴 표현이 남음
    DUPLICATE = "duplicate"  # 다른 항목과 같은 변경(합치거나 하나를 빼야 함)
    CONFLICT = "conflict"  # 다른 항목과 같은 부재를 같은 성질로 바꾸거나, 뺀 부재를 다시 가리킴


BLOCKING = frozenset(
    {
        IntakeIssueCode.UNSUPPORTED_OP,
        IntakeIssueCode.UNREADABLE,
        IntakeIssueCode.EXTRACT_UNVERIFIED,
        IntakeIssueCode.TARGET_UNRESOLVED,
        IntakeIssueCode.TARGET_AMBIGUOUS,
        IntakeIssueCode.VALUE_MISSING,
        IntakeIssueCode.LLM_RULE_DISAGREE,
        IntakeIssueCode.DUPLICATE,
        IntakeIssueCode.CONFLICT,
    }
)
"""그대로 '맞음'으로 확정할 수 없는 문제: 고치거나(대상·수치·비서) 빼야 한다. 나머지(지도와 다른 지금 값·추정 값·
개정·잘림·AI가 안 뽑은 줄·남은 표현)는 사람이 보고 '맞음'을 누르면 그 판단으로 확정한다(지금 값은 지도 값을 쓴다).
남은 표현(예: '하고 브라켓 2번은 삭제')은 그대로 확정하면 그 부분이 빠지므로 화면이 강조한다."""


class IntakeIssue(Frozen):
    code: IntakeIssueCode
    message: str = Field(min_length=1, max_length=300)  # 명사형
    slot: str | None = None  # 문제가 걸린 슬롯(없으면 항목 전체)

    @property
    def blocking(self) -> bool:
        return self.code in BLOCKING


class TargetCandidate(Frozen):
    """대상 부재 후보(확인표 고르기). 확률은 판단 계층의 보정 확률(합성 문장 기준)."""

    part_id: str
    label: str
    probability: float | None = Field(default=None, ge=0, le=1)


class AiReading(Frozen):
    """AI가 이 항목에서 읽은 것(화면 비교용, 값은 원문 조각에 있는 것만)."""

    op: str | None = None  # 연산 8종 이름 또는 unsupported
    target: str | None = Field(default=None, max_length=200)
    before: str | None = Field(default=None, max_length=60)
    after: str | None = Field(default=None, max_length=60)
    reason: str | None = Field(default=None, max_length=200)


class IntakeItem(Frozen):
    item_id: str = Field(pattern=r"^I\d{1,3}$")
    source: SourceSpan  # 문서 원문 기준 위치와 조각
    extractor: Extractor
    draft: ChangeDraft | None = None  # 조각을 해석한 초안(슬롯 위치는 조각 기준). 연산을 못 읽으면 None
    slots: tuple[SlotSpec, ...] = ()  # 초안 연산의 칸 명세(확인표가 이름·숫자 칸·대상 칸을 안다). 초안이 없으면 비움
    candidates: tuple[TargetCandidate, ...] = Field(default=(), max_length=CANDIDATES_SHOWN)
    issues: tuple[IntakeIssue, ...] = ()
    ai: AiReading | None = None

    @model_validator(mode="after")
    def _slots_follow_draft(self) -> IntakeItem:
        if self.slots != (self.draft.specs() if self.draft is not None else ()):
            raise ValueError("칸 명세가 초안 연산과 다름")
        return self

    @property
    def blocking(self) -> bool:
        return any(i.blocking for i in self.issues)


class IntakeHeader(Frozen):
    """문서 머리 정보. 원문에서 읽은 것(사람이 고칠 수 있다)."""

    ecn_ref: str | None = Field(default=None, max_length=120)  # 원문 설계변경 번호
    title: str | None = Field(default=None, max_length=200)
    revision: str | None = Field(default=None, max_length=40)
    requested_by: str | None = Field(default=None, max_length=80)
    requested_on: date | None = None
    reason: str | None = Field(default=None, max_length=300)


class ExistingEcn(Frozen):
    """같은 원문 번호로 이미 기록한 설계변경(이어 갈지 묻는다)."""

    ecn_id: str
    title: str
    state: str
    can_continue: bool  # 실행·종료된 설계변경은 새 개정을 받지 않는다 → 새 ID로


class IntakeProposal(Frozen):
    proposal_id: str
    snapshot_id: str
    data_mode: DataMode
    kind: SourceKind
    document: str = Field(min_length=1, max_length=MAX_DOCUMENT_CHARS)  # 정규화한 원문(항목 위치의 기준)
    header: IntakeHeader
    items: tuple[IntakeItem, ...] = Field(max_length=MAX_ITEMS)
    extractor: Literal["rule", "rule+llm"]
    problems: tuple[IntakeIssue, ...] = ()  # 문서 단위 문제(항목 상한, AI 호출 실패 등)
    ecn_id: str  # 확정하면 쓸 기록 ID(원문 번호 정규화 + 해시, 없으면 문서 해시)
    existing: ExistingEcn | None = None
    calibration_note: str  # 확률의 근거(합성 문장 기준 보정)

    @model_validator(mode="after")
    def _unique(self) -> IntakeProposal:
        ids = [i.item_id for i in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("항목 ID 중복")
        return self


class ItemAction(StrEnum):
    ACCEPT = "accept"  # 맞음(추정·AI 값·지도와 다른 지금 값은 이 판단으로 확정)
    EDIT = "edit"  # 대상·수치를 고침(또는 비서가 완성한 초안으로 바꿈)
    DROP = "drop"  # 뺌


class ItemDecision(Frozen):
    item_id: str
    action: ItemAction
    part_ids: tuple[str, ...] | None = None  # 고친 대상(대상 슬롯이 하나인 연산)
    values: dict[str, float] = Field(default_factory=dict)  # 고친 수치(슬롯 이름 → 값)
    draft: ChangeDraft | None = None  # 비서가 완성한 초안(이것이 있으면 항목 초안을 바꾼다)

    @model_validator(mode="after")
    def _shape(self) -> ItemDecision:
        edits = self.part_ids is not None or bool(self.values) or self.draft is not None
        if self.action is ItemAction.EDIT and not edits:
            raise ValueError("고침에는 바꿀 대상·수치·초안 중 하나 이상 필요")
        if self.action is not ItemAction.EDIT and edits:
            raise ValueError("고친 값은 '고침'에만 가능")
        if any(v <= 0 for v in self.values.values()):
            raise ValueError("수치는 0 초과 필요")
        return self


class IntakeConfirmation(Frozen):
    proposal_id: str
    context: TurnContext
    header: IntakeHeader
    decisions: tuple[ItemDecision, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    continue_ecn: bool = False  # 같은 원문 번호의 기존 설계변경에 새 개정으로 이어 감

    @model_validator(mode="after")
    def _unique(self) -> IntakeConfirmation:
        ids = [d.item_id for d in self.decisions]
        if len(set(ids)) != len(ids):
            raise ValueError("같은 항목 결정 중복")
        return self


class ItemProblem(Frozen):
    item_id: str | None  # None이면 문서 전체
    message: str


class IntakeResult(Frozen):
    ecn_id: str
    request: AnalysisRequest
    result: AnalysisResult
    kept: int = Field(ge=1)  # 분석에 넣은 항목 수
    dropped: int = Field(ge=0)


class IntakeTextInput(Frozen):
    text: str = Field(min_length=1, max_length=MAX_DOCUMENT_CHARS)
    ship_ids: tuple[str, ...] = Field(min_length=1)
