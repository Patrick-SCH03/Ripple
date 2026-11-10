"""블록 경계 연결(P-03)과 분야 간 도면(P-04): 이 설계변경 범위 밖으로 이어지는 연결·도면."""

from __future__ import annotations

from ripple.contracts.domain import Relation
from ripple.contracts.result import PrecheckItem, PrecheckLevel

from .scope import PIPE_KINDS, Scope, link
from .text import FINDINGS, REASONS, code_of, joined

DISCIPLINE_NAMES = {"hull": "선체", "piping": "배관", "outfitting": "의장", "machinery": "기계"}


def boundaries(scope: Scope) -> list[PrecheckItem]:
    """P-03 블록 경계 연결: 빼거나 바꾸거나 새로 만드는 배관 부재의 배관 연결(pipe_joint) 상대가 다른 블록이고,
    그 블록이 이 설계변경 범위(대상·새 부재의 블록)에 없음 → 상대 블록 확인(확인 필요).
    지도에 배관 연결이 하나도 없으면 점검 불가."""
    pipes = [p for p in (*scope.changed, *scope.new_ids) if scope.kind(p) in PIPE_KINDS]
    if pipes and not scope.has_pipe_joints:
        return [scope.unchecked("P-03", pipes)]
    by_block: dict[str, list[tuple[str, str]]] = {}
    for part_id in pipes:
        own = scope.view.block_of(part_id)
        removed = part_id in scope.view.removed
        joints = (
            scope.view.original_neighbours(part_id, Relation.PIPE_JOINT)
            if removed
            else scope.view.neighbours(part_id, Relation.PIPE_JOINT)
        )
        for other_part in joints:
            other = scope.view.block_of(other_part)
            if own is not None and other is not None and other != own and other not in scope.scope_blocks:
                by_block.setdefault(other, []).append((part_id, other_part))
    items: list[PrecheckItem] = []
    for other, pairs in sorted(by_block.items()):
        mine = joined(scope.label(p) for p, _ in pairs)
        theirs = joined(scope.label(o) for _, o in pairs)
        items.append(
            scope.item(
                "P-03",
                "boundary",
                other,
                finding=FINDINGS["boundary"],
                level=PrecheckLevel.CHECK,
                targets=(other, *(p for p, _ in pairs), *(o for _, o in pairs)),
                evidence=(
                    *(link(p, o, Relation.PIPE_JOINT, virtual=p in scope.view.new_parts) for p, o in pairs),
                    *(link(o, other, Relation.PART_OF) for _, o in pairs),
                ),
                text=(
                    f"바뀌는 배관({mine})이 {code_of(other)} 블록 배관({theirs})과 배관 연결로 이어짐 · "
                    f"{code_of(other)} 블록은 이 설계변경 범위 밖 — 상대 블록 연결부 확인 필요"
                ),
                reason=REASONS["boundary"],
            )
        )
    return items


def secondary(scope: Scope) -> list[PrecheckItem]:
    """P-04 분야 간 도면: 바뀌는 부재(R-D01이 도면 개정의 출발로 본 부재)의 다른 분야 도면(secondary_drawing_ids)이
    분석의 도면 개정 목록에 없음 → 다른 분야 도면 미반영(확인 필요). R-D01의 의미(자기 도면만)는 그대로다.
    지도에 다른 분야 도면 정보가 하나도 없으면 점검 불가."""
    parts = sorted(scope.revised_parts())
    if parts and not scope.has_secondary:
        return [scope.unchecked("P-04", parts)]
    revised = scope.revision_list()
    by_drawing: dict[str, list[str]] = {}
    for part_id in parts:
        for drawing in scope.index.parts[part_id].secondary_drawing_ids:
            if drawing not in revised:
                by_drawing.setdefault(drawing, []).append(part_id)
    items: list[PrecheckItem] = []
    for drawing, members in sorted(by_drawing.items()):
        items.append(
            scope.item(
                "P-04",
                "secondary",
                drawing,
                finding=FINDINGS["secondary"],
                level=PrecheckLevel.CHECK,
                targets=(drawing, *members),
                evidence=tuple(link(p, drawing, "secondary_drawing") for p in members),
                text=(
                    f"바뀌는 부재({joined(scope.label(p) for p in members)})가 함께 그려진 "
                    f"{_drawing(scope, drawing)}이 도면 개정 목록에 없음 — 그 분야 도면 담당과 개정 여부 확인 필요"
                ),
                reason=REASONS["secondary"],
            )
        )
    return items


def _drawing(scope: Scope, drawing_id: str) -> str:
    """'배관도 DWG-P11C-CS-P01(개정 A)' — 지도에 없는 도면이면 ID 그대로."""
    found = scope.index.drawings.get(drawing_id)
    if found is None:
        return f"도면 {drawing_id}"
    return f"{DISCIPLINE_NAMES.get(found.discipline, found.discipline)} 도면 {found.drawing_no}(개정 {found.revision})"
