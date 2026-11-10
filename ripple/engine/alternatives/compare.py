"""대안 평가·최적 조합·권고(docs/engine.md(대안) 4절).

대안마다 요청과 같은 평가기로 확정일 평가·곡선·마감일을 내고, 충족 대안은 (확정일 × 보류 집합) 중 대표값 총액이
가장 작은 조합을 고른다. 확정일은 요청의 확정일(확정 가능일)부터 탐색 기간 끝까지이고, 보류 집합은
{요청의 보류, 요청의 보류 ∪ 그 대안의 보류 권고}다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ripple.contracts.analysis import AnalysisRequest, HoldAction
from ripple.contracts.change import AddPart, ChangeOp
from ripple.contracts.params import ParamSet
from ripple.contracts.result import (
    REQUEST_ALT,
    AlternativeOrigin,
    AlternativeResult,
    Amount,
    CheapestSpan,
    CurvePoint,
    Eligibility,
    EligibilityCheck,
    HoldAdvice,
    Recommendation,
    ZeroLossDeadline,
    expected_deadline,
)
from ripple.contracts.rulebook import RuleBook
from ripple.contracts.strength import StrengthRules

from ..index import GraphIndex
from ..propagate import RequestError
from ..timing import Evaluation, Evaluator, merge_impacts
from .strength import judge
from .templates import Draft, Plan, plan

CRITERION = "판 강도 여유가 요청안 이상(예비 비교)"
REQUEST_CRITERION = "요청안(비교 기준)"
BASIS = (
    "판 요구 두께 t ∝ s·√(h·k) + t_c 형태로 요청안 대비 상대 비교"
    "(재료 계수 k: IACS UR S4, 강종 항복 강도: IACS UR W11), 선급 판정 아님"
)
LIMIT_NOTE = "대안 판정은 요청안 대비 예비 비교 · 선급 판정 아님 — 좌굴·선체 거더 강도·피로 미검토"
NEW_WORK_NOTE = "새 부재 제작 공수는 비용에만 반영 · 공정 기간 미반영"


@dataclass(frozen=True, slots=True)
class Baseline:
    """요청안 평가(analyze가 이미 만든 것을 다시 쓴다)."""

    evaluator: Evaluator
    points: tuple[CurvePoint, ...]
    evaluations: dict[date, Evaluation]
    final: Evaluation
    advice: tuple[HoldAdvice, ...]


@dataclass(frozen=True, slots=True)
class Best:
    confirm_on: date
    total: Amount
    holds: tuple[HoldAction, ...]


@dataclass(frozen=True, slots=True)
class Scored:
    alt_id: str
    label: str
    origin: AlternativeOrigin
    ops: tuple[ChangeOp, ...]
    scope_reduced: bool
    eligibility: EligibilityCheck
    total: Amount
    max_exit_delay_days: int
    impacted_count: int
    deadline: ZeroLossDeadline
    best: Best | None
    points: tuple[CurvePoint, ...]  # 요청의 보류로 본 곡선


@dataclass(frozen=True, slots=True)
class Comparison:
    alternatives: tuple[AlternativeResult, ...]
    recommendation: Recommendation
    cheapest_by_date: tuple[CheapestSpan, ...]
    notes: tuple[str, ...]


def compare(
    index: GraphIndex,
    request: AnalysisRequest,
    rulebook: RuleBook,
    params: ParamSet,
    strength: StrengthRules,
    baseline: Baseline,
) -> Comparison:
    found = plan(index, request.change, strength, params)
    scored = [_request(request, found, baseline)]
    notes = list(found.notes)
    for draft in found.drafts:
        eligibility = _eligibility(found, draft)
        alt_request = request.model_copy(
            update={"change": request.change.model_copy(update={"ops": draft.ops}), "include_alternatives": False}
        )
        try:
            evaluator = Evaluator(index, alt_request, rulebook, params)
        except RequestError as error:
            notes.append(f"{draft.label}: 지도와 맞지 않아 제외({'; '.join(error.problems)})")
            continue
        scored.append(_draft(draft, eligibility, alt_request, evaluator))
        notes.extend(draft.notes)
    kept = [s for s in scored if s.origin is not AlternativeOrigin.REQUEST]
    if kept:
        notes.append(LIMIT_NOTE)
    if any(isinstance(op, AddPart) for s in kept for op in s.ops):
        notes.append(NEW_WORK_NOTE)
    meets = sorted(
        (s for s in scored if s.best is not None),
        key=lambda s: (
            s.best.total.value if s.best else 0,
            s.origin is not AlternativeOrigin.REQUEST,
            len(s.best.holds) if s.best else 0,
            s.best.confirm_on if s.best else date.min,
            s.alt_id,
        ),
    )
    ranks = {s.alt_id: i for i, s in enumerate(meets, 1)}
    results = tuple(_result(s, ranks.get(s.alt_id)) for s in scored)
    top = meets[0]
    assert top.best is not None
    recommendation = Recommendation(
        alt_id=top.alt_id, confirm_on=top.best.confirm_on, holds=top.best.holds, total=top.best.total
    )
    return Comparison(results, recommendation, _cheapest(meets), tuple(dict.fromkeys(notes)))


def _cheapest(meets: list[Scored]) -> tuple[CheapestSpan, ...]:
    """날짜마다 충족 대안 중 곡선 대표값이 가장 작은 것(같으면 요청안 먼저, 그다음 대안 ID), 이어지는 날을 묶음."""
    spans: list[CheapestSpan] = []
    for day_points in zip(*(s.points for s in meets), strict=True):
        point, scored = min(
            zip(day_points, meets, strict=True),
            key=lambda pair: (
                pair[0].total.value,
                pair[1].origin is not AlternativeOrigin.REQUEST,
                pair[1].alt_id,
            ),
        )
        if spans and spans[-1].alt_id == scored.alt_id:
            spans[-1] = spans[-1].model_copy(update={"end": point.confirm_on})
        else:
            spans.append(
                CheapestSpan(alt_id=scored.alt_id, start=point.confirm_on, end=point.confirm_on, total=point.total)
            )
    return tuple(spans)


def _eligibility(found: Plan, draft: Draft) -> EligibilityCheck:
    designer = found.designer_note or draft.designer_note
    if designer or draft.gains is None or not found.required:
        return EligibilityCheck(
            status=Eligibility.DESIGNER, criterion=CRITERION, basis=BASIS, note=designer or "설계자 확인 필요"
        )
    judged = judge(found.required, draft.gains)
    return EligibilityCheck(
        status=judged.status,
        criterion=CRITERION,
        basis=BASIS,
        ratio_vs_request=round(judged.ratio, 3),
        note=judged.note,
    )


def _request(request: AnalysisRequest, found: Plan, baseline: Baseline) -> Scored:
    final = baseline.final
    return Scored(
        alt_id=REQUEST_ALT,
        label=found.request_label,
        origin=AlternativeOrigin.REQUEST,
        ops=request.change.ops,
        scope_reduced=False,
        eligibility=EligibilityCheck(
            status=Eligibility.MEETS, criterion=REQUEST_CRITERION, ratio_vs_request=1.0, note="비교 기준"
        ),
        total=final.total,
        max_exit_delay_days=final.max_exit_delay,
        impacted_count=len(merge_impacts(final.impacts)),
        deadline=expected_deadline(baseline.points),
        best=_best(baseline.evaluator, request, baseline.points, baseline.advice),
        points=baseline.points,
    )


def _draft(draft: Draft, eligibility: EligibilityCheck, request: AnalysisRequest, evaluator: Evaluator) -> Scored:
    points, evaluations = evaluator.curve(request.holds)
    confirm_on = request.effective_confirm_on
    final = evaluations.get(confirm_on) or evaluator.evaluate(confirm_on, request.holds)
    best = None
    if eligibility.status is Eligibility.MEETS:
        advice = evaluator.hold_advice({day: ev.total for day, ev in evaluations.items()})
        best = _best(evaluator, request, points, advice)
    return Scored(
        alt_id=draft.alt_id,
        label=draft.label,
        origin=AlternativeOrigin.TEMPLATE,
        ops=draft.ops,
        scope_reduced=draft.scope_reduced,
        eligibility=eligibility,
        total=final.total,
        max_exit_delay_days=final.max_exit_delay,
        impacted_count=len(merge_impacts(final.impacts)),
        deadline=expected_deadline(points),
        best=best,
        points=points,
    )


def _best(
    evaluator: Evaluator,
    request: AnalysisRequest,
    points: tuple[CurvePoint, ...],
    advice: tuple[HoldAdvice, ...],
) -> Best:
    """확정 가능일(요청의 확정일)부터 탐색 기간 끝까지의 날 × 보류 집합 중 대표값 총액 최소.

    같으면 이른 확정일, 그다음 보류가 적은 쪽. 확정일이 탐색 기간 밖이면 그날 하루만 본다.
    """
    holds, earliest = request.holds, request.effective_confirm_on
    options: list[tuple[tuple[HoldAction, ...], tuple[CurvePoint, ...]]] = [(holds, points)]
    if advice:
        advised = (*holds, *(HoldAction(po_id=a.po_id, hold_days=a.max_hold_days) for a in advice))
        extra = tuple(sorted(advised, key=lambda h: h.po_id))
        options.append((extra, evaluator.curve(extra)[0]))
    candidates: list[tuple[tuple[HoldAction, ...], date, Amount]] = []
    for held, pts in options:
        days = [(held, p.confirm_on, p.total) for p in pts if p.confirm_on >= earliest]
        candidates += days or [(held, earliest, evaluator.evaluate(earliest, held).total)]
    chosen, day, total = min(candidates, key=lambda c: (c[2].value, c[1], len(c[0])))
    return Best(confirm_on=day, total=total, holds=tuple(sorted(chosen, key=lambda h: h.po_id)))


def _result(s: Scored, rank: int | None) -> AlternativeResult:
    best = s.best
    return AlternativeResult(
        alt_id=s.alt_id,
        label=s.label,
        origin=s.origin,
        ops=s.ops,
        scope_reduced=s.scope_reduced,
        eligibility=s.eligibility,
        total=s.total,
        max_exit_delay_days=s.max_exit_delay_days,
        impacted_count=s.impacted_count,
        deadline=s.deadline,
        best_confirm_on=best.confirm_on if best else None,
        best_total=best.total if best else None,
        best_holds=best.holds if best else (),
        rank=rank,
    )
