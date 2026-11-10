"""평가 보고서의 근거 경로와 비용 줄 대응에 대한 결함 주입 검사."""

from __future__ import annotations

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import Settings
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.domain import Relation
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import impact_report
from ripple.eval.evidence_metrics import check_cost_line, check_impact
from ripple.generator.build import generate
from ripple.generator.io import load_config
from scripts.eval_report import _required_ids
from scripts.gate_cases import STAGES, _load_cases


def run(c: Checker) -> None:
    c.section("평가 보고서: 의미상 근거와 비용 대응")
    settings = Settings.from_env({})
    rulebook = load_rulebook(settings.rules_path)
    params = load_params(settings.params_path)
    case = _load_cases(STAGES[1], False)[0]
    index = GraphIndex(generate(load_config(), case.snapshot.generator_seed).snapshot)
    request = AnalysisRequest.model_validate(case.request)
    report = impact_report(index, request, rulebook, params.version)
    normal = [check_impact(index, request, impact) for impact in report.impacts]
    c.check("E1 정상 영향의 근거 완전성을 계산", bool(normal) and all(item.complete for item in normal))

    impacted = next(impact for impact in report.impacts if impact.path and impact.rule_id != "R-M01")
    first = impacted.path[0]
    wrong_relation = first.model_copy(update={"relation": Relation.SAME_SPEC})
    wrong_hop = impacted.model_copy(update={"path": (wrong_relation, *impacted.path[1:])})
    invalid = check_impact(index, request, wrong_hop)
    c.check("실재 노드 사이의 지도에 없는 관계를 검출", not invalid.links_ok and not invalid.complete)

    other = next(
        part_id for part_id in index.parts if part_id not in {first.src, *index.out(first.src, first.relation)}
    )
    wrong_start = first.model_copy(update={"src": other})
    wrong_origin = impacted.model_copy(update={"path": (wrong_start, *impacted.path[1:])})
    checked = check_impact(index, request, wrong_origin)
    c.check("요청 밖 부재에서 출발한 경로를 검출", not checked.origin_ok and not checked.complete)

    config = load_config()
    generated = generate(config)
    for number in (1, 2):
        stored = _load_cases(STAGES[number], False)
        built = {
            item.case_id: item
            for item in STAGES[number].build(generated.snapshot, generated.seed, config.scenario_date)
        }
        c.check(
            f"보고서 {number}단계 필수 사례 = 저장된 관문 사례 파일(건수를 코드에 두지 않음)",
            _required_ids(number, stored, built) == sorted(case.case_id for case in stored),
        )
        try:
            _required_ids(number, stored[1:], built)
            dropped = False
        except ValueError as error:
            dropped = stored[0].case_id in str(error)
        c.check(f"보고서 {number}단계 사례 파일이 하나 빠지면 그 ID를 대며 멈춤", dropped)

    cost_case = _load_cases(STAGES[2], False)[0]
    cost_index = GraphIndex(generate(load_config(), cost_case.snapshot.generator_seed).snapshot)
    cost_request = AnalysisRequest.model_validate(cost_case.request)
    result = analyze(cost_index, cost_request, rulebook, params)
    reorder = next(line for line in result.cost_lines if ":reorder:" in line.line_id)
    po_change = next(
        line for line in result.cost_lines if ":po_change:" in line.line_id and line.entity_id == reorder.entity_id
    )
    intact_reorder = check_cost_line(reorder, result.impacts, cost_index, cost_request)
    intact_change = check_cost_line(po_change, result.impacts, cost_index, cost_request)
    without_reorder = tuple(
        impact
        for impact in result.impacts
        if (impact.rule_id, impact.entity_id, impact.impact_type.value)
        != (reorder.rule_id, reorder.entity_id, "reorder")
    )
    c.check("정상 재발주·변경 줄을 각각 대응", intact_reorder.matched and intact_change.matched)
    c.check(
        "reorder 영향만 빼면 재발주 줄만 근거 없음",
        not check_cost_line(reorder, without_reorder, cost_index, cost_request).matched
        and check_cost_line(po_change, without_reorder, cost_index, cost_request).matched,
    )
    without_change = tuple(
        impact
        for impact in result.impacts
        if (impact.rule_id, impact.entity_id, impact.impact_type.value)
        != (po_change.rule_id, po_change.entity_id, "po_change")
    )
    c.check(
        "po_change 영향만 빼면 변경 줄만 근거 없음",
        not check_cost_line(po_change, without_change, cost_index, cost_request).matched
        and check_cost_line(reorder, without_change, cost_index, cost_request).matched,
    )
