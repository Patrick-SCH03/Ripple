"""요청 호선의 변경 일정(docs/engine.md(비용·일정) 6-3·6-4·6-7): 늦어진 공정·구역 출구·인도 결과·출구 여유·주경로."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import timedelta

from ripple.contracts.result import DeliveryImpact, ExitMargin, ScheduleImpact, ZoneExitDelay

from ..cost import CostBreakdown
from ..cost.onboard import OnboardBlock
from ..schedule import (
    Adjustments,
    DeliveryOutcome,
    ShipSchedule,
    Times,
    delivery_outcome,
    driving_path,
    forward,
)
from .adjust import adjustments
from .context import DayScenario, EvalContext


@dataclass(frozen=True, slots=True)
class ChangedSchedules:
    """요청 호선들을 다시 계산한 일정."""

    delays: dict[str, int]  # 늦어진 공정 → 늘어난 일수
    exits: list[ZoneExitDelay]
    outcomes: dict[str, DeliveryOutcome]  # 호선 → 인도 결과
    times: dict[str, Times]  # 호선 → 변경 일정
    margins: list[ExitMargin]  # 여유가 줄어든 출구

    @property
    def max_exit_delay(self) -> int:
        return max((e.delay_days for e in self.exits), default=0)


class ShipScheduler:
    """요청 호선마다 조정 일정을 다시 계산한다(기준 일정은 전파기가 한 번 만든 것을 쓴다)."""

    def __init__(self, context: EvalContext) -> None:
        self.index = context.index
        self.request = context.request
        self.baseline = context.baseline

    def run(self, scenario: DayScenario, costs: CostBreakdown, onboard: Mapping[str, OnboardBlock]) -> ChangedSchedules:
        """요청 호선마다 조정 일정을 다시 계산: 늦어진 공정·구역 출구, 인도 결과, 변경 일정, 여유가 줄어든 출구."""
        delays: dict[str, int] = {}
        exits: list[ZoneExitDelay] = []
        margins: list[ExitMargin] = []
        outcomes: dict[str, DeliveryOutcome] = {}
        changed_times: dict[str, Times] = {}
        day, held, state = scenario.day, scenario.held, scenario.state
        for ship_id in sorted(self.request.change.ship_ids):
            schedule = self.baseline.ships.get(ship_id)
            if schedule is None:
                continue
            adjusted = adjustments(self.index, schedule, day, costs.rework_days, costs.demands, held, state, onboard)
            changed = forward(schedule.network, adjusted)
            changed_times[ship_id] = changed
            for a_id in schedule.network.order:
                added = (changed.ef[a_id] - schedule.base.ef[a_id]).days
                if added > 0:
                    delays[a_id] = added
            outcome = delivery_outcome(self.index, schedule.network, schedule.base, changed)
            outcomes[ship_id] = outcome
            exits.extend(self._exit_delays(schedule, changed, outcome))
            margins.extend(self._exit_margins(schedule, changed, outcome, adjusted))
        return ChangedSchedules(delays, exits, outcomes, changed_times, margins)

    def schedule_impact(self, changed: ChangedSchedules, delivery: DeliveryImpact | None) -> ScheduleImpact:
        """계약의 일정 영향: 공정·출구는 ID 순, 가장 늦어진 출구의 변경 전후 주경로."""
        return ScheduleImpact(
            added_days_by_activity=dict(sorted(changed.delays.items())),
            zone_exits=tuple(sorted(changed.exits, key=lambda e: e.exit_activity_id)),
            max_exit_delay_days=changed.max_exit_delay,
            delivery=delivery,
            exit_margins=tuple(sorted(changed.margins, key=lambda m: m.exit_activity_id)),
            **self._critical_paths(changed.exits, changed.times),
        )

    def _exit_margins(
        self, schedule: ShipSchedule, changed: Times, outcome: DeliveryOutcome, adjusted: Adjustments
    ) -> Iterator[ExitMargin]:
        """늦어지지 않았지만 이 변경이 선행 조건을 늦춘 출구의 남은 여유(명세 6-7, 정보)."""
        net, base = schedule.network, schedule.base
        for exit_id in net.exits:
            if outcome.exit_delays[exit_id] > 0 or base.es[exit_id] <= net.as_of:
                continue
            # 이 변경으로 완료가 늦어진 선행(EF' > EF⁰)·선상 설치 일수를 더한 선행(6-3)과 출구에 건 자재 제약만 본다:
            # 출구를 다른 블록이 정하고 있어도 늦어진 블록 기준으로 출구까지 남은 날을 보인다(대표 0일인데 실제로는 며칠
            # 차이였던 누락 사례가 이 꼴)
            lag = adjusted.extra_lag
            pushed = [
                changed.ef[p] + timedelta(days=d + lag.get((p, exit_id), 0))
                for p, d in net.nodes[exit_id].preds
                if changed.ef[p] > base.ef[p] or lag.get((p, exit_id), 0) > 0
            ]
            floor = adjusted.start_floor.get(exit_id)
            if floor is not None:
                pushed.append(floor)
            if not pushed:
                continue
            after = max(pushed)
            zone_id = self._zone_of(exit_id)
            zone = self.index.zones.get(zone_id)
            yield ExitMargin(
                zone_id=zone_id,
                zone_name=zone.name if zone is not None else "",
                exit_activity_id=exit_id,
                margin_days=(changed.es[exit_id] - after).days,
            )

    def _exit_delays(self, schedule: ShipSchedule, changed: Times, outcome: DeliveryOutcome) -> Iterator[ZoneExitDelay]:
        for exit_id in schedule.network.exits:
            d = outcome.exit_delays[exit_id]
            if d > 0:
                zone_id = self._zone_of(exit_id)
                zone = self.index.zones.get(zone_id)
                yield ZoneExitDelay(
                    zone_id=zone_id,
                    zone_name=zone.name if zone is not None else "",
                    exit_activity_id=exit_id,
                    base_date=schedule.base.ef[exit_id],
                    new_date=changed.ef[exit_id],
                    delay_days=d,
                )

    def _zone_of(self, exit_id: str) -> str:
        for boundary in self.index.snapshot.boundaries:
            if boundary.exit_activity_id == exit_id:
                return boundary.zone_id
        zone = exit_id.removesuffix(":exit")
        return zone if zone in self.index.zones else exit_id

    def _critical_paths(self, exits: list[ZoneExitDelay], changed: dict[str, Times]) -> dict[str, tuple[str, ...]]:
        if not exits:
            return {"critical_path_before": (), "critical_path_after": ()}
        worst = min(exits, key=lambda e: (-e.delay_days, e.exit_activity_id))
        ship_id = self.index.activities[worst.exit_activity_id].ship_id
        base = self.baseline.ships[ship_id].base
        return {
            "critical_path_before": driving_path(base, worst.exit_activity_id),
            "critical_path_after": driving_path(changed[ship_id], worst.exit_activity_id),
        }
