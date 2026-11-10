"""일정·인도 영향(docs/engine.md(비용·일정) 7절)과 영향 병합(docs/engine.md(전파) 6절).

R-S01 = 새 자재·재작업·선상 설치가 관문 대상의 기준 착수일을 넘기는 공정(+ 그 탑재 때문에 늦어진 다른 블록 탑재),
R-L01 = 예상 인도 지연이 늘어난 호선.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Iterator, Mapping
from datetime import date, timedelta

from ripple.contracts.domain import ActivityKind, EntityType, Relation
from ripple.contracts.result import Hop, Impact, ImpactType

from ..cost import Demand
from ..cost.onboard import OnboardBlock
from ..onboard import demand_key
from ..propagate import Propagator
from ..schedule import DeliveryOutcome, Network, Times
from .adjust import ONE_DAY, exit_successors, gate_targets
from .context import EvalContext
from .rule_ids import DELIVERY_RULE, SCHEDULE_RULE


class TimingImpacts:
    """판정일 평가의 일정 지연(R-S01)·인도 지연(R-L01) 영향. 규칙은 부를 때마다 규칙집에서 찾는다."""

    def __init__(self, context: EvalContext) -> None:
        self.index = context.index
        self.rulebook = context.rulebook
        self.baseline = context.baseline
        self._ops_by_part = _ops_by_part(context.propagator)

    def schedule(
        self,
        day: date,
        needed: tuple[Demand, ...],
        rework_days: Mapping[str, int],
        onboard: Mapping[str, OnboardBlock],
    ) -> list[Impact]:
        """R-S01(7절): (가) 착수 전 소비 공정은 도착 다음 날이, (나) 이미 착수한 소비 공정은 재작업 자재를 받아 재작업을
        끝내는 날(max(t + 1, 도착일) + 재작업 일수)이, (다) 선상 설치 수요는 선상 설치가 끝나는 날
        (max(도착일 + 1, EF⁰(탑재)) + d_on)이 관문 대상의 기준 착수일보다 늦으면."""
        rule = self.rulebook.get(SCHEDULE_RULE)
        on_board = {demand_key(d): block for block in onboard.values() for d in block.demands}
        impacts = []
        for demand in needed:
            if demand.consumer is None or demand.arrival is None:
                continue
            if not self._ops_by_part.get(demand.part_id, set()) & set(rule.ops):
                continue
            schedule = self.baseline.schedule_of(demand.consumer)
            if schedule is None:
                continue
            net, base = schedule.network, schedule.base
            gate = self._gate_of(demand, net, base, day, rework_days, on_board.get(demand_key(demand)))
            if gate is None:
                continue
            ready, targets, note = gate
            for target in targets:
                if ready <= base.es[target]:
                    continue
                hops = _supply_hops(demand, demand.consumer, rule.id)
                hops.extend(_chain_hops(net, demand.consumer, target, rule.id))
                impacts.append(
                    Impact(
                        entity_type=EntityType.ACTIVITY,
                        entity_id=target,
                        ship_id=self.index.activities[target].ship_id,
                        impact_type=ImpactType.SCHEDULE_DELAY,
                        severity=rule.severity,
                        rule_id=rule.id,
                        path=tuple(hops),
                        note=f"{note}, 기준 착수일 {base.es[target].isoformat()}",
                    )
                )
        return impacts

    def downstream(self, gated: Iterable[Impact], delays: Mapping[str, int]) -> list[Impact]:
        """R-S01 (라)(7절): 관문 대상이 탑재인 일정 지연마다, 그 탑재 뒤에 탑재하는 다른 블록 탑재 중 변경 일정에서
        완료가 늦어진 것(EF' > EF⁰). 경로 = 관문 대상까지의 경로 + 탑재 → 탑재 선후행(늦어진 다른 블록 탑재만 거친
        가장 짧은 것, 같으면 공정 ID 순). 블록 사이 탑재 선후행이 없는 지도에서는 아무것도 내지 않는다."""
        rule = self.rulebook.get(SCHEDULE_RULE)
        impacts = []
        for impact in gated:
            if impact.rule_id != rule.id or impact.impact_type is not ImpactType.SCHEDULE_DELAY:
                continue
            schedule = self.baseline.schedule_of(impact.entity_id)
            if schedule is None or schedule.network.nodes[impact.entity_id].kind is not ActivityKind.ERECTION:
                continue
            net, base = schedule.network, schedule.base
            origin = net.nodes[impact.entity_id].block_id
            for target, hops in _later_erections(net, impact.entity_id, origin, delays, rule.id):
                impacts.append(
                    Impact(
                        entity_type=EntityType.ACTIVITY,
                        entity_id=target,
                        ship_id=self.index.activities[target].ship_id,
                        impact_type=ImpactType.SCHEDULE_DELAY,
                        severity=rule.severity,
                        rule_id=rule.id,
                        path=(*impact.path, *hops),
                        note=f"선행 탑재 지연으로 탑재 완료 {delays[target]}일 늦어짐, 기준 착수일 "
                        f"{base.es[target].isoformat()}",
                    )
                )
        return impacts

    def delivery(self, outcomes: dict[str, DeliveryOutcome]) -> list[Impact]:
        """R-L01(7절): 예상 인도 지연이 늘어난 호선마다, 가장 늦어진 출구에서 인도 이정표까지의 선후행."""
        rule = self.rulebook.get(DELIVERY_RULE)
        impacts = []
        for ship_id, outcome in sorted(outcomes.items()):
            added = outcome.added
            if added is None or added <= 0:
                continue
            worst_exit = min(outcome.exit_delays, key=lambda e: (-outcome.exit_delays[e], e))
            hops = self._precedes_path(worst_exit, rule.id)
            entity = hops[-1].dst if hops else worst_exit
            impacts.append(
                Impact(
                    entity_type=EntityType.ACTIVITY,
                    entity_id=entity,
                    ship_id=ship_id,
                    impact_type=ImpactType.DELIVERY_DELAY,
                    severity=rule.severity,
                    rule_id=rule.id,
                    path=hops,
                    note=f"예상 인도 지연 {outcome.before}일 → {outcome.after}일",
                )
            )
        return impacts

    def _gate_of(
        self,
        demand: Demand,
        net: Network,
        base: Times,
        day: date,
        rework_days: Mapping[str, int],
        on_board: OnboardBlock | None,
    ) -> tuple[date, tuple[str, ...], str] | None:
        """R-S01의 (가)·(나)·(다): 관문이 풀리는 날, 관문 대상, 메모 앞부분. 해당 없으면 None."""
        assert demand.consumer is not None and demand.arrival is not None
        arrival = demand.arrival.isoformat()
        if on_board is not None:
            ready = max(demand.arrival + ONE_DAY, base.ef[on_board.erection]) + timedelta(days=on_board.days)
            exits = exit_successors(net, on_board.erection)
            return ready, exits, f"새 자재 도착 {arrival}, 후행 설치 {on_board.days}일"
        block_id = net.nodes[demand.consumer].block_id or ""
        targets = gate_targets(net, base, block_id, day)
        if base.es[demand.consumer] > day:
            return demand.arrival + ONE_DAY, targets, f"새 자재 도착 {arrival}"
        rework = rework_days.get(block_id, 0)
        if rework <= 0:
            return None
        ready = max(day + ONE_DAY, demand.arrival) + timedelta(days=rework)
        return ready, targets, f"재작업 자재 도착 {arrival}, 재작업 {rework}일"

    def _precedes_path(self, start: str, rule_id: str) -> tuple[Hop, ...]:
        """출구 이정표에서 선후행을 따라 후행이 없는 이정표(인도)까지."""
        hops: list[Hop] = []
        current = start
        while True:
            nexts = [
                a
                for a in self.index.out(current, Relation.PRECEDES)
                if self.index.activities[a].kind is ActivityKind.MILESTONE
            ]
            if not nexts:
                return tuple(hops)
            nxt = sorted(nexts)[0]
            hops.append(Hop(src=current, dst=nxt, relation=Relation.PRECEDES, rule_id=rule_id))
            current = nxt


def merge_impacts(impacts: Iterable[Impact]) -> tuple[Impact, ...]:
    """키마다 근거 경로가 가장 짧은 하나(같으면 경로 문자열 순), 키 순 정렬(docs/engine.md(전파) 6절)."""
    best: dict[tuple[str, str, str, str], Impact] = {}
    for impact in impacts:
        order = (len(impact.path), tuple((h.src, h.dst, h.relation.value, h.rule_id) for h in impact.path))
        current = best.get(impact.key)
        if current is None or order < (
            len(current.path),
            tuple((h.src, h.dst, h.relation.value, h.rule_id) for h in current.path),
        ):
            best[impact.key] = impact
    return tuple(best[key] for key in sorted(best))


def _supply_hops(demand: Demand, consumer: str, rule_id: str) -> list[Hop]:
    """수요 부재 → 공급 발주 품목 → 소비 공정(품목이 없으면 부재 → 소비 공정)."""
    if demand.line_id is None:
        return [Hop(src=demand.part_id, dst=consumer, relation=Relation.CONSUMED_BY, rule_id=rule_id)]
    return [
        Hop(src=demand.part_id, dst=demand.line_id, relation=Relation.SUPPLIED_BY, rule_id=rule_id),
        Hop(src=demand.line_id, dst=consumer, relation=Relation.CONSUMED_BY, rule_id=rule_id),
    ]


def _chain_hops(net: Network, start: str, target: str, rule_id: str) -> list[Hop]:
    """블록 공정 사슬을 따라 start에서 target(탑재 또는 구역 출구)까지의 선후행 단계."""
    hops: list[Hop] = []
    current = start
    while current != target:
        nexts = [s for s, _ in net.succs.get(current, ())]
        if not nexts:
            return hops
        nxt = target if target in nexts else sorted(nexts)[0]
        hops.append(Hop(src=current, dst=nxt, relation=Relation.PRECEDES, rule_id=rule_id))
        current = nxt
    return hops


def _later_erections(
    net: Network, start: str, origin: str | None, delays: Mapping[str, int], rule_id: str
) -> Iterator[tuple[str, tuple[Hop, ...]]]:
    """start(탑재)에서 선후행을 따라 닿는 늦어진 다른 블록 탑재와 그까지의 가장 짧은 선후행 단계
    (너비 우선, 후행은 ID 순)."""
    seen = {start}
    queue: deque[tuple[str, tuple[Hop, ...]]] = deque([(start, ())])
    while queue:
        current, hops = queue.popleft()
        for successor, _ in net.succs.get(current, ()):
            node = net.nodes[successor]
            later = node.kind is ActivityKind.ERECTION and node.block_id != origin and delays.get(successor, 0) > 0
            if successor in seen or not later:
                continue
            seen.add(successor)
            path = (*hops, Hop(src=current, dst=successor, relation=Relation.PRECEDES, rule_id=rule_id))
            yield successor, path
            queue.append((successor, path))


def _ops_by_part(propagator: Propagator) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for planned in propagator.view.ops:
        for part_id in planned.targets():
            found.setdefault(part_id, set()).add(planned.name)
    return found
