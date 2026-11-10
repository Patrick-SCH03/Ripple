"""변경 일정의 조정(docs/engine.md(비용·일정) 6-3): 새 자재·재작업 관문, 보류한 발주의 자재 제약, 선상 설치 lag."""

from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping
from datetime import date, timedelta

from ripple.contracts.analysis import HoldAction
from ripple.contracts.domain import POStatus

from ..cost import Demand
from ..cost.onboard import OnboardBlock
from ..index import GraphIndex
from ..onboard import DemandKey, demand_key
from ..schedule import Adjustments, Network, ShipSchedule, Times
from ..state import StateModel

ONE_DAY = timedelta(days=1)


def adjustments(
    index: GraphIndex,
    schedule: ShipSchedule,
    day: date,
    rework_days: dict[str, int],
    needed: tuple[Demand, ...],
    holds: tuple[HoldAction, ...],
    state: StateModel,
    onboard: Mapping[str, OnboardBlock],
) -> Adjustments:
    """한 호선의 조정: 재작업 일수는 블록 공정에, 새 자재·재작업 관문과 보류한 발주의 입고는 착수 하한에,
    선상 설치 일수는 탑재 후행의 lag에 건다."""
    net, base = schedule.network, schedule.base
    on_board = {demand_key(d) for block in onboard.values() for d in block.demands}
    gates, started_arrivals = _material_gates(net, base, needed, day, on_board)
    extra = _rework_extra(net, base, rework_days, started_arrivals, gates, day)
    start_floor: dict[str, date] = {}
    for block_id, values in gates.items():
        for target in gate_targets(net, base, block_id, day):
            _raise_floor(start_floor, target, max(values))
    for hold in holds:
        arrival = entry_estimate_from(state, hold.po_id)
        if arrival is None:
            continue
        for consumer in _held_consumers(index, net, hold.po_id):
            _raise_floor(start_floor, consumer, arrival)
    extra_lag = _onboard_lags(net, onboard, start_floor)
    return Adjustments(extra_days=extra, extra_lag=extra_lag, start_floor=start_floor)


def gate_targets(net: Network, base: Times, block_id: str, day: date) -> tuple[str, ...]:
    """탑재 관문: 판정일에 탑재 전이면 그 블록 탑재, 이미 탑재했으면 탑재의 후행 구역 출구(선상 재작업)."""
    chain = net.chains.get(block_id)
    if not chain:
        return ()
    erection = chain[-1]
    if base.es[erection] > day:
        return (erection,)
    return exit_successors(net, erection)


def exit_successors(net: Network, erection: str) -> tuple[str, ...]:
    """탑재의 후행 중 구역 출구 이정표(6-3). 블록 사이 탑재 선후행이 있는 지도의 다음 블록 탑재는 뺀다 —
    관문·선상 설치 lag는 출구에만 건다(다음 블록 탑재는 선후행으로만 이 탑재를 따른다)."""
    exits = set(net.exits)
    return tuple(successor for successor, _ in net.succs.get(erection, ()) if successor in exits)


def entry_estimate_from(state: StateModel, po_id: str) -> date | None:
    return next(w.estimate for w in state.windows(po_id) if w.stage is POStatus.RECEIVED)


def _held_consumers(index: GraphIndex, net: Network, po_id: str) -> Iterator[str]:
    """보류한 발주의 자재를 쓰는 공정 중 아직 착수하지 않은 것(발주 품목 순)."""
    for line in index.lines.values():
        consumer = line.consumed_by_activity_id
        if consumer is None or line.po_id != po_id or consumer not in net.nodes:
            continue
        if net.nodes[consumer].started is None:
            yield consumer


def _raise_floor(start_floor: dict[str, date], a_id: str, when: date) -> None:
    start_floor[a_id] = max(start_floor.get(a_id, when), when)


def _material_gates(
    net: Network, base: Times, needed: tuple[Demand, ...], day: date, on_board: Collection[DemandKey]
) -> tuple[dict[str, list[date]], dict[str, list[date]]]:
    """새 자재가 필요한 블록: 소비 공정이 착수 전이면 '도착 다음 날' 관문, 이미 착수했으면 도착일(재작업 시작 하한).
    배 위로 보낸 수요(on_board)는 관문에 넣지 않는다(탑재 후행에 따로 건다, _onboard_lags)."""
    gates: dict[str, list[date]] = {}
    started_arrivals: dict[str, list[date]] = {}
    for demand in needed:
        if demand.consumer is None or demand.arrival is None or demand.consumer not in net.nodes:
            continue
        if demand_key(demand) in on_board:
            continue
        block = net.nodes[demand.consumer].block_id or ""
        if base.es[demand.consumer] > day:  # 착수 전: 블록은 진행하되 새 자재를 받아 처리해야 탑재
            gates.setdefault(block, []).append(demand.arrival + ONE_DAY)
        else:
            started_arrivals.setdefault(block, []).append(demand.arrival)
    return gates, started_arrivals


def _rework_extra(
    net: Network,
    base: Times,
    rework_days: dict[str, int],
    started_arrivals: dict[str, list[date]],
    gates: dict[str, list[date]],
    day: date,
) -> dict[str, int]:
    """재작업 일수를 판정일 뒤 첫 블록 공정에 더하고, 재작업이 끝나는 날을 그 블록의 관문에 더한다(gates를 고친다)."""
    extra: dict[str, int] = {}
    for block_id, d in rework_days.items():
        chain = net.chains.get(block_id)
        if not chain:
            continue
        carrier = next((a for a in chain if base.ef[a] > day), None)
        if carrier is not None:
            extra[carrier] = extra.get(carrier, 0) + d
        done_by = max([day + ONE_DAY, *started_arrivals.get(block_id, [])]) + timedelta(days=d)
        gates.setdefault(block_id, []).append(done_by)
    return extra


def _onboard_lags(
    net: Network, onboard: Mapping[str, OnboardBlock], start_floor: dict[str, date]
) -> dict[tuple[str, str], int]:
    """선상 설치(6-3): 탑재의 후행(구역 출구)마다 lag += d_on, 자재 제약 ≥ max(도착일 + 1) + d_on(start_floor를 고친다).
    출구는 탑재가 끝나고 자재를 받은 뒤 선상 설치가 끝나야 착수한다."""
    lags: dict[tuple[str, str], int] = {}
    for block in onboard.values():
        if block.erection not in net.nodes:
            continue
        arrivals = [d.arrival for d in block.demands if d.arrival is not None]
        ready = max(arrivals) + ONE_DAY + timedelta(days=block.days)
        for successor in exit_successors(net, block.erection):
            lags[(block.erection, successor)] = lags.get((block.erection, successor), 0) + block.days
            _raise_floor(start_floor, successor, ready)
    return lags
