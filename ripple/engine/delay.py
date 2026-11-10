"""지연 파급 비용(docs/engine.md(비용·일정) 4-11, cost-v6): 구역 출구가 실제로 밀려 생기는 간접비(가정).

지체상금 노출 금액처럼 총액 밖에 따로 싣는다 — 총액·판정·추가손실 곡선·결정 기한·보류 권고·대안·평가(E2a)에 넣지 않는다.
공정 여유를 빼고 실제로 밀리는 날만 센다: 구역 출구 지연(CPM 여유 반영, 6-3)만 쓰고 블록 탑재 지연은 쓰지 않는다(여유로
흡수되는 탑재 지연은 손실이 아님). 지체상금과 겹치지 않게 늘어난 인도 지연(지체상금·노출 금액이 세는 날)은 뺀다:
일수 = max(0, 구역 출구 지연 최댓값 − 늘어난 인도 지연(계산하지 못했으면 0)), 금액 = 일수 × 하루 비용.
"""

from __future__ import annotations

from ripple.contracts.result import DelayRipple, ScheduleImpact

from .cost import Params, amount_of
from .cost.factors import factors_for

KEY = "delay_ripple.cost_per_day_krw"


def delay_ripple(schedule: ScheduleImpact, params: Params) -> DelayRipple | None:
    """확정일 대표 일정(6-3·6-4)의 지연 파급 비용. 구역 출구가 밀리지 않거나 그 날이 모두 인도 지연이면 None."""
    overlap = schedule.delivery.added_delay_days if schedule.delivery is not None else 0
    days = schedule.max_exit_delay_days - overlap
    if days <= 0:
        return None
    return DelayRipple(
        amount=amount_of(lambda sc: days * params.get(KEY, sc)),
        days=days,
        exit_delay_days=schedule.max_exit_delay_days,
        delivery_overlap_days=overlap,
        factors=factors_for((KEY,), params.raw),
    )
