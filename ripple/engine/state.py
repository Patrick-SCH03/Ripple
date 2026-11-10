"""단계 추정: 발주·발주 품목·블록이 어느 날 어느 단계인가(docs/domain.md 3·4절).

상태는 저장하지 않고 근거(확인된 진입일·관측)와 계획, 기준일로 그때그때 계산한다. 기준일 뒤의
근거는 그날 알 수 없으므로 쓰지 않는다. 하루의 단계는 세 값으로 낸다.
- earliest: 근거로 확실히 들어간 가장 뒤 단계
- latest: 근거상 들어갔을 수 있는 가장 뒤 단계
- likely: 대표 단계(계획 추정 포함). 근거도 계획도 없으면 None → 화면의 '판단 불가'
규칙은 문턱 질문("발주 이후인가")을 StageOn.at_least로 묻는다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import StrEnum
from typing import Protocol

from ripple.contracts.analysis import HoldAction
from ripple.contracts.domain import (
    BLOCK_STAGE_ORDER,
    PO_STATUS_ORDER,
    STAGE_OF_ACTIVITY,
    Activity,
    ActivityKind,
    BlockStage,
    EntityType,
    POStatus,
    PurchaseOrder,
    Relation,
)

from .index import GraphIndex

ONE_DAY = timedelta(days=1)
ENTRY_STAGES: tuple[POStatus, ...] = (
    POStatus.ORDERED,
    POStatus.MATERIAL_SECURED,
    POStatus.IN_FABRICATION,
    POStatus.RECEIVED,
)
"""진입일을 추정하는 발주 단계. 미발주는 시작 상태이고, 가공은 발주 품목의 소비 공정 착수로 정한다."""
STEEL_CATEGORIES = frozenset({"plate", "section"})
"""블록의 '강재 입고'를 정하는 자재 분류."""

_RANKS: dict[type[StrEnum], dict[StrEnum, int]] = {
    POStatus: {stage: i for i, stage in enumerate(PO_STATUS_ORDER)},
    BlockStage: {stage: i for i, stage in enumerate(BLOCK_STAGE_ORDER)},
}


def rank(stage: StrEnum) -> int:
    """진행 순서상 위치(발주 단계·블록 단계). 정의 순서가 진행 순서다(contracts.domain)."""
    return _RANKS[type(stage)][stage]


class Basis(StrEnum):
    """추정 근거. 근거 패널과 설명이 단계를 어떻게 정했는지 밝힐 때 쓴다."""

    EVIDENCE = "evidence"  # 확인된 진입일·관측으로 정해짐
    PLAN = "plan"  # 근거 범위 안에서 계획으로 추정
    OFF_PLAN = "off_plan"  # 계획이 근거 범위를 벗어나 가까운 끝값으로 추정(계획 이탈, 뒤 단계로 이어짐)
    UNKNOWN = "unknown"  # 근거도 계획도 없어 정할 수 없음


# ---------- 하루의 단계 ----------


@dataclass(frozen=True, slots=True)
class StageOn[S: StrEnum]:
    """어느 날의 단계. 진행 순서로 earliest ≤ likely ≤ latest."""

    earliest: S
    latest: S
    likely: S | None
    basis: Basis

    def __post_init__(self) -> None:
        low, high = rank(self.earliest), rank(self.latest)
        if low > high or (self.likely is not None and not low <= rank(self.likely) <= high):
            raise ValueError(f"단계 범위 불일치: {self.earliest} ≤ {self.likely} ≤ {self.latest}")

    @property
    def known(self) -> bool:
        return self.likely is not None

    def surely_at_least(self, stage: S) -> bool:
        return rank(self.earliest) >= rank(stage)

    def possibly_at_least(self, stage: S) -> bool:
        return rank(self.latest) >= rank(stage)

    def at_least(self, stage: S) -> bool | None:
        """그날 stage 이상인가. 근거로 정해지면 그대로, 아니면 대표 단계로 답하고, 정할 수 없으면 None."""
        if self.surely_at_least(stage):
            return True
        if not self.possibly_at_least(stage):
            return False
        return None if self.likely is None else rank(self.likely) >= rank(stage)


# ---------- 발주 단계 ----------


@dataclass(frozen=True, slots=True)
class StageWindow:
    """발주 단계 하나의 진입일: 근거가 허락하는 범위 [lo, hi]와 대표 진입일."""

    stage: POStatus
    lo: date | None  # 가장 이른 진입일(None = 근거상 제한 없음)
    hi: date | None  # 가장 늦은 진입일(None = 들어갔다는 근거 없음)
    estimate: date | None  # 대표 진입일(None = 정할 수 없음)
    basis: Basis

    def surely_by(self, day: date) -> bool:
        return self.hi is not None and self.hi <= day

    def possibly_by(self, day: date) -> bool:
        return self.lo is None or self.lo <= day

    def entered_by(self, day: date) -> bool | None:
        """그날까지 들어갔나: 근거로 정해지면 그대로, 아니면 대표 진입일로, 그것도 없으면 None."""
        if self.surely_by(day):
            return True
        if not self.possibly_by(day):
            return False
        return None if self.estimate is None else self.estimate <= day


def stage_windows(po: PurchaseOrder, as_of: date) -> tuple[StageWindow, ...]:
    """발주 단계별 진입 범위와 대표 진입일(docs/domain.md 3절).

    범위: 확인된 진입일이면 그날. 아니면 하한 = 앞 단계로 관측된 마지막 날의 다음 날·앞 단계의 확인된
    진입일, 상한 = 그 단계 이상으로 처음 관측된 날·뒤 단계의 확인된 진입일.
    대표: 앞 단계의 대표 진입일(첫 단계는 계획 발주일) + 계획 간격 차이를 범위 안으로 조인 값.
    """
    confirmed = {stage: day for stage, day in po.entered_on.items() if day <= as_of}
    seen = [(rank(o.status), o.observed_on) for o in po.observations if o.observed_on <= as_of]
    offsets = {
        POStatus.ORDERED: 0,
        POStatus.MATERIAL_SECURED: po.material_secured_days,
        POStatus.IN_FABRICATION: po.fabrication_start_days,
        POStatus.RECEIVED: po.lead_time_days,
    }
    windows: list[StageWindow] = []
    previous: StageWindow | None = None
    for stage in ENTRY_STAGES:
        k = rank(stage)
        lo = max(
            [day + ONE_DAY for r, day in seen if r < k] + [day for s, day in confirmed.items() if rank(s) < k],
            default=None,
        )
        hi = min(
            [day for r, day in seen if r >= k] + [day for s, day in confirmed.items() if rank(s) > k],
            default=None,
        )
        if stage in confirmed:
            entered = confirmed[stage]
            window = StageWindow(stage, entered, entered, entered, Basis.EVIDENCE)
        elif lo is not None and lo == hi:
            window = StageWindow(stage, lo, hi, lo, Basis.EVIDENCE)
        else:
            window = _estimated(stage, lo, hi, _plan_entry(po, stage, previous, offsets))
        windows.append(window)
        previous = window
    return tuple(windows)


def _plan_entry(
    po: PurchaseOrder, stage: POStatus, previous: StageWindow | None, offsets: Mapping[POStatus, int]
) -> tuple[date, Basis] | None:
    if previous is None:
        return None if po.planned_order_date is None else (po.planned_order_date, Basis.PLAN)
    if previous.estimate is None:
        return None
    carried = Basis.OFF_PLAN if previous.basis is Basis.OFF_PLAN else Basis.PLAN
    return previous.estimate + timedelta(days=offsets[stage] - offsets[previous.stage]), carried


def _estimated(stage: POStatus, lo: date | None, hi: date | None, plan: tuple[date, Basis] | None) -> StageWindow:
    if plan is None:
        return StageWindow(stage, lo, hi, None, Basis.UNKNOWN)
    planned, basis = plan
    estimate = planned
    if lo is not None and estimate < lo:
        estimate = lo
    if hi is not None and estimate > hi:
        estimate = hi
    return StageWindow(stage, lo, hi, estimate, Basis.OFF_PLAN if estimate != planned else basis)


def hold_windows(windows: Sequence[StageWindow], as_of: date, hold_days: int) -> tuple[StageWindow, ...]:
    """보류: 기준일에 아직 들어가지 않은 단계를 보류 일수만큼 미룬다. 이미 들어간 단계는 그대로다."""
    shift = timedelta(days=hold_days)

    def later(day: date | None) -> date | None:
        return day + shift if day is not None and day > as_of else day

    return tuple(replace(w, lo=later(w.lo), hi=later(w.hi), estimate=later(w.estimate)) for w in windows)


def po_stage_on(windows: Sequence[StageWindow], day: date) -> StageOn[POStatus]:
    earliest = latest = POStatus.NOT_ORDERED
    for window in windows:
        if window.surely_by(day):
            earliest = window.stage
        if window.possibly_by(day):
            latest = window.stage
    likely: POStatus | None = POStatus.NOT_ORDERED
    for window in windows:
        entered = window.entered_by(day)
        if entered is None:
            likely = None
            break
        if not entered:
            break
        likely = window.stage
    open_bases = [w.basis for w in windows if w.possibly_by(day) and not w.surely_by(day)]
    return StageOn(earliest, latest, likely, _day_basis(earliest, latest, likely, open_bases))


def processed_on(po: PurchaseOrder, as_of: date) -> date | None:
    """발주 근거로 '가공'이 확인된 가장 이른 날(기준일 뒤 근거는 쓰지 않음)."""
    days = [o.observed_on for o in po.observations if o.status is POStatus.PROCESSED and o.observed_on <= as_of]
    confirmed = po.entered_on.get(POStatus.PROCESSED)
    if confirmed is not None and confirmed <= as_of:
        days.append(confirmed)
    return min(days, default=None)


# ---------- 공정 착수 ----------


@dataclass(frozen=True, slots=True)
class ActivityStart:
    """공정 착수일. actual은 기준일까지 확인된 실제 착수일이고 earliest ≤ expected다."""

    actual: date | None
    earliest: date  # 가장 이른 착수일
    expected: date  # 대표 착수일


class ActivityClock(Protocol):
    def start(self, activity_id: str) -> ActivityStart: ...


class PlanClock:
    """1단계 기본 시계: 실제 착수일, 없으면 계획 착수일(기준일 다음 날보다 이르지 않게).

    공정은 계획 착수일보다 일찍 시작하지 않는다(contracts.domain.Activity). 앞 공정 지연을 뒤로
    넘기는 일정 계산(CPM)은 2단계에서 이 자리를 대신한다.
    """

    def __init__(self, activities: Mapping[str, Activity], as_of: date) -> None:
        self._activities = activities
        self._as_of = as_of

    def start(self, activity_id: str) -> ActivityStart:
        activity = self._activities[activity_id]
        actual = activity.actual_start
        if actual is not None and actual <= self._as_of:
            return ActivityStart(actual=actual, earliest=actual, expected=actual)
        earliest = max(activity.planned_start, self._as_of + ONE_DAY)
        return ActivityStart(actual=None, earliest=earliest, expected=earliest)


# ---------- 발주 품목·블록 단계 ----------


def line_stage_on(
    po_state: StageOn[POStatus], processed: date | None, consumer: ActivityStart | None, day: date
) -> StageOn[POStatus]:
    """발주 품목 단계 = 발주 단계, 다만 소비 공정이 착수했거나 발주 근거가 '가공'이면 '가공'.

    가공은 입고 뒤에만 올 수 있다고 본다. 소비 공정을 모르면 가공 여부를 추정하지 않는다(가능성만 연다).
    """
    if (processed is not None and processed <= day) or (
        consumer is not None and consumer.actual is not None and consumer.actual <= day
    ):
        done = POStatus.PROCESSED
        return StageOn(done, done, done, Basis.EVIDENCE)
    receivable = po_state.possibly_at_least(POStatus.RECEIVED)
    possibly = receivable and (consumer is None or consumer.earliest <= day)
    probably = consumer is not None and po_state.likely is POStatus.RECEIVED and consumer.expected <= day
    latest = POStatus.PROCESSED if possibly else po_state.latest
    likely = POStatus.PROCESSED if probably else po_state.likely
    bases = [po_state.basis, Basis.PLAN]
    return StageOn(po_state.earliest, latest, likely, _day_basis(po_state.earliest, latest, likely, bases))


def block_stage_on(
    activities: Sequence[tuple[ActivityKind, ActivityStart]], steel: Sequence[StageOn[POStatus]], day: date
) -> StageOn[BlockStage]:
    """블록 단계 = 그날까지 착수한 가장 뒤 블록 공정의 단계(docs/domain.md 4절).

    공정 착수 전이면 강재 발주 품목이 모두 입고됐는지로 '강재 입고'/'미착수'를 정한다.
    강재 품목이 없으면 그 구분은 정하지 않는다(재작업 배수는 둘 다 0).
    """
    blocks = [(STAGE_OF_ACTIVITY[kind], start) for kind, start in activities if kind in STAGE_OF_ACTIVITY]
    surely = [stage for stage, s in blocks if s.actual is not None and s.actual <= day]
    possibly = [stage for stage, s in blocks if s.earliest <= day]
    probably = [stage for stage, s in blocks if s.expected <= day]
    received = POStatus.RECEIVED
    steel_surely = bool(steel) and all(line.surely_at_least(received) for line in steel)
    steel_possibly = all(line.possibly_at_least(received) for line in steel)
    steel_likely = _all_of([line.at_least(received) for line in steel]) if steel else None

    earliest = _block_stage(surely, steel_surely)
    latest = _block_stage(possibly, steel_possibly)
    likely = _block_stage(probably, steel_likely) if probably or steel_likely is not None else None
    bases = [Basis.PLAN] + [
        line.basis for line in steel if line.possibly_at_least(received) and not line.surely_at_least(received)
    ]
    return StageOn(earliest, latest, likely, _day_basis(earliest, latest, likely, bases))


def _block_stage(started: list[BlockStage], steel_in: bool | None) -> BlockStage:
    if started:
        return max(started, key=rank)
    return BlockStage.STEEL_RECEIVED if steel_in else BlockStage.NOT_STARTED


def _all_of(answers: Iterable[bool | None]) -> bool | None:
    """세 값 논리곱: 하나라도 아니면 False, 모르는 것이 있으면 None."""
    values = list(answers)
    if False in values:
        return False
    return None if None in values else True


def _day_basis[S: StrEnum](earliest: S, latest: S, likely: S | None, open_bases: Iterable[Basis]) -> Basis:
    if earliest == latest:
        return Basis.EVIDENCE
    if likely is None:
        return Basis.UNKNOWN
    return Basis.OFF_PLAN if Basis.OFF_PLAN in set(open_bases) else Basis.PLAN


# ---------- 지도에 묶은 계산기 ----------


class StateModel:
    """지도·기준일·보류 묶음 하나의 단계 계산. 규칙·비용·보류 권고가 같은 인스턴스를 쓴다."""

    def __init__(
        self,
        index: GraphIndex,
        as_of: date,
        holds: Iterable[HoldAction] = (),
        clock: ActivityClock | None = None,
    ) -> None:
        self.index = index
        self.as_of = as_of
        self._holds = {hold.po_id: hold.hold_days for hold in holds}
        self._clock = clock or PlanClock(index.activities, as_of)
        self._windows: dict[str, tuple[StageWindow, ...]] = {}
        self._steel: dict[str, tuple[str, ...]] = {}

    def start_of(self, activity_id: str) -> ActivityStart:
        return self._clock.start(activity_id)

    def windows(self, po_id: str) -> tuple[StageWindow, ...]:
        if po_id not in self._windows:
            windows = stage_windows(self.index.orders[po_id], self.as_of)
            hold_days = self._holds.get(po_id)
            self._windows[po_id] = hold_windows(windows, self.as_of, hold_days) if hold_days else windows
        return self._windows[po_id]

    def po_stage_on(self, po_id: str, day: date) -> StageOn[POStatus]:
        return po_stage_on(self.windows(po_id), day)

    def line_stage_on(self, line_id: str, day: date) -> StageOn[POStatus]:
        line = self.index.lines[line_id]
        consumer = None if line.consumed_by_activity_id is None else self._clock.start(line.consumed_by_activity_id)
        processed = processed_on(self.index.orders[line.po_id], self.as_of)
        return line_stage_on(self.po_stage_on(line.po_id, day), processed, consumer, day)

    def block_stage_on(self, block_id: str, day: date) -> StageOn[BlockStage]:
        members = self.index.into(block_id, Relation.PART_OF)
        activities = [
            (self.index.activities[a].kind, self._clock.start(a))
            for a in members
            if self.index.type_of(a) is EntityType.ACTIVITY
        ]
        steel = [self.line_stage_on(line_id, day) for line_id in self.steel_lines(block_id)]
        return block_stage_on(activities, steel, day)

    def steel_lines(self, block_id: str) -> tuple[str, ...]:
        """블록의 강재(판·형강) 부재를 공급하는 발주 품목."""
        if block_id not in self._steel:
            index = self.index
            lines = {
                index.line_of_part[part_id]
                for part_id in index.into(block_id, Relation.PART_OF)
                if part_id in index.line_of_part
                and index.specs[index.parts[part_id].spec_id].category in STEEL_CATEGORIES
            }
            self._steel[block_id] = tuple(sorted(lines))
        return self._steel[block_id]
