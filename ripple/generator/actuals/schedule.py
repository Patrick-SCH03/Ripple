"""참 변경 일정: 새 자재 도착, 재작업 운반 공정, 탑재 관문, 구역 출구·인도 지연(docs/engine.md(비용·일정) 5·6-3).

외자재(1.33.0): 리드타임이 생산 리드타임(규격 표준·파라미터)이면 참 운송 일수(참 파라미터 transport_days)를 더한다 —
리드타임 변동(`lead_days`)은 생산분에만.

전진 계산은 숨긴 모델의 `_forward`가 한다(이 모듈은 그 입력과 결과 비교만).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from ripple.contracts.change import AddPart, ChangeRequest, ReroutePipe
from ripple.contracts.domain import ActivityKind, POStatus

from .case import Case
from .common import DAY, STEEL
from .delivery import delivery_added
from .material import Material, imported
from .network import block_chain
from .world import World

LeadDays = Callable[[ChangeRequest, str, str, int], int]
"""(설계변경, 새 규격, 분류, 표준 리드타임) → 새 규격 자재가 오기까지 걸리는 날(숨긴 모델의 `_lead_days` —
진단 스크립트의 하위 클래스가 바꿔 끼운다)."""


@dataclass(frozen=True, slots=True)
class Demand:
    """새 자재가 소비 공정에 도착하는 날."""

    consumer: str
    arrival: date


def demand_dates(
    world: World,
    case: Case,
    materials: list[Material],
    covered: Mapping[str, float],
    lead_days: LeadDays,
    *,
    planned_orders: bool,
) -> list[Demand]:
    """재고로 못 채운 바뀌는 부재의 새 규격(발주됐으면 확정일, 아니면 발주일부터)과 새 부재 자재(확정일부터)의 도착.

    planned_orders = 미발주 품목의 앞으로의 발주일을 지도의 계획 발주일로 본다(요인 order_date 고정).
    """
    demands: list[Demand] = []
    for m in materials:
        if not m.line_id or m.new_qty <= covered[m.part_id]:
            continue
        line = world.lines[m.line_id]
        consumer = line.consumed_by_activity_id
        if consumer is None:
            continue
        stage = case.line_stage(world, m.line_id)
        ordered = world.po_stages[line.po_id][POStatus.ORDERED]
        if planned_orders and stage is POStatus.NOT_ORDERED:
            planned = world.orders[line.po_id].planned_order_date
            if planned is not None:
                ordered = max(planned, case.as_of + DAY)
        if ordered > case.as_of:
            ordered += timedelta(days=case.held.get(line.po_id, 0))
        start = case.confirm_on if stage is not POStatus.NOT_ORDERED else ordered
        days = lead_days(case.change, m.new_spec_id, m.category, m.lead) + world.transport_days(m.transport)
        demands.append(Demand(consumer, start + timedelta(days=days)))
    demands.extend(_new_part_demands(world, case, lead_days))
    return demands


def _new_part_demands(world: World, case: Case, lead_days: LeadDays) -> list[Demand]:
    """부재 추가(강재 제외)·새 스풀의 자재: 새 부재 블록의 선행 의장 공정에 확정일 + 리드타임에 도착."""
    demands: list[Demand] = []
    for op in case.change.ops:
        if not isinstance(op, AddPart | ReroutePipe):
            continue
        specs = (op.spec_id,) if isinstance(op, AddPart) else op.added_spool_spec_ids
        new_block: str | None = (
            op.block_id
            if isinstance(op, AddPart)
            else (world.parts[min(op.removed_part_ids)].block_id if op.removed_part_ids else None)
        )
        for spec_id in specs:
            spec = world.specs[spec_id]
            if new_block is None or (isinstance(op, AddPart) and spec.category in STEEL):
                continue
            consumer = next(
                (
                    a.activity_id
                    for a in case.nodes.values()
                    if a.block_id == new_block and a.kind is ActivityKind.PRE_OUTFITTING
                ),
                None,
            )
            if consumer:
                lead = spec.std_lead_time_days or round(world.param(f"lead_time_days.{spec.category}"))
                days = lead_days(case.change, spec_id, spec.category, lead) + world.transport_days(imported(spec))
                demands.append(Demand(consumer, case.confirm_on + timedelta(days=days)))
    return demands


def schedule_changes(
    case: Case, work_days: Mapping[str, int], demands: list[Demand]
) -> tuple[dict[str, int], dict[str, date]]:
    """변경 일정 전진 계산의 (추가 일수, 관문): 재작업 일수는 운반 공정에, 자재 도착·재작업 완료는 탑재 관문에 둔다."""
    extra, waiting = _rework_and_waiting(case, work_days, demands)
    return extra, _erection_gates(case, waiting)


def exit_delays(world: World, case: Case, changed_ef: Mapping[str, date]) -> tuple[dict[str, int], int | None]:
    """(구역 출구별 지연, 늘어난 인도 지연): 참 기준 일정 대비 변경 일정의 구역 출구 완료일."""
    exits = [a_id for a_id in case.order if case.nodes[a_id].kind is ActivityKind.MILESTONE]
    delays = {a_id: (changed_ef[a_id] - case.base_ef[a_id]).days for a_id in exits}
    delivery = delivery_added(
        {a_id: case.base_ef[a_id] for a_id in exits},
        {a_id: changed_ef[a_id] for a_id in exits},
        {a_id: case.nodes[a_id].planned_start for a_id in exits},
        world.boundaries,
    )
    return delays, delivery


def _rework_and_waiting(
    case: Case, work_days: Mapping[str, int], demands: list[Demand]
) -> tuple[dict[str, int], dict[str, list[date]]]:
    """(운반 공정 → 재작업 일수, 블록 → 탑재가 기다리는 날들).

    착수 전 소비 공정의 자재는 도착 다음 날을 기다리고, 이미 착수한 공정의 자재 도착은 재작업 시작을 늦춘다.
    """
    extra: dict[str, int] = {}
    waiting: dict[str, list[date]] = defaultdict(list)
    started_waiting: dict[str, list[date]] = defaultdict(list)
    for demand in demands:
        demand_block = case.nodes[demand.consumer].block_id
        if demand_block is None:
            continue
        if case.base_es[demand.consumer] > case.confirm_on:
            waiting[demand_block].append(demand.arrival + DAY)
        else:
            started_waiting[demand_block].append(demand.arrival)
    for block, days in work_days.items():
        if days <= 0:
            continue
        carrier = next(
            (a for a in block_chain(case.nodes, block) if case.base_ef[a.activity_id] > case.confirm_on), None
        )
        if carrier is not None:
            extra[carrier.activity_id] = days
        waiting[block].append(max([case.confirm_on + DAY, *started_waiting[block]]) + timedelta(days=days))
    return extra, waiting


def _erection_gates(case: Case, waiting: Mapping[str, list[date]]) -> dict[str, date]:
    """블록 탑재(이미 착수했으면 탑재 뒤 공정)가 기다리는 가장 늦은 날, 보류 발주 품목의 미뤄진 입고일."""
    gates: dict[str, date] = {}
    for block, arrivals in waiting.items():
        erection = next(
            (a for a in case.nodes.values() if a.block_id == block and a.kind is ActivityKind.ERECTION), None
        )
        if erection is None:
            continue
        targets = (
            [erection.activity_id]
            if case.base_es[erection.activity_id] > case.confirm_on
            else [
                a.activity_id
                for a in case.nodes.values()
                if any(p.activity_id == erection.activity_id for p in a.predecessors)
            ]
        )
        for target in targets:
            gates[target] = max(gates.get(target, date.min), *arrivals)
    for consumer, arrival in case.held_gates.items():
        gates[consumer] = max(gates.get(consumer, date.min), arrival)
    return gates
