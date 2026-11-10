"""분석(docs/engine.md(비용·일정)): 요청 → 확정일 평가 + 일정 위험 + 추가손실 곡선 + 보류 권고 + 요약 판정
+ 후행 설치(선상 설치) 선택지(6-8) + 지연 파급 비용(4-11, 총액 밖) + 블록별 강재 중량 변화(12절, 정보) → AnalysisResult.

대안을 켜면(include_alternatives) 강도형 요청의 템플릿 대안·판정·최적 조합·권고를 붙인다(docs/engine.md(대안)).
설계변경 사전 점검(docs/engine.md(사전 점검))은 결과를 다 만든 뒤 붙인다 — 판정·총액·결정 기한을 바꾸지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping

from ripple.contracts.analysis import AnalysisRequest, Versions
from ripple.contracts.domain import ActivityKind
from ripple.contracts.identity import analysis_id
from ripple.contracts.params import ParamSet
from ripple.contracts.result import (
    AnalysisResult,
    CurvePoint,
    HoldAdvice,
    ScheduleImpact,
    TimingResult,
    Verdict,
    expected_deadline,
)
from ripple.contracts.rulebook import RuleBook
from ripple.contracts.strength import StrengthRules

from .alternatives import Baseline, Comparison, compare
from .basis import state_basis
from .cost.split import cost_split
from .delay import delay_ripple
from .index import GraphIndex
from .outlook import with_outlooks
from .precheck import with_prechecks
from .propagate import impact_graph, versions_for
from .rules import RULES
from .timing import ANALYSIS_RULES, Evaluation, Evaluator, merge_impacts
from .trace import trace_chains
from .verdict import verdict
from .weight import weight_change

SCHEDULE_NOTE = (
    "일정은 파라미터 대표값 기준 · 새 자재가 리드타임 범위 끝에 오는 경우는 일정 위험으로 별도 표시 · "
    "진수·인도는 구역 경계 조건(여유)으로 계산 · "
    "인력·정반·크레인 등 자원 제약과 납기 변동 미반영"
)
COST_NOTE = (
    "일정 지연 자체의 간접비(작업반 대기·재배치)는 총변경비용 제외 — 지연 파급 비용(가정)으로 별도 표시 · "
    "공정 여유로 흡수되는 지연은 빼고 구역 출구가 실제로 밀리는 날만 산입 · 인도 지연으로 지체상금에 넣은 날도 제외"
)


def _effectivity_notes(request: AnalysisRequest) -> tuple[str, ...]:
    """적용 시작일(정보, 계약 1.23.0)이 확정일보다 앞서면 알린다 — 확정 전에는 생산에 반영할 수 없다. 계산은 그대로."""
    effectivity = request.change.effectivity
    start = effectivity.effective_on if effectivity else None
    confirm_on = request.effective_confirm_on
    if start is None or start >= confirm_on:
        return ()
    return (f"적용 시작일({start.isoformat()})이 확정일({confirm_on.isoformat()})보다 앞섬 — 날짜 확인 필요",)


def _verdict(
    index: GraphIndex, request: AnalysisRequest, evaluator: Evaluator, final: Evaluation, schedule: ScheduleImpact
) -> Verdict:
    """요약 판정(docs/engine.md(비용·일정) 8-4): 확정일 평가만 쓴다(곡선의 다른 날은 쓰지 않는다)."""
    delivery = schedule.delivery
    return verdict(
        final.lines,
        final.total,
        final.max_exit_delay,
        final.unresolved,
        evaluator.params,
        erection_delayed=any(
            index.activities[a].kind is ActivityKind.ERECTION for a in final.schedule.added_days_by_activity
        ),
        design_pending=request.change.design_status.pending,
        risk_exit_delay=schedule.risk.max_exit_delay_days if schedule.risk else 0,
        permissible_delay=delivery is not None and delivery.permissible and delivery.added_delay_days > 0,
    )


def analysis_versions(
    snapshot_id: str, request: AnalysisRequest, rulebook: RuleBook, params: ParamSet, strength: StrengthRules | None
) -> Versions:
    """이 요청을 지금 분석하면 결과에 붙는 버전 묶음(분석 ID의 판). 강도 규칙 버전은 대안 포함 분석에서만.

    기록의 판 대조(ripple/api/records.py)도 이 함수를 쓴다: 지도를 뺀 판이 다르면 다시 계산한 분석 ID가 기록과 달라진다.
    """
    strength_version = strength.version if request.include_alternatives and strength is not None else None
    return versions_for(snapshot_id, rulebook, params.version, strength_version)


def analyze(
    index: GraphIndex,
    request: AnalysisRequest,
    rulebook: RuleBook,
    params: ParamSet,
    strength: StrengthRules | None = None,
    *,
    ncr_counts: Mapping[str, int] | None = None,
    prechecks: bool = True,
) -> AnalysisResult:
    """ncr_counts = 같은 유형 합성 NCR 건수(규칙 ID → 건수, 합성 데이터 결과에만 실림). prechecks=False면 사전 점검을
    붙이지 않는다(사전 점검이 다른 필드를 바꾸지 않는지 보는 검사용)."""
    result = _analyze(index, request, rulebook, params, strength)
    return with_prechecks(index, request, result, ncr_counts) if prechecks else result


def _analyze(
    index: GraphIndex,
    request: AnalysisRequest,
    rulebook: RuleBook,
    params: ParamSet,
    strength: StrengthRules | None,
) -> AnalysisResult:
    if request.include_alternatives and strength is None:
        raise ValueError("대안 판정에 강도 규칙(rules/strength.yaml) 필요")
    evaluator = Evaluator(index, request, rulebook, params)
    points, evaluations = evaluator.curve(request.holds)
    confirm_on = request.effective_confirm_on
    final: Evaluation = evaluations.get(confirm_on) or evaluator.evaluate(confirm_on, request.holds)
    # 일정 위험은 확정일 일정에만 붙인다(대표 일정 검증과 함께 — 위험 출구 ⊇ 대표 출구)
    schedule = ScheduleImpact.model_validate(
        {**final.schedule.model_dump(), "risk": evaluator.risk(confirm_on, request.holds, final)}
    )
    totals = {day: ev.total for day, ev in evaluations.items()}
    advice = evaluator.hold_advice(totals)
    impacts = merge_impacts((*final.impacts, *evaluator.hold_impacts(advice)))
    alternatives = None
    if request.include_alternatives and strength is not None:
        alternatives = compare(
            index, request, rulebook, params, strength, Baseline(evaluator, points, evaluations, final, advice)
        )
    versions = analysis_versions(index.snapshot.snapshot_id, request, rulebook, params, strength)
    return AnalysisResult(
        analysis_id=analysis_id(versions, request),
        versions=versions,
        request=request,
        data_mode=index.snapshot.data_mode,
        impacts=impacts,
        cost_lines=with_outlooks(final.lines, confirm_on, {day: ev.lines for day, ev in evaluations.items()}),
        total=final.total,
        schedule=schedule,
        timing=_timing(points, advice, final),
        alternatives=alternatives.alternatives if alternatives else (),
        recommendation=alternatives.recommendation if alternatives else None,
        cheapest_by_date=alternatives.cheapest_by_date if alternatives else (),
        unresolved=final.unresolved,
        graph=impact_graph(evaluator.propagator.view, impacts),
        verdict=_verdict(index, request, evaluator, final, schedule),
        pending_rules=tuple(r.id for r in rulebook.rules if r.id not in RULES and r.id not in ANALYSIS_RULES),
        notes=_notes(request, final, alternatives),
        # 판단이 걸린 상태: 기준일·보류 없는 바탕 상태로만(확정일·보류 시나리오의 미래 상태는 넣지 않음)
        state_basis=state_basis(evaluator.propagator.state(()), final.lines, impacts, final.unresolved, advice),
        trace=trace_chains(evaluator.propagator.view, evaluator.propagator.state(()), impacts, final.lines),
        onboard=evaluator.onboard_option(confirm_on, request.holds, final),
        # 지연 파급 비용(4-11): 확정일 대표 일정에서 따로 계산하고 총액·판정·곡선·대안에는 넣지 않는다
        delay_ripple=delay_ripple(schedule, evaluator.params),
        # 블록별 강재 중량 변화(12절, 정보): 4-0의 바뀌는 규격(평가기가 이미 계산한 값)을 그대로 쓴다
        weight_change=weight_change(index, evaluator.propagator.view, evaluator.changes, evaluator.params),
        # 구분별 합(4-12): 확정일 비용 줄의 구분·공수를 더할 뿐 — 공수 + 재료비 + 지체상금 = 총액
        cost_split=cost_split(final.lines),
    )


def _timing(points: tuple[CurvePoint, ...], advice: tuple[HoldAdvice, ...], final: Evaluation) -> TimingResult:
    """확정 시점(8절): 기준일 총액·곡선·추가손실 0 마감일·보류 권고·확정일의 잉여 자재 전용."""
    return TimingResult(
        base_cost=points[0].total,
        curve=points,
        deadline=expected_deadline(points),
        holds=advice,
        reallocations=final.reallocations,
    )


def _notes(request: AnalysisRequest, final: Evaluation, alternatives: Comparison | None) -> tuple[str, ...]:
    """전파·비용 메모, 일정·비용 한계, 적용 시작일, 대안 메모 순(겹치면 처음 것만)."""
    notes = (
        *final.propagation.notes,
        *final.notes,
        SCHEDULE_NOTE,
        COST_NOTE,
        *_effectivity_notes(request),
        *(alternatives.notes if alternatives else ()),
    )
    return tuple(dict.fromkeys(notes))
