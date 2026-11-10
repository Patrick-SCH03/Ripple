"""관문 사례 대상 고르기: 지도에서 조건에 맞는 부재를 ID 순으로 결정적으로 고른다(1·2·3단계가 함께 쓴다)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from ripple.contracts.domain import BlockStage, GraphSnapshot, Part, PartKind, POStatus, Relation
from ripple.engine.index import GraphIndex
from ripple.engine.schedule.baseline import Baseline
from ripple.engine.state import StateModel


class Picker:
    """지도에서 조건에 맞는 부재를 ID 순으로 고른다.

    `scheduled`이면 상태 함수가 2단계 엔진처럼 기준 일정(CPM)의 공정 착수일을 시계로 쓴다
    (docs/engine.md(비용·일정) 1절).
    """

    def __init__(self, snapshot: GraphSnapshot, as_of: date, scheduled: bool = False) -> None:
        self.snapshot = snapshot
        self.index = GraphIndex(snapshot)
        self.baseline = Baseline(self.index, as_of) if scheduled else None
        self.state = StateModel(self.index, as_of, clock=self.baseline)
        self.as_of = as_of
        self.parts = sorted(snapshot.parts, key=lambda p: p.part_id)

    def first(self, test: Callable[[Part], bool], what: str) -> Part:
        for part in self.parts:
            if test(part):
                return part
        raise LookupError(f"관문 사례를 만들 부재가 없어요: {what}")

    def code(self, part: Part) -> str:
        return part.block_id.split(":")[-1]

    def started(self, block_id: str) -> bool:
        return self.state.block_stage_on(block_id, self.as_of).at_least(BlockStage.SUB_ASSEMBLY) is True

    def line_stage(self, part: Part) -> POStatus | None:
        line = self.index.line_of_part.get(part.part_id)
        return None if line is None else self.state.line_stage_on(line, self.as_of).likely

    def neighbours(self, part: Part, relation: Relation) -> list[Part]:
        return [self.index.parts[n] for n in self.index.out(part.part_id, relation)]

    # ---------- 사례 대상(1·2단계가 함께 쓴다) ----------

    def stock_joint(self) -> tuple[Part, float]:
        """예약 없는 첫 재고 로트의 두께와, 그 강종으로 블록 이음에 놓인 가장 얇은 T31C 판."""
        lot = next(s for s in sorted(self.snapshot.stock, key=lambda s: s.lot_id) if s.reserved_block_id is None)
        spec = self.index.specs[lot.spec_id]
        joint = min(
            (
                p
                for p in self.parts
                if self.code(p) == "T31C"
                and p.kind is PartKind.PLATE
                and p.grade == spec.grade
                and any(n.block_id != p.block_id for n in self.neighbours(p, Relation.BUTT_WELD))
            ),
            key=lambda p: (p.thickness_mm or 0, p.part_id),
        )
        return joint, spec.thickness_mm or 0

    def valve_twin(self) -> tuple[Part, str]:
        """미착수 P11C 밸브와, 연결 규격(호칭 지름·압력 등급)이 같은 다른 밸브 사양."""
        valve = self.first(lambda p: p.kind is PartKind.VALVE and self.code(p) == "P11C", "P11C 밸브")
        spec = self.index.specs[valve.spec_id]
        twin = next(
            s.spec_id
            for s in sorted(self.snapshot.specs, key=lambda s: s.spec_id)
            if s.category == "valve"
            and s.spec_id != spec.spec_id
            and (s.nominal_diameter_dn, s.pressure_class) == (spec.nominal_diameter_dn, spec.pressure_class)
        )
        return valve, twin

    def planned_order(self, part: Part) -> date | None:
        """부재를 공급하는 발주의 계획 발주일."""
        return self.index.orders[self.index.lines[self.index.line_of_part[part.part_id]].po_id].planned_order_date

    def supported_spool(self) -> Part:
        return self.first(
            lambda p: (
                p.kind is PartKind.PIPE_SPOOL and self.code(p) == "E21C" and bool(self.neighbours(p, Relation.SUPPORT))
            ),
            "서포트가 있는 E21C 스풀",
        )

    def started_plate_elsewhere(self) -> Part:
        """E21C·T31C가 아닌 착수한 블록의 첫 판(배관 경로 변경이 관통하는 판)."""
        return self.first(
            lambda p: p.kind is PartKind.PLATE and self.code(p) not in {"E21C", "T31C"} and self.started(p.block_id),
            "착수한 다른 블록 판",
        )

    def vague_plate(self) -> Part:
        """기준일에 발주 단계를 알 수 없는 품목의 첫 판."""
        return self.first(
            lambda p: p.kind is PartKind.PLATE and p.part_id in self.index.line_of_part and self.line_stage(p) is None,
            "단계를 알 수 없는 품목의 판",
        )
