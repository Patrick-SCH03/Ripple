"""인도: 늘어난 인도 지연과 지체상금(docs/engine.md(비용·일정) 6-4·4-6)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date

from ripple.contracts.change import ChangeCause
from ripple.contracts.domain import ZoneBoundary

from .amounts import Raw
from .case import Case
from .world import World


def delivery_added(
    before: Mapping[str, date],
    after: Mapping[str, date],
    planned: Mapping[str, date],
    boundaries: Mapping[str, ZoneBoundary],
) -> int | None:
    """늘어난 인도 지연: 두 일정 각각의 (계획 대비 늦음 − 여유)로 구한 예상 지연의 차이.

    경계 조건이 없는 출구가 늦어지면 None.
    """
    if any(after[key] > before[key] and key not in boundaries for key in after):
        return None
    return expected_delivery(after, planned, boundaries) - expected_delivery(before, planned, boundaries)


def expected_delivery(
    finishes: Mapping[str, date],
    planned: Mapping[str, date],
    boundaries: Mapping[str, ZoneBoundary],
) -> int:
    """일정 하나의 예상 인도 지연 D: 예보 지연과, 완료일이 있는 경계 출구마다 (계획 대비 늦음 − 여유) 중 큰 값."""
    forecast = max((b.forecast_delivery_delay_days for b in boundaries.values()), default=0)
    late = [
        max(0, (finishes[key] - planned[key]).days) - boundary.float_to_delivery_days
        for key, boundary in boundaries.items()
        if key in finishes
    ]
    return max([forecast, *late])


def liquidated_damages(world: World, case: Case, delivery: int | None) -> Raw:
    """인도 지연의 지체상금. 선주 요청 변경은 인도일 조정 대상(허용 지연, 명세 4-6)이라 넣지 않는다.

    변경 전 예상 인도 지연은 참 기준 일정의 망 안 경계 출구로 구하고, 늘어난 인도 지연을 더해 변경 후로 본다.
    """
    raw: Raw = defaultdict(float)
    change = case.change
    if delivery is None or change.cause is ChangeCause.OWNER_REQUEST:
        return raw
    exits = {a_id: case.base_ef[a_id] for a_id in world.boundaries if a_id in case.nodes}
    before = expected_delivery(exits, {a_id: case.nodes[a_id].planned_start for a_id in exits}, world.boundaries)
    after = before + delivery
    for ship in world.snapshot.ships:
        if ship.ship_id not in change.ship_ids:
            continue
        terms = ship.ld_terms
        grace = terms.grace_days if terms else world.param("liquidated_damages.grace_days")
        daily = terms.rate_per_day_of_price if terms else world.param("liquidated_damages.rate_per_day_of_price")
        cap = terms.max_days if terms else world.param("liquidated_damages.max_days")
        delta = min(max(after - grace, 0), cap) - min(max(before - grace, 0), cap)
        if delta:
            raw[(f"ld:{ship.ship_id}", "liquidated_damages")] += ship.contract_price_krw * daily * delta
    return raw
