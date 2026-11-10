"""설치 시점(P-01)과 새 스풀 서포트(P-05): 새로 생기거나 바뀌는 의장품이 블록 공정·서포트와 맞는가."""

from __future__ import annotations

from ripple.contracts.domain import OUTFIT_PART_KINDS, ActivityKind, PartKind, Relation
from ripple.contracts.result import PrecheckItem, PrecheckLevel

from ..overlay import PlannedOp
from .scope import Scope, link
from .text import FINDINGS, REASONS, code_of, joined


def installation(scope: Scope) -> list[PrecheckItem]:
    """P-01 설치 시점: 확정일에 선행의장이 시작됐을 블록(실적 착수 또는 기준 일정 착수일 ES⁰ ≤ 확정일 — 확정일 평가의
    상태 함수와 같은 시계)에 새로 생기거나(새 부재) 바뀌는(두께·강종·치수·사양) 의장품 → 후행 설치 불가피(주의).
    블록에 선행의장 공정이 지도에 없으면 점검 불가."""
    by_block: dict[str, list[str]] = {}
    for part_id in (*scope.new_ids, *sorted(scope.view.reshaped)):
        block = scope.view.block_of(part_id)
        if block is not None and scope.kind(part_id) in OUTFIT_PART_KINDS:
            by_block.setdefault(block, []).append(part_id)
    items: list[PrecheckItem] = []
    missing: list[str] = []
    for block, parts in sorted(by_block.items()):
        outfitting = [a for a in scope.block_activities(block) if a.kind is ActivityKind.PRE_OUTFITTING]
        if not outfitting:
            missing.append(block)
            continue
        activity = outfitting[0]
        start = scope.start_on_confirm(activity)
        if start.expected > scope.confirm_on:
            continue
        names = joined(scope.label(p) for p in parts)
        then = "블록 설치 불가, 탑재 뒤 선상 후행 설치"
        if scope.finished(activity):
            state = f"{code_of(block)} 블록 선행의장 완료"
        elif start.actual is not None:
            state = f"{code_of(block)} 블록 선행의장 진행 중"
            then = "선행의장 완료 전 미반영 시 탑재 뒤 선상 후행 설치"
        else:
            state = (
                f"{code_of(block)} 블록은 확정일({scope.confirm_on.isoformat()})이면 선행의장 착수 상태"
                f"(기준 일정 착수 {start.expected.isoformat()})"
            )
            then = "확정 전 블록에서 달지 못하면 탑재 뒤 선상 후행 설치"
        items.append(
            scope.item(
                "P-01",
                "late_install",
                block,
                finding=FINDINGS["late_install"],
                level=PrecheckLevel.CAUTION,
                targets=(block, *parts, activity.activity_id),
                evidence=(
                    *(link(p, block, Relation.PART_OF, virtual=p in scope.view.new_parts) for p in parts),
                    link(activity.activity_id, block, Relation.PART_OF),
                ),
                text=f"{state} — 새로 생기거나 바뀌는 의장품({names}): {then}",
                reason=REASONS["late_install"],
            )
        )
    if missing:
        items.append(scope.unchecked("P-01", missing, blocks=joined(code_of(b) for b in missing)))
    return items


def supports(scope: Scope) -> list[PrecheckItem]:
    """P-05 새 스풀 서포트: 이 변경이 만드는 새 스풀에 서포트 연결이 없음(확인 필요). 빼는 스풀을 받치던 서포트는 근거로
    함께 보인다(다시 쓸 수 있는지). 지도에 서포트 부재가 하나도 없으면 점검 불가 — 모든 연산의 새 스풀을 대상으로."""
    found: list[tuple[PlannedOp, list[str]]] = []  # (연산, 서포트 연결 없는 새 스풀)
    for planned in scope.view.ops:
        spools = [n for n in planned.new_ids if scope.kind(n) is PartKind.PIPE_SPOOL]
        bare = [n for n in spools if not scope.view.neighbours(n, Relation.SUPPORT)]
        if bare:
            found.append((planned, bare))
    if found and not scope.has_kind(PartKind.PIPE_SUPPORT):
        return [scope.unchecked("P-05", [n for _, bare in found for n in bare])]
    items: list[PrecheckItem] = []
    for planned, bare in found:
        held = [
            (support, removed)
            for removed in sorted(planned.removed())
            for support in scope.index.out(removed, Relation.SUPPORT)
            if scope.kind(support) is PartKind.PIPE_SUPPORT
        ]
        text = f"새 스풀({joined(scope.label(n) for n in bare)})에 서포트 연결 없음"
        if held:
            old = joined(scope.label(s) for s, _ in held)
            text += f" — 빼는 스풀을 받치던 서포트({old}) 재사용 가능 여부 함께 확인"
        else:
            text += " — 서포트 설계·단품 발주 확인 필요"
        items.append(
            scope.item(
                "P-05",
                "support",
                bare[0],
                finding=FINDINGS["support"],
                level=PrecheckLevel.CHECK,
                targets=(*bare, *(s for s, _ in held)),
                evidence=tuple(link(s, r, Relation.SUPPORT) for s, r in held),
                text=text,
                reason=REASONS["support"],
            )
        )
    return items
