"""조달 규칙: 발주 품목 변경·취소(R-T01·R-M02)와 잉여 자재 전용(R-M01)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from datetime import timedelta

from ripple.contracts.change import DimensionChange, GradeChange, ThicknessChange
from ripple.contracts.domain import EntityType, POLine, POStatus, Relation, StockLot
from ripple.contracts.result import ImpactType, Unresolved, UnresolvedKind

from ..describe import PO_STATUS_NAMES
from ..overlay import ChangeView
from .base import Finding, RuleContext, stage_note

SpecKey = tuple[str, ...]


def r_t01(ctx: RuleContext) -> Iterator[Finding]:
    """규격이 바뀌는 부재의 발주 품목: 발주 이후면 변경·취소 + 새 규격 발주."""
    for planned in ctx.planned():
        for part_id in planned.existing_targets():
            yield from _ordered_lines(ctx, part_id, reorder=True)


def r_m02(ctx: RuleContext) -> Iterator[Finding]:
    """빼는 부재의 발주 품목: 발주 이후면 수량 감축·취소."""
    for planned in ctx.planned():
        for part_id in planned.removed():
            yield from _ordered_lines(ctx, part_id, reorder=False)


def _ordered_lines(ctx: RuleContext, part_id: str, reorder: bool) -> Iterator[Finding]:
    for line_id in ctx.view.lines_of(part_id):
        stage = ctx.state.line_stage_on(line_id, ctx.judge_on)
        ordered = stage.at_least(POStatus.ORDERED)
        if ordered is False:
            continue
        path = (ctx.hop(part_id, line_id, Relation.SUPPLIED_BY),)
        note = stage_note("확정일 품목 단계", stage, PO_STATUS_NAMES)
        unresolved = (
            None
            if ordered
            else Unresolved(
                kind=UnresolvedKind.PO_STATE,
                entity_id=line_id,
                reason="확정일 발주 품목 단계를 알 수 없어 변경·취소 가능성으로 표시",
            )
        )
        yield Finding(EntityType.PO_LINE, line_id, ImpactType.PO_CHANGE, path, part_id, note, unresolved)
        if reorder:
            yield Finding(EntityType.PO_LINE, line_id, ImpactType.REORDER, path, part_id, note)


def r_m01(ctx: RuleContext) -> Iterator[Finding]:
    """잉여 자재 전용: (가) 변경 뒤 규격과 같은 재고, (나) 잉여 자재와 같은 규격의 다른 블록 수요."""
    demand = _lines_by_spec(ctx)
    for planned in ctx.planned():
        reshaped = isinstance(planned.op, (ThicknessChange, GradeChange, DimensionChange))
        for part_id in planned.existing_targets():
            if reshaped:
                key = _part_key(ctx, part_id, by_id=isinstance(planned.op, DimensionChange))
                if key is not None:
                    yield from _stock_for(ctx, part_id, key)
            yield from _surplus_from(ctx, part_id, demand)


def _part_key(ctx: RuleContext, part_id: str, by_id: bool) -> SpecKey | None:
    """변경 뒤 규격: 판·형강이면 (분류, 강종, 두께), 그 밖에는 치수 변경일 때만 규격 ID."""
    index = ctx.view.index
    part = index.parts[part_id]
    spec = index.specs.get(part.spec_id)
    if spec is not None and spec.grade is not None and spec.thickness_mm is not None:
        grade = ctx.view.grade(part_id) or spec.grade
        thickness = ctx.view.thickness(part_id) or spec.thickness_mm
        return ("attr", spec.category, grade, f"{thickness:g}")
    return ("id", part.spec_id) if by_id else None


def _lot_key(ctx: RuleContext, lot: StockLot) -> SpecKey:
    spec = ctx.view.index.specs.get(lot.spec_id)
    if spec is not None and spec.grade is not None and spec.thickness_mm is not None:
        return ("attr", spec.category, spec.grade, f"{spec.thickness_mm:g}")
    return ("id", lot.spec_id)


def _stock_for(ctx: RuleContext, part_id: str, key: SpecKey) -> Iterator[Finding]:
    block = ctx.view.block_of(part_id)
    for lot_id in sorted(ctx.view.index.stock):
        lot = ctx.view.index.stock[lot_id]
        if lot.processed or lot.received_date > ctx.state.as_of:
            continue
        if block is not None and lot.reserved_block_id == block:
            continue
        if _lot_key(ctx, lot) != key:
            continue
        reserved = f"{lot.reserved_block_id.split(':')[-1]}용 예약" if lot.reserved_block_id else "예약 없음"
        note = f"변경 뒤 규격과 같은 재고 {lot.spec_id} {lot.qty:g}({reserved})"
        path = (ctx.hop(part_id, lot_id, Relation.SAME_SPEC),)
        yield Finding(EntityType.STOCK, lot_id, ImpactType.REALLOCATE_STOCK, path, part_id, note)


def _lines_by_spec(ctx: RuleContext) -> dict[str, list[str]]:
    index = ctx.view.index
    found: dict[str, list[str]] = defaultdict(list)
    for line_id in sorted(index.lines):
        order = index.orders.get(index.lines[line_id].po_id)
        if order is not None and order.ship_id in ctx.ships:
            found[index.lines[line_id].spec_id].append(line_id)
    return found


def _still_needs(view: ChangeView, line: POLine) -> list[str]:
    """이 요청 뒤에도 품목의 자재가 필요한 부재(빼거나 두께·강종·치수·장비 사양을 바꾸는 부재는 수요가 아님)."""
    return [p for p in line.part_ids if view.keeps_material(p)]


def _surplus_from(ctx: RuleContext, part_id: str, demand: dict[str, list[str]]) -> Iterator[Finding]:
    view, index = ctx.view, ctx.view.index
    block = view.block_of(part_id)
    window_end = ctx.judge_on + timedelta(days=ctx.horizon_days)
    for line_id in view.lines_of(part_id):
        if ctx.state.line_stage_on(line_id, ctx.judge_on).likely is not POStatus.RECEIVED:
            continue
        line = index.lines[line_id]
        for other_id in demand.get(line.spec_id, []):
            other = index.lines[other_id]
            blocks = {view.block_of(p) for p in _still_needs(view, other)} - {None, block}
            consumer = other.consumed_by_activity_id
            if other_id == line_id or not blocks or consumer is None or consumer not in index.activities:
                continue
            if ctx.state.line_stage_on(other_id, ctx.judge_on).at_least(POStatus.RECEIVED) is not False:
                continue
            start = ctx.state.start_of(consumer).expected
            if not ctx.judge_on < start <= window_end:
                continue
            note = f"남는 {line.spec_id}(가공 전)을 {other_id} 수요(소비 공정 착수 예정 {start.isoformat()})로 전용"
            path = (
                ctx.hop(part_id, line_id, Relation.SUPPLIED_BY),
                ctx.hop(line_id, other_id, Relation.SAME_SPEC),
            )
            yield Finding(EntityType.PO_LINE, other_id, ImpactType.REALLOCATE_STOCK, path, part_id, note)
