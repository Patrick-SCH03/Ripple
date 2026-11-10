"""위치 규칙: 바뀌는 부재의 블록 재작업(R-B01)과 도면 개정(R-D01).

다른 규칙 뒤에 돌고, 대상 부재와 함께 규칙표 also_from 영향(테이퍼·칼라·부재 수정)을 받은 이웃 부재에서도
출발한다(docs/engine.md(전파) 4절).
"""

from __future__ import annotations

from collections.abc import Iterator

from ripple.contracts.domain import BlockStage, EntityType, Relation
from ripple.contracts.result import ImpactType, Unresolved, UnresolvedKind

from ..describe import BLOCK_STAGE_NAMES
from .base import Finding, RuleContext, stage_note


def r_b01(ctx: RuleContext) -> Iterator[Finding]:
    """블록 단계가 소조립 이후면 재작업(모르면 재작업으로 표시하고 이유를 남김)."""
    for part_id in sorted(ctx.changed):
        block = ctx.view.block_of(part_id)
        if block is None:
            continue
        stage = ctx.state.block_stage_on(block, ctx.judge_on)
        started = stage.at_least(BlockStage.SUB_ASSEMBLY)
        if started is False:
            continue
        lead = ctx.changed[part_id]
        path = (*lead, ctx.hop(part_id, block, Relation.PART_OF))
        unresolved = (
            None
            if started
            else Unresolved(
                kind=UnresolvedKind.BLOCK_STAGE,
                entity_id=block,
                reason="확정일 블록 단계를 알 수 없어 재작업 가능성으로 표시",
            )
        )
        note = stage_note("확정일 블록 단계", stage, BLOCK_STAGE_NAMES)
        origin = lead[0].src if lead else part_id
        yield Finding(EntityType.BLOCK, block, ImpactType.REWORK, path, origin, note, unresolved)


def r_d01(ctx: RuleContext) -> Iterator[Finding]:
    """바뀌는 부재가 그려진 도면 개정."""
    for part_id in sorted(ctx.changed):
        drawing = ctx.view.drawing_of(part_id)
        if drawing is None:
            continue
        lead = ctx.changed[part_id]
        path = (*lead, ctx.hop(part_id, drawing, Relation.DRAWN_IN))
        origin = lead[0].src if lead else part_id
        yield Finding(EntityType.DRAWING, drawing, ImpactType.DRAWING_REVISION, path, origin)
