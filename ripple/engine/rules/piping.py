"""배관 규칙: 연결 규격(R-P01), 새 경로의 구조 관통(R-P02), 서포트(R-P03)."""

from __future__ import annotations

from collections.abc import Iterator

from ripple.contracts.change import EquipmentSpecChange, ReroutePipe
from ripple.contracts.domain import EntityType, MaterialSpec, Relation
from ripple.contracts.result import ImpactType, Unresolved, UnresolvedKind

from .base import Finding, RuleContext


def _joint(spec: MaterialSpec | None) -> tuple[int, str] | None:
    """연결 규격(호칭 구경 DN, 압력 등급). 하나라도 없으면 None."""
    if spec is None or spec.nominal_diameter_dn is None or spec.pressure_class is None:
        return None
    return spec.nominal_diameter_dn, spec.pressure_class


def r_p01(ctx: RuleContext) -> Iterator[Finding]:
    """장비 사양이 바뀌어 연결 규격이 달라지면 배관 연결 이웃 수정(모르면 수정으로 표시하고 이유를 남김)."""
    specs = ctx.view.index.specs
    for planned in ctx.planned():
        op = planned.op
        if not isinstance(op, EquipmentSpecChange):
            continue
        before, after = _joint(specs.get(op.from_spec_id)), _joint(specs.get(op.to_spec_id))
        if before is not None and after is not None and before == after:
            continue
        for part_id in op.part_ids:
            unresolved = None
            if before is not None and after is not None:
                note = f"연결 규격 DN{before[0]} {before[1]} → DN{after[0]} {after[1]}: 플랜지·개스킷 교체"
            else:
                note = "새 사양의 연결 규격(구경·압력 등급)을 알 수 없어 인접 배관 수정으로 표시"
                reason = f"{op.to_spec_id}의 연결 규격(구경·압력 등급) 정보 없음 — 인접 배관 수정으로 가정"
                unresolved = Unresolved(kind=UnresolvedKind.CONNECTION, entity_id=part_id, reason=reason)
            for other in ctx.view.neighbours(part_id, Relation.PIPE_JOINT):
                path = (ctx.hop(part_id, other, Relation.PIPE_JOINT),)
                yield Finding(EntityType.PART, other, ImpactType.MODIFY_PART, path, part_id, note, unresolved)


def r_p02(ctx: RuleContext) -> Iterator[Finding]:
    """새 배관 경로가 지나는 판: 관통 구멍(부재 수정)과 칼라. 구조 관통부 추가라 설계자 확인."""
    for planned in ctx.planned():
        op = planned.op
        if not isinstance(op, ReroutePipe) or not planned.new_ids:
            continue
        first = planned.new_ids[0]
        for plate in sorted(set(op.crosses_part_ids)):
            if not ctx.view.is_part(plate) or plate in ctx.view.removed:
                continue
            path = (ctx.hop(first, plate, Relation.PENETRATION),)
            note = "새 배관 경로가 지나는 판(구조 관통부 추가 — 설계자 확인 필요)"
            yield Finding(EntityType.PART, plate, ImpactType.MODIFY_PART, path, first, note)
            yield Finding(EntityType.PART, plate, ImpactType.COLLAR_RESIZE, path, first, note)


def r_p03(ctx: RuleContext) -> Iterator[Finding]:
    """빼는 스풀을 받치던 서포트: 옮기거나 없앰(원본 연결로 찾음)."""
    for planned in ctx.planned():
        for spool in planned.removed():
            for support in ctx.view.original_neighbours(spool, Relation.SUPPORT):
                path = (ctx.hop(spool, support, Relation.SUPPORT),)
                note = "받치던 스풀이 빠짐 — 서포트 이동·철거 필요"
                yield Finding(EntityType.PART, support, ImpactType.MODIFY_PART, path, spool, note)
