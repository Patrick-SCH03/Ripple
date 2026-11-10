"""새 자재 수요(docs/engine.md(비용·일정) 5절): 일정이 기다려야 하는 자재와 도착일(리드타임 대표값).

발주 단계와 상관없이 만든다. 바뀌는 규격 부재는 공급 품목이 발주 이후면 판정일에 다시 발주하고, 발주 전이면
원래 발주 예정일(대표 진입일)에 새 규격으로 발주한다. 부재 추가·새 스풀은 판정일에 발주한다.
일정 위험 평가(6-6)는 리드타임만 ⌈일수 × 분류 배율⌉로 늘린다(배율 = 파라미터 범위 끝 ÷ 대표값, 출처와 상관없이).
1.33.0 외자재: LT'가 생산 리드타임(규격 표준·파라미터)이면 운송 일수를 더한다 — 급발주 배율·일정 위험 배율은 생산분에만
곱하고, 운송은 대표 일정이면 대표값, 위험 평가면 범위 끝을 더한다.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction

from ripple.contracts.change import AddPart, ReroutePipe
from ripple.contracts.domain import POStatus, TransportMode

from .amounts import Params
from .inputs import STEEL_CATEGORIES, CostInput
from .material import SpecChange, assumed_transport_note, new_spool_qty

LEAD_GROUP = "lead_time_days"
TRANSPORT_GROUP = "transport_days"
EXPEDITE = "reorder.expedite_lead_time_ratio"
NO_CONSUMER_NOTE = "공급 발주 품목의 소비 공정이 지도에 없음 — 일정 제약 미적용"


@dataclass(frozen=True, slots=True)
class Demand:
    part_id: str  # 수요를 만든 부재(기존 부재 또는 새 부재)
    line_id: str | None  # 기존 부재의 공급 발주 품목
    qty: float
    consumer: str | None  # 소비 공정
    arrival: date | None  # 도착일(모르면 None — 일정 제약 없음)
    note: str = ""
    category: str = ""  # 규격 분류(일정 위험 배율을 고르는 키)
    transport: TransportMode | None = None  # 1.33.0 리드타임에 더한 외자재 운송 방식(일정 위험 결과에 싣는 키)
    transport_assumed: bool = False  # 외자재인데 운송 방식이 비어 선박으로 가정함


def lead_ratios(params: Params) -> dict[str, Fraction]:
    """일정 위험(6-6)의 분류별 리드타임 배율 = 범위 끝 ÷ 대표값. 십진 문자열로 정확히 나눈다(70 × 1.2 = 84)."""
    return {
        category: Fraction(str(param.high)) / Fraction(str(param.value))
        for category, param in sorted(params.raw.group(LEAD_GROUP).items())
        if param.value > 0
    }


def lead_days(ratios: Mapping[str, Fraction] | None, category: str, days: int) -> int:
    """리드타임 일수: 대표 일정은 그대로, 일정 위험 평가는 ⌈일수 × 배율⌉(배율이 없는 분류는 그대로)."""
    ratio = None if ratios is None else ratios.get(category)
    return days if ratio is None else math.ceil(days * ratio)


def transport_days(params: Params, mode: TransportMode | None, *, risk: bool) -> int:
    """외자재 운송 일수(5절·6-6): 대표 일정은 transport_days.<방식> 대표값, 일정 위험은 범위 끝(배율을 곱하지 않음).
    운송을 더하지 않는 수요(국산·원래 발주 리드타임)는 0."""
    if mode is None:
        return 0
    param = params.raw.get(f"{TRANSPORT_GROUP}.{mode}")
    return math.ceil(param.high) if risk else round(param.value)


def _transport(inp: CostInput, mode: TransportMode | None) -> int:
    return transport_days(inp.params, mode, risk=inp.lead_ratios is not None)


def demands(inp: CostInput, changes: tuple[SpecChange, ...], covered: dict[str, float]) -> tuple[Demand, ...]:
    found: list[Demand] = []
    for ch in changes:
        qty = ch.q_new - covered.get(ch.part_id, 0.0)
        if qty > 1e-9:
            found.append(_spec_demand(inp, ch, qty))
    for planned_op in inp.view.ops:
        op = planned_op.op
        if isinstance(op, AddPart):
            if inp.index.specs[op.spec_id].category not in STEEL_CATEGORIES:  # 강재는 야드 일반 재고에서 바로 씀
                found.append(_new_demand(inp, planned_op.new_ids[0], op.spec_id, op.qty))
        elif isinstance(op, ReroutePipe):
            each = new_spool_qty(inp.index, op, inp.params)
            for new_id, spec_id in zip(planned_op.new_ids, op.added_spool_spec_ids, strict=True):
                found.append(_new_demand(inp, new_id, spec_id, each))
    return tuple(sorted(found, key=lambda d: d.part_id))


def _spec_demand(inp: CostInput, ch: SpecChange, qty: float) -> Demand:
    """바뀌는 규격 부재 하나의 새 자재 수요(공급 발주 품목의 발주 단계로 다시 발주하는 날을 정한다)."""
    if ch.line_id is None:
        note = "공급 발주 품목 없음 — 일정 제약 미적용"
        return Demand(ch.part_id, None, qty, None, None, note, ch.category)
    t = inp.day
    line = inp.index.lines[ch.line_id]
    ordered = inp.state.line_stage_on(ch.line_id, t).at_least(POStatus.ORDERED)
    days = ch.lead_time_days
    if ordered is True:  # 발주 이상으로 정해지면 급발주 리드타임(5절, 판단 불가면 표준 그대로 — 생산분에만)
        days = math.ceil(days * Fraction(str(inp.params.value(EXPEDITE))))
    lead = timedelta(days=lead_days(inp.lead_ratios, ch.category, days) + _transport(inp, ch.transport))
    if ordered is not False:  # 발주 이후이거나 모르면(보수적으로) 판정일에 다시 발주
        arrival: date | None = t + lead
        note = ""
    else:
        planned = entry_estimate(inp, line.po_id, POStatus.ORDERED)
        arrival = None if planned is None else planned + lead
        note = "" if planned is not None else "원래 발주 예정일 미상 — 일정 제약 미적용"
    consumer = line.consumed_by_activity_id
    if consumer is None or consumer not in inp.index.activities:
        consumer, note = None, NO_CONSUMER_NOTE
    elif arrival is not None and ch.transport_assumed and ch.shipped_spec_id is not None:
        note = assumed_transport_note(ch.shipped_spec_id)  # 도착일을 실제로 계산한 수요에서만 가정 안내
    return Demand(ch.part_id, ch.line_id, qty, consumer, arrival, note, ch.category, ch.transport, ch.transport_assumed)


def entry_estimate(inp: CostInput, po_id: str, stage: POStatus) -> date | None:
    """발주 단계의 대표 진입일(보류 반영된 상태 함수)."""
    return next(w.estimate for w in inp.state.windows(po_id) if w.stage is stage)


def _new_demand(inp: CostInput, part_id: str, spec_id: str, qty: float) -> Demand:
    spec = inp.index.specs[spec_id]
    block = inp.view.block_of(part_id)
    consumer = inp.consumer_of(block, spec.category)
    lead = spec.std_lead_time_days or round(inp.params.value(f"{LEAD_GROUP}.{spec.category}"))
    if consumer is None:
        note = "새 부재의 블록·소비 공정 미상 — 일정 제약 미적용"
        return Demand(part_id, None, qty, None, None, note, spec.category)
    days = lead_days(inp.lead_ratios, spec.category, lead) + _transport(inp, spec.import_transport)
    note = assumed_transport_note(spec_id) if spec.transport_assumed else ""
    arrival = inp.day + timedelta(days=days)
    return Demand(
        part_id, None, qty, consumer, arrival, note, spec.category, spec.import_transport, spec.transport_assumed
    )
