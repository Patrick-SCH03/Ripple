"""생성기가 만드는 자료 계약: 설계변경 사례와 자연어 문장 사례.

평가 도구·판단 계층 보정·화면의 예시 입력이 함께 쓴다.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from .base import Frozen
from .change import ChangeRequest


class EcnSplit(StrEnum):
    DEV = "dev"  # 개발용(규칙·파라미터 조정, 판단 계층 선택)
    EVAL = "eval"  # 평가용(튜닝에 쓰지 않음)


class GeneratedEcn(Frozen):
    split: EcnSplit
    as_of: date  # 분석 기준일(시나리오 기준일)
    change: ChangeRequest


class NlSplit(StrEnum):
    """문장 자료 분할(docs/input.md(판단 계층) 4절). 분할마다 시드가 다르다."""

    TRAIN = "train"  # 점수기 가중치 학습
    TEMPERATURE = "temperature"  # 온도 보정, 검정할 문턱 목록
    SELECTION = "selection"  # 개발 중 반복(특징·후보 규칙·사전 고르기)
    TAU = "tau"  # 자동 진행 문턱 검정
    SET = "set"  # 되묻기 집합 q̂
    EVAL = "eval"  # 합격 기준 E8(최종 인증 한 번)
    ECN_DEV = "ecn_dev"  # 설계변경 이력 개발 200건의 문장(E3)
    ECN_EVAL = "ecn_eval"  # 설계변경 이력 평가 100건의 문장


ValueForm = Literal["absolute", "from_to", "delta", "ratio", "none"]


class MentionTruth(Frozen):
    """문장 속 조각 하나가 가리키는 정답.

    부재 조각은 그 부재를 다른 부재와 구별하는 부분(번호·코드)이고, 번호 없이 이름만으로
    가리키면 이름 전체다. 값 조각은 값 표현 전체('15에서 17로', '2mm 증가')이고 value는 슬롯 값이다.
    """

    slot: str  # 변경 연산 필드 이름(part_ids·plate_part_id·block_id·spec_id·to_mm …), 연산은 "op", 의도는 "intent"
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    value: str | float  # 부재·블록·규격 ID, 강종, 치수 종류, 수치, 연산 이름, 의도
    exists: bool = True  # 가리키는 대상이 지도에 있음(없는 번호를 쓴 문장이면 False)

    @model_validator(mode="after")
    def _span(self) -> MentionTruth:
        if self.end <= self.start:
            raise ValueError("조각의 끝이 시작보다 뒤가 아님")
        return self


class NlSample(Frozen):
    """문장 하나와 정답. 단위(판단 계층의 요청 문 단위)는 문장 하나다."""

    sample_id: str
    split: NlSplit
    text: str = Field(min_length=1, max_length=1000)
    ship_id: str
    as_of: date
    change: ChangeRequest  # 정답 변경 요청(연산 하나). 없는 대상을 쓴 문장이면 그 ID를 그대로 둔다
    mentions: tuple[MentionTruth, ...] = ()
    value_form: ValueForm
    intent_stated: bool  # 변경 사유를 문장에 적었음
    noise: tuple[str, ...] = ()  # 넣은 변형: typo·spacing·order·abbreviation·case
    source_ecn_id: str | None = None  # 설계변경 이력 문장이면 그 ECN

    @model_validator(mode="after")
    def _consistent(self) -> NlSample:
        if len(self.change.ops) != 1:
            raise ValueError("문장 사례는 변경 연산 하나만")
        if any(m.end > len(self.text) for m in self.mentions):
            raise ValueError("조각 위치가 문장 밖")
        return self
