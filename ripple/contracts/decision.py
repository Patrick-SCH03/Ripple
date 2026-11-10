"""판단 계층 계약: 선택지형 질문과 보정된 답(docs/input.md(판단 계층)).

정해진 선택지 중 하나를 고르는 판단(대상 특정, 의도·연산 분류, 엑셀 열 매핑)에만 쓴다.
비용·일정·적격 판정과 설명문에는 쓰지 않는다. 모든 질문에는 '해당 없음'이 들어 있다.

자동 진행은 문(gate) 단위로 정한다. 요청 문은 변경 요청 하나(대상·연산·의도 판단 전부),
열 문은 엑셀 열 하나다. 주제마다는 온도와 되묻기 집합 q̂만 둔다.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from datetime import date
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType

from pydantic import Field, model_validator

from .base import Frozen

NONE_OPTION = "__none__"
"""'해당 없음' 선택지 ID. 정답이 후보에 없거나 대상이 존재하지 않을 때의 정답이다."""


class DecisionTopic(StrEnum):
    TARGET_PART = "target_part"  # 문장 속 표현 → 부재
    CHANGE_INTENT = "change_intent"
    CHANGE_OP = "change_op"
    EXCEL_COLUMN = "excel_column"  # 엑셀 열 → Ripple 필드


class GateKind(StrEnum):
    REQUEST = "request"  # 변경 요청 하나(대상·연산)
    COLUMN = "column"  # 엑셀 열 하나
    INTENT = "intent"  # 변경 사유 하나(분석 뒤 기록: 자동 진행이면 바로 기록, 아니면 묻는다)


GATE_TOPICS: Mapping[GateKind, tuple[DecisionTopic, ...]] = MappingProxyType(
    {
        GateKind.REQUEST: (DecisionTopic.TARGET_PART, DecisionTopic.CHANGE_OP),
        GateKind.COLUMN: (DecisionTopic.EXCEL_COLUMN,),
        GateKind.INTENT: (DecisionTopic.CHANGE_INTENT,),
    }
)
"""문마다 그 단위를 이루는 판단 주제."""


class DecisionBackend(StrEnum):
    LOCAL = "local"  # 로컬 특징 점수기(기본, 모든 모드)
    GEMINI = "gemini"  # 옛 값(Gemini는 경로에서 뺌, 계약 호환으로만 남김)
    JEV = "jev"  # 합성 모드 전용, 비교 실험


class Route(StrEnum):
    AUTO = "auto"  # 자동 진행
    CONFIRM = "confirm"  # 후보 하나를 확인받기
    CHOOSE = "choose"  # 되묻기 집합 안에서 고르기
    RESTATE = "restate"  # 다시 설명해 달라고 묻기


class Option(Frozen):
    option_id: str = Field(min_length=1)
    label: str  # 되묻기 화면에 보이는 이름
    entity_id: str | None = None


class ChoiceQuestion(Frozen):
    question_id: str
    topic: DecisionTopic
    mention: str  # 판단 대상 표현, 예: "3번 탱크 횡격벽 하단 판"
    options: tuple[Option, ...] = Field(min_length=2, max_length=256)

    @model_validator(mode="after")
    def _options(self) -> ChoiceQuestion:
        ids = [o.option_id for o in self.options]
        if len(set(ids)) != len(ids):
            raise ValueError("선택지 ID 중복")
        if NONE_OPTION not in ids:
            raise ValueError("모든 질문에 '해당 없음' 선택지 필요")
        return self

    @property
    def option_ids(self) -> tuple[str, ...]:
        return tuple(o.option_id for o in self.options)


class DecisionTargets(Frozen):
    """보정 목표값. 합격 기준을 보기 전에 고정한다."""

    alpha: float = Field(gt=0, lt=0.5)  # 되묻기 집합 미포함률
    delta: float = Field(gt=0, lt=0.5)  # 자동 진행 보장이 틀릴 확률
    epsilon: dict[GateKind, float]  # 문마다 자동 진행 단위의 오류율 상한
    max_choices: int = Field(ge=2, le=20)
    coverage_levels: tuple[float, ...] = Field(min_length=1)  # 검정 순서: 자동 진행 비율 수준(오름차순)

    @model_validator(mode="after")
    def _consistent(self) -> DecisionTargets:
        if set(self.epsilon) != set(GateKind):
            raise ValueError("모든 문에 오류율 상한 필요")
        if not all(0 < e < 0.5 for e in self.epsilon.values()):
            raise ValueError("오류율 상한은 0과 0.5 사이 값 필요")
        levels = self.coverage_levels
        if not all(0 < v < 1 for v in levels) or any(b <= a for a, b in pairwise(levels)):
            raise ValueError("자동 진행 비율 수준은 (0, 1) 안의 오름차순 필요")
        return self


class TopicCalibration(Frozen):
    """주제 하나의 보정 산출물: 온도와 되묻기 집합 q̂(ripple.decide.policy가 만든다)."""

    topic: DecisionTopic
    backend: DecisionBackend
    temperature: float = Field(gt=0)
    set_qhat: float = Field(ge=0, le=1)  # 1이면 모든 선택지
    n_temperature: int = Field(ge=0)
    n_set: int = Field(ge=0)  # 집합 보정에 쓴 단위 수(필터 뒤, 단위마다 점수 하나)
    temperature_split: str  # 자료 해시
    set_split: str


class ScorerModel(Frozen):
    """주제 하나의 로컬 점수기 가중치(ripple.decide.scorer가 학습 분할로 학습). 특징 이름 → 가중치."""

    topic: DecisionTopic
    backend: DecisionBackend = DecisionBackend.LOCAL
    weights: dict[str, float]
    n_train: int = Field(ge=0)
    train_split: str  # 자료 해시


class Gate(Frozen):
    """문 하나의 자동 진행 문턱. 단위 신뢰도(판단 최상위 확률의 최솟값) 기준이고 None이면 끔."""

    kind: GateKind
    auto_threshold: float | None = Field(default=None, gt=0, le=1)
    n_units: int = Field(ge=0)
    split: str  # τ 분할 자료 해시


class DecisionConfig(Frozen):
    version: str = Field(pattern=r"^(decision|column)-v\d+$")  # column-vN: 엑셀 열 문 보정 산출물(따로 보정)
    updated: date
    targets: DecisionTargets
    scorers: tuple[ScorerModel, ...] = ()
    topics: tuple[TopicCalibration, ...] = ()
    gates: tuple[Gate, ...] = ()

    @model_validator(mode="after")
    def _unique(self) -> DecisionConfig:
        groups = (
            ("점수기", [s.topic for s in self.scorers]),
            ("주제", [t.topic for t in self.topics]),
            ("문", [g.kind for g in self.gates]),
        )
        for name, keys in groups:
            duplicated = [k for k, n in Counter(keys).items() if n > 1]
            if duplicated:
                raise ValueError(f"{name}마다 보정 산출물은 하나만 · 중복 {duplicated}")
        return self

    def topic(self, topic: DecisionTopic) -> TopicCalibration | None:
        return next((t for t in self.topics if t.topic is topic), None)

    def scorer(self, topic: DecisionTopic) -> ScorerModel | None:
        return next((s for s in self.scorers if s.topic is topic), None)

    def gate(self, kind: GateKind) -> Gate | None:
        return next((g for g in self.gates if g.kind is kind), None)


class DecisionAnswer(Frozen):
    question_id: str
    topic: DecisionTopic
    probabilities: dict[str, float]  # 보정된 확률, 선택지마다 하나, 합 1
    top: str
    prediction_set: tuple[str, ...]  # 되묻기 집합(자동 진행·미리 채운 확인이면 최상위 하나)
    route: Route
    backend: DecisionBackend
    policy_version: str

    @model_validator(mode="after")
    def _consistent(self) -> DecisionAnswer:
        probs = self.probabilities
        if NONE_OPTION not in probs:
            raise ValueError("확률에 '해당 없음' 누락")
        if not all(0.0 <= p <= 1.0 for p in probs.values()) or not math.isclose(sum(probs.values()), 1.0, abs_tol=1e-6):
            raise ValueError("확률은 0~1, 합은 1 필요")
        if self.top not in probs or probs[self.top] < max(probs.values()):
            raise ValueError("최상위가 확률 최대 선택지가 아님")
        chosen = self.prediction_set
        if not chosen or self.top not in chosen or len(set(chosen)) != len(chosen) or not set(chosen) <= set(probs):
            raise ValueError("되묻기 집합은 최상위를 포함한 선택지 묶음 필요")
        if self.route is Route.AUTO and (self.top == NONE_OPTION or chosen != (self.top,)):
            raise ValueError("자동 진행은 '해당 없음'이 아닌 최상위 하나로만 가능")
        if self.route is Route.CONFIRM and len(chosen) != 1:
            raise ValueError("확인은 후보 하나일 때만 가능")
        if self.route is Route.CHOOSE and len(chosen) < 2:
            raise ValueError("고르기는 후보 둘 이상일 때만 가능")
        return self
