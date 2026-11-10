"""엑셀 매핑 제안의 값: 열 문 보정 산출물(ColumnModel), 열 경로(RoutedColumn), 시트·파일 제안(SheetPlan·FilePlan),
사람이 정한 시트 상태(Override), 사람이 확인할 것(pending)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ripple.contracts.decision import DecisionAnswer, DecisionConfig, DecisionTopic, Gate, GateKind, TopicCalibration

from .columns import ColumnJudgment, SheetJudgment
from .tables import SheetGuess


@dataclass(frozen=True, slots=True)
class ColumnModel:
    """열 문 보정 산출물(params/column_v1.yaml)을 쓰기 좋게 푼 것."""

    version: str
    weights: Mapping[str, float]
    calibrations: Mapping[DecisionTopic, TopicCalibration]
    gate: Gate
    max_choices: int

    @property
    def temperature(self) -> float:
        return self.calibrations[DecisionTopic.EXCEL_COLUMN].temperature

    @staticmethod
    def of(config: DecisionConfig) -> ColumnModel:
        scorer = config.scorer(DecisionTopic.EXCEL_COLUMN)
        gate = config.gate(GateKind.COLUMN)
        topic = config.topic(DecisionTopic.EXCEL_COLUMN)
        if scorer is None or gate is None or topic is None:
            raise ValueError("열 문 보정 산출물에 점수기·문턱·온도 모두 필요")
        return ColumnModel(config.version, scorer.weights, {topic.topic: topic}, gate, config.targets.max_choices)


@dataclass(frozen=True, slots=True)
class RoutedColumn:
    judgment: ColumnJudgment
    answer: DecisionAnswer | None  # 판단 열의 판단 계층 답(정확 일치·남은 항목 없음이면 None)
    auto: bool  # 확인 없이 채움


@dataclass(frozen=True, slots=True)
class SheetPlan:
    """파일 시트 하나의 제안: 양식 시트·머리글 행(표 찾기 또는 덮어쓰기)과 열 판단."""

    guess: SheetGuess
    judged: SheetJudgment | None
    columns: tuple[RoutedColumn, ...]

    @property
    def certain(self) -> bool:
        return self.guess.certain


@dataclass(frozen=True, slots=True)
class FilePlan:
    sheets: tuple[SheetPlan, ...]
    exact: bool  # 지정 양식 그대로(plain_template)


@dataclass(frozen=True, slots=True)
class Override:
    """사람이 정한 시트 상태·머리글 행(열 확인 화면). template None = 읽지 않음."""

    template: str | None
    header_rows: tuple[int, ...] | None = None


def pending(plan: FilePlan) -> Sequence[str]:
    """사람이 확인할 것(화면 위쪽에 모음): 확실하지 않은 시트, 자동 진행이 아닌 열."""
    found = []
    for sheet in plan.sheets:
        if not sheet.certain:
            found.append(f"{sheet.guess.file_sheet}: 시트")
        found += [f"{sheet.guess.file_sheet}:{c.judgment.file_column.position}" for c in sheet.columns if not c.auto]
    return found
