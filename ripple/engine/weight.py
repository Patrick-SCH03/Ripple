"""블록별 강재 중량 변화(docs/engine.md(비용·일정) 12절, 계약 1.34.0): 요청이 바꾸는 부재의 원래·새 중량을
블록별로 묶는다.

새 가정값을 쓰지 않는다 — 중량은 엔진이 이미 쓰는 값만:
- 규격 단위가 t인 부재: 자재비 차이(4-0·4-1, C-01 줄의 qty·new_qty)와 같은 수량. 두께 변경이면
  q × to_mm / from_mm, 강종 변경은 그대로, 부재 추가는 연산의 qty, 경로 변경의 새 스풀은 C-01과 같은 스풀 수량.
- 단위가 t가 아닌 부재(의장품 ea·m): 지도의 부재 중량(weight_kg)이 있을 때만(강종 변경은 그대로, 빼면 0).
- 그 밖(치수·장비 사양 변경, t가 아닌 부재의 두께 변경, 중량 없는 의장품, t가 아닌 새 부재)은 '중량 정보 없음'.
무게중심은 부재 좌표가 없어 계산하지 않는다. 비용·일정·판정·곡선·대안에 쓰지 않는다(정보).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ripple.contracts.change import AddPart, ReroutePipe, ThicknessChange
from ripple.contracts.result import WEIGHT_DIGITS, BlockWeight, PartWeight, WeightChange, WeightSource

from .cost import Params, SpecChange
from .cost.material import new_spool_qty
from .describe import describe
from .index import GraphIndex
from .overlay import ChangeView

UNKNOWN_FIELD_OPS = frozenset({"dimension", "equipment_spec"})
"""새 중량을 정할 규칙·값이 없는 연산(치수는 대상으로만 표시, 장비 새 규격의 중량은 지도에 없음)."""
WEIGHED_OPS = frozenset(
    {"thickness", "grade", "dimension", "equipment_spec", "remove_part", "add_part", "reroute_pipe"}
)
"""중량 변화에 넣는 연산. 관통부 추가(구멍 하나)와 이어서 바뀌는 부재(테이퍼·칼라·부재 수정)는 넣지 않는다."""
UNKNOWN_BLOCK = "블록 모름"


@dataclass(frozen=True, slots=True)
class _Weighed:
    source: WeightSource
    before: float | None
    after: float | None


NO_WEIGHT = _Weighed(WeightSource.NONE, None, None)


def weight_change(index: GraphIndex, view: ChangeView, changes: tuple[SpecChange, ...], params: Params) -> WeightChange:
    """요청의 연산이 바꾸는 부재(기존·새·빼는 부재)마다 중량을 정해 블록별로 묶는다.
    changes = 4-0의 바뀌는 규격(엔진이 이미 계산한 값 — Evaluator.changes)."""
    ops_of: dict[str, set[str]] = defaultdict(set)
    thickness: dict[str, tuple[float | None, float]] = {}
    for planned in view.ops:
        if planned.name not in WEIGHED_OPS:
            continue
        for part_id in planned.targets():
            ops_of[part_id].add(planned.name)
        if isinstance(planned.op, ThicknessChange):
            for part_id in planned.op.part_ids:
                thickness[part_id] = (index.parts[part_id].thickness_mm, planned.op.to_mm)
    by_spec = {ch.part_id: ch for ch in changes}
    spools = _new_spool_weights(index, view, params)
    grouped: dict[str | None, list[PartWeight]] = defaultdict(list)
    for part_id in sorted(ops_of):
        ops = ops_of[part_id]
        weighed = (
            _new_part(index, view, part_id, spools)
            if part_id in view.new_parts
            else _existing(index, view, part_id, ops, by_spec)
        )
        block_id = view.block_of(part_id)
        from_mm, to_mm = thickness.get(part_id, (None, None))
        grouped[block_id].append(
            PartWeight(
                part_id=part_id,
                label=_label(index, view, part_id),
                block_id=block_id,
                ops=tuple(sorted(ops)),
                source=weighed.source,
                before_t=_t(weighed.before),
                after_t=_t(weighed.after),
                from_mm=from_mm,
                to_mm=to_mm,
            )
        )
    blocks = [
        _block(index, block_id, grouped[block_id]) for block_id in sorted(grouped, key=lambda b: (b is None, b or ""))
    ]
    return WeightChange(
        blocks=tuple(blocks),
        before_t=_t(sum(b.before_t for b in blocks)) or 0.0,
        after_t=_t(sum(b.after_t for b in blocks)) or 0.0,
        delta_t=_t(sum(b.delta_t for b in blocks)) or 0.0,
        counted=sum(b.counted for b in blocks),
        missing=sum(b.missing for b in blocks),
    )


def _t(value: float | None) -> float | None:
    """중량(t)을 계약 자리로 반올림(−0은 0으로)."""
    return None if value is None else round(value, WEIGHT_DIGITS) + 0.0


def _part_weight_t(index: GraphIndex, part_id: str) -> tuple[WeightSource, float] | None:
    """기존 부재의 원래 중량: 규격 단위 t면 수량(C-01과 같은 값), 아니면 지도의 부재 중량, 없으면 None."""
    part = index.parts[part_id]
    if index.specs[part.spec_id].unit == "t":
        return WeightSource.QTY_T, part.qty
    if part.weight_kg is not None:
        return WeightSource.WEIGHT_KG, part.weight_kg / 1000
    return None


def _existing(
    index: GraphIndex, view: ChangeView, part_id: str, ops: set[str], by_spec: dict[str, SpecChange]
) -> _Weighed:
    known = _part_weight_t(index, part_id)
    if known is None:
        return NO_WEIGHT
    source, before = known
    if part_id in view.removed:
        return _Weighed(source, before, 0.0)
    if ops & UNKNOWN_FIELD_OPS:
        return NO_WEIGHT
    change = by_spec.get(part_id)
    if source is WeightSource.QTY_T and change is not None:
        return _Weighed(source, change.q, change.q_new)  # 4-0: 두께 변경 q × to/from, 강종 변경 q 그대로
    if ops == {"grade"}:
        return _Weighed(source, before, before)  # 강종만 바뀜 — 중량 그대로(4-0과 같은 생각)
    return NO_WEIGHT  # t가 아닌 부재의 두께 변경: 새 중량 규칙 없음


def _new_spool_weights(index: GraphIndex, view: ChangeView, params: Params) -> dict[str, float]:
    """경로 변경의 새 스풀 중 규격 단위가 t인 것의 수량(C-01 _spool_rows와 같은 new_spool_qty)."""
    found: dict[str, float] = {}
    for planned in view.ops:
        if isinstance(planned.op, ReroutePipe):
            each = new_spool_qty(index, planned.op, params)
            for new_id, spec_id in zip(planned.new_ids, planned.op.added_spool_spec_ids, strict=True):
                spec = index.specs.get(spec_id)
                if spec is not None and spec.unit == "t":
                    found[new_id] = each
    return found


def _new_part(index: GraphIndex, view: ChangeView, part_id: str, spools: dict[str, float]) -> _Weighed:
    """새 부재: 부재 추가는 규격 단위 t면 연산의 qty(C-01과 같음), 새 스풀은 t 규격이면 스풀 수량. 그 밖은 정보 없음."""
    if part_id in spools:
        return _Weighed(WeightSource.QTY_T, 0.0, spools[part_id])
    for planned in view.ops:
        op = planned.op
        if isinstance(op, AddPart) and part_id in planned.new_ids:
            spec = index.specs.get(op.spec_id)
            if spec is not None and spec.unit == "t":
                return _Weighed(WeightSource.QTY_T, 0.0, op.qty)
    return NO_WEIGHT


def _label(index: GraphIndex, view: ChangeView, part_id: str) -> str:
    return view.new_node(part_id).label if part_id in view.new_parts else describe(index, part_id).label


def _block(index: GraphIndex, block_id: str | None, parts: list[PartWeight]) -> BlockWeight:
    known = [p for p in parts if p.source is not WeightSource.NONE]
    before = _t(sum(p.before_t or 0.0 for p in known)) or 0.0
    after = _t(sum(p.after_t or 0.0 for p in known)) or 0.0
    block = index.blocks.get(block_id) if block_id else None
    return BlockWeight(
        block_id=block_id,
        name=block.name if block else UNKNOWN_BLOCK,
        before_t=before,
        after_t=after,
        delta_t=_t(after - before) or 0.0,
        counted=len(known),
        missing=len(parts) - len(known),
        parts=tuple(parts),
    )
