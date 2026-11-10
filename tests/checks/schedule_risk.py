"""일정 위험(docs/engine.md(비용·일정) 6-6): 새 자재 리드타임을 분류별 범위 끝으로 잡은 확정일 일정.

배율·올림 · 개발 설계변경 200건(위험 ≥ 대표, 대표 계산은 그대로) · 배율 1이면 위험 = 대표 ·
위험 일정에서만 인도를 계산하지 못하는 사례(경계 조건을 지운 지도) — 대표 사유·판정에 섞이지 않음.
"""

from __future__ import annotations

from collections import Counter
from fractions import Fraction

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.domain import GraphSnapshot
from ripple.contracts.params import ParamSet
from ripple.contracts.result import AnalysisResult, ScheduleImpact, UnresolvedKind
from ripple.contracts.rulebook import RuleBook
from ripple.engine.analyze import analyze
from ripple.engine.cost.amounts import Params
from ripple.engine.cost.demand import LEAD_GROUP, TRANSPORT_GROUP, lead_days, lead_ratios
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.engine.timing import Evaluator
from ripple.engine.verdict import verdict
from ripple.generator.build import generate
from ripple.generator.io import load_config

EXPECTED_RATIOS = {
    "equipment": Fraction(3, 2),
    "fitting": Fraction(2),
    "pipe": Fraction(3, 2),
    "plate": Fraction(6, 5),
    "section": Fraction(6, 5),
    "valve": Fraction(3),
}
Risky = list[tuple[AnalysisRequest, AnalysisResult]]


def run(c: Checker) -> None:
    generated = generate(load_config())
    index = GraphIndex(generated.snapshot)
    book = load_rulebook(PROJECT_ROOT / "rules" / "propagation.yaml")
    params = load_params(PROJECT_ROOT / "params" / "cost_v1.yaml")
    _ratios(c, params)
    dev = [AnalysisRequest(change=e.change, as_of=e.as_of) for e in generated.ecns if e.split is EcnSplit.DEV]
    risky = _dev(c, index, book, params, dev)
    _unit_ratio(c, index, book, params, risky)
    _risk_only_reason(c, generated.snapshot, book, params, risky)


def _ratios(c: Checker, params: ParamSet) -> None:
    c.section("일정 위험: 배율(범위 끝 ÷ 대표값)과 올림")
    ratios = lead_ratios(Params(params))
    c.check(
        "배율 = 판·형강 1.2 · 배관 1.5 · 밸브 3 · 부속 2 · 장비 1.5(정확한 분수)", ratios == EXPECTED_RATIOS, ratios
    )
    c.check(
        "리드타임 = ⌈일수 × 배율⌉(판 70일 → 84 · 71일 → 86 · 밸브 90일 → 270), 배율 없는 분류·대표 일정은 그대로",
        lead_days(ratios, "plate", 70) == 84
        and lead_days(ratios, "plate", 71) == 86
        and lead_days(ratios, "valve", 90) == 270
        and lead_days(ratios, "unknown", 70) == 70
        and lead_days(None, "plate", 70) == 70,
    )


def _rep_only(schedule: ScheduleImpact) -> ScheduleImpact:
    return schedule.model_copy(update={"risk": None})


def _dev(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, requests: list[AnalysisRequest]) -> Risky:
    c.section("일정 위험: 개발 설계변경 200건(위험 ≥ 대표, 대표 계산은 그대로)")
    counts: Counter[str] = Counter()
    below: list[str] = []
    moved: list[str] = []
    unscaled_same = True
    risky: Risky = []
    for request in requests:
        try:
            result = analyze(index, request, book, params)
        except RequestError:
            counts["rejected"] += 1
            continue
        rep, risk = result.schedule, result.schedule.risk
        if risk is None:
            below.append(f"{request.change.ecn_id}: 위험 없음")
            continue
        by_exit = {z.exit_activity_id: z.delay_days for z in risk.zone_exits}
        ordered = all(by_exit.get(z.exit_activity_id, 0) >= z.delay_days for z in rep.zone_exits)
        ordered &= risk.max_exit_delay_days >= rep.max_exit_delay_days
        if rep.delivery is None:
            ordered &= risk.delivery is None  # 대표가 계산 불가면 위험도(출구는 더 늦을 뿐)
        elif risk.delivery is not None:
            ordered &= risk.delivery.added_delay_days >= rep.delivery.added_delay_days
        if not ordered:
            below.append(request.change.ecn_id)
        # 대표 = 곡선의 확정일 점(대표 평가)과 같은 총액·출구 최대 지연 — 위험 일정이 비용·곡선에 들어가지 않음
        point = next(p for p in result.timing.curve if p.confirm_on == request.effective_confirm_on)
        if point.total != result.total or point.max_exit_delay_days != rep.max_exit_delay_days:
            moved.append(request.change.ecn_id)
        if not risk.ratios:
            counts["unscaled"] += 1
            unscaled_same &= risk.zone_exits == rep.zone_exits and risk.delivery == rep.delivery and not risk.unresolved
        counts["n"] += 1
        counts["more"] += risk.max_exit_delay_days > rep.max_exit_delay_days
        counts["zero"] += rep.max_exit_delay_days == 0 and risk.max_exit_delay_days > 0
        counts["delivery"] += (
            rep.delivery is not None
            and risk.delivery is not None
            and risk.delivery.added_delay_days > rep.delivery.added_delay_days
        )
        if risk.max_exit_delay_days > rep.max_exit_delay_days:
            risky.append((request, result))
    c.check(
        f"{counts['n']}건 모두 위험이 있고 대표보다 이르지 않음(출구별·최대·인도 — 대표가 계산 불가면 위험도 불가)",
        counts["n"] + counts["rejected"] == len(requests) and counts["n"] >= 190 and not below,
        below[:5],
    )
    c.check(
        "총액·출구 최대 지연은 곡선의 확정일 점(대표 평가)과 같음 — 위험이 비용·곡선에 안 들어감", not moved, moved[:5]
    )
    c.check(
        f"늦춘 새 자재가 없는 {counts['unscaled']}건(배율 목록 빈 경우)은 위험 = 대표",
        counts["unscaled"] >= 1 and unscaled_same,
        counts["unscaled"],
    )
    c.check(
        f"위험 > 대표 {counts['more']}건 · 대표 0일·위험만 늦음 {counts['zero']}건 · 인도 위험 {counts['delivery']}건"
        " (화면 합집합 행·빈 상태 검증 재료가 데이터에 있음)",
        counts["more"] >= 1 and counts["zero"] >= 1 and counts["delivery"] >= 1,
        dict(counts),
    )
    return risky


def _flat(params: ParamSet) -> ParamSet:
    """리드타임·외자재 운송 일수 범위 끝을 대표값으로(배율 1, 운송도 대표값 — 1.33.0)."""
    heads = (f"{LEAD_GROUP}.", f"{TRANSPORT_GROUP}.")
    flat = {k: (p.model_copy(update={"high": p.value}) if k.startswith(heads) else p) for k, p in params.params.items()}
    return params.model_copy(update={"params": flat})


def _unit_ratio(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, risky: Risky) -> None:
    c.section("일정 위험: 배율 1(외자재 운송도 범위 끝 = 대표)이면 위험 = 대표(대표 일정은 범위 끝과 상관없음)")
    flat = _flat(params)
    wrong: list[str] = []
    for request, result in risky[:6]:
        again = analyze(index, request, book, flat)
        risk = again.schedule.risk
        if (
            risk is None
            or risk.zone_exits != again.schedule.zone_exits
            or risk.delivery != again.schedule.delivery
            or set(risk.ratios.values()) != {1.0}
            or _rep_only(again.schedule) != _rep_only(result.schedule)
        ):
            wrong.append(request.change.ecn_id)
    c.check(
        f"위험이 컸던 {min(len(risky), 6)}건: 배율 1이면 위험 출구·인도 = 대표, 대표 일정은 그대로", not wrong, wrong
    )


def _risk_only_reason(c: Checker, snapshot: GraphSnapshot, book: RuleBook, params: ParamSet, risky: Risky) -> None:
    c.section("일정 위험: 위험 일정에서만 인도 계산 불가(대표 사유·판정·확인 목록에 섞지 않음)")
    found = next(((q, r) for q, r in risky if not r.schedule.zone_exits and r.schedule.delivery is not None), None)
    if found is None:
        c.check("대표 0일·위험만 늦는 사례가 있어야 만든 입력을 꾸밈", False)
        return
    request, result = found
    assert result.schedule.risk is not None
    exit_id = result.schedule.risk.zone_exits[0].exit_activity_id
    boundaries = tuple(b for b in snapshot.boundaries if b.exit_activity_id != exit_id)
    bare = GraphIndex(snapshot.model_copy(update={"boundaries": boundaries}))  # 그 구역의 경계 조건만 지움
    out = analyze(bare, request, book, params)
    risk = out.schedule.risk
    c.check(
        f"{request.change.ecn_id}·{exit_id} 경계 조건을 지운 지도: 대표는 인도 계산(그 출구가 대표에선 안 늦음),"
        " 위험은 그 출구가 늦어 인도 계산 불가 + 위험 전용 이유",
        risk is not None
        and out.schedule.delivery is not None
        and risk.delivery is None
        and any(u.kind is UnresolvedKind.DELIVERY for u in risk.unresolved)
        and not set(risk.unresolved) & set(out.unresolved),
        None if risk is None else (risk.unresolved, out.unresolved),
    )
    evaluator = Evaluator(bare, request, book, params)
    final = evaluator.evaluate(request.effective_confirm_on, request.holds)
    expected = verdict(
        final.lines,
        final.total,
        final.max_exit_delay,
        final.unresolved,
        evaluator.params,
        erection_delayed=any(a.endswith(":erection") for a in final.schedule.added_days_by_activity),
        risk_exit_delay=risk.max_exit_delay_days if risk else 0,
    )
    c.check(
        "대표 계산 불가 목록·총액은 대표 평가 그대로, 판정은 대표 평가 + 위험 출구 이유 하나만"
        "(확인 목록은 대표 사유로만)",
        out.unresolved == final.unresolved and out.total == final.total and out.verdict == expected,
    )
