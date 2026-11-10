"""기준 일정: 호선마다 망·변경 없는 CPM 결과·가장 늦은 착수일(docs/engine.md(비용·일정) 6-2·6-5).

상태 함수의 공정 시계(ActivityClock)이기도 하다. 단계 판정·비용·일정이 같은 착수일을 쓰게 한다
(docs/engine.md(비용·일정) 1절). 망에 없는 공정(진수·인도 이정표)은 1단계 시계 규칙(실적, 없으면 계획
착수일과 기준일 다음 날 중 늦은 날)을 쓴다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

from ..index import GraphIndex
from ..state import ActivityStart, PlanClock
from .cpm import Times, forward, latest_starts
from .network import Network, build_network


@dataclass(frozen=True, slots=True)
class ShipSchedule:
    network: Network
    base: Times
    latest: Mapping[str, date]  # 블록 탑재일을 늦추지 않는 가장 늦은 착수일


class Baseline:
    def __init__(self, index: GraphIndex, as_of: date) -> None:
        self.as_of = as_of
        ships = sorted({a.ship_id for a in index.activities.values()})
        schedules: dict[str, ShipSchedule] = {}
        for ship_id in ships:
            network = build_network(index, ship_id, as_of)
            base = forward(network)
            schedules[ship_id] = ShipSchedule(network, base, MappingProxyType(latest_starts(network, base)))
        self.ships: Mapping[str, ShipSchedule] = MappingProxyType(schedules)
        self._home = {a_id: ship for ship, s in schedules.items() for a_id in s.network.nodes}
        self._plan = PlanClock(index.activities, as_of)

    def schedule_of(self, activity_id: str) -> ShipSchedule | None:
        ship = self._home.get(activity_id)
        return None if ship is None else self.ships[ship]

    def start(self, activity_id: str) -> ActivityStart:
        schedule = self.schedule_of(activity_id)
        if schedule is None:
            return self._plan.start(activity_id)
        node = schedule.network.nodes[activity_id]
        if node.started is not None:
            return ActivityStart(actual=node.started, earliest=node.started, expected=node.started)
        planned = schedule.base.es[activity_id]
        return ActivityStart(actual=None, earliest=planned, expected=planned)
