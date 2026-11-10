"""연결 추적(docs/domain.md 13절, 계약 1.23.0): 대상 부재마다 EBOM → MBOM → 구매 → 시공 사슬.

- EBOM = 도면@개정(Part.drawing_no@revision), MBOM = 블록(Part.block_id),
  구매 = 공급 발주 품목(POLine.part_ids — 한 부재가 여러 품목일 수 있음),
  시공 = 품목의 소비 공정(POLine.consumed_by_activity_id)과 블록의 다음 착수 공정.
- 고리는 분석 결과가 아니라 지도(GraphIndex)와 변경 후 보기(ChangeView)에서 만든다:
  영향이 없는 연결도 '있음'으로 보이고,
  지도에 연결이 없을 때만 gaps에 적는다. '이번 변경 영향'은 영향·비용 줄이 가리키는 엔터티로 따로 표시한다.
- 상태는 기준일·보류 없는 바탕 상태(Propagator.state(()))로만 적는다(판단이 걸린 상태와 같은 원칙).
"""

from __future__ import annotations

from collections.abc import Iterable

from ripple.contracts.domain import BLOCK_ACTIVITY_ORDER, EntityType, Relation
from ripple.contracts.result import CostLine, Impact, TraceChain, TraceLink

from .describe import BLOCK_STAGE_NAMES, PART_KIND_NAMES, PO_STATUS_NAMES, describe
from .overlay import ChangeView
from .state import StateModel


def trace_chains(
    view: ChangeView, state: StateModel, impacts: Iterable[Impact], lines: Iterable[CostLine]
) -> tuple[TraceChain, ...]:
    affected = {i.entity_id for i in impacts} | {line.entity_id for line in lines}
    targets = sorted({t for planned in view.ops for t in planned.targets()})
    return tuple(_chain(view, state, part_id, affected) for part_id in targets)


def _label(view: ChangeView, entity_id: str) -> str:
    if entity_id in view.new_parts:
        new = view.new_parts[entity_id]
        return f"새 {PART_KIND_NAMES.get(new.kind, new.kind.value)} {new.spec_id}"
    try:
        return describe(view.index, entity_id).label
    except KeyError:
        return entity_id


def _chain(view: ChangeView, state: StateModel, part_id: str, affected: set[str]) -> TraceChain:
    """고리를 도면 → 블록 → 발주 품목 → 공정 순으로 만들고, 빠진 연결은 그 순서로 gaps에 적는다."""
    gaps: list[str] = []
    new = part_id in view.new_parts

    drawing_id = view.drawing_of(part_id)
    drawing = None
    if drawing_id is None:
        gaps.append("도면 연결 없음" if not new else "새 부재 — 붙는 부재가 없어 도면 미상")
    else:
        drawing = TraceLink(
            kind="drawing", entity_id=drawing_id, label=_label(view, drawing_id), affected=drawing_id in affected
        )

    block_id = view.block_of(part_id)
    block = None
    if block_id is None:
        gaps.append("블록 연결 없음")
    else:
        block = _block_link(view, state, block_id, affected)

    line_ids = () if new else view.lines_of(part_id)
    po_lines = tuple(_po_line_link(view, state, line_id, affected) for line_id in line_ids)
    consumers, missing = _consumers(view, line_ids)
    gaps.extend(missing)
    if not line_ids:
        gaps.append("새 부재 — 발주 품목 아직 없음" if new else "발주 품목 연결 없음")
    if block_id is not None:
        consumers, gap = _with_next_block_activity(state, block_id, consumers)
        if gap is not None:
            gaps.append(gap)

    return TraceChain(
        part_id=part_id,
        label=_label(view, part_id),
        new=new,
        removed=part_id in view.removed,
        drawing=drawing,
        block=block,
        po_lines=po_lines,
        activities=tuple(_activity_link(view, state, a, affected) for a in consumers),
        gaps=tuple(gaps),
    )


def _block_link(view: ChangeView, state: StateModel, block_id: str, affected: set[str]) -> TraceLink:
    stage = state.block_stage_on(block_id, state.as_of).likely
    return TraceLink(
        kind="block",
        entity_id=block_id,
        label=_label(view, block_id),
        status=BLOCK_STAGE_NAMES[stage] if stage is not None else None,
        affected=block_id in affected,
    )


def _po_line_link(view: ChangeView, state: StateModel, line_id: str, affected: set[str]) -> TraceLink:
    stage_on = state.line_stage_on(line_id, state.as_of).likely
    return TraceLink(
        kind="po_line",
        entity_id=line_id,
        label=_label(view, line_id),
        status=PO_STATUS_NAMES[stage_on] if stage_on is not None else None,
        affected=line_id in affected,
    )


def _consumers(view: ChangeView, line_ids: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """품목 순 소비 공정(겹치면 한 번)과, 소비 공정이 없거나 공정이 아닌 품목의 끊긴 고리(품목 순)."""
    index = view.index
    consumers: list[str] = []
    gaps: list[str] = []
    for line_id in line_ids:
        consumer = index.lines[line_id].consumed_by_activity_id
        if consumer is None or index.type_of(consumer) is not EntityType.ACTIVITY:
            gaps.append(f"{line_id} 소비 공정 연결 없음")
        elif consumer not in consumers:
            consumers.append(consumer)
    return tuple(consumers), tuple(gaps)


def _with_next_block_activity(
    state: StateModel, block_id: str, consumers: tuple[str, ...]
) -> tuple[tuple[str, ...], str | None]:
    """블록의 다음 착수 공정을 끝에 더한 공정(이미 있으면 그대로)과, 블록 공정도 소비 공정도 없을 때의 끊긴 고리."""
    next_up = _next_block_activity(state, block_id)
    if next_up is None:
        return consumers, None if consumers else "블록 공정 연결 없음"
    if next_up in consumers:
        return consumers, None
    return (*consumers, next_up), None


def _next_block_activity(state: StateModel, block_id: str) -> str | None:
    """블록 공정 중 기준일에 아직 착수 전인 첫 공정, 모두 착수했으면 마지막 공정."""
    index = state.index
    order = {kind: i for i, kind in enumerate(BLOCK_ACTIVITY_ORDER)}
    members = sorted(
        (a for a in index.into(block_id, Relation.PART_OF) if a in index.activities),
        key=lambda a: (order.get(index.activities[a].kind, len(order)), a),
    )
    for activity_id in members:
        start = state.start_of(activity_id).actual
        if start is None or start > state.as_of:
            return activity_id
    return members[-1] if members else None


def _activity_link(view: ChangeView, state: StateModel, activity_id: str, affected: set[str]) -> TraceLink:
    activity = view.index.activities[activity_id]
    start = state.start_of(activity_id).actual
    finish = activity.actual_finish
    if finish is not None and finish <= state.as_of:
        status = "완료"
    elif start is not None and start <= state.as_of:
        status = "진행 중"
    else:
        status = "착수 전"
    return TraceLink(
        kind="activity",
        entity_id=activity_id,
        label=_label(view, activity_id),
        status=status,
        affected=activity_id in affected,
    )


__all__ = ["trace_chains"]
