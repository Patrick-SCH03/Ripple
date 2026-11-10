"""수정 기록 계약(계약 1.27.0, docs/input.md(문서 접수) 7절): 사람이 AI·규칙의 제안을 어떻게 받아들이고 고쳤는가.

문서 접수 확인표와 AI 비서 대화에서 사람이 정한 것을 한 줄씩 남긴다. 쓰임은 둘이다.
1. 지표: 칸·채움 방식별 '사람이 고친 비율'(특강 p41 STEP3), 뺀 비율, 비서로 넘긴 비율.
2. 재보정 자료: 판단 계층 질문의 선택지·특징 값·확률·경로와 사람의 최종 선택(원문 없이도 다시 학습할 수 있게
   특징 값을 남긴다). 원문은 합성 모드에서만 남긴다(실데이터는 ID·값·방식만).
체험·개발 모드 행은 지표와 재보정 자료에서 뺀다(따로 개수만 센다).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from .base import Frozen
from .domain import DataMode


class CorrectionOrigin(StrEnum):
    INTAKE = "intake"  # 문서 접수 확인표
    ASSISTANT = "assistant"  # AI 비서 대화의 질문 답


class CorrectionAction(StrEnum):
    ACCEPT = "accept"  # 제안 그대로
    EDIT = "edit"  # 다른 값으로 고침
    DROP = "drop"  # 항목을 뺌
    ADD = "add"  # 제안에 없던 값을 사람이 넣음
    HANDOFF = "handoff"  # 비서로 넘겨 고침


class DecisionTrace(Frozen):
    """판단 계층 질문 하나의 재보정 자료(원문 없이 다시 학습할 수 있는 형태)."""

    topic: str
    question_id: str
    options: tuple[str, ...] = Field(min_length=2)
    features: dict[str, dict[str, float]]  # 선택지 → 특징 이름 → 값
    probabilities: dict[str, float] = Field(default_factory=dict)  # 보정 확률(보정 산출물이 없으면 빈 사전)
    route: str | None = None
    ready: bool | None = None  # 판단 밖 자동 진행 자격(값·슬롯 완결성)

    @model_validator(mode="after")
    def _consistent(self) -> DecisionTrace:
        if set(self.features) != set(self.options):
            raise ValueError("특징 값은 선택지마다 하나씩 필요")
        return self


class CorrectionEvent(Frozen):
    at: datetime
    actor: str  # 로그인 아이디
    demo: bool = False
    dev: bool = False
    data_mode: DataMode
    origin: CorrectionOrigin
    ref: str  # 제안 ID 또는 대화 ID
    item: str | None = None  # 항목 ID 또는 질문 키
    slot: str  # 'op'·슬롯 이름·'item'(항목 전체)
    action: CorrectionAction
    proposed: str | None = Field(default=None, max_length=400)  # 제안 값(JSON 글)
    final: str | None = Field(default=None, max_length=400)  # 사람이 확정한 값(JSON 글)
    method: str | None = None  # 제안 값의 채움 방식(rule·decision·map·guess·llm …)
    extractor: str | None = None  # rule | llm
    model: str | None = None  # AI 모델 이름(쓴 경우)
    trace: DecisionTrace | None = None
    text: str | None = Field(default=None, max_length=1000)  # 원문 조각(합성 모드만)

    @model_validator(mode="after")
    def _privacy(self) -> CorrectionEvent:
        if self.data_mode is not DataMode.SYNTHETIC and self.text is not None:
            raise ValueError("실데이터 모드에서는 원문 기록 불가")
        return self


class CorrectionRate(Frozen):
    """한 묶음(칸·채움 방식)의 사람 결정 집계."""

    key: str  # 예: 'slot:to_mm' · 'method:llm' · 'item'
    decided: int = Field(ge=0)
    accepted: int = Field(ge=0)
    edited: int = Field(ge=0)
    dropped: int = Field(ge=0)
    handed_off: int = Field(ge=0)

    @property
    def edit_rate(self) -> float | None:
        base = self.accepted + self.edited
        return None if base == 0 else self.edited / base


class CorrectionSummary(Frozen):
    since: datetime | None = None
    rows: int = Field(ge=0)  # 집계에 넣은 행
    excluded: int = Field(ge=0)  # 체험·개발 모드라 뺀 행
    rates: tuple[CorrectionRate, ...] = ()
