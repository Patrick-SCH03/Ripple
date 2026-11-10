"""판정일 하루 평가(docs/engine.md(비용·일정) 1절): 영향 → 비용 줄 → 변경 일정(CPM) → 인도 지연·지체상금 → 일정 영향.

선상 설치를 적용하면(6-3) 탑재를 늦출 의장품을 배 위로 보내고 할증 줄(C-03)을 더한다. 선주 요청 변경(4-6 허용 지연)이면
지체상금 줄 대신 인도 영향에 노출 금액을 싣는다.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from ripple.contracts.identity import permissible_delay
from ripple.contracts.result import Amount, Unresolved, UnresolvedKind

from ..cost import CostInput, Demand, cost_breakdown
from ..cost.onboard import onboard_cost
from .context import DayScenario, EvalContext
from .delivery import delivery_impact
from .evaluation import Evaluation
from .impacts import TimingImpacts, merge_impacts
from .onboard import chosen_demands
from .ships import ShipScheduler

NO_CONSUMER_REASON = "공급 발주 품목의 소비 공정이 지도에 없음 — 새 자재 지연의 일정 영향 계산 불가"


class DayEvaluator:
    """판정일 하루를 평가한다. 보류에 따른 상태(StateModel)는 평가기가 메모해 조건(DayScenario)에 넣는다."""

    def __init__(self, context: EvalContext) -> None:
        self.context = context
        self.ships = ShipScheduler(context)
        self.impacts = TimingImpacts(context)

    def evaluate(self, scenario: DayScenario) -> Evaluation:
        """선상 설치 적용(scenario.on_board)이면 고른 수요(fixed_onboard면 그 수요)를 배 위로 보낸다."""
        ctx, day, apply = self.context, scenario.day, scenario.on_board
        propagation = ctx.propagator.run(day, scenario.state, with_graph=scenario.with_graph)
        inp = CostInput(
            ctx.index, propagation, ctx.params, ctx.request.horizon_days, ctx.activity_of, scenario.lead_ratios
        )
        costs = cost_breakdown(inp, ctx.changes)
        onboard = onboard_cost(inp, chosen_demands(ctx.request, ctx.baseline, costs, day, scenario.fixed_onboard))
        applied = onboard.blocks if apply else {}
        changed = self.ships.run(scenario, costs, applied)
        lines = [*costs.lines, *(onboard.lines if apply else ())]
        unresolved = [*propagation.unresolved, *_no_consumer(costs.demands)]
        delivery = delivery_impact(inp, changed.outcomes, lines, unresolved, permissible_delay(ctx.request))
        lines.sort(key=lambda line: line.line_id)
        schedule = self.ships.schedule_impact(changed, delivery)
        gated = self.impacts.schedule(day, costs.demands, costs.rework_days, applied)
        impacts = merge_impacts(
            (
                *propagation.impacts,
                *gated,
                *self.impacts.downstream(gated, changed.delays),
                *self.impacts.delivery(changed.outcomes),
            )
        )
        return Evaluation(
            day=day,
            propagation=propagation,
            lines=tuple(lines),
            total=Amount.total([line.amount for line in lines]),
            schedule=schedule,
            max_exit_delay=changed.max_exit_delay,
            impacts=impacts,
            unresolved=tuple(sorted(unresolved, key=lambda u: (u.kind.value, u.entity_id or ""))),
            reallocations=costs.reallocations,
            demands=costs.demands,
            notes=costs.notes,
            onboard=onboard.blocks,
            on_board=apply,
        )


def _no_consumer(demands: Iterable[Demand]) -> Iterator[Unresolved]:
    """공급 품목이 있는데 소비 공정을 모르는 수요(5절): 일정 영향을 0으로 보이지 않게 품목마다 '연결 확인 필요'."""
    lines = sorted({d.line_id for d in demands if d.line_id is not None and d.consumer is None})
    for line_id in lines:  # 이유는 고정 문장(품목은 entity_id로 보이고, 결재 확인 목록이 같은 이유를 묶는다)
        yield Unresolved(kind=UnresolvedKind.CONNECTION, entity_id=line_id, reason=NO_CONSUMER_REASON)
