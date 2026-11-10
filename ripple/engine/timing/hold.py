"""발주 보류 권고(docs/engine.md(비용·일정) 8-3, R-H01): 보류해도 어느 날이든 손해가 없고 피하는 손실이 있는 발주.

보류 기간은 그 발주 품목을 쓰는 착수 전 공정의 가장 늦은 착수일(6-5)까지 남은 날의 최소다.
곡선은 평가기의 메모(Curves)를 쓴다 — 보류 권고와 대안의 최적 조합이 같은 곡선을 다시 쓴다.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Protocol

from ripple.contracts.analysis import MAX_HOLD_DAYS, HoldAction
from ripple.contracts.domain import EntityType, Relation
from ripple.contracts.result import Amount, HoldAdvice, Hop, Impact, ImpactType, expected_deadline

from ..cost import difference
from ..state import StateModel
from .adjust import entry_estimate_from
from .context import EvalContext
from .curve import Curve
from .evaluation import Evaluation
from .rule_ids import HOLD_RULE

HOLD_REASON = "남은 단계를 보류 기간만큼 미뤄 확정 전 손실이 커지는 단계 진입 방지(탑재일은 그대로)"


class Curves(Protocol):
    """보류 권고가 쓰는 평가기의 메모(같은 보류 집합이면 같은 상태·곡선)."""

    def state(self, holds: Iterable[HoldAction]) -> StateModel: ...

    def curve(self, holds: tuple[HoldAction, ...]) -> Curve: ...


class HoldAdvisor:
    """요청의 보류에 더해 발주 하나씩 보류해 본 곡선으로 권고를 고른다. 규칙은 부를 때마다 규칙집에서 찾는다."""

    def __init__(self, context: EvalContext) -> None:
        self.index = context.index
        self.request = context.request
        self.rulebook = context.rulebook
        self.propagator = context.propagator

    def advice(self, totals: dict[date, Amount], curves: Curves) -> tuple[HoldAdvice, ...]:
        """totals = 요청의 보류로 본 판정일별 총액. 보류 곡선이 지배 조건(어느 날이든 손해 없음)을 깨거나
        피하는 손실이 없으면 권하지 않는다."""
        request = self.request
        rule = self.rulebook.get(HOLD_RULE)
        touched = self._touched(rule.ops)
        orders = sorted(set(touched) - {h.po_id for h in request.holds})
        state = curves.state(request.holds)
        _, base_evals = curves.curve(request.holds)
        advice = []
        for po_id in orders:
            arrival = entry_estimate_from(state, po_id)
            if arrival is None or arrival <= request.as_of:
                continue
            slack = self._slack(po_id, arrival)
            if not slack or min(slack) < 1:
                continue
            days = min(*slack, MAX_HOLD_DAYS)  # 요청 보류 상한(8-3)
            extra = (*request.holds, HoldAction(po_id=po_id, hold_days=days))
            held_points, held_evals = curves.curve(extra)
            if _worse_somewhere(base_evals, held_evals):
                continue
            best = min(totals, key=lambda day: (-(totals[day].value - held_evals[day].total.value), day))
            avoided = difference(totals[best], held_evals[best].total)
            if avoided.high <= 0:
                continue
            advice.append(
                HoldAdvice(
                    po_id=po_id,
                    rule_id=rule.id,
                    max_hold_days=days,
                    hold_until=request.as_of + timedelta(days=days),
                    avoided=avoided,
                    reason=HOLD_REASON,
                    deadline_after=expected_deadline(held_points),
                    line_ids=tuple(sorted(touched[po_id])),
                )
            )
        return tuple(advice)

    def impacts(self, advice: tuple[HoldAdvice, ...]) -> list[Impact]:
        """권고한 발주의 품목마다 발주 보류 영향(R-H01)."""
        rule = self.rulebook.get(HOLD_RULE)
        view = self.propagator.view
        advised = {a.po_id for a in advice}
        impacts = []
        for part_id in sorted(view.targets(rule.ops)):
            for line_id in view.lines_of(part_id):
                line = self.index.lines[line_id]
                if line.po_id not in advised:
                    continue
                impacts.append(
                    Impact(
                        entity_type=EntityType.PO_LINE,
                        entity_id=line_id,
                        ship_id=self.index.orders[line.po_id].ship_id,
                        impact_type=ImpactType.PO_HOLD,
                        severity=rule.severity,
                        rule_id=rule.id,
                        path=(Hop(src=part_id, dst=line_id, relation=Relation.SUPPLIED_BY, rule_id=rule.id),),
                        note="확정 전 발주 보류 권고",
                    )
                )
        return impacts

    def _touched(self, ops: Iterable[str]) -> dict[str, set[str]]:
        """보류 규칙이 보는 대상 부재의 공급 발주 → 그 품목들."""
        view = self.propagator.view
        touched: dict[str, set[str]] = {}
        for part_id in sorted(view.targets(ops)):
            for line_id in view.lines_of(part_id):
                touched.setdefault(self.index.lines[line_id].po_id, set()).add(line_id)
        return touched

    def _slack(self, po_id: str, arrival: date) -> list[int]:
        """발주 품목마다 소비 공정의 가장 늦은 착수일 − 입고 예상일(착수 전 공정만)."""
        return [
            (latest - arrival).days
            for line in self.index.lines.values()
            if line.po_id == po_id
            for latest in [self._latest_if_pending(line.consumed_by_activity_id)]
            if latest is not None
        ]

    def _latest_if_pending(self, activity_id: str | None) -> date | None:
        """기준일에 착수 전인 공정의 가장 늦은 착수일(망에 없거나 이미 착수했으면 None)."""
        schedule = None if activity_id is None else self.propagator.baseline.schedule_of(activity_id)
        if activity_id is None or schedule is None or schedule.network.nodes[activity_id].started is not None:
            return None
        return schedule.latest.get(activity_id)


def _worse_somewhere(base: dict[date, Evaluation], held: dict[date, Evaluation]) -> bool:
    """보류 곡선이 탐색 기간의 어느 날이든 총비용 대표값이나 구역 출구 지연을 늘리는가(8-3 지배 조건)."""
    return any(
        held[day].total.value > ev.total.value or held[day].max_exit_delay > ev.max_exit_delay
        for day, ev in base.items()
    )
