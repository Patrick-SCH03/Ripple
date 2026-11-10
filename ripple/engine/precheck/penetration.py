"""관통부 정합(P-02): 경로가 바뀌는 배관이 지나는 판의 칼라·관통부와, 빼는 배관이 지나던 관통부.

지도의 칼라 유무가 기준이다(형상 검사가 아님). 판정 기준은 잠정(docs/engine.md(사전 점검) 2절 '정하지 않은 것'):
새 경로가 지나는 판에 같은 계통 배관이 지나는 칼라가 있거나, 빼는 배관이 그 판을 이미 지났거나(관통부 다시 씀),
이 요청이 그 판에 칼라 추가·관통부 추가를 함께 하면 '관통부 있음'으로 본다.
"""

from __future__ import annotations

from ripple.contracts.change import ReroutePipe
from ripple.contracts.domain import PartKind, Relation
from ripple.contracts.result import PrecheckItem, PrecheckLevel, PrecheckLink

from .scope import PIPE_KINDS, Scope, link
from .text import FINDINGS, REASONS, code_of, joined


def penetrations(scope: Scope) -> list[PrecheckItem]:
    """P-02: 관통부 누락 의심(확인 필요) · 구멍 막음 필요(주의). 지도에 칼라가 하나도 없으면 누락 쪽은 점검 불가.
    같은 판을 지나는 경로 변경이 여럿이면 판마다 항목 하나로 합친다(새 스풀은 경로 변경 순서대로 모두)."""
    items: list[PrecheckItem] = []
    blind: list[str] = []
    missing: dict[str, list[str]] = {}
    for op, new_ids in scope.reroutes:
        if not new_ids:
            continue
        for plate in sorted(set(op.crosses_part_ids)):
            if scope.kind(plate) is not PartKind.PLATE:
                continue
            if not scope.has_kind(PartKind.COLLAR):
                blind.append(plate)
            elif not _opening(scope, plate, op, new_ids[0]):
                listed = missing.setdefault(plate, [])
                listed += [n for n in new_ids if n not in listed]
    items += [_missing(scope, plate, tuple(new_ids)) for plate, new_ids in sorted(missing.items())]
    items += _holes(scope)
    if blind:
        items.append(scope.unchecked("P-02", dict.fromkeys(blind)))  # 같은 판은 한 번(처음 나온 순서)
    return items


def _system(scope: Scope, op: ReroutePipe, first_new: str) -> str | None:
    new = scope.view.new_parts.get(first_new)
    if new is not None and new.system is not None:
        return new.system
    removed = [scope.index.parts[r] for r in sorted(op.removed_part_ids) if r in scope.index.parts]
    return removed[0].system if removed else None


def _opening(scope: Scope, plate: str, op: ReroutePipe, first_new: str) -> bool:
    """그 판에 새 경로가 쓸 관통부가 있는가(위 모듈 설명의 세 경우)."""
    if plate in scope.added_collars or plate in scope.added_penetrations:
        return True
    if plate in {p for removed in op.removed_part_ids for p, _ in _crossings(scope, removed)}:
        return True
    system = _system(scope, op, first_new)
    for collar in _collars(scope, plate):
        pipes = [p for p in scope.index.out(collar, Relation.PENETRATION) if scope.kind(p) in PIPE_KINDS]
        if any(system is None or scope.index.parts[p].system == system for p in pipes):
            return True
    return False


def _collars(scope: Scope, plate: str) -> list[str]:
    """그 판에 필릿 용접으로 붙은 칼라."""
    return [c for c in scope.index.out(plate, Relation.FILLET_WELD) if scope.kind(c) is PartKind.COLLAR]


def _crossings(scope: Scope, pipe: str) -> list[tuple[str, str | None]]:
    """그 배관이 지나는 (판, 칼라): 판과 바로 관통하거나, 배관과 관통하는 칼라가 판에 필릿 용접으로 붙음."""
    found: list[tuple[str, str | None]] = []
    for other in scope.index.out(pipe, Relation.PENETRATION):
        kind = scope.kind(other)
        if kind is PartKind.PLATE:
            found.append((other, None))
        elif kind is PartKind.COLLAR:
            found += [
                (p, other) for p in scope.index.out(other, Relation.FILLET_WELD) if scope.kind(p) is PartKind.PLATE
            ]
    return sorted(set(found), key=lambda pair: (pair[0], pair[1] or ""))


def _missing(scope: Scope, plate: str, new_ids: tuple[str, ...]) -> PrecheckItem:
    block = scope.view.block_of(plate) or ""
    names = joined(scope.label(n) for n in new_ids)
    return scope.item(
        "P-02",
        "missing",
        plate,
        finding=FINDINGS["penetration_missing"],
        level=PrecheckLevel.CHECK,
        targets=(plate, *new_ids),
        evidence=(link(new_ids[0], plate, Relation.PENETRATION, virtual=True),),
        text=(
            f"새 경로({names})가 지나는 판({code_of(block)} {scope.label(plate)})에 같은 계통 배관의 칼라·관통부가 "
            "지도에 없음 — 관통부·칼라의 도면 반영 여부 확인 필요"
        ),
        reason=REASONS["penetration_missing"],
    )


def _holes(scope: Scope) -> list[PrecheckItem]:
    """빼는 배관이 지나던 판 중 새 경로가 다시 지나지 않는 판 → 구멍 막음 필요(판마다 하나)."""
    reused = {c for op, _ in scope.reroutes for c in op.crosses_part_ids}
    by_plate: dict[str, list[tuple[str, str | None]]] = {}
    for removed in sorted(scope.view.removed):
        if scope.kind(removed) not in PIPE_KINDS:
            continue
        for plate, collar in _crossings(scope, removed):
            if plate not in reused:
                by_plate.setdefault(plate, []).append((removed, collar))
    items: list[PrecheckItem] = []
    for plate, pairs in sorted(by_plate.items()):
        evidence: list[PrecheckLink] = []
        for removed, collar in pairs:
            if collar is None:
                evidence.append(link(plate, removed, Relation.PENETRATION))
            else:
                evidence += [link(collar, removed, Relation.PENETRATION), link(collar, plate, Relation.FILLET_WELD)]
        collars = [c for _, c in pairs if c is not None]
        where = f"판({scope.label(plate)})" + (f"의 칼라({joined(scope.label(c) for c in collars)})" if collars else "")
        items.append(
            scope.item(
                "P-02",
                "hole",
                plate,
                finding=FINDINGS["hole_close"],
                level=PrecheckLevel.CAUTION,
                targets=(plate, *collars, *(r for r, _ in pairs)),
                evidence=evidence,
                text=(
                    f"빼는 배관({joined(scope.label(r) for r, _ in pairs)})이 지나던 {where} 관통부 잔존 — "
                    "구멍 막음 작업의 변경 범위 포함 여부 확인 필요"
                ),
                reason=REASONS["hole_close"],
            )
        )
    return items
