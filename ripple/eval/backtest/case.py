"""사례 한 건(엑셀 한 행)과 양식의 열(docs/backtest.md 2절).

원문 칸(변경 내용·블록·구역)은 양식에만 있고 사례(Case)에 담지 않는다 — 지도·결과·출력 어디로도 옮기지 않기 위해서다.
숫자 칸은 숫자만 받고(범위는 최소·최대 두 칸), 빈 칸은 None으로 둔다. 잘못 적은 칸은 사례의 problems에 남는다.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from ripple.contracts.change import ChangeCause
from ripple.contracts.domain import BlockStage
from ripple.engine.describe import BLOCK_STAGE_NAMES

from .defaults import BlockType, DelayBasis, Performer, SpoolMethod

ColumnKind = Literal["id", "text", "choice", "number", "count"]
WON_PER_MANWON = 10_000

CAUSES: dict[str, ChangeCause] = {
    "설계 간섭": ChangeCause.DESIGN_ERROR,
    "선주 코멘트": ChangeCause.OWNER_REQUEST,
    "규정": ChangeCause.CLASS_RULE,
    "기자재 사양": ChangeCause.EQUIPMENT,
    "현장 오작": ChangeCause.PRODUCTION,
}
BLOCK_TYPES: dict[str, BlockType] = {"평": "flat", "곡": "curved", "선수미": "bow_stern"}
PERFORMERS: dict[str, Performer] = {"직영": "direct", "사내 협력사": "in_house_subcontractor"}
SPOOL_METHODS: dict[str, SpoolMethod] = {"사내 재제작": "in_house", "사외 재발주": "outside", "치수 변경": "dimension"}
DELAY_BASES: dict[str, DelayBasis] = {"탑재": "erection", "구역 출구": "exit", "인도": "delivery"}
STAGES: dict[str, BlockStage] = {name: stage for stage, name in BLOCK_STAGE_NAMES.items()}
"""발견 단계 선택지 = 지금 엔진의 블록 단계 이름(진행 순서)."""
STAGE_ALIASES: dict[str, BlockStage] = {
    "판계": BlockStage.PANEL,
    "판넬조립": BlockStage.PANEL,
    "조립": BlockStage.ASSEMBLY,
    "대조립": BlockStage.ASSEMBLY,
}
"""같은 단계의 다른 이름(읽을 때만): 엔진 단계 이름이 바뀌어도(판계 ↔ 판넬조립, 조립 ↔ 대조립) 옛 양식을 읽는다."""


@dataclass(frozen=True, slots=True)
class Column:
    key: str
    header: str
    kind: ColumnKind
    options: tuple[str, ...] = ()
    note: str = ""
    private: bool = False  # 원문 칸: 읽지 않고 결과로 옮기지 않음


COLUMNS: tuple[Column, ...] = (
    Column("case_no", "사례 번호", "id", note="회사·호선을 알 수 없는 짧은 번호(예: C1) · 비우면 '사례 n'"),
    Column("content", "변경 내용", "text", note="무엇을 바꿨나(원문) · 결과 파일에는 미포함", private=True),
    Column("cause", "변경 원인", "choice", tuple(CAUSES)),
    Column("area", "블록·구역", "text", note="예: 기관실 블록(번호는 가려도 됨) · 결과 파일에는 미포함", private=True),
    Column("block_type", "블록 종류", "choice", tuple(BLOCK_TYPES), note="재작업 난이도(형상) · 비우면 계수 1(가정)"),
    Column("block_weight_t", "블록 무게(t)", "number", note="모르면 비움(블록 종류별 기본값)"),
    Column("stage", "발견 단계", "choice", tuple(STAGES), note="엔진의 블록 단계 이름 · 비우면 계산 제외"),
    Column("members", "바뀐 부재 수", "count", note="배관 스풀을 뺀 부재"),
    Column("spools", "재제작 스풀 수", "count"),
    Column(
        "spool_method",
        "재제작 방식",
        "choice",
        tuple(SPOOL_METHODS),
        note="스풀을 어떻게 다시 만들었나 · 비우면 사내 재제작으로 계산(가정)",
    ),
    Column("drawings", "개정 도면 수", "count"),
    Column("po_changes", "발주 변경 건수", "count"),
    Column("mh_min", "추가 공수 최소(MH)", "number", note="변경 전체 공수 · 한 값만 알면 최소·최대에 같은 값"),
    Column("mh_max", "추가 공수 최대(MH)", "number"),
    Column("cost_min", "비용 최소(만원)", "number", note="대략 범위 · 한 값만 알면 최소·최대에 같은 값"),
    Column("cost_max", "비용 최대(만원)", "number"),
    Column("delay_days", "지연 일수(일)", "number", note="이 변경으로 늦어진 날"),
    Column(
        "delay_basis",
        "지연 기준",
        "choice",
        tuple(DELAY_BASES),
        note="지연 일수를 어디서 쟀나 · 비우면 구역 출구로 비교(가정)",
    ),
    Column("performer", "수행 주체", "choice", tuple(PERFORMERS), note="사내 협력사는 작업반으로(탑재는 직영)"),
    Column("decision_days", "결정까지 걸린 일수(일)", "count", note="변경 요청 → 확정 · 비우면 0일(가정)"),
)
COLUMN_BY_KEY: dict[str, Column] = {column.key: column for column in COLUMNS}


@dataclass(frozen=True, slots=True)
class Span:
    """실제 값의 범위(최소·최대). 대표값은 가운데."""

    low: float
    high: float

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2


@dataclass(frozen=True, slots=True)
class Case:
    number: str
    row: int  # 엑셀 행 번호
    cause: ChangeCause | None
    block_type: BlockType | None
    block_weight_t: float | None
    stage: BlockStage | None
    members: int | None
    spools: int | None
    drawings: int | None
    po_changes: int | None
    mh: Span | None
    cost_krw: Span | None
    delay_days: float | None
    performer: Performer | None
    decision_days: int | None
    spool_method: SpoolMethod | None = None
    delay_basis: DelayBasis | None = None
    problems: tuple[str, ...] = ()  # 잘못 적은 칸(있으면 계산하지 않음)


class _Reader:
    """한 행의 칸을 형식대로 읽고, 잘못 적은 칸은 문제로 모은다."""

    def __init__(self, values: Mapping[str, object]) -> None:
        self.values = values
        self.problems: list[str] = []

    def blank(self, key: str) -> bool:
        value = self.values.get(key)
        return value is None or (isinstance(value, str) and not value.strip())

    def text(self, key: str) -> str | None:
        return None if self.blank(key) else str(self.values[key]).strip()

    def number(self, key: str) -> float | None:
        if self.blank(key):
            return None
        value = self.values[key]
        parsed = _as_number(value)
        if parsed is None or parsed < 0:
            self.problems.append(f"{COLUMN_BY_KEY[key].header}: 0 이상의 숫자만 가능({value!r})")
            return None
        return parsed

    def count(self, key: str) -> int | None:
        parsed = self.number(key)
        if parsed is None:
            return None
        if not parsed.is_integer():
            self.problems.append(f"{COLUMN_BY_KEY[key].header}: 정수만 가능({parsed:g})")
            return None
        return int(parsed)

    def choice[T](self, key: str, options: Mapping[str, T]) -> T | None:
        found = self.text(key)
        if found is None:
            return None
        if found not in options:
            self.problems.append(f"{COLUMN_BY_KEY[key].header}: 목록에 있는 값만 가능({found!r})")
            return None
        return options[found]

    def span(self, low_key: str, high_key: str, scale: float = 1.0) -> Span | None:
        low, high = self.number(low_key), self.number(high_key)
        if low is None and high is None:
            return None
        low = high if low is None else low
        high = low if high is None else high
        assert low is not None and high is not None
        if low > high:
            self.problems.append(f"{COLUMN_BY_KEY[low_key].header}가 최대 초과")
            return None
        return Span(low * scale, high * scale)


def _as_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            parsed = float(value.replace(",", "").strip())
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def parse_case(values: Mapping[str, object], row: int, ordinal: int) -> Case:
    """엑셀 한 행(열 키 → 칸 값) → 사례. 원문 칸은 values에 있어도 읽지 않는다."""
    read = _Reader({key: value for key, value in values.items() if not COLUMN_BY_KEY[key].private})
    return Case(
        number=read.text("case_no") or f"사례 {ordinal}",
        row=row,
        cause=read.choice("cause", CAUSES),
        block_type=read.choice("block_type", BLOCK_TYPES),
        block_weight_t=_positive(read, "block_weight_t"),
        stage=read.choice("stage", {**STAGE_ALIASES, **STAGES}),
        members=read.count("members"),
        spools=read.count("spools"),
        drawings=read.count("drawings"),
        po_changes=read.count("po_changes"),
        mh=read.span("mh_min", "mh_max"),
        cost_krw=read.span("cost_min", "cost_max", WON_PER_MANWON),
        delay_days=read.number("delay_days"),
        performer=read.choice("performer", PERFORMERS),
        decision_days=read.count("decision_days"),
        spool_method=read.choice("spool_method", SPOOL_METHODS),
        delay_basis=read.choice("delay_basis", DELAY_BASES),
        problems=tuple(read.problems),
    )


def _positive(read: _Reader, key: str) -> float | None:
    value = read.number(key)
    if value == 0:
        read.problems.append(f"{COLUMN_BY_KEY[key].header}: 0보다 큰 값만 가능(모르면 빈칸)")
        return None
    return value
