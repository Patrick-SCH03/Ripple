"""구조 규칙: 맞대기 판 테이퍼(R-T02), 필릿 용접 재검토(R-T03), 관통 칼라(R-T04)."""

from __future__ import annotations

from collections.abc import Iterator

from ripple.contracts.change import AddPenetration
from ripple.contracts.domain import EntityType, Relation
from ripple.contracts.result import ImpactType

from .base import Finding, RuleContext


def r_t02(ctx: RuleContext) -> Iterator[Finding]:
    """변경 뒤 맞대기 판 사이 두께 차가 문턱 이상이면 이웃 판 테이퍼."""
    settings = ctx.rule.settings
    thin = float(settings["threshold_mm"]["thin_plate_le_10mm"])
    thick = float(settings["threshold_mm"]["thin_plate_gt_10mm"])
    ratio = settings.get("max_thickness_diff_ratio")
    for planned in ctx.planned():
        for part_id in planned.existing_targets():
            mine = ctx.view.thickness(part_id)
            if mine is None:
                continue
            for other in ctx.view.neighbours(part_id, Relation.BUTT_WELD):
                path = (ctx.hop(part_id, other, Relation.BUTT_WELD),)
                theirs = ctx.view.thickness(other)
                if theirs is None:
                    note = "이웃 판 두께 정보 없음 — 테이퍼 여부 확인 필요"
                    yield Finding(EntityType.PART, other, ImpactType.TAPER, path, part_id, note)
                    continue
                diff = round(abs(mine - theirs), 6)
                limit = thin if min(mine, theirs) <= 10 else thick
                if diff < limit:
                    continue
                note = f"변경 뒤 두께 {mine:g}mm ↔ {theirs:g}mm, 차 {diff:g}mm ≥ 문턱 {limit:g}mm"
                if ratio is not None and diff > float(ratio) * max(mine, theirs):
                    note += f" · 두께 차가 두꺼운 판의 {float(ratio):.0%} 초과 — 설계자 확인 필요"
                yield Finding(EntityType.PART, other, ImpactType.TAPER, path, part_id, note)


def r_t03(ctx: RuleContext) -> Iterator[Finding]:
    """두께가 바뀐 부재에 필릿 용접된 부재: 용접 사양 재검토."""
    for planned in ctx.planned():
        for part_id in planned.existing_targets():
            for other in ctx.view.neighbours(part_id, Relation.FILLET_WELD):
                path = (ctx.hop(part_id, other, Relation.FILLET_WELD),)
                note = "필릿 용접 상대 두께 변경 — 용접 사양(각장) 재검토"
                yield Finding(EntityType.PART, other, ImpactType.WELD_RECHECK, path, part_id, note)


def r_t04(ctx: RuleContext) -> Iterator[Finding]:
    """두께가 바뀐 판·새 관통부를 지나는 배관: 칼라·슬리브 치수 변경."""
    for planned in ctx.planned():
        op = planned.op
        if isinstance(op, AddPenetration):
            if ctx.view.is_part(op.pipe_part_id):
                path = (ctx.hop(op.plate_part_id, op.pipe_part_id, Relation.PENETRATION),)
                note = f"새 관통부(지름 {op.diameter_mm:g}mm)에 칼라·슬리브 추가"
                yield Finding(EntityType.PART, op.pipe_part_id, ImpactType.COLLAR_RESIZE, path, op.plate_part_id, note)
            continue
        for part_id in planned.existing_targets():
            for other in ctx.view.neighbours(part_id, Relation.PENETRATION):
                path = (ctx.hop(part_id, other, Relation.PENETRATION),)
                note = "관통되는 판의 두께 변경 — 칼라·슬리브 치수 변경"
                yield Finding(EntityType.PART, other, ImpactType.COLLAR_RESIZE, path, part_id, note)
