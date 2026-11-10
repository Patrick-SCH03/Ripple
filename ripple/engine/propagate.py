"""영향 탐색 엔진(docs/engine.md(전파)): 요청 검증 → 변경 후 보기 → 규칙 → 병합 → 영향 보고.

같은 입력이면 같은 출력이고, 연산 순서를 바꿔도 분석 ID와 계산 결과가 같다.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date

from ripple.contracts.analysis import AnalysisRequest, HoldAction, Versions
from ripple.contracts.base import CONTRACT_VERSION
from ripple.contracts.domain import EntityType, Relation
from ripple.contracts.graphview import GraphEdge, GraphView
from ripple.contracts.identity import analysis_id
from ripple.contracts.result import Hop, Impact, ImpactReport, ImpactType, Unresolved, UnresolvedKind
from ripple.contracts.rulebook import Rule, RuleBook

from . import ENGINE_VERSION
from .describe import describe
from .index import GraphIndex
from .overlay import ChangeView
from .rules import RULES, Finding, RuleContext
from .schedule import Baseline
from .state import StateModel
from .validate import RequestError, validate_request

SYMMETRIC = frozenset(
    {Relation.BUTT_WELD, Relation.FILLET_WELD, Relation.PENETRATION, Relation.SUPPORT, Relation.PIPE_JOINT}
)
LIMITATION_NOTE = "같은 종류 연결 중 일부만 빠진 경우(예: 격자 이웃 하나 누락)는 입력에 완전성 정보가 없어 탐지 불가"
ESTIMATE_NOTE = "확정일이 기준일 뒤라 그날 단계는 기준일까지의 근거와 계획으로 추정"


@dataclass(frozen=True, slots=True)
class Propagation:
    impacts: tuple[Impact, ...]
    unresolved: tuple[Unresolved, ...]
    graph: GraphView  # 그래프를 만들지 않은 실행(곡선의 날마다 평가)이면 노드가 빈 그래프
    pending_rules: tuple[str, ...]
    notes: tuple[str, ...]
    judge_on: date = field(compare=False)
    view: ChangeView = field(compare=False, repr=False)
    state: StateModel = field(compare=False, repr=False)
    findings: tuple[tuple[str, Finding], ...] = field(compare=False, repr=False)  # 병합 전 (규칙 ID, 발견)


def versions_for(
    snapshot_id: str, rulebook: RuleBook, params_version: str, strength_version: str | None = None
) -> Versions:
    """결과에 영향을 준 버전 묶음. 강도 규칙 버전은 대안 포함 분석에서만 넣는다."""
    return Versions(
        contract=CONTRACT_VERSION,
        snapshot_id=snapshot_id,
        rules=rulebook.version,
        params=params_version,
        engine=ENGINE_VERSION,
        strength=strength_version,
    )


def impact_report(index: GraphIndex, request: AnalysisRequest, rulebook: RuleBook, params_version: str) -> ImpactReport:
    versions = versions_for(index.snapshot.snapshot_id, rulebook, params_version)
    result = propagate(index, request, rulebook)
    return ImpactReport(
        analysis_id=analysis_id(versions, request),
        versions=versions,
        request=request,
        data_mode=index.snapshot.data_mode,
        impacts=result.impacts,
        unresolved=result.unresolved,
        graph=result.graph,
        pending_rules=result.pending_rules,
        notes=result.notes,
    )


def propagate(index: GraphIndex, request: AnalysisRequest, rulebook: RuleBook) -> Propagation:
    propagator = Propagator(index, request, rulebook)
    return propagator.run(request.effective_confirm_on, propagator.state(request.holds))


class Propagator:
    """요청 하나를 검증하고 변경 후 보기를 한 번 만든 뒤, 판정일·상태(보류)마다 규칙을 돌린다.

    2단계 확정 시점 계산이 기준일부터 탐색 기간 끝까지 날마다 같은 요청을 다시 평가할 때 쓴다.
    """

    def __init__(self, index: GraphIndex, request: AnalysisRequest, rulebook: RuleBook) -> None:
        problems = validate_request(index, request)
        if problems:
            raise RequestError(problems)
        self.index = index
        self.request = request
        self.rulebook = rulebook
        self.view = ChangeView(index, request.change)
        self.baseline = Baseline(index, request.as_of)  # 공정 시계 = 기준 일정 착수일(docs/engine.md(비용·일정) 1절)
        requested = {op.op for op in request.change.ops}
        self._active = [rule for rule in rulebook.rules if rule.id in RULES and requested & set(rule.ops)]
        self._used = _used_relations(rulebook)

    def state(self, holds: Iterable[HoldAction]) -> StateModel:
        """기준일 근거·보류 묶음·기준 일정 공정 시계로 만든 상태 함수(판정일과 무관하게 재사용)."""
        return StateModel(self.index, self.request.as_of, holds, clock=self.baseline)

    def run(self, judge_on: date, state: StateModel, with_graph: bool = True) -> Propagation:
        request, view = self.request, self.view

        def context(rule: Rule, changed: Mapping[str, tuple[Hop, ...]]) -> RuleContext:
            return RuleContext(
                rule=rule,
                view=view,
                state=state,
                judge_on=judge_on,
                horizon_days=request.horizon_days,
                ships=frozenset(request.change.ship_ids),
                used_relations=self._used,
                changed=changed,
            )

        found: list[tuple[Rule, Finding]] = []
        for rule in (r for r in self._active if not RULES[r.id].late):
            found.extend((rule, f) for f in RULES[rule.id].fn(context(rule, {})))
        for rule in (r for r in self._active if RULES[r.id].late):
            changed = _changed_parts(view, rule, found)
            found.extend((rule, f) for f in RULES[rule.id].fn(context(rule, changed)))
        _check_effects(found)

        impacts = _merge(view, found)
        notes = [LIMITATION_NOTE]
        if judge_on > request.as_of:
            notes.append(ESTIMATE_NOTE)
        graph = (
            impact_graph(view, impacts)
            if with_graph
            else GraphView(snapshot_id=self.index.snapshot.snapshot_id, nodes=(), edges=())
        )
        return Propagation(
            impacts=impacts,
            unresolved=_unresolved(f for _, f in found),
            graph=graph,
            pending_rules=tuple(r.id for r in self.rulebook.rules if r.id not in RULES),
            notes=tuple(notes),
            judge_on=judge_on,
            view=view,
            state=state,
            findings=tuple((rule.id, finding) for rule, finding in found),
        )


def _used_relations(rulebook: RuleBook) -> dict[str, frozenset[Relation]]:
    """연산마다 그 연산을 다루는 1단계 규칙이 대상 부재에서 따라가는 관계(R-X01 검사 범위)."""
    used: dict[str, set[Relation]] = defaultdict(set)
    for rule in rulebook.rules:
        if rule.id in RULES:
            for op_name in rule.ops:
                used[op_name] |= RULES[rule.id].traverses
    return {name: frozenset(relations) for name, relations in used.items()}


def _changed_parts(view: ChangeView, rule: Rule, found: Iterable[tuple[Rule, Finding]]) -> dict[str, tuple[Hop, ...]]:
    """대상 부재(경로 없음) + also_from 영향을 받은 이웃 부재(그 영향의 가장 짧은 경로)."""
    also = {ImpactType(value) for value in rule.settings.get("also_from", ())}
    changed: dict[str, tuple[Hop, ...]] = dict.fromkeys(view.targets(rule.ops), ())
    best: dict[str, tuple[Hop, ...]] = {}
    for _, finding in found:
        part_id = finding.entity_id
        if finding.entity_type is not EntityType.PART or finding.impact_type not in also or part_id in changed:
            continue
        if part_id not in best or _path_order(finding.path) < _path_order(best[part_id]):
            best[part_id] = finding.path
    return changed | best


def _check_effects(found: Iterable[tuple[Rule, Finding]]) -> None:
    for rule, finding in found:
        if finding.impact_type not in rule.effect:
            raise AssertionError(f"{rule.id}가 규칙표에 없는 영향 {finding.impact_type}을 생성")


def _path_order(path: tuple[Hop, ...]) -> tuple[int, tuple[tuple[str, str, str, str], ...]]:
    return len(path), tuple((h.src, h.dst, h.relation.value, h.rule_id) for h in path)


def _merge(view: ChangeView, found: Iterable[tuple[Rule, Finding]]) -> tuple[Impact, ...]:
    """키(엔터티 종류, ID, 규칙, 영향 종류)마다 근거 경로가 가장 짧은 하나만 남기고 키 순으로 정렬."""
    best: dict[tuple[str, str, str, str], tuple[Rule, Finding]] = {}
    for rule, finding in found:
        key = (finding.entity_type.value, finding.entity_id, rule.id, finding.impact_type.value)
        if key not in best or _path_order(finding.path) < _path_order(best[key][1].path):
            best[key] = (rule, finding)
    return tuple(
        Impact(
            entity_type=finding.entity_type,
            entity_id=finding.entity_id,
            ship_id=_ship_of(view, finding),
            impact_type=finding.impact_type,
            severity=rule.severity,
            rule_id=rule.id,
            path=finding.path,
            note=finding.note,
        )
        for _, (rule, finding) in sorted(best.items())
    )


def _ship_of(view: ChangeView, finding: Finding) -> str:
    """엔터티의 호선. 도면·재고 로트처럼 호선이 없으면 근거 경로 출발 부재의 호선."""
    index, entity = view.index, finding.entity_id
    ship: str | None = None
    if finding.entity_type is EntityType.PART:
        ship = view.ship_of(entity)
    elif finding.entity_type is EntityType.BLOCK:
        ship = index.blocks[entity].ship_id
    elif finding.entity_type is EntityType.PO_LINE:
        order = index.orders.get(index.lines[entity].po_id)
        ship = None if order is None else order.ship_id
    return ship or view.ship_of(finding.origin) or view.fallback_ship


def _unresolved(findings: Iterable[Finding]) -> tuple[Unresolved, ...]:
    """같은 (종류, 엔터티)는 하나로 합치고 이유 문장을 잇는다."""
    reasons: dict[tuple[UnresolvedKind, str | None], list[str]] = defaultdict(list)
    for finding in findings:
        item = finding.unresolved
        if item is not None and item.reason not in reasons[(item.kind, item.entity_id)]:
            reasons[(item.kind, item.entity_id)].append(item.reason)
    keys = sorted(reasons, key=lambda k: (k[0].value, k[1] or ""))
    return tuple(
        Unresolved(kind=kind, entity_id=entity, reason=" ".join(reasons[(kind, entity)])) for kind, entity in keys
    )


def impact_graph(view: ChangeView, impacts: tuple[Impact, ...]) -> GraphView:
    """대상 부재와 모든 근거 경로의 노드·연결. 원본 지도에 없는 노드·연결(변경으로 생김)은 점선(virtual).

    연결 방향은 파급 방향(대상 → 영향)이고, 노드 속성 role은 target(바꾸는 부재) · removed(빼는 부재) · new(새 부재).
    """
    edges: dict[tuple[str, str, Relation], tuple[str, str, Relation]] = {}

    def add(src: str, dst: str, relation: Relation) -> None:
        """연결 방향은 파급 방향(먼저 본 근거 경로)을 따른다. 대칭 관계는 한 번만 담는다."""
        key = (min(src, dst), max(src, dst), relation) if relation in SYMMETRIC else (src, dst, relation)
        edges.setdefault(key, (src, dst, relation))

    for impact in sorted(impacts, key=lambda i: len(i.path)):
        for hop in impact.path:
            add(hop.src, hop.dst, hop.relation)
    for edge in view.virtual_edges:
        add(edge.source, edge.target, edge.relation)
    roles = {
        target: "new" if target in view.new_parts else "removed" if target in view.removed else "target"
        for planned in view.ops
        for target in planned.targets()
    }
    ids = set(roles) | {end for a, b, _ in edges.values() for end in (a, b)} | {i.entity_id for i in impacts}
    nodes = []
    for node_id in sorted(ids):
        node = view.new_node(node_id) if node_id in view.new_parts else describe(view.index, node_id)
        if node_id in roles:
            node = node.model_copy(update={"attrs": {**node.attrs, "role": roles[node_id]}})
        nodes.append(node)
    return GraphView(
        snapshot_id=view.index.snapshot.snapshot_id,
        nodes=tuple(nodes),
        edges=tuple(
            GraphEdge(source=a, target=b, relation=r, virtual=not _original(view, a, b, r))
            for a, b, r in sorted(edges.values(), key=lambda e: (e[0], e[1], e[2].value))
        ),
    )


def _original(view: ChangeView, src: str, dst: str, relation: Relation) -> bool:
    return dst in view.index.out(src, relation)


__all__ = ["Propagation", "Propagator", "RequestError", "impact_graph", "impact_report", "propagate", "versions_for"]
