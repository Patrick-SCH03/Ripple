"""숨긴 세계: 지도 찾아보기 표, 생성기가 정한 참 발주 단계 날짜, 참 파라미터(docs/data.md(생성기) 6-1 참 날짜)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date, timedelta

from ripple.contracts.domain import DIRECT_PERFORMER, ActivityKind, ConnectionKind, POStatus

from ..build import Generated


class World:
    """숨긴 모델 하나가 읽는 것. 사례(설계변경·확정일·보류)마다 바뀌지 않는다."""

    def __init__(self, generated: Generated, values: Mapping[str, float]) -> None:
        snapshot = generated.snapshot
        self.snapshot = snapshot
        self.po_stages = generated.actual_po_stages
        self.values = values
        self.parts = {p.part_id: p for p in snapshot.parts}
        self.specs = {s.spec_id: s for s in snapshot.specs}
        self.lines = {line.line_id: line for line in snapshot.po_lines}
        self.orders = {po.po_id: po for po in snapshot.purchase_orders}
        self.blocks = {b.block_id: b for b in snapshot.blocks}
        self.activities = {a.activity_id: a for a in snapshot.activities}
        self.boundaries = {b.exit_activity_id: b for b in snapshot.boundaries}
        self.drawing_discipline = {d.drawing_id: d.discipline for d in snapshot.drawings}
        self.part_lines: dict[str, list[str]] = defaultdict(list)
        for line in snapshot.po_lines:
            for part_id in line.part_ids:
                self.part_lines[part_id].append(line.line_id)
        self.neighbors: dict[tuple[str, ConnectionKind], set[str]] = defaultdict(set)
        for edge in snapshot.connections:
            self.neighbors[(edge.a, edge.kind)].add(edge.b)
            self.neighbors[(edge.b, edge.kind)].add(edge.a)

    def param(self, key: str) -> float:
        return self.values[key]

    def transport_days(self, mode: str | None) -> int:
        """외자재 참 운송 일수(참 파라미터 transport_days.<방식>, 일 단위 반올림). 운송을 더하지 않으면 0."""
        return 0 if mode is None else round(self.param(f"transport_days.{mode}"))

    def line_of(self, part_id: str) -> str | None:
        """부재의 발주 품목(여럿이면 ID가 가장 앞선 것)."""
        return min(self.part_lines.get(part_id, ()), default=None)

    def crew(self, block_id: str) -> str:
        """블록 작업 인력: 사외 제작 블록이면 협력사, 아니면 직영."""
        return "subcontractor" if self.blocks[block_id].fabricator_id else "prime"

    def labor_of(self, block_id: str, kind: ActivityKind) -> str:
        """블록 공정 하나의 인건비 종류(v3): 작업반이 맡았으면 작업반, 직영이면 직영, 모르면 블록 작업 인력(위)."""
        activity = next(
            (a for a in self.activities.values() if a.block_id == block_id and a.kind is kind),
            None,
        )
        performer = activity.performer if activity is not None else None
        if performer is None:
            return self.crew(block_id)
        return "prime" if performer == DIRECT_PERFORMER else "crew"

    def line_stage(
        self,
        line_id: str,
        day: date,
        starts: Mapping[str, date],
        holds: Mapping[str, int],
        as_of: date,
    ) -> POStatus:
        """그날의 참 발주 단계: 기준일 뒤 단계 진입일은 보류만큼 미루고, 소비 공정이 착수했으면 가공됨."""
        line = self.lines[line_id]
        reached = POStatus.NOT_ORDERED
        for stage in (POStatus.ORDERED, POStatus.MATERIAL_SECURED, POStatus.IN_FABRICATION, POStatus.RECEIVED):
            entered = self.po_stages[line.po_id][stage]
            if entered > as_of:
                entered += timedelta(days=holds.get(line.po_id, 0))
            if entered <= day:
                reached = stage
        consumer = line.consumed_by_activity_id
        if consumer is not None and starts.get(consumer, date.max) <= day:
            return POStatus.PROCESSED
        return reached
