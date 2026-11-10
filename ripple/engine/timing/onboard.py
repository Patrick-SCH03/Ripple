"""선상 설치(docs/engine.md(비용·일정) 6-3·6-8): 요청 호선마다 배 위로 보낼 수요를 고르고, 다른 실행 방식과 비교한다."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from datetime import date

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.result import OnboardOption

from ..cost import CostBreakdown, Demand
from ..cost.onboard import OnboardBlock
from ..onboard import DemandKey, Outcome, onboard_demands, onboard_option
from ..schedule import Baseline
from .evaluation import Evaluation


def chosen_demands(
    request: AnalysisRequest,
    baseline: Baseline,
    costs: CostBreakdown,
    day: date,
    fixed: Collection[DemandKey] | None,
) -> dict[str, tuple[tuple[Demand, ...], str]]:
    """요청 호선마다 선상 설치 수요(6-3): 블록 → (수요, 탑재 공정)."""
    chosen: dict[str, tuple[tuple[Demand, ...], str]] = {}
    for ship_id in sorted(request.change.ship_ids):
        schedule = baseline.ships.get(ship_id)
        if schedule is not None:
            chosen.update(
                onboard_demands(schedule.network, schedule.base, costs.demands, costs.rework_days, day, fixed)
            )
    return chosen


def wants_option(final: Evaluation) -> bool:
    """선상 설치 선택지를 낼지(6-8): 기다리는 요청이면 어느 블록이든 탑재 지연이 선상 설치 일수보다 길 때만(짧으면
    기다리는 편이 나음), 선상 설치 요청이면 늘 싣는다."""
    blocks = final.onboard
    if not blocks:
        return False
    return final.on_board or any(_erection_delay(final, (b,)) > b.days for b in blocks.values())


def option_of(final: Evaluation, other: Evaluation) -> OnboardOption:
    """같은 날·보류로 다른 실행 방식을 평가한 other와의 비교."""
    blocks = final.onboard
    return onboard_option(final.on_board, blocks, _outcome(final, blocks), _outcome(other, blocks))


def _erection_delay(ev: Evaluation, blocks: Iterable[OnboardBlock]) -> int:
    return max((ev.schedule.added_days_by_activity.get(b.erection, 0) for b in blocks), default=0)


def _outcome(ev: Evaluation, blocks: Mapping[str, OnboardBlock]) -> Outcome:
    delivery = ev.schedule.delivery
    return Outcome(
        total=ev.total,
        erection_delay=_erection_delay(ev, blocks.values()),
        exit_delay=ev.max_exit_delay,
        delivery_added=None if delivery is None else delivery.added_delay_days,
    )
