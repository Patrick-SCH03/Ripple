"""요청 검증(docs/engine.md(전파) 2절): 지도와 맞지 않는 요청은 계산하지 않고 이유를 모두 돌려준다."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.change import (
    AddPart,
    AddPenetration,
    ChangeOp,
    DimensionChange,
    EquipmentSpecChange,
    FieldChange,
    GradeChange,
    RemovePart,
    ReroutePipe,
    ThicknessChange,
    referenced_part_ids,
    removed_part_ids,
)
from ripple.contracts.domain import Part, PartKind, Relation
from ripple.contracts.identity import canonical_json, normalized_op

from .index import GraphIndex
from .overlay import op_key

PartLookup = Callable[[str, str], Part | None]  # (부재 ID, 역할) → 부재, 없으면 문제를 적고 None


class RequestError(ValueError):
    """지도와 맞지 않는 요청. problems는 사람이 읽는 이유 목록이다(명사형)."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(problems))


def validate_request(index: GraphIndex, request: AnalysisRequest) -> list[str]:
    change = request.change
    ships = set(change.ship_ids)
    problems = [f"지도에 없는 호선: {s}" for s in sorted(ships - set(index.ships))]

    shapes = Counter(canonical_json(normalized_op(op)) for op in change.ops)
    if any(n > 1 for n in shapes.values()):
        problems.append("같은 연산 중복")
    makers = {canonical_json(normalized_op(op)): op_key(op) for op in change.ops if _makes_parts(op)}
    if len(set(makers.values())) < len(makers):
        problems.append("새 부재를 만드는 연산 둘의 임시 ID 중복 — 수량 등 값을 달리해 다시 요청")

    def part(part_id: str, role: str) -> Part | None:
        found = index.parts.get(part_id)
        if found is None:
            problems.append(f"{role} {part_id} 지도에 없음")
        elif found.ship_id not in ships:
            problems.append(f"{role} {part_id}: 요청 호선({', '.join(sorted(ships))}) 밖")
        return found

    for op in change.ops:
        problems.extend(_check_op(index, op, part, ships))

    edited = Counter((op.op, part_id) for op in change.ops if isinstance(op, FieldChange) for part_id in op.part_ids)
    problems.extend(f"{part_id}의 같은 성질({name}) 두 번 변경" for (name, part_id), n in edited.items() if n > 1)
    removed = Counter(part_id for op in change.ops for part_id in removed_part_ids(op))
    problems.extend(f"{part_id} 빼기 중복" for part_id, n in removed.items() if n > 1)
    for op in change.ops:
        clashes = sorted(set(referenced_part_ids(op)) & set(removed))
        problems.extend(f"빼는 부재 {part_id}을(를) 다른 연산이 참조" for part_id in clashes)
    for hold in request.holds:
        order = index.orders.get(hold.po_id)
        if order is None:
            problems.append(f"보류할 발주 {hold.po_id} 지도에 없음")
        elif order.ship_id not in ships:
            problems.append(f"보류할 발주 {hold.po_id}: 요청 호선 밖")
    return problems


def _check_op(index: GraphIndex, op: ChangeOp, part: PartLookup, ships: set[str]) -> Iterator[str]:
    if isinstance(op, AddPart):
        yield from _check_add_part(index, op, part, ships)
    elif isinstance(op, ReroutePipe):
        yield from _check_reroute(index, op, part)
    elif isinstance(op, AddPenetration):
        yield from _check_penetration(index, op, part)
    else:
        yield from _check_existing_parts(op, part)


def _check_existing_parts(op: ChangeOp, part: PartLookup) -> Iterator[str]:
    """기존 부재를 바꾸거나 빼는 연산: 부재가 지도에 있는지, 요청의 '바꾸기 전' 값이 지도와 같은지."""
    if isinstance(op, DimensionChange | RemovePart):
        role = "치수를 바꾸는 부재" if isinstance(op, DimensionChange) else "빼는 부재"
        for part_id in op.part_ids:
            part(part_id, role)
        return
    yield from _check_from_values(op, part)


def _check_from_values(op: ChangeOp, part: PartLookup) -> Iterator[str]:
    """두께·강종·사양 변경: 요청의 '바꾸기 전' 값이 지도와 같은가."""
    if isinstance(op, ThicknessChange):
        for part_id in op.part_ids:
            found = part(part_id, "두께를 바꾸는 부재")
            if found and found.thickness_mm is not None and abs(found.thickness_mm - op.from_mm) > 1e-9:
                yield f"{part_id} 두께 불일치 — 지도 {found.thickness_mm:g}mm · 요청 {op.from_mm:g}mm"
    elif isinstance(op, GradeChange):
        for part_id in op.part_ids:
            found = part(part_id, "강종을 바꾸는 부재")
            if found and found.grade is not None and found.grade != op.from_grade:
                yield f"{part_id} 강종 불일치 — 지도 {found.grade} · 요청 {op.from_grade}"
    elif isinstance(op, EquipmentSpecChange):
        for part_id in op.part_ids:
            found = part(part_id, "사양을 바꾸는 부재")
            if found and found.spec_id != op.from_spec_id:
                yield f"{part_id} 규격 불일치 — 지도 {found.spec_id} · 요청 {op.from_spec_id}"


def _check_penetration(index: GraphIndex, op: AddPenetration, part: PartLookup) -> Iterator[str]:
    plate = part(op.plate_part_id, "관통되는 판")
    pipe = part(op.pipe_part_id, "관통하는 배관")
    if plate and plate.kind is not PartKind.PLATE:
        yield f"관통부 추가의 {op.plate_part_id}: 판이 아닌 부재"
    if plate and pipe and op.pipe_part_id in index.out(op.plate_part_id, Relation.PENETRATION):
        yield f"{op.plate_part_id}과(와) {op.pipe_part_id} 사이 관통 연결 이미 존재"


def _check_add_part(index: GraphIndex, op: AddPart, part: PartLookup, ships: set[str]) -> Iterator[str]:
    block = index.blocks.get(op.block_id)
    if block is None:
        yield f"부재를 더할 블록 {op.block_id} 지도에 없음"
    elif block.ship_id not in ships:
        yield f"부재를 더할 블록 {op.block_id}: 요청 호선({', '.join(sorted(ships))}) 밖"
    if op.spec_id not in index.specs:
        yield f"새 부재의 규격 {op.spec_id} 지도에 없음"
    if op.attach_to_part_id is not None:
        part(op.attach_to_part_id, "새 부재가 붙는 부재")


def _check_reroute(index: GraphIndex, op: ReroutePipe, part: PartLookup) -> Iterator[str]:
    for part_id in op.removed_part_ids:
        found = part(part_id, "빼는 스풀")
        if found and found.kind is not PartKind.PIPE_SPOOL:
            yield f"경로 변경으로 빼는 {part_id}: 배관 스풀이 아닌 부재"
    for spec_id in op.added_spool_spec_ids:
        if spec_id not in index.specs:
            yield f"더하는 스풀의 규격 {spec_id} 지도에 없음"
    for part_id in op.crosses_part_ids:
        crossed = part(part_id, "새 경로가 관통하는 판")
        if crossed and crossed.kind is not PartKind.PLATE:
            yield f"새 경로가 관통하는 {part_id}: 판이 아닌 부재"
    if op.crosses_part_ids and not op.added_spool_spec_ids:
        yield "관통하는 판이 있으면 더하는 스풀 하나 이상 필요"
    ships = {index.parts[p].ship_id for p in (*op.removed_part_ids, *op.crosses_part_ids) if p in index.parts}
    if len(ships) > 1:
        yield f"배관 경로 변경 하나에 여러 호선({', '.join(sorted(ships))}) 혼재"


def _makes_parts(op: ChangeOp) -> bool:
    """임시 ID(NEW:<h8>:<n>)를 쓰는 연산: 부재 추가, 더하는 스풀이 있는 경로 변경."""
    return isinstance(op, AddPart) or (isinstance(op, ReroutePipe) and bool(op.added_spool_spec_ids))
