"""일정 위험(docs/engine.md(비용·일정) 6-6): 새 자재 리드타임만 분류별 범위 끝으로 늘린 같은 날·같은 보류의 일정."""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction

from ripple.contracts.result import ScheduleRisk, TransportLeg

from ..cost import Params
from ..cost.demand import lead_ratios, transport_days
from ..onboard import DemandKey, demand_key
from .evaluation import Evaluation


def risk_scenario(
    params: Params, representative: Evaluation
) -> tuple[dict[str, Fraction], frozenset[DemandKey] | None]:
    """위험 평가의 조건: 분류별 리드타임 배율과, 대표 평가가 배 위로 보낸 수요(선상 설치를 적용했을 때만)."""
    ratios = lead_ratios(params)
    fixed = (
        frozenset(demand_key(d) for block in representative.onboard.values() for d in block.demands)
        if representative.on_board
        else None
    )
    return ratios, fixed


def schedule_risk(
    ev: Evaluation, ratios: Mapping[str, Fraction], representative: Evaluation, params: Params
) -> ScheduleRisk:
    """위험 평가 ev에서 일정 부분(구역 출구·인도·위험에서만 생긴 계산 불가)만 쓰고 비용 줄·총액은 버린다.
    늦춘 새 자재(도착일·소비 공정이 있는 수요)의 분류 배율과 더한 외자재 운송 일수(범위 끝, 1.33.0)를 싣는다."""
    waited = [d for d in ev.demands if d.arrival is not None and d.consumer is not None]
    scaled = sorted({d.category for d in waited if d.category in ratios})
    modes = sorted({d.transport for d in waited if d.transport is not None})
    transport = tuple(
        TransportLeg(
            mode=mode,
            days=transport_days(params, mode, risk=True),
            assumed=any(d.transport_assumed for d in waited if d.transport == mode),
        )
        for mode in modes
    )
    known = set(representative.unresolved)
    delivery = ev.schedule.delivery  # 위험 평가의 비용(지체상금·노출 금액 포함)은 버린다(6-6)
    return ScheduleRisk(
        ratios={category: float(ratios[category]) for category in scaled},
        zone_exits=ev.schedule.zone_exits,
        max_exit_delay_days=ev.schedule.max_exit_delay_days,
        delivery=None if delivery is None else delivery.model_copy(update={"exposure": None}),
        unresolved=tuple(u for u in ev.unresolved if u not in known),
        transport=transport,
    )
