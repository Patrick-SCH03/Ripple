"""경계 조건으로 계산하는 인도 지연(docs/engine.md(비용·일정) 6-4, docs/domain.md 5절).

D = max(E, max_z(late_z − F_z)), late_z = 구역 출구의 계획 대비 늦음. 경계 조건이 없는 구역의 출구가
변경으로 늦어지면 인도 지연을 계산하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ripple.contracts.domain import ZoneBoundary

from ..index import GraphIndex
from .cpm import Times
from .network import Network


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    before: int | None  # 변경 전 예상 인도 지연(일), 계산 불가면 None
    after: int | None
    exit_delays: dict[str, int]  # 구역 출구 → 변경으로 늘어난 일수(0 포함)
    missing_boundary: tuple[str, ...]  # 경계 조건이 없는데 늦어진 구역 출구

    @property
    def added(self) -> int | None:
        if self.before is None or self.after is None:
            return None
        return self.after - self.before


def delivery_outcome(index: GraphIndex, network: Network, base: Times, changed: Times) -> DeliveryOutcome:
    boundaries: dict[str, ZoneBoundary] = {
        b.exit_activity_id: b for b in index.snapshot.boundaries if b.exit_activity_id in network.nodes
    }
    forecast = max((b.forecast_delivery_delay_days for b in boundaries.values()), default=0)
    delays = {exit_id: (changed.ef[exit_id] - base.ef[exit_id]).days for exit_id in network.exits}
    missing = tuple(exit_id for exit_id, d in delays.items() if d > 0 and exit_id not in boundaries)

    def expected(times: Times) -> int:
        worst = forecast
        for exit_id, boundary in boundaries.items():
            late = max(0, (times.ef[exit_id] - network.nodes[exit_id].planned_start).days)
            worst = max(worst, late - boundary.float_to_delivery_days)
        return worst

    if missing:
        return DeliveryOutcome(before=None, after=None, exit_delays=delays, missing_boundary=missing)
    return DeliveryOutcome(before=expected(base), after=expected(changed), exit_delays=delays, missing_boundary=())
