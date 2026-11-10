"""대안·강도 사전검사·최적 조합(docs/engine.md(대안)): 규칙, 식 성질, 템플릿 손 계산, 판정, 최적 조합, 왕복, 시간."""

from __future__ import annotations

import math
import time
from collections import Counter
from datetime import date, timedelta
from statistics import fmean, quantiles
from typing import Any

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook, load_strength, read_yaml
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.analysis import AnalysisRequest, HoldAction
from ripple.contracts.change import AddPart, ChangeIntent, ChangeRequest, GradeChange, ThicknessChange
from ripple.contracts.dataset import EcnSplit, GeneratedEcn
from ripple.contracts.domain import PartKind, Relation
from ripple.contracts.params import ParamSet
from ripple.contracts.result import AnalysisResult, Eligibility
from ripple.contracts.rulebook import RuleBook
from ripple.contracts.strength import StrengthRules
from ripple.engine.alternatives import plan
from ripple.engine.alternatives.strength import PlateState, gain, half_up, round3, round_up_half_mm
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.engine.timing import Evaluator
from ripple.engine.validate import validate_request
from ripple.generator.build import generate
from ripple.generator.io import load_config

Context = tuple[GraphIndex, RuleBook, ParamSet, StrengthRules, date]


def run(c: Checker) -> None:
    strength = load_strength(PROJECT_ROOT / "rules" / "strength.yaml")
    _rules(c, strength)
    _formula(c, strength)
    config = load_config()
    generated = generate(config)
    index = GraphIndex(generated.snapshot)
    book = load_rulebook(PROJECT_ROOT / "rules" / "propagation.yaml")
    params = load_params(PROJECT_ROOT / "params" / "cost_v1.yaml")
    ctx: Context = (index, book, params, strength, config.scenario_date)
    cases = [e for e in generated.ecns if e.split is EcnSplit.DEV and _strength_type(index, e.change)]
    results = _analyses(c, ctx, cases)
    _templates(c, ctx, cases)
    _judgements(c, ctx, results)
    _intents(c, ctx, cases)
    _best(c, ctx, results)
    _earliest(c, ctx, cases)
    _spans(c, ctx, results)
    _unchanged(c, ctx, cases[:12])


def _strength_type(index: GraphIndex, change: ChangeRequest) -> bool:
    """docs/engine.md(대안) 1절의 (가)·(나)·(다) 요청(의도와 무관)."""
    if len(change.ops) != 1:
        return False
    op = change.ops[0]
    if isinstance(op, ThicknessChange):
        return op.to_mm > op.from_mm and all(index.parts[p].kind is PartKind.PLATE for p in op.part_ids)
    if isinstance(op, GradeChange):
        return all(index.parts[p].kind is PartKind.PLATE for p in op.part_ids)
    if isinstance(op, AddPart):
        attach = index.parts.get(op.attach_to_part_id or "")
        return op.kind is PartKind.STIFFENER and attach is not None and attach.kind is PartKind.PLATE
    return False


# ---------- 규칙·식 ----------


def _rules(c: Checker, strength: StrengthRules) -> None:
    c.section("대안: 강도 규칙(rules/strength.yaml)")
    c.check(
        "재료 계수: 연강 1.0 · AH32 0.78 · AH36 0.72 · DH36도 0.72(같은 항복 강도) · 모르는 강종은 없음",
        (strength.k("A"), strength.k("AH32"), strength.k("AH36"), strength.k("DH36"), strength.k("XH99"))
        == (1.0, 0.78, 0.72, 0.72, None),
    )
    raw: dict[str, Any] = read_yaml(PROJECT_ROOT / "rules" / "strength.yaml")
    down = {**raw, "upgrade": {**raw["upgrade"], "values": {**raw["upgrade"]["values"], "AH36": "AH32"}}}
    c.check("항복 강도를 낮추는 강종 상향은 거부", c.raises(lambda: StrengthRules.model_validate(down)))
    flat = {**raw, "material_factor": {**raw["material_factor"], "values": {235: 1.0, 315: 1.0, 355: 0.72, 390: 0.68}}}
    c.check("재료 계수가 항복 강도와 함께 줄지 않으면 거부", c.raises(lambda: StrengthRules.model_validate(flat)))
    bare = {**raw, "material_factor": {**raw["material_factor"], "source": None}}
    c.check("근거 있음 값에 출처가 없으면 거부", c.raises(lambda: StrengthRules.model_validate(bare)))


def _formula(c: Checker, strength: StrengthRules) -> None:
    c.section("대안: 강도 여유 지표의 성질")
    tc = strength.plate_corrosion_addition_mm.value
    before = PlateState(thickness_mm=15.0, spacing_m=0.8, k=0.72)
    c.check(
        "보강재 간격을 절반으로 하면 이득 2",
        math.isclose(gain(before, PlateState(15.0, 0.4, 0.72), tc), 2.0),
    )
    c.check(
        "같은 항복 강도 강종(AH36 → DH36)은 이득 1",
        math.isclose(gain(before, PlateState(15.0, 0.8, strength.k("DH36") or 0), tc), 1.0),
    )
    c.check(
        "두께 이득 = (t₁ − t_c) / (t₀ − t_c)",
        math.isclose(gain(before, PlateState(17.0, 0.8, 0.72), tc), (17.0 - tc) / (15.0 - tc)),
    )
    c.check(
        "0.5mm 올림: 15.0 → 15.0, 15.01 → 15.5, 15.5 → 15.5",
        (round_up_half_mm(15.0), round_up_half_mm(15.01), round_up_half_mm(15.5)) == (15.0, 15.5, 15.5),
    )
    c.check(
        "반올림은 .5에서 위로(은행가 반올림 아님): 2.5 → 3, 3.5 → 4, 0.0005 → 0.001",
        (half_up(2.5), half_up(3.5), round3(0.0005), round3(0.3825)) == (3, 4, 0.001, 0.383),
    )


# ---------- 분석 ----------


def _analyses(c: Checker, ctx: Context, cases: list[GeneratedEcn]) -> dict[str, AnalysisResult]:
    c.section("대안: 생성기 강도형 설계변경")
    index, book, params, strength, as_of = ctx
    results: dict[str, AnalysisResult] = {}
    took: list[float] = []
    for ecn in cases:
        request = AnalysisRequest(change=ecn.change, as_of=as_of, include_alternatives=True)
        started = time.perf_counter()
        try:
            results[ecn.change.ecn_id] = analyze(index, request, book, params, strength)
        except RequestError:
            continue
        took.append(time.perf_counter() - started)
    c.check(
        f"강도형 설계변경 {len(cases)}건 모두 대안 포함 분석 계약 통과(요청 거부 0건)",
        bool(cases) and len(results) == len(cases),
        len(results),
    )
    counts = Counter(a.eligibility.status.value for r in results.values() for a in r.alternatives[1:])
    c.check(f"충족·부족·설계자 확인 대안이 모두 나옴 {dict(counts)}", all(counts[s.value] > 0 for s in Eligibility))
    p95 = quantiles(took, n=20)[-1] if len(took) >= 20 else max(took, default=0.0)
    c.check(
        f"대안 포함 1건 평균 {fmean(took) * 1000:.0f}ms · p95 {p95 * 1000:.0f}ms"
        f" · 최대 {max(took, default=0) * 1000:.0f}ms ≤ 1초",
        bool(took) and p95 <= 1.0,
    )
    again = {
        ecn_id: analyze(index, r.request, book, params, strength).model_dump_json()
        for ecn_id, r in list(results.items())[:8]
    }
    c.check(
        "같은 요청이면 대안·권고까지 바이트가 같음(8건)",
        all(results[k].model_dump_json() == v for k, v in again.items()),
    )
    return results


def _templates(c: Checker, ctx: Context, cases: list[GeneratedEcn]) -> None:
    """템플릿 연산을 명세 3절 식으로 따로 만들어 엔진과 비교한다."""
    c.section("대안: 템플릿 손 계산(명세 3절)")
    index, _, params, strength, _ = ctx
    tc = strength.plate_corrosion_addition_mm.value
    mismatched: list[str] = []
    invalid: list[str] = []
    seen: Counter[str] = Counter()
    for ecn in cases:
        found = plan(index, ecn.change, strength, params)
        op = ecn.change.ops[0]
        for draft in found.drafts:
            seen[draft.alt_id] += 1
            alt = ecn.change.model_copy(update={"ops": draft.ops})
            if validate_request(index, AnalysisRequest(change=alt, as_of=ctx[4])):
                invalid.append(f"{ecn.change.ecn_id}:{draft.alt_id}")
            expected = _expected_ops(index, strength, params, op, draft.alt_id, tc)
            if expected is not None and expected != draft.ops:
                mismatched.append(f"{ecn.change.ecn_id}:{draft.alt_id}")
    c.check(f"템플릿 연산이 명세 식과 같음 {dict(seen)}", not mismatched and sum(seen.values()) > 0, mismatched[:3])
    c.check("템플릿 연산이 모두 요청 검증을 통과", not invalid, invalid[:3])


def _expected_ops(
    index: GraphIndex, strength: StrengthRules, params: ParamSet, op: object, alt_id: str, tc: float
) -> tuple[object, ...] | None:
    if alt_id == "ALT-T1" and isinstance(op, ThicknessChange):
        ops = []
        for pid in op.part_ids:
            p = index.parts[pid]
            assert p.weight_kg and p.thickness_mm and p.span_m and p.stiffener_spacing_m
            n = max(1, math.floor(p.weight_kg / (7.85 * p.thickness_mm) / (p.span_m * p.stiffener_spacing_m) + 0.5))
            attached = sorted(
                x
                for x, r in index.neighbours(pid)
                if r is Relation.FILLET_WELD and index.parts.get(x) and index.parts[x].kind is PartKind.STIFFENER
            )
            pool = attached or sorted(
                q.part_id for q in index.parts.values() if q.block_id == p.block_id and q.kind is PartKind.STIFFENER
            )
            counts = Counter(index.parts[s].spec_id for s in pool)
            spec = sorted(counts, key=lambda s: (-counts[s], s))[0]
            ref = index.parts[sorted(s for s in pool if index.parts[s].spec_id == spec)[0]]
            assert ref.span_m
            qty = math.floor(n * ref.qty / ref.span_m * p.span_m * 1000 + 0.5) / 1000
            ops.append(
                AddPart(block_id=p.block_id, kind=PartKind.STIFFENER, spec_id=spec, qty=qty, attach_to_part_id=pid)
            )
        return tuple(ops)
    if alt_id == "ALT-T3" and isinstance(op, GradeChange):
        ratio = math.sqrt((strength.k(op.from_grade) or 0) / (strength.k(op.to_grade) or 1))
        groups: dict[tuple[float, float], list[str]] = {}
        for pid in op.part_ids:
            t0 = index.parts[pid].thickness_mm or 0.0
            t1 = math.ceil((tc + (t0 - tc) * ratio) * 2 - 1e-9) / 2
            groups.setdefault((t0, t1), []).append(pid)
        return tuple(ThicknessChange(part_ids=tuple(ids), from_mm=a, to_mm=b) for (a, b), ids in sorted(groups.items()))
    if alt_id == "ALT-T4" and isinstance(op, AddPart) and op.attach_to_part_id:
        t0 = index.parts[op.attach_to_part_id].thickness_mm or 0.0
        t1 = math.ceil((tc + 2 * (t0 - tc)) * 2 - 1e-9) / 2
        return (ThicknessChange(part_ids=(op.attach_to_part_id,), from_mm=t0, to_mm=t1),)
    return None


def _judgements(c: Checker, ctx: Context, results: dict[str, AnalysisResult]) -> None:
    c.section("대안: 판정")
    _, _, _, strength, _ = ctx
    tc = strength.plate_corrosion_addition_mm.value
    wrong: list[str] = []
    for ecn_id, r in results.items():
        op = r.request.change.ops[0]
        for a in r.alternatives[1:]:
            if a.eligibility.status is Eligibility.DESIGNER:
                continue
            expected = _ratio(ctx, op, a.alt_id, a.ops, tc)
            if expected is None or round(expected, 3) != a.eligibility.ratio_vs_request:
                wrong.append(f"{ecn_id}:{a.alt_id}:{a.eligibility.ratio_vs_request}≠{expected}")
                continue
            meets = expected >= 1 - 1e-9
            if meets != (a.eligibility.status is Eligibility.MEETS):
                wrong.append(f"{ecn_id}:{a.alt_id}:status")
    c.check("판정 비율 = min(대안 이득 / 요청안 이득)을 따로 계산한 값과 같고, 1 이상이면 충족", not wrong, wrong[:3])
    scoped = [a for r in results.values() for a in r.alternatives if a.scope_reduced]
    c.check(
        f"적용 범위 축소 대안({len(scoped)}개)은 모두 설계자 확인·순위 없음",
        bool(scoped) and all(a.eligibility.status is Eligibility.DESIGNER and a.rank is None for a in scoped),
    )
    grade_short = [
        a
        for r in results.values()
        if isinstance(r.request.change.ops[0], AddPart)
        for a in r.alternatives
        if a.alt_id == "ALT-T2"
    ]
    c.check(
        "보강재 추가 요청의 강종 상향 대안은 부족(이득 √(k/k′) < 2)",
        all(a.eligibility.status is Eligibility.SHORT for a in grade_short),
        [a.eligibility for a in grade_short[:2]],
    )


def _ratio(ctx: Context, op: object, alt_id: str, ops: tuple[object, ...], tc: float) -> float | None:
    _, _, _, strength, _ = ctx

    def k(grade: str | None) -> float:
        return strength.k(grade) or float("nan")

    if isinstance(op, ThicknessChange):
        need = (op.to_mm - tc) / (op.from_mm - tc)
        if alt_id == "ALT-T1":
            return 2.0 / need
        if alt_id == "ALT-T2":
            return min(math.sqrt(k(g.from_grade) / k(g.to_grade)) / need for g in ops if isinstance(g, GradeChange))
    if isinstance(op, GradeChange):
        need = math.sqrt(k(op.from_grade) / k(op.to_grade))
        return min((t.to_mm - tc) / (t.from_mm - tc) / need for t in ops if isinstance(t, ThicknessChange))
    if isinstance(op, AddPart):
        if alt_id == "ALT-T4":
            t = ops[0]
            assert isinstance(t, ThicknessChange)
            return (t.to_mm - tc) / (t.from_mm - tc) / 2.0
        if alt_id == "ALT-T2":
            g = ops[0]
            assert isinstance(g, GradeChange)
            return math.sqrt(k(g.from_grade) / k(g.to_grade)) / 2.0
    return None


def _intents(c: Checker, ctx: Context, cases: list[GeneratedEcn]) -> None:
    c.section("대안: 의도·범위")
    index, book, params, strength, as_of = ctx
    sample = next(
        e
        for e in cases
        if e.change.intent is ChangeIntent.STRENGTH
        and isinstance(e.change.ops[0], ThicknessChange)
        and len(e.change.ops[0].part_ids) > 1
    )

    def run_with(change: ChangeRequest) -> AnalysisResult:
        return analyze(
            index, AnalysisRequest(change=change, as_of=as_of, include_alternatives=True), book, params, strength
        )

    unknown = run_with(sample.change.model_copy(update={"intent": None}))
    c.check(
        "사유가 비면 요청안 밖의 대안은 모두 설계자 확인, 권고는 요청안",
        len(unknown.alternatives) > 1
        and all(a.eligibility.status is Eligibility.DESIGNER for a in unknown.alternatives[1:])
        and unknown.recommendation is not None
        and unknown.recommendation.alt_id == "ALT-REQ",
    )
    known = run_with(sample.change)
    c.check(
        "대안 포함 분석은 사유가 다르면 분석 ID가 다르고 강도 규칙 버전이 버전 묶음에 있음",
        known.analysis_id != unknown.analysis_id and known.versions.strength == strength.version,
    )
    other = run_with(sample.change.model_copy(update={"intent": ChangeIntent.RULE_CHANGE}))
    c.check(
        "규칙·선급 요구 사유는 대안을 만들지 않고 이유를 적음",
        len(other.alternatives) == 1 and any("강도 보강일 때만" in n for n in other.notes),
    )
    op = sample.change.ops[0]
    assert isinstance(op, ThicknessChange)
    thinner = run_with(
        sample.change.model_copy(
            update={"ops": (op.model_copy(update={"from_mm": op.from_mm, "to_mm": op.from_mm - 1}),)}
        )
    )
    c.check(
        "두께를 줄이는 요청은 대안을 만들지 않고 이유를 적음",
        len(thinner.alternatives) == 1 and any("줄이는" in n for n in thinner.notes),
    )
    plain = analyze(index, AnalysisRequest(change=sample.change, as_of=as_of), book, params)
    c.check(
        "대안을 끈 분석은 대안·권고·강도 버전이 없고 강도 규칙 없이도 돈다",
        plain.alternatives == () and plain.recommendation is None and plain.versions.strength is None,
    )
    c.check(
        "대안을 켰는데 강도 규칙이 없으면 거부",
        c.raises(
            lambda: analyze(
                index, AnalysisRequest(change=sample.change, as_of=as_of, include_alternatives=True), book, params
            )
        ),
    )


def _best(c: Checker, ctx: Context, results: dict[str, AnalysisResult]) -> None:
    """최적 조합을 메모 없는 새 평가기로 날짜 × 보류 집합 전부 다시 평가해 고르고, 권고 조건으로 다시 분석한다."""
    c.section("대안: 최적 조합·권고")
    checked, held, wrong, trips = _brute(ctx, list(results.values())[:15])
    c.check(
        f"최적 조합 = 날짜 × 보류 집합 브루트포스(충족 대안 {checked}개, 보류가 든 조합 {held}개)",
        checked > 0 and not wrong,
        wrong[:3],
    )
    c.check("왕복: 최적 조건(대안·확정일·보류)으로 다시 분석한 총액 = 최적 총액", not trips, trips[:3])
    ranks_ok = all(
        sorted(a.rank for a in r.alternatives if a.rank is not None)
        == list(range(1, 1 + sum(a.eligibility.status is Eligibility.MEETS for a in r.alternatives)))
        for r in results.values()
    )
    c.check("충족 대안마다 순위 1부터 빠짐없이, 권고 = 1위", ranks_ok)
    wins = Counter(r.recommendation.alt_id for r in results.values() if r.recommendation)
    c.check(f"권고 분포 {dict(wins)} — 요청안이 아닌 대안을 권고한 사례가 있음", wins["ALT-REQ"] < len(results))


def _unchanged(c: Checker, ctx: Context, cases: list[GeneratedEcn]) -> None:
    c.section("대안: 요청안 결과는 대안을 켜도 그대로")
    index, book, params, strength, as_of = ctx
    changed: list[str] = []
    for ecn in cases:
        off = analyze(index, AnalysisRequest(change=ecn.change, as_of=as_of), book, params)
        on = analyze(
            index, AnalysisRequest(change=ecn.change, as_of=as_of, include_alternatives=True), book, params, strength
        )
        same = (
            off.cost_lines == on.cost_lines
            and off.timing == on.timing
            and off.verdict == on.verdict
            and off.impacts == on.impacts
            and off.schedule == on.schedule
            and on.alternatives[0].total == off.total
        )
        if not same:
            changed.append(ecn.change.ecn_id)
    c.check(f"비용 줄·곡선·판정·영향·일정이 같고 요청안 총액 = 분석 총액({len(cases)}건)", not changed, changed[:3])


def _spans(c: Checker, ctx: Context, results: dict[str, AnalysisResult]) -> None:
    """날짜별 최저 비용 대안: 충족 대안마다 따로 분석한 곡선으로 날짜별 최소를 다시 골라 구간으로 묶는다."""
    c.section("대안: 날짜별 최저 비용 대안 구간")
    index, book, params, _, _ = ctx
    picked = [r for r in results.values() if sum(a.eligibility.status is Eligibility.MEETS for a in r.alternatives) > 1]
    wrong: list[str] = []
    switched = 0
    for r in picked[:20]:
        curves = {}
        for a in r.alternatives:
            if a.eligibility.status is not Eligibility.MEETS:
                continue
            alone = r.request.model_copy(
                update={"change": r.request.change.model_copy(update={"ops": a.ops}), "include_alternatives": False}
            )
            curves[a.alt_id] = analyze(index, alone, book, params).timing.curve
        expected: list[tuple[str, date, date, int]] = []
        for i, point in enumerate(r.timing.curve):
            alt_id = min(curves, key=lambda k: (curves[k][i].total.value, k != "ALT-REQ", k))
            if expected and expected[-1][0] == alt_id:
                expected[-1] = (alt_id, expected[-1][1], point.confirm_on, expected[-1][3])
            else:
                expected.append((alt_id, point.confirm_on, point.confirm_on, curves[alt_id][i].total.value))
        got = [(s.alt_id, s.start, s.end, s.total.value) for s in r.cheapest_by_date]
        if got != expected:
            wrong.append(r.request.change.ecn_id)
        switched += len(got) > 1
    c.check(
        f"구간 = 대안마다 따로 분석한 곡선의 날짜별 최소({len(picked[:20])}건, 갈림 {switched}건)",
        bool(picked) and not wrong and switched > 0,
        wrong[:3],
    )


def _brute(ctx: Context, results: list[AnalysisResult]) -> tuple[int, int, list[str], list[str]]:
    """충족 대안마다 확정 가능일(요청 확정일) 이후 날짜 × {요청 보류, + 보류 권고}를 새 평가기로 모두 평가해 최소를
    고르고(같으면 이른 날, 보류 적은 쪽), 엔진 최적과 비교한다. 확정일이 탐색 기간 밖이면 그날 하루. 왕복도 본다."""
    index, book, params, _, _ = ctx
    wrong: list[str] = []
    trips: list[str] = []
    held = checked = 0
    for r in results:
        earliest = r.request.effective_confirm_on
        for a in r.alternatives:
            if a.best_total is None or a.best_confirm_on is None:
                continue
            checked += 1
            request = r.request.model_copy(
                update={"change": r.request.change.model_copy(update={"ops": a.ops}), "include_alternatives": False}
            )
            fresh = Evaluator(index, request, book, params)
            points, evaluations = fresh.curve(request.holds)
            advice = fresh.hold_advice({d: ev.total for d, ev in evaluations.items()})
            options = [request.holds]
            if advice:
                advised = (*request.holds, *(HoldAction(po_id=x.po_id, hold_days=x.max_hold_days) for x in advice))
                options.append(tuple(sorted(advised, key=lambda h: h.po_id)))
            days = [p.confirm_on for p in points if p.confirm_on >= earliest] or [earliest]
            candidates = []
            for holds in options:
                for day in days:
                    total = fresh.evaluate(day, holds).total
                    candidates.append((total.value, day, len(holds), holds, total))
            _, day, _, holds, total = min(candidates, key=lambda x: (x[0], x[1], x[2]))
            name = f"{r.request.change.ecn_id}:{a.alt_id}"
            if (day, total, holds) != (a.best_confirm_on, a.best_total, a.best_holds):
                wrong.append(name)
            held += bool(a.best_holds)
            again = analyze(
                index,
                request.model_copy(update={"confirm_on": a.best_confirm_on, "holds": a.best_holds}),
                book,
                params,
            )
            if again.total != a.best_total:
                trips.append(f"{name}:{again.total.value}≠{a.best_total.value}")
    return checked, held, wrong, trips


def _earliest(c: Checker, ctx: Context, cases: list[GeneratedEcn]) -> None:
    """확정일 = 확정 가능일: 그 전 날은 고르지 않고, 늦게 확정해야 하면 발주 보류가 든 조합이 최적이 될 수 있다."""
    c.section("대안: 확정 가능일(요청 확정일) 이후 최적 조합")
    index, book, params, strength, as_of = ctx

    def run_at(ecn: GeneratedEcn, offset: int) -> AnalysisResult:
        request = AnalysisRequest(
            change=ecn.change, as_of=as_of, confirm_on=as_of + timedelta(days=offset), include_alternatives=True
        )
        return analyze(index, request, book, params, strength)

    later = [r for r in (run_at(e, 20) for e in cases) if len(r.alternatives) > 1][:12]
    checked, held, wrong, trips = _brute(ctx, later)
    c.check(
        f"확정일 +20일: 최적 조합 = 확정일 이후 날짜 × 보류 집합 브루트포스"
        f"(충족 대안 {checked}개, 보류가 든 조합 {held}개)",
        checked > 0 and held > 0 and not wrong,
        wrong[:3],
    )
    c.check("확정일 +20일: 왕복(최적 조건으로 다시 분석한 총액 = 최적 총액)", not trips, trips[:3])
    early = [
        a
        for r in later
        for a in r.alternatives
        if a.best_confirm_on and a.best_confirm_on < r.request.effective_confirm_on
    ]
    c.check("최적 확정일은 확정 가능일보다 앞서지 않음", not early, [a.alt_id for a in early[:3]])
    demo = next(e for e in cases if e.change.ecn_id == "ECN-D-0045")
    shifted = run_at(demo, 10)
    request_alt = shifted.alternatives[0]
    rec = shifted.recommendation
    c.check(
        "ECN-D-0045를 10일 뒤에야 확정하면: 보류 권고 발주를 보류한 요청안이 권고되고 보류 없는 금액보다 쌈",
        rec is not None
        and rec.alt_id == "ALT-REQ"
        and bool(rec.holds)
        and rec.confirm_on == shifted.request.effective_confirm_on
        and rec.total.value < request_alt.total.value,
        (rec, request_alt.total),
    )
    beyond = run_at(demo, shifted.request.horizon_days + 10)
    outside = [a for a in beyond.alternatives if a.best_confirm_on is not None]
    c.check(
        "확정일이 탐색 기간 밖이면 최적 확정일 = 그날(곡선 밖 하루를 따로 평가)",
        bool(outside) and all(a.best_confirm_on == beyond.request.effective_confirm_on for a in outside),
        [(a.alt_id, a.best_confirm_on) for a in outside],
    )
    checked, _, wrong, trips = _brute(ctx, [beyond])
    c.check("탐색 기간 밖 확정일도 브루트포스·왕복과 같음", checked > 0 and not wrong and not trips, (wrong, trips))
