"""연결 확인(R-X01): 따라가야 할 관계가 통째로 없으면 계산에서 빼고 '확인 필요'로 남긴다."""

from __future__ import annotations

from collections.abc import Iterator

from ripple.contracts.domain import EntityType, PartKind, Relation
from ripple.contracts.result import ImpactType, Unresolved, UnresolvedKind

from ..describe import RELATION_NAMES
from .base import Finding, RuleContext


def r_x01(ctx: RuleContext) -> Iterator[Finding]:
    required = {
        PartKind(kind): frozenset(Relation(r) for r in relations)
        for kind, relations in ctx.rule.settings.get("required_relations", {}).items()
    }
    for planned in ctx.planned():
        used = ctx.used_relations.get(planned.name, frozenset())
        for part_id in planned.existing_targets():
            if ctx.view.index.type_of(part_id) is not EntityType.PART:
                continue
            needed = required.get(ctx.view.kind(part_id), frozenset()) & used
            missing = sorted(r for r in needed if not ctx.view.has_relation(part_id, r))
            if missing:
                names = ", ".join(RELATION_NAMES[r] for r in missing)
                yield _confirm(part_id, f"{names} 연결 정보 없음 — 그 경로는 계산에서 제외")
        for new_id in planned.new_ids:
            new = ctx.view.new_parts[new_id]
            lacking = [
                name
                for name, absent in (
                    ("블록", new.block_id is None),
                    ("도면", new.drawing_id is None),
                    ("붙는 위치", new.kind is not PartKind.EQUIPMENT and not ctx.view.connected(new_id)),
                )
                if absent
            ]
            if lacking:
                yield _confirm(new_id, f"새 부재의 {', '.join(lacking)} 미상 — 이웃 영향 추적 불가")


def _confirm(part_id: str, note: str) -> Finding:
    unresolved = Unresolved(kind=UnresolvedKind.CONNECTION, entity_id=part_id, reason=f"{note}.")
    return Finding(EntityType.PART, part_id, ImpactType.NEEDS_CONFIRMATION, (), part_id, note, unresolved)
