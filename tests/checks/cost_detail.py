"""비용 줄 설명(docs/engine.md(비용·일정) 4-9·8-5): 발생 사유 · 가정과 범위 · 늦어지면 · 보류 권고 품목."""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Mapping
from datetime import date, timedelta

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.analysis import AnalysisRequest, HoldAction
from ripple.contracts.change import EquipmentSpecChange, ThicknessChange
from ripple.contracts.dataset import GeneratedEcn
from ripple.contracts.domain import BlockStage, GraphSnapshot, PartKind, Relation
from ripple.contracts.params import ParamSet, ParamStatus
from ripple.contracts.result import (
    Amount,
    AnalysisResult,
    CostFactor,
    CostLine,
    Determinacy,
    LineOutlook,
    OutlookKind,
)
from ripple.contracts.rulebook import RuleBook
from ripple.engine.analyze import analyze
from ripple.engine.cost.factors import WORK_HOURS, factor_name
from ripple.engine.describe import BLOCK_STAGE_NAMES, PO_STATUS_NAMES
from ripple.engine.index import GraphIndex
from ripple.engine.outlook import outlook_of
from ripple.engine.propagate import RequestError
from ripple.engine.timing import Evaluation, Evaluator
from ripple.generator.build import generate
from ripple.generator.io import load_config

from .cost import request_of

DAY = date(2026, 10, 20)
ASSUMED = "보고 계산(확인 필요)"
WEAKEST = {ParamStatus.ASSUMPTION: 0, ParamStatus.MENTOR: 1, ParamStatus.EVIDENCE: 2}
STAGE_NAMES = {s.value: n for s, n in BLOCK_STAGE_NAMES.items()} | {s.value: n for s, n in PO_STATUS_NAMES.items()}


def run(c: Checker) -> None:
    _outlook_rules(c)
    _validators(c)
    config = load_config()
    generated = generate(config)
    index = GraphIndex(generated.snapshot)
    book = load_rulebook(PROJECT_ROOT / "rules" / "propagation.yaml")
    params = load_params(PROJECT_ROOT / "params" / "cost_v1.yaml")
    results = _sweep(c, index, book, params, generated.ecns)
    _against_curve(c, index, book, params, results)
    _unknown_wording(c, index, book, params, generated.ecns)
    _assumed_minor(c, generated.snapshot, index, book, params, config.scenario_date)


# ---------- 늦어지면: 순수 함수 ----------


def _line(
    value: float = 100, stage: str | None = "assembly", known: bool = True, high: float | None = None
) -> CostLine:
    return CostLine(
        line_id="R-B01:rework:B",
        rule_id="R-B01",
        entity_id="B",
        label="B 블록 재작업",
        formula="검사",
        inputs={} if stage is None else {"stage": stage},
        amount=Amount(value=value, low=value, high=value if high is None else high),
        determinacy=Determinacy.KNOWN if known else Determinacy.STATE_UNKNOWN,
    )


def _days(*lines: CostLine | None) -> list[tuple[date, Mapping[str, CostLine]]]:
    """확정일 다음날부터 하루씩, 줄이 None이면 그날 그 줄이 없음."""
    return [(DAY + timedelta(days=i + 1), {} if x is None else {x.line_id: x}) for i, x in enumerate(lines)]


def _outlook_rules(c: Checker) -> None:
    c.section("비용 줄 설명: 늦어지면(순수 함수)")
    base = _line()
    unchecked = outlook_of(base, [])
    c.check("확정일 뒤로 평가한 날이 없으면 '보지 않음'", unchecked == LineOutlook(kind=OutlookKind.UNCHECKED))
    steady = outlook_of(base, _days(base, base, base))
    c.check(
        "끝까지 같으면 '그대로'와 본 마지막 날",
        steady == LineOutlook(kind=OutlookKind.STEADY, checked_until=DAY + timedelta(days=3)),
        steady,
    )
    later = _line(150, "pre_outfitting")
    changed = outlook_of(base, _days(base, later, _line(180, "pre_painting")))
    c.check(
        "처음 금액이 바뀐 날·그날 금액·단계 변화(뒤의 변화는 보지 않음)",
        changed
        == LineOutlook(
            kind=OutlookKind.CHANGES, on=DAY + timedelta(days=2), amount=later.amount, note="단계 대조립 → 선행의장"
        ),
        changed,
    )
    same_stage = outlook_of(base, _days(_line(120)))
    c.check(
        "단계가 같으면 금액만 바뀌고 단계 변화 문구 없음",
        same_stage.note is None and same_stage.on == DAY + timedelta(days=1),
    )
    unknown = outlook_of(_line(known=False), _days(later))
    c.check(
        "확정일 단계를 모르는 줄은 단계 변화 문구 없음", unknown.kind is OutlookKind.CHANGES and unknown.note is None
    )
    into_unknown = outlook_of(base, _days(_line(150, "pre_outfitting", known=False)))
    c.check("바뀐 날 단계를 모르게 되면 단계 변화 문구 없음", into_unknown.note is None)
    removed = outlook_of(base, _days(base, None, later))
    c.check(
        "금액이 바뀌기 전에 줄이 없어지면 '없어짐'과 그날",
        removed == LineOutlook(kind=OutlookKind.REMOVED, on=DAY + timedelta(days=2)),
        removed,
    )
    widened = outlook_of(base, _days(_line(100, high=140)))
    c.check("대표값이 같아도 범위가 바뀌면 바뀐 것으로 봄", widened.kind is OutlookKind.CHANGES)
    no_stage = outlook_of(_line(stage=None), _days(_line(130, stage=None)))
    c.check("판정 단계가 없는 줄(작은 작업 등)은 단계 변화 문구 없음", no_stage.note is None)


def _validators(c: Checker) -> None:
    c.section("비용 줄 설명: 계약 검증")
    d = DAY
    amount = Amount.exact(1)
    bad = {
        "그대로인데 본 마지막 날이 없음": lambda: LineOutlook(kind=OutlookKind.STEADY),
        "보지 않음인데 날짜가 있음": lambda: LineOutlook(kind=OutlookKind.UNCHECKED, on=d),
        "바뀌는데 그날 금액이 없음": lambda: LineOutlook(kind=OutlookKind.CHANGES, on=d),
        "없어지는데 금액이 있음": lambda: LineOutlook(kind=OutlookKind.REMOVED, on=d, amount=amount),
        "없어지는데 단계 변화 문구가 있음": lambda: LineOutlook(kind=OutlookKind.REMOVED, on=d, note="단계"),
        "바뀌는데 본 마지막 날이 있음": lambda: LineOutlook(
            kind=OutlookKind.CHANGES, on=d, amount=amount, checked_until=d
        ),
        "가정값 최소 > 대표값": lambda: CostFactor(
            label="x", unit="t", value=1, low=2, high=3, status=ParamStatus.ASSUMPTION, keys=("k",)
        ),
        "가정값 키 없음": lambda: CostFactor(
            label="x", unit="t", value=1, low=1, high=1, status=ParamStatus.ASSUMPTION, keys=()
        ),
    }
    for name, build in bad.items():
        c.check(f"거부: {name}", c.raises(build))


# ---------- 생성기 설계변경으로 ----------


def _sweep(
    c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, ecns: tuple[GeneratedEcn, ...]
) -> list[AnalysisResult]:
    c.section("비용 줄 설명: 생성기 설계변경 60건의 모든 줄")
    rng = random.Random(11)
    results: list[AnalysisResult] = []
    problems: Counter[str] = Counter()
    seen: Counter[str] = Counter()
    lines = 0
    for ecn in rng.sample(list(ecns), 60):
        try:
            result = analyze(index, AnalysisRequest(change=ecn.change, as_of=ecn.as_of), book, params)
        except RequestError:
            continue
        results.append(result)
        for line in result.cost_lines:
            lines += 1
            for problem in _line_problems(line, result, params):
                problems[problem] += 1
            outlook = line.outlook
            if outlook is not None:
                seen[outlook.kind.value + (":단계" if outlook.note else "")] += 1
            if any(k.startswith("rework.equivalent_weight_t.") for k in line.param_keys):
                seen["환산 중량"] += 1
        for hold in result.timing.holds:
            ids = hold.line_ids
            ok = bool(ids) and list(ids) == sorted(set(ids))
            ok &= all(i in index.lines and index.lines[i].po_id == hold.po_id for i in ids)
            if not ok:
                problems["보류 권고 품목이 비었거나 다른 발주 품목"] += 1
            seen["보류 권고"] += 1
    c.check(
        f"분석 {len(results)}건의 비용 줄 {lines}개: 이유·가정값·늦어지면·보류 권고 품목이 성질을 지킴",
        not problems and len(results) >= 50,
        dict(problems),
    )
    c.check(
        "표본에 금액이 바뀌는 날(단계 변화 포함)·그대로·환산 중량·보류 권고가 모두 있음",
        all(seen[k] > 0 for k in ("changes:단계", "steady", "환산 중량", "보류 권고")),
        dict(seen),
    )
    return results


def _line_problems(line: CostLine, result: AnalysisResult, params: ParamSet) -> list[str]:
    problems: list[str] = []
    reason = line.reason or ""
    if not reason.strip() or "{" in reason or "None" in reason:
        problems.append("이유가 비었거나 채워지지 않은 자리")
    unknown = "알 수 없어" in reason
    if unknown != (line.determinacy is Determinacy.STATE_UNKNOWN):
        problems.append("판단 불가 줄과 '알 수 없어' 문구가 어긋남")
    known_rework = line.rule_id == "R-B01" and line.determinacy is Determinacy.KNOWN
    if known_rework and BLOCK_STAGE_NAMES[BlockStage(str(line.inputs["stage"]))] not in reason:
        problems.append("재작업 이유에 확정일 블록 단계가 없음")
    keys = [k for f in line.factors for k in f.keys]
    if sorted(keys) != sorted(set(line.param_keys)) or len(keys) != len(set(keys)):
        problems.append("가정값 키 합집합 ≠ 쓴 파라미터 키")
    for factor in line.factors:
        items = [params.get(k) for k in factor.keys]
        sums = tuple(round(sum(getattr(p, f) for p in items), 6) for f in ("value", "low", "high"))
        if sums != (factor.value, factor.low, factor.high):
            problems.append("가정값이 파라미터(합친 값은 합)와 다름")
        if factor.status is not min((p.status for p in items), key=WEAKEST.__getitem__):
            problems.append("합친 가정값 상태가 가장 약한 것이 아님")
        if any(factor_name(k) is None and not k.startswith(WORK_HOURS) for k in factor.keys):
            problems.append("이름표에 없는 파라미터 키(화면에 키가 그대로 보임)")
    outlook = line.outlook
    request = result.request
    confirm = request.effective_confirm_on
    end = request.as_of + timedelta(days=request.horizon_days)
    if outlook is None:
        problems.append("분석 결과 줄에 늦어지면이 없음")
    elif confirm >= end:
        if outlook.kind is not OutlookKind.UNCHECKED:
            problems.append("확정일이 탐색 끝인데 '보지 않음'이 아님")
    elif outlook.kind is OutlookKind.UNCHECKED:
        problems.append("뒤로 볼 날이 있는데 '보지 않음'")
    elif outlook.kind is OutlookKind.STEADY and outlook.checked_until != end:
        problems.append("'그대로'의 본 마지막 날이 탐색 끝이 아님")
    elif outlook.on is not None and not confirm < outlook.on <= end:
        problems.append("바뀌는 날이 확정일 뒤·탐색 기간 안이 아님")
    elif outlook.kind is OutlookKind.CHANGES and outlook.amount == line.amount:
        problems.append("바뀐다는데 그날 금액이 같음")
    elif outlook.note is not None and (line.determinacy is not Determinacy.KNOWN or "stage" not in line.inputs):
        problems.append("단계를 모르는(또는 단계가 없는) 줄에 단계 변화 문구")
    return problems


def _against_curve(
    c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, results: list[AnalysisResult]
) -> None:
    c.section("비용 줄 설명: 늦어지면 = 곡선의 날마다 평가와 같음")
    picked = [r for r in results if any(o.outlook and o.outlook.kind is OutlookKind.CHANGES for o in r.cost_lines)][:3]
    held = next((r for r in results if r.timing.holds), None)
    requests = [r.request for r in picked]
    if picked:
        middle = picked[0].request
        requests.append(middle.model_copy(update={"confirm_on": middle.as_of + timedelta(days=10)}))
        requests.append(middle.model_copy(update={"confirm_on": middle.as_of + timedelta(days=middle.horizon_days)}))
        beyond = middle.as_of + timedelta(days=middle.horizon_days + 5)
        requests.append(middle.model_copy(update={"confirm_on": beyond}))
    if held is not None:
        hold = held.timing.holds[0]
        requests.append(
            held.request.model_copy(update={"holds": (HoldAction(po_id=hold.po_id, hold_days=hold.max_hold_days),)})
        )
    total = same = 0
    kinds: Counter[str] = Counter()
    for request in requests:
        result = analyze(index, request, book, params)
        _, evaluations = Evaluator(index, request, book, params).curve(request.holds)
        confirm = request.effective_confirm_on
        days = sorted(d for d in evaluations if d > confirm)
        for line in result.cost_lines:
            total += 1
            expected = _expected(line, days, evaluations)
            same += line.outlook == expected
            kinds[expected.kind.value] += 1
    c.check(
        f"요청 {len(requests)}건(중간 확정일·탐색 끝·탐색 밖 확정·보류 포함)의 줄 {total}개: 손으로 따라간 결과와 같음",
        total > 0 and same == total and len(requests) >= 5,
        (same, total, dict(kinds)),
    )
    c.check("탐색 끝에 확정하면 모든 줄이 '보지 않음'", kinds["unchecked"] > 0, dict(kinds))


def _expected(line: CostLine, days: list[date], evaluations: Mapping[date, Evaluation]) -> LineOutlook:
    """곡선의 날마다 평가(Evaluation.lines)를 처음부터 따라가며 다시 정한다."""
    if not days:
        return LineOutlook(kind=OutlookKind.UNCHECKED)
    for day in days:
        found = [x for x in evaluations[day].lines if x.line_id == line.line_id]
        if not found:
            return LineOutlook(kind=OutlookKind.REMOVED, on=day)
        other: CostLine = found[0]
        if (other.amount.value, other.amount.low, other.amount.high) != (
            line.amount.value,
            line.amount.low,
            line.amount.high,
        ):
            note = None
            both_known = line.determinacy is Determinacy.KNOWN and other.determinacy is Determinacy.KNOWN
            a, b = line.inputs.get("stage"), other.inputs.get("stage")
            if both_known and a is not None and b is not None and a != b:
                note = f"단계 {STAGE_NAMES[str(a)]} → {STAGE_NAMES[str(b)]}"
            return LineOutlook(kind=OutlookKind.CHANGES, on=day, amount=other.amount, note=note)
    return LineOutlook(kind=OutlookKind.STEADY, checked_until=days[-1])


def _unknown_wording(
    c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, ecns: tuple[GeneratedEcn, ...]
) -> None:
    c.section("비용 줄 설명: 단계를 모를 때의 문구")
    found: list[CostLine] = []
    for ecn in ecns:
        request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of)
        try:
            evaluation = Evaluator(index, request, book, params).evaluate(request.as_of, ())
        except RequestError:
            continue
        found += [x for x in evaluation.lines if x.determinacy is Determinacy.STATE_UNKNOWN]
        if len(found) >= 6:
            break
    good = all("알 수 없어" in (x.reason or "") and "가장 큰" in (x.reason or "") for x in found)
    c.check(
        f"판단 불가 줄 {len(found)}개: 이유가 '어느 단계인지 알 수 없어 … 가장 큰(비싼) 단계로 계산'",
        len(found) >= 1 and good,
        [x.reason for x in found if "가장 큰" not in (x.reason or "")][:2],
    )


def _assumed_minor(
    c: Checker, snapshot: GraphSnapshot, index: GraphIndex, book: RuleBook, params: ParamSet, as_of: date
) -> None:
    c.section("비용 줄 설명: 정보가 없어 가정한 작은 작업")
    parts = sorted(index.parts.values(), key=lambda p: p.part_id)
    valve = next(p for p in parts if p.kind is PartKind.VALVE and index.out(p.part_id, Relation.PIPE_JOINT))
    joint = index.specs[valve.spec_id]
    other = next(
        s.spec_id
        for s in sorted(index.specs.values(), key=lambda s: s.spec_id)
        if s.category == joint.category
        and (s.nominal_diameter_dn, s.pressure_class) != (joint.nominal_diameter_dn, joint.pressure_class)
        and s.nominal_diameter_dn is not None
        and s.pressure_class is not None
    )

    def p01(to_spec: str) -> list[CostLine]:
        op = EquipmentSpecChange(part_ids=(valve.part_id,), from_spec_id=valve.spec_id, to_spec_id=to_spec)
        lines = Evaluator(index, request_of(as_of, op), book, params).evaluate(as_of, ()).lines
        return [x for x in lines if x.rule_id == "R-P01"]

    unknown, known = p01("VL-UNKNOWN-NEW"), p01(other)
    c.check(
        f"연결 규격을 모르는 사양 변경: 인접 배관 수정 이유가 '…{ASSUMED}'(단정하지 않음)",
        bool(unknown) and all(ASSUMED in (x.reason or "") for x in unknown),
        [x.reason for x in unknown][:1],
    )
    c.check(
        "연결 규격을 아는 사양 변경은 가정 문구 없이 교체 이유",
        bool(known) and not any(ASSUMED in (x.reason or "") for x in known),
        [x.reason for x in known][:1],
    )
    plate = next(
        p for p in parts if p.kind is PartKind.PLATE and p.thickness_mm and index.out(p.part_id, Relation.BUTT_WELD)
    )
    neighbour = index.out(plate.part_id, Relation.BUTT_WELD)[0]
    blank_parts = tuple(
        p.model_copy(update={"thickness_mm": None}) if p.part_id == neighbour else p for p in snapshot.parts
    )
    blank = snapshot.model_copy(update={"parts": blank_parts})
    op = ThicknessChange(
        part_ids=(plate.part_id,), from_mm=plate.thickness_mm or 0, to_mm=(plate.thickness_mm or 0) + 3
    )

    def taper(on: GraphIndex) -> CostLine | None:
        lines = Evaluator(on, request_of(as_of, op), book, params).evaluate(as_of, ()).lines
        return next((x for x in lines if x.rule_id == "R-T02" and x.entity_id == neighbour), None)

    assumed, measured = taper(GraphIndex(blank)), taper(index)
    c.check(
        f"이웃 판 두께를 모르면 테이퍼 이유가 '…{ASSUMED}', 두께를 알면 문턱 초과 이유",
        assumed is not None
        and ASSUMED in (assumed.reason or "")
        and measured is not None
        and ASSUMED not in (measured.reason or ""),
        (assumed and assumed.reason, measured and measured.reason),
    )
