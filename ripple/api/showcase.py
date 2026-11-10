"""소개 화면 예시(web/src/pages/landing/example.json).

시연 합성 지도(generator/demo_map.yaml — 공개 시연 배포와 같은 지도)의 데모 설계변경 하나를 엔진으로 분석한 값만 담는다.

소개 화면의 숫자·이름이 엔진 결과와 어긋나지 않게 scripts/export_showcase.py가 이 함수로 파일을 만들고,
검사(tests/checks/showcase.py)는 다시 만들어 저장된 파일과 같은지 본다. 화면 문구는 화면이 짓고 여기는 값만 둔다.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.domain import EntityType
from ripple.contracts.result import AnalysisResult, CostLine, ImpactType, Severity
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.graph.files import load_snapshot
from ripple.records.recorded import curve_point, delay_cost

from .deps import AppContext
from .samples import Sample, pick_samples, read_ecns

SHOWCASE_ECN = "ECN-D-0119"  # README '실제 예시'와 같은 사례
SHOWCASE_PATH = Path("web/src/pages/landing/example.json")
GROUPED = (ImpactType.TAPER, ImpactType.WELD_RECHECK)  # 부재가 많아 종류로 묶는 영향
SEVERITY_ORDER = (Severity.LOW, Severity.MEDIUM, Severity.HIGH)


@dataclass
class _Node:
    key: str
    parent: str | None
    relation: str
    entity_type: EntityType
    impacts: set[ImpactType] = field(default_factory=set)
    rules: set[str] = field(default_factory=set)
    entities: list[str] = field(default_factory=list)
    severity: Severity = Severity.LOW


def render_showcase(showcase: dict[str, Any]) -> str:
    """저장 형식: 들여쓰기 2칸, 한글 그대로, 끝 줄바꿈."""
    return json.dumps(showcase, ensure_ascii=False, indent=2) + "\n"


@dataclass(frozen=True)
class ShowcaseAnalysis:
    index: GraphIndex
    sample: Sample
    result: AnalysisResult


def analyze_showcase(context: AppContext) -> ShowcaseAnalysis:
    """context의 지도에서 예시 사례(SHOWCASE_ECN)를 기준일에 확정한 분석. 검사도 같은 분석으로 값을 대조한다."""
    settings = context.settings
    index = GraphIndex(load_snapshot(settings.snapshot_path, settings.data_mode))
    samples = pick_samples(index, read_ecns(settings.snapshot_path.parent / "ecn_dev.jsonl"), context.rulebook)
    sample = next(s for s in samples if s.ecn_id == SHOWCASE_ECN)
    result = analyze(index, sample.request, context.rulebook, context.params, context.strength)
    return ShowcaseAnalysis(index, sample, result)


def build_showcase(context: AppContext) -> dict[str, Any]:
    """context의 지도(시연 합성 지도 설정으로 만든 합성 지도)에서 예시 사례를 분석해 값만 뽑는다."""
    found = analyze_showcase(context)
    index, sample, result = found.index, found.sample, found.result
    return {
        "source": f"합성 지도 {index.snapshot.snapshot_id} · 샘플 {SHOWCASE_ECN}을 기준일에 확정한 분석"
        "(scripts/export_showcase.py)",
        "ecn_id": SHOWCASE_ECN,
        "title": sample.title,
        "as_of": sample.request.as_of.isoformat(),
        "change": _change(index, sample.request, result),
        "verdict": {"level": result.verdict.level.value, "reasons": list(result.verdict.reasons)},
        "total": result.total.model_dump(mode="json"),
        "deadline": _deadline(result),
        # 업무 화면 영향 범위 머리('영향 n건')와 같은 수 — 공정 일정 영향(탑재 지연 등)까지 센다. 그림 카드는 비용이
        # 번지는 길만 그리므로 카드 수 ≤ 이 수(검사)
        "impact_count": len(result.impacts),
        "cost_line_count": len(result.cost_lines),
        "zone_exit": _zone_exit(result),
        # 결정 기한에 확정할 때 구역 출구 예상 최대 지연(곡선 값) — 결정 기한 카드 '늦출수록 출구 지연
        # 늘어남(기준일 n일 → 결정 기한 확정 시 m일)'의 m
        "deadline_exit_days": _deadline_exit(result),
        # 결정 기한 다음 날 확정하면 생기는 추가손실(곡선 대표값) — 결재함 '미루면 ○월 ○일부터 +x'·결정 기한
        # 카드 '다음 날부터 x 늘어남'과 같은 값(records.recorded.delay_cost). step_up은 그 가운데 가장 크게
        # 바뀌는 비용 줄 하나(이유)
        "delay": _delay(result),
        "step_up": _step_up(result),
        "horizon_end": result.timing.curve[-1].confirm_on.isoformat() if result.timing.curve else None,
        "nodes": _nodes(index, result),
    }


def _change(index: GraphIndex, request: AnalysisRequest, result: AnalysisResult) -> dict[str, Any]:
    """바뀌는 부재와 그 부재 자체의 비용 줄(자재비 차이 등) 합계."""
    op = request.change.ops[0]
    part_ids = tuple(getattr(op, "part_ids", ()))
    blocks = sorted({index.parts[p].block_id for p in part_ids})
    block = index.blocks[blocks[0]]
    return {
        "op": op.op,
        "block": block.block_id.split(":")[-1],
        "block_name": block.name,
        "part_count": len(part_ids),
        "from_mm": getattr(op, "from_mm", None),
        "to_mm": getattr(op, "to_mm", None),
        "amount": sum(li.amount.value for li in result.cost_lines if li.entity_id in part_ids),
    }


def _deadline(result: AnalysisResult) -> str | None:
    last_day = result.timing.deadline.last_day
    return None if last_day is None else last_day.isoformat()


def _zone_exit(result: AnalysisResult) -> dict[str, Any] | None:
    exits = sorted(result.schedule.zone_exits, key=lambda z: -z.delay_days)
    if not exits or exits[0].delay_days == 0:
        return None
    return {"name": exits[0].zone_name, "delay_days": exits[0].delay_days}


def _deadline_exit(result: AnalysisResult) -> int | None:
    point = curve_point(result.timing.curve, result.timing.deadline.last_day)
    return None if point is None else point.max_exit_delay_days


def _delay(result: AnalysisResult) -> dict[str, Any] | None:
    late = delay_cost(result)
    return None if late is None else {"on": late[1].isoformat(), "loss": late[0]}


def _step_up(result: AnalysisResult) -> dict[str, Any] | None:
    """마감일 다음 날 금액이 처음 바뀌는 비용 줄(가장 큰 것)."""
    changing = [line for line in result.cost_lines if line.outlook and line.outlook.amount and line.outlook.on]
    if not changing:
        return None
    first = min(line.outlook.on for line in changing if line.outlook and line.outlook.on)
    line = max(
        (li for li in changing if li.outlook and li.outlook.on == first),
        key=lambda li: (li.outlook.amount.value if li.outlook and li.outlook.amount else 0) - li.amount.value,
    )
    assert line.outlook is not None and line.outlook.amount is not None and line.outlook.on is not None
    return {
        "on": line.outlook.on.isoformat(),
        "entity_id": line.entity_id,
        "before": line.amount.value,
        "after": line.outlook.amount.value,
        "note": line.outlook.note,
    }


def _nodes(index: GraphIndex, result: AnalysisResult) -> list[dict[str, Any]]:
    """영향을 그림 카드로: 테이퍼·용접 재검토는 종류로 묶고 나머지는 엔터티마다.

    두 번째 고리(경로가 두 단계 이상)는 거쳐 온 엔터티의 카드를 부모로 둔다. 공정(일정 지연) 영향은 카드로 그리지
    않는다 — 그림은 비용이 번지는 길이고, 일정은 판정·추가손실 0 마감일 줄로 보인다."""
    nodes: dict[str, _Node] = {}
    member: dict[str, str] = {}  # 엔터티 → 카드 키
    for impact in sorted(result.impacts, key=lambda i: (len(i.path), i.entity_id)):
        if impact.entity_type is EntityType.ACTIVITY:
            continue
        key = impact.impact_type.value if impact.impact_type in GROUPED else impact.entity_id
        parent = member.get(impact.path[-2].dst) if len(impact.path) > 1 else None
        node = nodes.get(key)
        if node is None:
            relation = impact.path[0].relation.value if impact.path else ""
            node = nodes[key] = _Node(key=key, parent=parent, relation=relation, entity_type=impact.entity_type)
        node.impacts.add(impact.impact_type)
        node.rules.add(impact.rule_id)
        if impact.entity_id not in node.entities:
            node.entities.append(impact.entity_id)
        node.severity = max(node.severity, impact.severity, key=SEVERITY_ORDER.index)
        member.setdefault(impact.entity_id, key)
    return [_node_json(index, node, result.cost_lines) for node in nodes.values()]


def _node_json(index: GraphIndex, node: _Node, lines: tuple[CostLine, ...]) -> dict[str, Any]:
    mine = [li for li in lines if li.entity_id in node.entities and li.rule_id in node.rules]
    body: dict[str, Any] = {
        "key": node.key,
        "parent": node.parent,
        "relation": node.relation,
        "entity_type": node.entity_type.value,
        "impacts": sorted(i.value for i in node.impacts),
        "severity": node.severity.value,
        "count": len(node.entities),
        "amount": sum(li.amount.value for li in mine),
    }
    if node.entity_type is EntityType.PART:
        body["kinds"] = dict(sorted(Counter(index.parts[p].kind.value for p in node.entities).items()))
    elif node.entity_type is EntityType.BLOCK:
        block = index.blocks[node.entities[0]]
        body["name"] = block.block_id.split(":")[-1]
        body["full_name"] = block.name
        body["stage"] = next((li.inputs.get("stage") for li in mine if "stage" in li.inputs), None)
    elif node.entity_type is EntityType.PO_LINE:
        line = index.lines[node.entities[0]]
        body["name"] = line.line_id.replace("#", " #")
        body["stage"] = next((li.inputs.get("stage") for li in mine if "stage" in li.inputs), None)
    elif node.entity_type is EntityType.DRAWING:
        body["name"] = node.entities[0].split("@")[0]
    return body
