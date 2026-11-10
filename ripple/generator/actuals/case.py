"""사례 하나의 결정(확정일·보류)과 참 기준 일정: 항목·일정 계산 모듈들이 같이 읽는다."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from ripple.contracts.change import ChangeRequest
from ripple.contracts.domain import Activity, POStatus

from .world import World


@dataclass(frozen=True, slots=True)
class Case:
    """설계변경 하나를 기준일에 보고 확정일·보류를 정한 경우.

    base_* = 참 기준 일정(변경 없음, 보류 없음), stage_es = 보류한 발주의 미뤄진 입고를 반영한 착수일(발주 단계의
    '가공됨' 판단용), held_gates = 보류 발주 품목의 미뤄진 참 입고일(착수 전 소비 공정의 제약).
    """

    change: ChangeRequest
    as_of: date
    confirm_on: date
    held: Mapping[str, int]
    order: tuple[str, ...]
    nodes: Mapping[str, Activity]
    floors: Mapping[str, date]
    base_es: Mapping[str, date]
    base_ef: Mapping[str, date]
    stage_es: Mapping[str, date]
    held_gates: Mapping[str, date]

    def line_stage(self, world: World, line_id: str) -> POStatus:
        """확정일의 참 발주 단계."""
        return world.line_stage(line_id, self.confirm_on, self.stage_es, self.held, self.as_of)


def held_arrivals(
    world: World,
    held: Mapping[str, int],
    nodes: Mapping[str, Activity],
    base_es: Mapping[str, date],
    as_of: date,
) -> dict[str, date]:
    """보류한 발주 품목의 미뤄진 참 입고일 → 기준일 뒤 착수하는 소비 공정마다 가장 늦은 입고일."""
    gates: dict[str, date] = {}
    for line in world.snapshot.po_lines:
        days = held.get(line.po_id, 0)
        consumer = line.consumed_by_activity_id
        if days <= 0 or consumer is None or consumer not in nodes or base_es[consumer] <= as_of:
            continue
        arrival = world.po_stages[line.po_id][POStatus.RECEIVED]
        if arrival > as_of:
            arrival += timedelta(days=days)
        gates[consumer] = max(gates.get(consumer, date.min), arrival)
    return gates
