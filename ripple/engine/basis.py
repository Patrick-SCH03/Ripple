"""판단이 걸린 상태(docs/domain.md 12절): 분석 결과를 만든 발주·공정의 기준일 바탕 상태와 근거.

대상은 엔진이 상태를 읽는 엔터티를 결과에서 거슬러 모은다: 비용 줄·영향·판단 불가·보류 권고가 가리키는
- 발주 품목 → 발주와 소비 공정(품목의 '가공'은 소비 공정 착수로 정해진다),
- 발주,
- 블록 → 블록 공정(마지막으로 착수한 것과 다음 것), 아직 착수 전이면 강재 품목의 발주(블록 단계는 강재 입고로 정해진다).
상태는 기준일에 보류 없이 계산한 바탕 상태 하나로만 낸다
(확정일·곡선·보류의 미래 상태는 '오늘 확인' 값으로 쓰면 안 되므로).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from ripple.contracts.domain import BLOCK_ACTIVITY_ORDER, EntityType, Relation
from ripple.contracts.result import BasisKind, CostLine, HoldAdvice, Impact, StateBasis, Unresolved

from .describe import describe
from .state import StateModel


@dataclass(slots=True)
class _Need:
    lines: set[str] = field(default_factory=set)  # 걸린 비용 줄
    via: set[str] = field(default_factory=set)  # 데려온 품목·블록


class _Collector:
    def __init__(self, state: StateModel) -> None:
        self.state = state
        self.index = state.index
        self.orders: defaultdict[str, _Need] = defaultdict(_Need)
        self.activities: defaultdict[str, _Need] = defaultdict(_Need)

    def entity(self, entity_id: str | None, cost_line: str | None = None) -> None:
        if entity_id is None:
            return
        kind = self.index.type_of(entity_id)
        if kind is EntityType.PO:
            self._order(entity_id, cost_line)
        elif kind is EntityType.PO_LINE:
            self._line(entity_id, cost_line)
        elif kind is EntityType.BLOCK:
            self._block(entity_id, cost_line)

    def _order(self, po_id: str, cost_line: str | None, via: str | None = None) -> None:
        need = self.orders[po_id]
        if cost_line:
            need.lines.add(cost_line)
        if via:
            need.via.add(via)

    def _activity(self, activity_id: str, cost_line: str | None, via: str) -> None:
        need = self.activities[activity_id]
        if cost_line:
            need.lines.add(cost_line)
        need.via.add(via)

    def _line(self, line_id: str, cost_line: str | None) -> None:
        line = self.index.lines[line_id]
        self._order(line.po_id, cost_line, line_id)
        if line.consumed_by_activity_id is not None:
            self._activity(line.consumed_by_activity_id, cost_line, line_id)

    def _block(self, block_id: str, cost_line: str | None) -> None:
        order = {kind: i for i, kind in enumerate(BLOCK_ACTIVITY_ORDER)}
        members = sorted(
            (a for a in self.index.into(block_id, Relation.PART_OF) if a in self.index.activities),
            key=lambda a: (order.get(self.index.activities[a].kind, len(order)), a),
        )
        as_of = self.state.as_of
        started = [a for a in members if (s := self.state.start_of(a).actual) is not None and s <= as_of]
        waiting = [a for a in members if a not in started]
        for activity_id in started[-1:] + waiting[:1]:
            self._activity(activity_id, cost_line, block_id)
        if not started:  # 착수 전 블록 단계(미착수·강재 입고)는 강재 품목 입고로 정한다
            for line_id in self.state.steel_lines(block_id):
                self._order(self.index.lines[line_id].po_id, None, block_id)


def state_basis(
    state: StateModel,
    lines: Iterable[CostLine],
    impacts: Iterable[Impact],
    unresolved: Iterable[Unresolved],
    holds: Iterable[HoldAdvice],
) -> tuple[StateBasis, ...]:
    """state는 기준일·보류 없는 바탕 상태(Propagator.state(()))여야 한다."""
    collector = _Collector(state)
    for line in lines:
        collector.entity(line.entity_id, line.line_id)
    for impact in impacts:
        collector.entity(impact.entity_id)
    for item in unresolved:
        collector.entity(item.entity_id)
    held = set()
    for advice in holds:
        held.add(advice.po_id)
        collector.entity(advice.po_id)
    rows = [_order_row(state, po_id, need, po_id in held) for po_id, need in sorted(collector.orders.items())]
    rows += [_activity_row(state, a, need) for a, need in sorted(collector.activities.items())]
    return tuple(rows)


def _order_row(state: StateModel, po_id: str, need: _Need, held: bool) -> StateBasis:
    as_of = state.as_of
    po = state.index.orders[po_id]
    stage = state.po_stage_on(po_id, as_of)
    days = [o.observed_on for o in po.observations if o.observed_on <= as_of]
    days += [d for d in po.entered_on.values() if d <= as_of]
    return StateBasis(
        entity_type="po",
        entity_id=po_id,
        label=describe(state.index, po_id).label,
        as_of=as_of,
        po_status=stage.likely,
        basis=BasisKind(stage.basis.value),
        last_confirmed=max(days, default=None),
        line_ids=tuple(sorted(need.lines)),
        hold=held,
        via=tuple(sorted(need.via)),
    )


def _activity_row(state: StateModel, activity_id: str, need: _Need) -> StateBasis:
    as_of = state.as_of
    activity = state.index.activities[activity_id]
    start = state.start_of(activity_id)
    started = start.actual if start.actual is not None and start.actual <= as_of else None
    finished = activity.actual_finish if activity.actual_finish and activity.actual_finish <= as_of else None
    days: list[date] = [c.confirmed_on for c in activity.confirmations if c.confirmed_on <= as_of]
    days += [d for d in (started, finished) if d is not None]
    return StateBasis(
        entity_type="activity",
        entity_id=activity_id,
        label=describe(state.index, activity_id).label,
        as_of=as_of,
        actual_start=started,
        actual_finish=finished,
        expected_start=None if started else start.expected,
        basis=BasisKind.EVIDENCE if started else BasisKind.PLAN,
        last_confirmed=max(days, default=None),
        line_ids=tuple(sorted(need.lines)),
        via=tuple(sorted(need.via)),
    )
