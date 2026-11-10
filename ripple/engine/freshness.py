"""자료 날짜(docs/domain.md 12절): 지도의 상태가 언제 기준인지 — 최신 한 건이 오래된 항목을 가리지 않게 개수도 함께.

- 발주: 관측일·확인된 진입일의 최신, 그리고 아직 입고 전(상태가 더 바뀔 수 있는) 발주 중
  마지막 확인이 오늘(업무상)보다 7일 넘게 전이거나 없는 발주 수.
- 공정: 실적 착수·완료일과 현장 확인일의 최신.
"""

from __future__ import annotations

from datetime import date, timedelta

from ripple.contracts.domain import PO_STATUS_ORDER, GraphSnapshot, POStatus
from ripple.contracts.workspace import STALE_DAYS, Freshness

_RECEIVED = PO_STATUS_ORDER.index(POStatus.RECEIVED)


def freshness(snapshot: GraphSnapshot, today: date) -> Freshness:
    cutoff = today - timedelta(days=STALE_DAYS)
    po_days: list[date] = []
    open_orders = stale = 0
    for po in snapshot.purchase_orders:
        days = [o.observed_on for o in po.observations if o.observed_on <= today]
        days += [d for d in po.entered_on.values() if d <= today]
        po_days += days
        reached = [o.status for o in po.observations if o.observed_on <= today] + [
            s for s, d in po.entered_on.items() if d <= today
        ]
        if any(PO_STATUS_ORDER.index(s) >= _RECEIVED for s in reached):
            continue
        open_orders += 1
        if not days or max(days) < cutoff:
            stale += 1
    activity_days: list[date] = []
    for activity in snapshot.activities:
        activity_days += [d for d in (activity.actual_start, activity.actual_finish) if d is not None and d <= today]
        activity_days += [c.confirmed_on for c in activity.confirmations if c.confirmed_on <= today]
    return Freshness(
        today=today,
        po_latest=max(po_days, default=None),
        open_orders=open_orders,
        stale_orders=stale,
        activity_latest=max(activity_days, default=None),
    )
