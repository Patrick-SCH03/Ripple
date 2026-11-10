"""관문 결과의 의미상 근거 경로와 비용 줄 대응 검사. 엔진 호출은 하지 않는다."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.domain import EntityType, Relation
from ripple.contracts.result import CostLine, Impact, ImpactType
from ripple.engine.index import GraphIndex
from ripple.engine.overlay import ChangeView


@dataclass(frozen=True, slots=True)
class EvidenceCheck:
    impact: Impact
    origin_kind: str
    origin_ok: bool
    links_ok: bool
    terminal_ok: bool
    virtual_links: tuple[str, ...]
    missing_links: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return self.origin_ok and self.links_ok and self.terminal_ok


def _virtual_kind(view: ChangeView, src: str, dst: str, relation: Relation, rule_id: str) -> str | None:
    if any(edge.relation is relation and {edge.source, edge.target} == {src, dst} for edge in view.virtual_edges):
        return "change_view"
    if src in view.new_parts:
        if relation is Relation.PART_OF and view.block_of(src) == dst:
            return "new_part_block"
        if relation is Relation.DRAWN_IN and view.drawing_of(src) == dst:
            return "new_part_drawing"
        # 명세 5절 새 자재 수요: 발주 품목이 없는 새 부재·새 스풀은 그 블록의 선행의장이 바로 소비 공정
        # (R-S01이 만드는 연결)
        if (
            relation is Relation.CONSUMED_BY
            and rule_id == "R-S01"
            and dst in view.index.activities
            and view.index.activities[dst].block_id == view.block_of(src)
            and view.index.activities[dst].kind == "pre_outfitting"
        ):
            return "new_part_demand"
    if relation is Relation.SAME_SPEC and rule_id == "R-M01":
        source_type, target_type = view.index.type_of(src), view.index.type_of(dst)
        if view.is_part(src) and target_type is EntityType.STOCK and _stock_matches(view, src, dst):
            return "same_spec_stock"
        if (
            source_type is EntityType.PO_LINE
            and target_type is EntityType.PO_LINE
            and view.index.lines[src].spec_id == view.index.lines[dst].spec_id
        ):
            return "same_spec_lines"
    return None


def _stock_matches(view: ChangeView, part_id: str, lot_id: str) -> bool:
    index = view.index
    part = index.parts.get(part_id)
    lot = index.stock[lot_id]
    if part is None:
        return False
    part_spec = index.specs.get(part.spec_id)
    lot_spec = index.specs.get(lot.spec_id)
    if part_spec is None or lot_spec is None:
        return False
    attributes = (part_spec.grade, part_spec.thickness_mm, lot_spec.grade, lot_spec.thickness_mm)
    if all(value is not None for value in attributes):
        return (
            part_spec.category == lot_spec.category
            and (view.grade(part_id) or part_spec.grade) == lot_spec.grade
            and (view.thickness(part_id) or part_spec.thickness_mm) == lot_spec.thickness_mm
        )
    return part.spec_id == lot.spec_id


def check_impact(
    index: GraphIndex, request: AnalysisRequest, impact: Impact, view: ChangeView | None = None
) -> EvidenceCheck:
    """출발점, 방향이 있는 지도 연결, 끝점/규칙을 각각 독립 검사한다."""
    view = view or ChangeView(index, request.change)
    targets = {target for planned in view.ops for target in planned.targets()}
    start = impact.path[0].src if impact.path else impact.entity_id
    if impact.impact_type is ImpactType.DELIVERY_DELAY and index.type_of(start) is EntityType.ACTIVITY:
        activity = index.activities[start]
        origin_kind = "exit_milestone" if activity.kind.value == "milestone" else "other_activity"
        origin_ok = origin_kind == "exit_milestone" and any(
            boundary.exit_activity_id == start for boundary in index.snapshot.boundaries
        )
    else:
        origin_kind = "new_part" if start in view.new_parts else "request_part" if start in targets else "other"
        origin_ok = start in targets and view.is_part(start)

    virtual: list[str] = []
    missing: list[str] = []
    for hop in impact.path:
        if hop.dst in index.out(hop.src, hop.relation):
            continue
        kind = _virtual_kind(view, hop.src, hop.dst, hop.relation, hop.rule_id)
        description = f"{hop.src} -{hop.relation.value}-> {hop.dst} [{hop.rule_id}]"
        if kind is None:
            missing.append(description)
        else:
            virtual.append(f"{kind}: {description}")
    continuous = all(a.dst == b.src for a, b in pairwise(impact.path))
    rule_ok = not impact.path or impact.path[-1].rule_id == impact.rule_id
    terminal_ok = (not impact.path or impact.path[-1].dst == impact.entity_id) and rule_ok and continuous
    return EvidenceCheck(impact, origin_kind, origin_ok, not missing, terminal_ok, tuple(virtual), tuple(missing))


@dataclass(frozen=True, slots=True)
class LineEvidence:
    line_id: str
    category: str
    matched: bool
    key: tuple[str, str, str]


def check_cost_line(
    line: CostLine,
    impacts: tuple[Impact, ...],
    index: GraphIndex,
    request: AnalysisRequest,
    view: ChangeView | None = None,
) -> LineEvidence:
    """비용 줄의 종류별 원인 키. 재발주와 발주 변경은 서로 다른 영향으로 확인한다."""
    kind = line.line_id.split(":", 2)[1]
    view = view or ChangeView(index, request.change)
    targets = {target for planned in view.ops for target in planned.targets()}
    effect = kind
    entity = line.entity_id
    category = "영향 직접 대응"
    if line.rule_id == "C-01" and kind == "material":
        category = "직접 계산: 요청 대상 또는 NEW 부재"
        return LineEvidence(line.line_id, category, entity in targets, (line.rule_id, entity, kind))
    if line.rule_id == "C-02" and kind == "new_work":
        category = "직접 계산: 추가 연산의 NEW 부재"
        return LineEvidence(line.line_id, category, entity in view.new_parts, (line.rule_id, entity, kind))
    if line.rule_id == "C-03" and kind == "onboard":
        category = "직접 계산: 선상 설치하는 블록의 새 의장품"
        blocks = {view.block_of(part) for part in targets | set(view.new_parts)}
        return LineEvidence(line.line_id, category, entity in blocks, (line.rule_id, entity, kind))
    if line.rule_id == "C-04" and kind == "after_paint":
        category = "직접 계산: 도장 뒤 재작업 블록(블록 재작업 영향)"
        rework = ImpactType.REWORK
        matched = any(i.rule_id == "R-B01" and i.entity_id == entity and i.impact_type is rework for i in impacts)
        return LineEvidence(line.line_id, category, matched, (line.rule_id, entity, kind))
    if kind == "ld":
        category = "집계: 같은 호선의 인도 지연 영향"
        effect = ImpactType.DELIVERY_DELAY.value
        matched = any(
            impact.rule_id == line.rule_id and impact.impact_type.value == effect and impact.ship_id == entity
            for impact in impacts
        )
        return LineEvidence(line.line_id, category, matched, (line.rule_id, entity, effect))
    if kind in {"stock", "handling"}:
        category = "집계: 재고/품목 전용 영향"
        effect = ImpactType.REALLOCATE_STOCK.value
    key = (line.rule_id, entity, effect)
    matched = any((i.rule_id, i.entity_id, i.impact_type.value) == key for i in impacts)
    return LineEvidence(line.line_id, category, matched, key)
