"""블록 재작업(docs/engine.md(비용·일정) 3절·4-4, R-B01): 블록별 영향 중량을 모으고 블록마다 재작업 줄을 만든다.

줄 하나의 계산(누적 공수 × 단계 배수 × 난이도 × 수행 주체 단가, 작업반 몫 나누기, 도장 뒤 고정 항목)은 rework_block.
영향 중량은 선체 부재와 의장품(OUTFIT_PART_KINDS)으로 나눠 모은다 — 의장품은 선행의장 공정부터만 다시 한다(4-4).
재작업 일수(일정용)는 대표값 공수를 하루 투입 공수로 나눠 올림한다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ripple.contracts.change import AddPart
from ripple.contracts.domain import OUTFIT_PART_KINDS, EntityType, PartKind
from ripple.contracts.result import CostLine, ImpactType

from .inputs import CostInput
from .rework_block import CREW, block_rework

__all__ = ["CREW", "Rework", "changed_weights", "part_weight", "rework"]
ALSO_FROM = frozenset({ImpactType.TAPER, ImpactType.COLLAR_RESIZE, ImpactType.MODIFY_PART})


@dataclass(frozen=True, slots=True)
class Rework:
    lines: tuple[CostLine, ...]
    days: dict[str, int]  # 블록 → 재작업 일수 d_B(대표값)


@dataclass(frozen=True, slots=True)
class Weight:
    hull: float = 0.0  # 선체 부재(판·보강재·브라켓·칼라) 중량(t)
    outfit: float = 0.0  # 의장품(배관 스풀·밸브·서포트·장비) 중량(t)
    keys: frozenset[str] = frozenset()  # 중량 정보가 없어 쓴 환산 중량 파라미터 키

    @property
    def tons(self) -> float:
        return self.hull + self.outfit


def changed_weights(inp: CostInput) -> dict[str, Weight]:
    """블록마다 바뀌는 부재 중량(t)의 합(선체·의장품 따로)과 쓴 환산 중량 키(3절). 같은 부재는 한 번."""
    view = inp.view
    new_qty = {
        planned.new_ids[0]: planned.op.qty
        for planned in view.ops
        if isinstance(planned.op, AddPart) and planned.new_ids
    }
    changed = set(view.targets(tuple(planned.name for planned in view.ops)))
    for _, finding in inp.propagation.findings:
        if finding.entity_type is EntityType.PART and finding.impact_type in ALSO_FROM:
            changed.add(finding.entity_id)
    hull: dict[str, float] = defaultdict(float)
    outfit: dict[str, float] = defaultdict(float)
    keys: dict[str, set[str]] = defaultdict(set)
    for part_id in sorted(changed):
        block = view.block_of(part_id)
        if block is None:
            continue
        weight, key = _weight(inp, part_id, new_qty.get(part_id))
        (outfit if _kind(inp, part_id) in OUTFIT_PART_KINDS else hull)[block] += weight
        if key is not None:
            keys[block].add(key)
    return {
        block: Weight(hull=hull.get(block, 0.0), outfit=outfit.get(block, 0.0), keys=frozenset(keys[block]))
        for block in sorted({*hull, *outfit})
    }


def _kind(inp: CostInput, part_id: str) -> PartKind:
    new = inp.view.new_parts.get(part_id)
    return new.kind if new is not None else inp.index.parts[part_id].kind


def part_weight(inp: CostInput, part_id: str) -> tuple[float, str | None]:
    """부재 하나의 중량(3절)과 환산 중량 키. 부재 추가의 새 부재는 연산 수량(규격 단위 t일 때)을 쓴다."""
    added = next(
        (p.op.qty for p in inp.view.ops if isinstance(p.op, AddPart) and p.new_ids and p.new_ids[0] == part_id),
        None,
    )
    return _weight(inp, part_id, added)


def _weight(inp: CostInput, part_id: str, added_qty: float | None) -> tuple[float, str | None]:
    """부재 하나의 중량(t)과, 중량 정보가 없어 환산 중량을 썼으면 그 파라미터 키."""
    view, index = inp.view, inp.index
    if part_id in view.new_parts:
        new = view.new_parts[part_id]
        spec = index.specs.get(new.spec_id)
        if added_qty is not None and spec is not None and spec.unit == "t":
            return added_qty, None
        return _equivalent(inp, new.kind)
    part = index.parts[part_id]
    return (part.weight_kg / 1000, None) if part.weight_kg is not None else _equivalent(inp, part.kind)


def _equivalent(inp: CostInput, kind: PartKind) -> tuple[float, str]:
    key = f"rework.equivalent_weight_t.{kind.value}"
    return inp.params.value(key), key


def rework(inp: CostInput) -> Rework:
    """재작업 영향(R-B01)이 있는 블록마다 재작업 줄(작업반 몫으로 나뉠 수 있음)·도장 뒤 고정 항목 줄과 재작업 일수."""
    weights = changed_weights(inp)
    lines: list[CostLine] = []
    days: dict[str, int] = {}
    seen: set[str] = set()
    for _, finding in inp.propagation.findings:
        block_id = finding.entity_id
        if finding.impact_type is not ImpactType.REWORK or block_id in seen:
            continue
        seen.add(block_id)
        changed = weights.get(block_id, Weight())
        block = block_rework(inp, block_id, changed.hull, changed.outfit, changed.keys)
        lines.extend(block.lines)
        if block.days > 0:
            days[block_id] = block.days
    return Rework(lines=tuple(sorted(lines, key=lambda line: line.line_id)), days=days)
