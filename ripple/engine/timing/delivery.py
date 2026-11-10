"""인도 지연과 지체상금(docs/engine.md(비용·일정) 4-6·6-4): 호선별 인도 결과 → 지체상금 줄·노출 금액·인도 영향."""

from __future__ import annotations

from ripple.contracts.result import CostLine, DeliveryImpact, Unresolved, UnresolvedKind

from ..cost import CostInput, damages_line
from ..schedule import DeliveryOutcome


def delivery_impact(
    inp: CostInput,
    outcomes: dict[str, DeliveryOutcome],
    lines: list[CostLine],
    unresolved: list[Unresolved],
    permissible: bool,
) -> DeliveryImpact | None:
    """호선별 인도 결과 → 지체상금 줄(lines에 더함)과 가장 늦어진 호선의 인도 지연. 계산 불가는 unresolved에 더한다.
    허용 지연(4-6, 선주 요청)이면 지체상금 줄을 더하지 않고 그 호선의 금액을 노출 금액으로 싣는다."""
    delivery: DeliveryImpact | None = None
    worst: tuple[int, str] | None = None
    for ship_id, outcome in sorted(outcomes.items()):
        if outcome.before is None or outcome.after is None:
            unresolved.append(
                Unresolved(
                    kind=UnresolvedKind.DELIVERY,
                    entity_id=ship_id,
                    reason="경계 조건이 없는 구역의 출구 지연 — 인도 지연·지체상금 미계산",
                )
            )
            continue
        ld = damages_line(inp, ship_id, outcome.before, outcome.after)
        if ld is not None and not permissible:
            lines.append(ld)
        added = outcome.after - outcome.before
        if worst is None or added > worst[0]:
            worst = (added, ship_id)
            exposure = ld.amount if permissible and ld is not None else None
            delivery = DeliveryImpact.of(outcome.before, outcome.after, permissible, exposure)
    if delivery is not None and any(u.kind is UnresolvedKind.DELIVERY for u in unresolved):
        delivery = None
    if delivery is None and not any(u.kind is UnresolvedKind.DELIVERY for u in unresolved):
        unresolved.append(Unresolved(kind=UnresolvedKind.DELIVERY, reason="일정 정보 없음 — 인도 지연 미계산"))
    return delivery
