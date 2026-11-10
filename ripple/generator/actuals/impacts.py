"""변경 후 보기와 연결 영향: 바뀌는 부재, 작은 작업·도면 개정 표시(docs/engine.md(전파) 3·5절)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from itertools import pairwise

from ripple.contracts.change import (
    AddPart,
    AddPenetration,
    ChangeRequest,
    EquipmentSpecChange,
    RemovePart,
    ReroutePipe,
    ThicknessChange,
)
from ripple.contracts.domain import ConnectionKind

from .common import new_part_key
from .world import World

ATTACH = {
    "plate": ConnectionKind.BUTT_WELD,
    "stiffener": ConnectionKind.FILLET_WELD,
    "bracket": ConnectionKind.FILLET_WELD,
    "collar": ConnectionKind.FILLET_WELD,
    "pipe_spool": ConnectionKind.PIPE_JOINT,
    "valve": ConnectionKind.PIPE_JOINT,
    "pipe_support": ConnectionKind.SUPPORT,
}
"""부재 추가에서 새 부재와 붙는 부재의 관계(docs/engine.md(전파) 3절 표, 장비는 연결 없음)."""
CHANGING_WORK = frozenset({"taper", "collar_resize", "modify_part"})
"""표시되면 그 부재도 바뀌는 부재가 되는 작은 작업(블록 재작업 중량에 들어간다)."""

Virtual = dict[tuple[str, ConnectionKind], set[str]]


def view(world: World, change: ChangeRequest) -> tuple[set[str], Virtual, dict[str, str]]:
    """변경 후 보기(docs/engine.md(전파) 3절): 빼는 부재, 새 연결, 새 부재의 규격.

    새 연결 = 부재 추가의 붙는 관계(종류별), 새 스풀끼리·남는 끝점과의 배관 연결, 관통하는 판, 관통부 추가.
    """
    removed: set[str] = set()
    for op in change.ops:
        if isinstance(op, RemovePart):
            removed.update(op.part_ids)
        elif isinstance(op, ReroutePipe):
            removed.update(op.removed_part_ids)
    virtual: Virtual = defaultdict(set)
    new_specs: dict[str, str] = {}

    def connect(a: str, b: str, kind: ConnectionKind) -> None:
        virtual[(a, kind)].add(b)
        virtual[(b, kind)].add(a)

    for op in change.ops:
        if isinstance(op, AddPart):
            new_id = f"NEW:{new_part_key(op)}:1"
            new_specs[new_id] = op.spec_id
            relation = ATTACH.get(op.kind.value)
            attach = op.attach_to_part_id
            if relation is not None and attach in world.parts and attach not in removed:
                connect(new_id, attach, relation)
        elif isinstance(op, ReroutePipe):
            _view_reroute(world, op, removed, new_specs, connect)
        elif isinstance(op, AddPenetration):
            connect(op.plate_part_id, op.pipe_part_id, ConnectionKind.PENETRATION)
    return removed, virtual, new_specs


def _view_reroute(
    world: World,
    op: ReroutePipe,
    removed: set[str],
    new_specs: dict[str, str],
    connect: Callable[[str, str, ConnectionKind], None],
) -> None:
    ids = [f"NEW:{new_part_key(op)}:{n}" for n in range(1, len(op.added_spool_spec_ids) + 1)]
    new_specs.update(zip(ids, op.added_spool_spec_ids, strict=True))
    for a, b in pairwise(ids):
        connect(a, b, ConnectionKind.PIPE_JOINT)
    ends = sorted(
        {
            end
            for spool in op.removed_part_ids
            for end in world.neighbors[(spool, ConnectionKind.PIPE_JOINT)]
            if end in world.parts and end not in removed
        }
    )
    if ids and ends:
        connect(ids[0], ends[0], ConnectionKind.PIPE_JOINT)
        for end in ends[1:]:
            connect(ids[-1], end, ConnectionKind.PIPE_JOINT)
    for plate in op.crosses_part_ids:
        if ids and plate in world.parts and plate not in removed:
            connect(ids[0], plate, ConnectionKind.PENETRATION)


def impacts(world: World, change: ChangeRequest) -> tuple[set[str], set[tuple[str, str, str]]]:
    """(바뀌는 부재, 작은 작업 표시 (규칙, 엔터티, 작업 종류)). 도면 개정은 바뀌는 부재·붙이는 부재의 도면마다."""
    marks = _Marks(world, change)
    marks.ops()
    marks.changed.discard("")
    marks.drawings()
    return marks.changed, marks.minor


class _Marks:
    """변경 후 보기 위에서 연산마다 연결 규칙을 따라 작은 작업을 표시한다(빼는 부재는 표시하지 않음)."""

    def __init__(self, world: World, change: ChangeRequest) -> None:
        self.world = world
        self.change = change
        self.changed: set[str] = set()
        self.minor: set[tuple[str, str, str]] = set()
        self.removed, self.virtual, self.new_specs = view(world, change)

    def neighbors(self, part_id: str, kind: ConnectionKind) -> set[str]:
        """변경 후 이웃: 원본 이웃 − 빼는 부재 + 새 연결(빼는 부재에서 출발하는 규칙은 원본 연결)."""
        return (self.world.neighbors[(part_id, kind)] - self.removed) | self.virtual[(part_id, kind)]

    def thickness(self, part_id: str) -> float | None:
        """변경 전 두께(새 부재는 규격의 두께)."""
        if part_id in self.new_specs:
            spec = self.world.specs.get(self.new_specs[part_id])
            return None if spec is None else spec.thickness_mm
        return self.world.parts[part_id].thickness_mm

    def mark(self, rule: str, entity: str, kind: str) -> None:
        if entity in self.removed:
            return
        self.minor.add((rule, entity, kind))
        if kind in CHANGING_WORK:
            self.changed.add(entity)

    def ops(self) -> None:
        parts = self.world.parts
        for op in self.change.ops:
            targets = getattr(op, "part_ids", ())
            if isinstance(op, ReroutePipe):
                targets = op.removed_part_ids
            if isinstance(op, AddPenetration):
                targets = (op.plate_part_id,)
            self.changed.update(p for p in targets if p in parts)
            if isinstance(op, ThicknessChange):
                self.thickness_change(op)
            elif isinstance(op, AddPenetration):
                self.mark("R-T04", op.pipe_part_id, "collar_resize")
            elif isinstance(op, EquipmentSpecChange):
                self.equipment_change(op)
            elif isinstance(op, ReroutePipe):
                for spool in op.removed_part_ids:
                    for other in self.world.neighbors[(spool, ConnectionKind.SUPPORT)]:
                        self.mark("R-P03", other, "modify_part")
                for plate in op.crosses_part_ids:
                    self.mark("R-P02", plate, "modify_part")
                    self.mark("R-P02", plate, "collar_resize")

    def thickness_change(self, op: ThicknessChange) -> None:
        for part_id in op.part_ids:
            for other in self.neighbors(part_id, ConnectionKind.BUTT_WELD):
                mine = op.to_mm
                theirs = next(
                    (x.to_mm for x in self.change.ops if isinstance(x, ThicknessChange) and other in x.part_ids),
                    self.thickness(other),
                )
                if theirs is None or abs(mine - theirs) >= (3 if min(mine, theirs) <= 10 else 4):
                    self.mark("R-T02", other, "taper")
            for other in self.neighbors(part_id, ConnectionKind.FILLET_WELD):
                self.mark("R-T03", other, "weld_recheck")
            for other in self.neighbors(part_id, ConnectionKind.PENETRATION):
                self.mark("R-T04", other, "collar_resize")

    def equipment_change(self, op: EquipmentSpecChange) -> None:
        before, after = self.world.specs.get(op.from_spec_id), self.world.specs.get(op.to_spec_id)
        same = (
            before is not None
            and after is not None
            and before.nominal_diameter_dn is not None
            and after.nominal_diameter_dn is not None
            and before.pressure_class is not None
            and after.pressure_class is not None
            and (before.nominal_diameter_dn, before.pressure_class) == (after.nominal_diameter_dn, after.pressure_class)
        )
        if not same:
            for part_id in op.part_ids:
                for other in self.neighbors(part_id, ConnectionKind.PIPE_JOINT):
                    self.mark("R-P01", other, "modify_part")

    def drawings(self) -> None:
        parts = self.world.parts
        drawings = {f"{parts[p].drawing_no}@{parts[p].revision}" for p in self.changed if p in parts}
        for op in self.change.ops:
            if isinstance(op, AddPart):
                attach_id = op.attach_to_part_id
                if attach_id is not None and attach_id in parts:
                    attached = parts[attach_id]
                    drawings.add(f"{attached.drawing_no}@{attached.revision}")
        for drawing in sorted(drawings):
            self.mark("R-D01", drawing, "drawing_revision")
