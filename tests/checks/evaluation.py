"""평가 도구의 성질: 관문 사례 계약, 판정 채점(재현율·정밀도), where-used 기준선, 사례 입력,
2단계 채점(금액·일정·확정 시점·판정)과 명세 8-4 판정 문장, 3단계 채점(대안 비교)."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook, load_strength
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.evaluation import CaseExpectation, ExpectedLine, GateCase, GateCaseInput
from ripple.contracts.result import Amount, AnalysisResult, DeadlineKind, Determinacy, ImpactType, VerdictLevel
from ripple.engine import verdict as verdict_rules
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import impact_report
from ripple.eval.alt_gate_inputs import alt_gate_inputs
from ripple.eval.alt_metrics import LABEL_PREFIXES, SKIPPED, omissions, score_alt_case
from ripple.eval.cost_gate_inputs import cost_gate_inputs
from ripple.eval.cost_metrics import CostCaseScore, close, score_cost_case, score_cost_gate
from ripple.eval.gate_inputs import gate_inputs
from ripple.eval.impact_metrics import (
    SetScore,
    produced_keys,
    score_case,
    score_gate,
    where_used,
    where_used_plm,
)
from ripple.eval.leaks import blind, find_leaks, hint_leaks, map_ids, needles
from ripple.explain.format import money
from ripple.generator.build import generate
from ripple.generator.io import load_config


def run(c: Checker) -> None:
    _set_scores(c)
    _contracts(c)
    _cases(c)
    _cost_contracts(c)
    _cost_cases(c)
    _verdict_phrases(c)
    _alt_contracts(c)
    _alt_cases(c)


def _set_scores(c: Checker) -> None:
    c.section("평가: 재현율·정밀도")
    half = SetScore(frozenset({1, 2}), frozenset({2, 3, 4}))
    c.check("재현율 = 맞힌 정답 / 정답, 정밀도 = 맞힌 출력 / 출력", (half.recall, half.precision) == (0.5, 1 / 3))
    c.check("F1은 재현율·정밀도의 조화 평균", abs(half.f1 - 0.4) < 1e-12)
    c.check(
        "정답도 출력도 없으면 둘 다 1",
        (SetScore(frozenset(), frozenset()).recall, SetScore(frozenset(), frozenset()).precision) == (1.0, 1.0),
    )
    c.check("아무것도 못 맞히면 F1 = 0", SetScore(frozenset({1}), frozenset({2})).f1 == 0.0)


def _expectation(**override: Any) -> CaseExpectation:
    body: dict[str, Any] = {"impacts": [{"entity_id": "PO-1#1", "impact_type": "po_change", "rule_id": "R-T01"}]}
    return CaseExpectation.model_validate(body | override)


def _contracts(c: Checker) -> None:
    c.section("평가: 관문 사례 계약")
    c.check("기대 영향 하나는 받음", len(_expectation().impacts) == 1)
    twice = [{"entity_id": "PO-1#1", "impact_type": "po_change", "rule_id": "R-T01"}] * 2
    c.check("같은 기대 영향이 둘이면 거부", c.raises(lambda: _expectation(impacts=twice)))
    c.check(
        "기대 영향과 금지 영향이 겹치면 거부",
        c.raises(lambda: _expectation(forbidden_impacts=[{"entity_id": "PO-1#1", "impact_type": "po_change"}])),
    )
    c.check(
        "규칙 ID 형식이 아니면 거부",
        c.raises(lambda: _expectation(impacts=[{"entity_id": "x", "impact_type": "rework", "rule_id": "T01"}])),
    )
    other_rule = [{"entity_id": "PO-1#1", "impact_type": "po_change", "rule_id": "R-M02"}]
    c.check(
        "같은 엔터티·종류라도 규칙이 다르면 금지할 수 있음",
        len(_expectation(forbidden_impacts=other_rule).forbidden_impacts) == 1,
    )


def _cases(c: Checker) -> None:
    c.section("평가: 관문 사례 입력·채점")
    config = load_config()
    generated = generate(config)
    index = GraphIndex(generated.snapshot)
    inputs = gate_inputs(generated.snapshot, generated.seed, config.scenario_date)
    c.check(
        "사례 입력 30건(관문 10 + E1 경계 20), ID는 G1-001부터 차례대로",
        [i.case_id for i in inputs] == [f"G1-{n:03d}" for n in range(1, 31)],
    )
    again = gate_inputs(generated.snapshot, generated.seed, config.scenario_date)
    c.check("같은 지도면 같은 사례 입력(결정적)", inputs == again)
    settings = Settings.from_env({})
    book = load_rulebook(settings.rules_path)
    params = load_params(settings.params_path).version
    reports = [impact_report(index, i.request, book, params) for i in inputs]
    used = {i.rule_id for r in reports for i in r.impacts}
    c.check(
        "사례 입력이 1단계 규칙 12개를 모두 건드림",
        used
        == {"R-T01", "R-M02", "R-T02", "R-T03", "R-T04", "R-P01", "R-P02", "R-P03", "R-M01", "R-B01", "R-D01", "R-X01"},
        sorted(used),
    )
    lots = {s.lot_id for s in generated.snapshot.stock}
    reallocations = {i.entity_id for r in reports for i in r.impacts if i.rule_id == "R-M01"}
    c.check(
        "잉여 자재 전용 두 방향 모두 양성 사례가 있음: (가) 재고 로트로, (나) 다른 블록의 발주 품목으로",
        bool(reallocations & lots) and bool(reallocations - lots),
        sorted(reallocations),
    )
    shown = [blind(i) for i in inputs]
    c.check(
        "계산자에게 주는 사례 입력은 제목 = 번호·focus 빈 값이고, 연산·기준일·확정일·보류는 그대로",
        all(
            s.title == s.request.change.title == f"설계변경 {i.request.change.ecn_id}"
            and s.focus == ""
            and s.request.change.ops == i.request.change.ops
            and (s.request.as_of, s.request.confirm_on, s.request.holds)
            == (i.request.as_of, i.request.confirm_on, i.request.holds)
            for s, i in zip(shown, inputs, strict=True)
        ),
    )

    def as_text(case: GateCaseInput) -> str:
        return json.dumps(case.model_dump(mode="json"), ensure_ascii=False)

    c.check(
        "판정 힌트 점검: 원래 사례 입력(focus)의 규칙 ID는 잡고, 계산자용 사본에는 부재·규격 ID가 있어도 잡히지 않음",
        bool(hint_leaks({i.case_id: as_text(i) for i in inputs}))
        and not hint_leaks({s.case_id: as_text(s) for s in shown}),
        hint_leaks({s.case_id: as_text(s) for s in shown})[:3],
    )
    ids = map_ids(generated.snapshot)
    shipped = {f"docs/{name}": (PROJECT_ROOT / "docs" / name).read_text(encoding="utf-8") for name in _STAGE3_DOCS}
    shipped |= {
        f"rules/{name}": (PROJECT_ROOT / "rules" / name).read_text(encoding="utf-8")
        for name in ("propagation.yaml", "strength.yaml")
    }
    shipped["params/cost_v1.yaml"] = (PROJECT_ROOT / "params" / "cost_v1.yaml").read_text(encoding="utf-8")
    block = generated.snapshot.blocks[0].block_id
    c.check(
        "계산자에게 가는 명세·규칙·파라미터의 예시에 지도의 실제 ID가 없음(실제 ID는 정답 엔터티와 겹칠 수 있음), "
        "점검은 블록 ID를 찾되 그 블록 부재 ID 안의 글자는 세지 않음",
        not find_leaks(shipped, ids)
        and bool(find_leaks({"x.md": f"예: {block} 블록"}, ids))
        and not find_leaks({"y.md": f"예: {block}-ZZ-999"}, ids),
        find_leaks(shipped, ids)[:3],
    )

    report = reports[0]
    exact = GateCase(
        **inputs[0].model_dump(),
        expected=CaseExpectation(
            impacts=tuple(
                {"entity_id": e, "impact_type": ImpactType(t), "rule_id": r}
                for e, t, r in sorted(produced_keys(report))
            ),
            unresolved=tuple({"kind": u.kind, "entity_id": u.entity_id} for u in report.unresolved),
        ),
        computed_by="검사",
        computed_on=date(2026, 10, 7),
    )
    score = score_case(exact, report, index)
    c.check(
        "정답과 출력이 같으면 재현율·정밀도 1, 관문 통과",
        score.impacts.recall == score.impacts.precision == 1.0 and score_gate([score], [score.case_id]).passed(),
    )
    c.check(
        "1단계 관문도 필수 사례가 빠지면 미달",
        not score_gate([score], [score.case_id, "G1-002"]).passed()
        and any("G1-002" in p for p in score_gate([score], [score.case_id, "G1-002"]).problems),
    )
    missing = exact.model_copy(
        update={"expected": exact.expected.model_copy(update={"impacts": exact.expected.impacts[1:]})}
    )
    partial = score_case(missing, report, index)
    c.check(
        "정답에서 하나를 빼면 출력 하나가 오탐(정밀도만 떨어짐)",
        partial.impacts.recall == 1.0 and len(partial.extra) == 1 and partial.impacts.precision < 1.0,
    )
    baseline = where_used(index, report)
    targets = [p for op in inputs[0].request.change.ops for p in getattr(op, "part_ids", ())]
    expected_baseline = {index.parts[p].block_id for p in targets} | {index.line_of_part[p] for p in targets}
    c.check("where-used 기준선 = 대상 부재의 블록과 공급 발주 품목", baseline == expected_baseline, sorted(baseline))
    plm = where_used_plm(index, report)
    drawings = {index.drawing_of(index.parts[p]) for p in targets}
    c.check("PLM 수준 기준선 = 좁은 기준선 + 대상 부재의 도면", plm == expected_baseline | drawings, sorted(plm))
    scored = score_case(exact, report, index)
    beyond = scored.entities.expected - plm
    c.check(
        "2차 영향 = PLM 기준선 밖의 정답 엔터티, 엔진이 찾은 것은 그중 출력에 있는 것",
        scored.second_order.expected == beyond and scored.second_order.produced == beyond & scored.entities.produced,
    )
    other = exact.model_copy(
        update={"snapshot": exact.snapshot.model_copy(update={"snapshot_id": "G-0000000000000000"})}
    )
    c.check("다른 지도로 계산한 사례는 채점하지 않음", c.raises(lambda: score_case(other, report, index)))


# ---------- 2단계 ----------


def _amount(value: int, low: int | None = None, high: int | None = None) -> dict[str, int | None]:
    return {"value_krw": value, "low_krw": low, "high_krw": high}


def _timing(**override: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "deadline": {"kind": "by_date", "last_day": "2026-11-01"},
        "deadline_total": _amount(100),
        "next_day_total": _amount(200),
    }
    return body | override


def _cost_case(**override: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "total": _amount(100),
        "timing": _timing(),
        "verdict": {"level": "approve", "reasons": ["발주 변경·재작업 없이 도면·자재 수정 수준이에요"]},
    }
    return body | override


def _cost_contracts(c: Checker) -> None:
    c.section("평가: 2단계 기대값 계약")
    total = CaseExpectation.model_validate(_cost_case()).total
    c.check("2단계 기대값(총액·일정·판정)만 있는 기대값을 받음", total is not None)
    c.check("범위가 없으면 최소·최대 = 대표값", total is not None and (total.low, total.high) == (100, 100))
    c.check(
        "금액 범위가 최소 ≤ 대표값 ≤ 최대가 아니면 거부",
        c.raises(lambda: CaseExpectation.model_validate(_cost_case(total=_amount(100, 120, 150)))),
    )
    line = {"line_id": "R-T01:po_change:PO-1#1", "amount": _amount(10), "formula": "r × q × P"}
    c.check(
        "같은 비용 줄 ID가 둘이면 거부",
        c.raises(lambda: CaseExpectation.model_validate(_cost_case(cost_lines=[line, line]))),
    )
    c.check(
        "줄 ID가 '규칙:종류:엔터티' 형식이 아니면 거부",
        c.raises(lambda: CaseExpectation.model_validate(_cost_case(cost_lines=[line | {"line_id": "PO-1#1"}]))),
    )
    c.check(
        "구역 출구 지연 0일을 적으면 거부(0보다 큰 구역만)",
        c.raises(lambda: CaseExpectation.model_validate(_cost_case(timing=_timing(zone_exit_delays={"S-001:ZCT": 0})))),
    )
    c.check(
        "기간 안에 추가손실이 생기는데 다음 날 총액이 없으면 거부",
        c.raises(lambda: CaseExpectation.model_validate(_cost_case(timing=_timing(next_day_total=None)))),
    )
    none_in = _timing(deadline={"kind": "none_in_horizon", "last_day": "2026-12-19"})
    c.check(
        "기간 안 추가손실이 없으면 다음 날 총액을 적지 않음",
        c.raises(lambda: CaseExpectation.model_validate(_cost_case(timing=none_in)))
        and CaseExpectation.model_validate(_cost_case(timing=none_in | {"next_day_total": None})).timing is not None,
    )
    hold = {
        "po_id": "PO-1",
        "max_hold_days": 3,
        "hold_until": "2026-10-23",
        "deadline_after": {"kind": "by_date", "last_day": "2026-11-04"},
    }
    c.check(
        "같은 발주의 보류 권고가 둘이면 거부",
        c.raises(lambda: CaseExpectation.model_validate(_cost_case(timing=_timing(holds=[hold, hold])))),
    )
    base = {
        "case_id": "G2-001",
        "stage": 2,
        "title": "검사",
        "snapshot": {"generator_seed": 1, "snapshot_id": "G-0000000000000000"},
        "request": {
            "change": {
                "ecn_id": "T-1",
                "title": "검사",
                "ship_ids": ["S-001"],
                "intent": "strength",
                "ops": [{"op": "remove_part", "part_ids": ["S-001:X"]}],
            },
            "as_of": "2026-10-20",
        },
        "computed_by": "검사",
        "computed_on": "2026-10-07",
    }
    c.check(
        "2단계 사례는 총액·일정·판정 기대값으로 만들 수 있음",
        GateCase.model_validate(base | {"expected": _cost_case()}).stage == 2,
    )
    c.check(
        "2단계 사례에 판정 기대값이 없으면 거부",
        c.raises(lambda: GateCase.model_validate(base | {"expected": _cost_case(verdict=None)})),
    )
    c.check(
        "1단계 사례에 기대 영향이 없으면 거부",
        c.raises(lambda: GateCase.model_validate(base | {"case_id": "G1-001", "stage": 1, "expected": {}})),
    )


def _plain(amount: Amount) -> dict[str, int | None]:
    return _amount(amount.value, amount.low, amount.high)


def exact_expectation(result: AnalysisResult) -> dict[str, Any]:
    """분석 결과를 그대로 옮긴 기대값(채점기 검사용. 관문 정답은 엔진 코드를 보지 않는 계산자가 만든다)."""
    curve = {point.confirm_on: point for point in result.timing.curve}
    deadline = result.timing.deadline
    within = deadline.kind is not DeadlineKind.NONE_IN_HORIZON
    return {
        "cost_lines": [
            {
                "line_id": line.line_id,
                "amount": _plain(line.amount),
                "determinacy": line.determinacy.value,
                "formula": line.formula,
            }
            for line in result.cost_lines
        ],
        "total": _plain(result.total),
        "unresolved": [{"kind": u.kind.value, "entity_id": u.entity_id} for u in result.unresolved],
        "timing": {
            "zone_exit_delays": {z.zone_id: z.delay_days for z in result.schedule.zone_exits if z.delay_days > 0},
            "delivery_added_days": None
            if result.schedule.delivery is None
            else result.schedule.delivery.added_delay_days,
            "delivery_exposure": _plain(exposure) if (exposure := _exposure(result)) else None,
            "onboard": None if result.onboard is None else _onboard(result),
            "delay_ripple": None if result.delay_ripple is None else _plain(result.delay_ripple.amount),
            "deadline": deadline.model_dump(mode="json"),
            "deadline_total": _plain(curve[deadline.last_day].total),
            "next_day_total": _plain(curve[deadline.last_day + timedelta(days=1)].total) if within else None,
            "holds": [
                {
                    "po_id": h.po_id,
                    "max_hold_days": h.max_hold_days,
                    "hold_until": h.hold_until.isoformat(),
                    "deadline_after": h.deadline_after.model_dump(mode="json"),
                }
                for h in result.timing.holds
            ],
        },
        "verdict": {"level": result.verdict.level.value, "reasons": list(result.verdict.reasons)},
    }


def _exposure(result: AnalysisResult) -> Amount | None:
    return None if result.schedule.delivery is None else result.schedule.delivery.exposure


def _onboard(result: AnalysisResult) -> dict[str, Any]:
    assert result.onboard is not None
    body = result.onboard.model_dump(mode="json")
    return {**body, "total_change": _plain(result.onboard.total_change)}


def _scale(amount: dict[str, int | None], factor: float) -> dict[str, int | None]:
    return {key: None if value is None else round(value * factor) for key, value in amount.items()}


def _cost_cases(c: Checker) -> None:
    c.section("평가: 2단계 사례 입력과 채점")
    config = load_config()
    generated = generate(config)
    index = GraphIndex(generated.snapshot)
    inputs = cost_gate_inputs(generated.snapshot, generated.seed, config.scenario_date)
    c.check(
        "2단계 사례 입력 13건, ID는 G2-001부터 차례대로",
        [i.case_id for i in inputs] == [f"G2-{n:03d}" for n in range(1, 14)] and all(i.stage == 2 for i in inputs),
    )
    c.check(
        "같은 지도면 같은 2단계 사례 입력(결정적)",
        inputs == cost_gate_inputs(generated.snapshot, generated.seed, config.scenario_date),
    )
    settings = Settings.from_env({})
    book = load_rulebook(settings.rules_path)
    params = load_params(settings.params_path)
    results = [analyze(index, i.request, book, params) for i in inputs]
    rules = {line.rule_id for r in results for line in r.cost_lines}
    kinds = {line.line_id.split(":")[1] for r in results for line in r.cost_lines}
    c.check(
        "사례가 비용 규칙을 고루 건드림(자재비·발주 변경·삭제·전용·재작업·도면·용접·배관 수정·지체상금)",
        {"C-01", "R-T01", "R-M02", "R-M01", "R-B01", "R-D01", "R-T03", "R-P02", "R-P03", "R-L01"} <= rules
        and {"stock", "handling", "reorder", "collar_resize", "ld"} <= kinds,
        (sorted(rules), sorted(kinds)),
    )
    c.check(
        "사례가 판정 세 종류·마감일 두 종류·보류 권고·출구·인도 지연·판단 불가를 모두 포함",
        {r.verdict.level for r in results} == set(VerdictLevel)
        and {DeadlineKind.BY_DATE, DeadlineKind.CONFIRM_NOW} <= {r.timing.deadline.kind for r in results}
        and any(r.timing.holds for r in results)
        and any(z.delay_days > 0 for r in results for z in r.schedule.zone_exits)
        and any(r.schedule.delivery is not None and r.schedule.delivery.added_delay_days > 0 for r in results)
        and any(line.determinacy is Determinacy.STATE_UNKNOWN for r in results for line in r.cost_lines)
        and any(r.unresolved for r in results),
        [(r.verdict.level.value, r.timing.deadline.kind.value) for r in results],
    )
    c.check(
        "사례가 허용 지연(노출 금액)·선상 설치(C-03·되돌리기 선택지)·선상 설치 선택지를 포함",
        any(_exposure(r) is not None for r in results)
        and any(line.rule_id == "C-03" for r in results for line in r.cost_lines)
        and {r.onboard.direction.value for r in results if r.onboard} == {"to_on_board", "to_wait"},
    )
    c.check(
        "사례가 cost-v6 항목을 포함(도장 뒤 고정 항목 C-04 · 작업반 줄 · 지연 파급 비용 있음과 없음)",
        any(line.rule_id == "C-04" for r in results for line in r.cost_lines)
        and any("@" in line.line_id for r in results for line in r.cost_lines)
        and {r.delay_ripple is None for r in results} == {True, False},
    )

    def case_of(n: int, body: dict[str, Any]) -> GateCase:
        return GateCase(
            **inputs[n].model_dump(),
            expected=CaseExpectation.model_validate(body),
            computed_by="검사",
            computed_on=date(2026, 10, 7),
        )

    exact = [exact_expectation(r) for r in results]
    scores = [score_cost_case(case_of(n, body), results[n]) for n, body in enumerate(exact)]
    c.check(
        "결과를 그대로 옮긴 기대값이면 13건 모두 통과, 관문 통과",
        all(s.passed for s in scores) and score_cost_gate(scores, [i.case_id for i in inputs]).passed(),
        [str(m) for s in scores for m in s.mismatches][:3],
    )
    required = [i.case_id for i in inputs]
    c.check("사례가 없으면 관문 미달", not score_cost_gate([], required).passed())
    c.check(
        "통과한 사례만 있어도 필수 사례가 하나 빠지면 관문 미달(승인한 것만 채점한 경우)",
        not score_cost_gate(scores[1:], required).passed()
        and any("G2-001" in p for p in score_cost_gate(scores[1:], required).problems),
    )
    c.check(
        "같은 사례를 두 번 채점하거나 사례 입력에 없는 사례가 섞이면 관문 미달",
        not score_cost_gate([*scores, scores[0]], required).passed()
        and not score_cost_gate([*scores, CostCaseScore("G2-099", ())], required).passed(),
    )

    def items(n: int, body: dict[str, Any]) -> list[str]:
        score: CostCaseScore = score_cost_case(case_of(n, body), results[n])
        return [m.item for m in score.mismatches]

    def variant(n: int) -> dict[str, Any]:
        return {**exact[n], "timing": dict(exact[n]["timing"]), "verdict": dict(exact[n]["verdict"])}

    # 금액: 한 줄만 1.5% 바꾸면 그 줄만 불일치, 0.5%는 통과
    n = next(i for i, r in enumerate(results) if any(abs(line.amount.low) >= 1000 for line in r.cost_lines))
    target = next(i for i, line in enumerate(results[n].cost_lines) if abs(line.amount.low) >= 1000)
    line_id = results[n].cost_lines[target].line_id
    for factor, should_fail in ((1.015, True), (0.985, True), (1.005, False)):
        body = variant(n)
        body["cost_lines"] = [
            {**line, "amount": _scale(line["amount"], factor)} if i == target else line
            for i, line in enumerate(exact[n]["cost_lines"])
        ]
        found = items(n, body)
        ok = bool(found) and all(item.startswith(f"줄 {line_id}") for item in found) if should_fail else not found
        c.check(f"줄 {line_id} 금액 × {factor}: {'불일치' if should_fail else '±1% 안이라 통과'}", ok, found)
    c.check("±1% 바닥은 1원(0원 기대에 1원은 통과, 2원은 불일치)", close(0, 1) and not close(0, 2))

    body = variant(n)
    body["cost_lines"] = [line for i, line in enumerate(exact[n]["cost_lines"]) if i != target]
    c.check("기대 줄 하나를 빼면 엔진 출력의 그 줄이 '더한 줄'", items(n, body) == [f"줄 {line_id}"], items(n, body))
    body = variant(n)
    flipped = "known" if exact[n]["cost_lines"][target]["determinacy"] == "state_unknown" else "state_unknown"
    body["cost_lines"] = [
        {**line, "determinacy": flipped} if i == target else line for i, line in enumerate(exact[n]["cost_lines"])
    ]
    c.check("판단 불가 표시만 바꾸면 불일치", items(n, body) == [f"줄 {line_id} 판단"], items(n, body))

    unknown = next(i for i, r in enumerate(results) if r.unresolved)
    body = variant(unknown)
    body["unresolved"] = [{**u, "entity_id": "PO-9999#1"} for u in exact[unknown]["unresolved"]]
    c.check("계산 불가 이유의 엔터티만 바꾸면 불일치", items(unknown, body) == ["계산 불가 이유"], items(unknown, body))

    # 일정·확정 시점
    late = next(i for i, r in enumerate(results) if any(z.delay_days > 0 for z in r.schedule.zone_exits))
    body = variant(late)
    body["timing"]["zone_exit_delays"] = {z: d + 1 for z, d in exact[late]["timing"]["zone_exit_delays"].items()}
    c.check("구역 출구 지연을 하루 바꾸면 불일치", items(late, body) == ["구역 출구 지연(일)"], items(late, body))
    body = variant(late)
    body["timing"]["delivery_added_days"] = (exact[late]["timing"]["delivery_added_days"] or 0) + 1
    c.check("늘어난 인도 지연을 하루 바꾸면 불일치", items(late, body) == ["늘어난 인도 지연(일)"], items(late, body))
    exposed = next(i for i, r in enumerate(results) if _exposure(r) is not None)
    body = variant(exposed)
    body["timing"]["delivery_exposure"] = None
    c.check("노출 금액을 빼면 불일치", items(exposed, body) == ["인도 지연 노출 금액"], items(exposed, body))
    rippled = next(i for i, r in enumerate(results) if r.delay_ripple is not None)
    body = variant(rippled)
    body["timing"]["delay_ripple"] = None
    found = items(rippled, body)
    c.check("지연 파급 비용을 빼면 그 항목만 불일치(총액과 따로)", found == ["지연 파급 비용(총액 밖)"], found)
    body = variant(rippled)
    body["timing"]["delay_ripple"] = _scale(exact[rippled]["timing"]["delay_ripple"], 1.015)
    found = items(rippled, body)
    c.check(
        "지연 파급 비용만 1.5% 바꾸면 그 항목만 불일치",
        bool(found) and all(i.startswith("지연 파급 비용") for i in found),
        found,
    )
    boarded = next(i for i, r in enumerate(results) if r.onboard is not None)
    body = variant(boarded)
    body["timing"]["onboard"] = {**exact[boarded]["timing"]["onboard"], "on_board_days": 9}
    found = items(boarded, body)
    c.check(
        "선상 설치 선택지의 선상 설치 일수만 바꾸면 그 항목만 불일치",
        found == ["선상 설치 선택지 on_board_days"],
        found,
    )
    body = variant(boarded)
    body["timing"]["onboard"] = None
    c.check("선상 설치 선택지를 빼면 불일치", items(boarded, body) == ["선상 설치 선택지"], items(boarded, body))

    for key, label in (("deadline_total", "마감일("), ("next_day_total", "마감일 다음 날(")):
        body = variant(late)
        body["timing"][key] = _scale(exact[late]["timing"][key], 1.015)
        found = items(late, body)
        c.check(f"{key}만 1.5% 바꾸면 그 항목만 불일치", bool(found) and all(i.startswith(label) for i in found), found)
    body = variant(late)
    deadline = exact[late]["timing"]["deadline"]
    moved = date.fromisoformat(deadline["last_day"]) + timedelta(days=1)
    body["timing"]["deadline"] = {**deadline, "last_day": moved.isoformat()}
    c.check("마감일을 하루 바꾸면 불일치", "추가손실 0 마감일" in items(late, body), items(late, body))

    held = next(i for i, r in enumerate(results) if r.timing.holds)
    po_id = results[held].timing.holds[0].po_id
    for field, label in (("max_hold_days", "가능 기간(일)"), ("deadline_after", "뒤 마감일")):
        body = variant(held)
        changed = []
        for h in exact[held]["timing"]["holds"]:
            if field == "max_hold_days":
                changed.append({**h, "max_hold_days": h["max_hold_days"] + 1})
            else:
                day = date.fromisoformat(h["deadline_after"]["last_day"]) + timedelta(days=1)
                changed.append({**h, "deadline_after": {**h["deadline_after"], "last_day": day.isoformat()}})
        body["timing"]["holds"] = changed
        c.check(f"보류 권고의 {label}만 바꾸면 불일치", f"보류 {po_id} {label}" in items(held, body), items(held, body))
    body = variant(held)
    body["timing"]["holds"] = []
    c.check("보류 권고를 빠뜨리면 불일치", items(held, body) == ["보류 권고 발주"], items(held, body))

    # 판정
    body = variant(0)
    body["verdict"]["reasons"] = list(reversed(exact[0]["verdict"]["reasons"]))
    c.check("판정 이유 순서만 다르면 통과(문장 집합으로 비교)", not items(0, body), items(0, body))
    body = variant(0)
    body["verdict"]["reasons"] = [*exact[0]["verdict"]["reasons"][1:], verdict_rules.UNKNOWN]
    c.check("판정 이유 문장이 다르면 불일치", items(0, body) == ["판정 이유"], items(0, body))
    body = variant(0)
    body["verdict"]["level"] = "approve" if exact[0]["verdict"]["level"] != "approve" else "review"
    c.check("판정 수준이 다르면 불일치", items(0, body) == ["판정 수준"], items(0, body))

    other = case_of(0, exact[0])
    c.check(
        "다른 지도·다른 요청으로 계산한 결과는 채점하지 않음",
        c.raises(lambda: score_cost_case(other, results[1]))
        and c.raises(
            lambda: score_cost_case(
                other.model_copy(
                    update={"snapshot": other.snapshot.model_copy(update={"snapshot_id": "G-0000000000000000"})}
                ),
                results[0],
            )
        ),
    )


def _verdict_phrases(c: Checker) -> None:
    c.section("평가: 명세 8-4 판정 문장 = 엔진 문장")
    spec = (PROJECT_ROOT / "docs" / "engine.md").read_text(encoding="utf-8")
    part = spec.index("\n## 비용·일정\n")
    start = spec.index("#### 8-4. 요약 판정", part)
    end = re.compile(r"\n#{2,3} ").search(spec, start)  # 8절 끝(다음 절 또는 다음 편)
    section = spec[start : end.start() if end else len(spec)]
    rows = re.findall(r"^\| [^|]*`(warn|review|approve)` \| (\d) \| ([^|]+?) \|", section, flags=re.MULTILINE)
    documented = [(level, int(order), phrase) for level, order, phrase in rows]
    engine = [
        ("warn", 1, verdict_rules.EXIT_DELAY),
        ("warn", 2, verdict_rules.DAMAGES),
        ("warn", 3, verdict_rules.PERMISSIBLE),
        ("warn", 4, verdict_rules.ERECTION_DELAY),
        ("warn", 5, verdict_rules.LATE_REWORK),
        ("review", 1, verdict_rules.PO_CHANGE),
        ("review", 2, verdict_rules.REWORK),
        ("review", 3, verdict_rules.ON_BOARD),
        ("review", 4, verdict_rules.OVER_LIMIT),
        ("review", 5, verdict_rules.RISK_EXIT),
        ("review", 6, verdict_rules.UNKNOWN),
        ("approve", 1, verdict_rules.SMALL),
    ]
    c.check("명세 표의 수준·순서·문장이 엔진 상수와 같음(12줄)", documented == engine, documented)


# ---------- 3단계(대안 비교) ----------

_STAGE3_DOCS = ("engine.md", "domain.md", "gate_cases.md")


def exact_alt_expectation(result: AnalysisResult) -> dict[str, Any]:
    """대안 포함 분석 결과를 그대로 옮긴 3단계 기대값(채점기 검사용)."""
    rec = result.recommendation
    assert rec is not None
    return {
        "alternatives": {
            "alternatives": [
                {
                    "alt_id": a.alt_id,
                    "ops": [op.model_dump(mode="json") for op in a.ops],
                    "scope_reduced": a.scope_reduced,
                    "eligibility": {
                        "status": a.eligibility.status.value,
                        "ratio_vs_request": a.eligibility.ratio_vs_request,
                    },
                    "total": _plain(a.total),
                    "max_exit_delay_days": a.max_exit_delay_days,
                    "deadline": None if a.deadline is None else a.deadline.model_dump(mode="json"),
                    "best": None
                    if a.best_confirm_on is None or a.best_total is None
                    else {
                        "confirm_on": a.best_confirm_on.isoformat(),
                        "holds": [h.model_dump(mode="json") for h in a.best_holds],
                        "total": _plain(a.best_total),
                    },
                    "rank": a.rank,
                    "formula": "엔진 결과 그대로(채점기 검사용)",
                }
                for a in result.alternatives
            ],
            "recommendation": {
                "alt_id": rec.alt_id,
                "confirm_on": rec.confirm_on.isoformat(),
                "holds": [h.model_dump(mode="json") for h in rec.holds],
                "total": _plain(rec.total),
            },
            "cheapest_by_date": [
                {"alt_id": s.alt_id, "start": s.start.isoformat(), "end": s.end.isoformat(), "total": _plain(s.total)}
                for s in result.cheapest_by_date
            ],
            "omitted": [{"alt_id": alt, "reason": reason.value} for alt, reason in sorted(omissions(result.notes))],
        }
    }


def _alt_body(**override: Any) -> dict[str, Any]:
    """충족 요청안 + 충족 대안 + 부족 대안이 있는 최소 3단계 기대값."""
    plate = "S-001:X-PL-001"

    def alt(alt_id: str, status: str, rank: int | None, value: int) -> dict[str, Any]:
        return {
            "alt_id": alt_id,
            "ops": [{"op": "thickness", "part_ids": [plate], "from_mm": 12.0, "to_mm": 13.5}],
            "eligibility": {"status": status, "ratio_vs_request": 1.0},
            "total": _amount(value),
            "max_exit_delay_days": 0,
            "deadline": {"kind": "by_date", "last_day": "2026-11-01"},
            "best": None if rank is None else {"confirm_on": "2026-10-20", "holds": [], "total": _amount(value)},
            "rank": rank,
            "formula": "검사",
        }

    body: dict[str, Any] = {
        "alternatives": [
            alt("ALT-REQ", "meets", 2, 200),
            alt("ALT-T1", "meets", 1, 100),
            alt("ALT-T2", "short", None, 50),
        ],
        "recommendation": {"alt_id": "ALT-T1", "confirm_on": "2026-10-20", "holds": [], "total": _amount(100)},
        "cheapest_by_date": [
            {"alt_id": "ALT-T1", "start": "2026-10-20", "end": "2026-11-01", "total": _amount(100)},
            {"alt_id": "ALT-REQ", "start": "2026-11-02", "end": "2026-12-19", "total": _amount(200)},
        ],
        "omitted": [],
    }
    return body | override


def _alt_contracts(c: Checker) -> None:
    c.section("평가: 3단계 기대값 계약")
    accepted = CaseExpectation.model_validate({"alternatives": _alt_body()}).alternatives
    c.check("충족 요청안·충족 대안·부족 대안과 권고·구간이 맞는 기대값을 받음", accepted is not None)
    body = _alt_body()

    def rejects(**override: Any) -> bool:
        return c.raises(lambda: CaseExpectation.model_validate({"alternatives": body | override}))

    alts = body["alternatives"]
    c.check("요청안이 없으면 거부", rejects(alternatives=alts[1:]))
    c.check(
        "요청안이 충족(비교 기준)이 아니면 거부",
        rejects(alternatives=[alts[0] | {"eligibility": {"status": "short"}, "best": None, "rank": None}, *alts[1:]]),
    )
    c.check("같은 대안 ID가 둘이면 거부", rejects(alternatives=[*alts, alts[2]]))
    c.check(
        "부족 대안에 최적 조합·순위를 적으면 거부",
        rejects(alternatives=[*alts[:2], alts[2] | {"rank": 3, "best": alts[1]["best"]}]),
    )
    c.check("순위에 빈틈이 있으면 거부", rejects(alternatives=[alts[0] | {"rank": 3}, *alts[1:]]))
    c.check(
        "권고가 1위 대안의 최적 조합과 다르면 거부",
        rejects(recommendation=body["recommendation"] | {"alt_id": "ALT-REQ"})
        and rejects(recommendation=body["recommendation"] | {"total": _amount(101)}),
    )
    spans = body["cheapest_by_date"]
    c.check(
        "날짜별 구간에 빈틈이 있거나 이웃 구간의 대안이 같으면 거부",
        rejects(cheapest_by_date=[spans[0], spans[1] | {"start": "2026-11-03"}])
        and rejects(cheapest_by_date=[spans[0], spans[1] | {"alt_id": "ALT-T1"}]),
    )
    c.check(
        "부족 대안이 날짜별 구간에 있으면 거부", rejects(cheapest_by_date=[spans[0] | {"alt_id": "ALT-T2"}, spans[1]])
    )
    c.check(
        "만들지 않은 대안이 목록에도 있으면 거부", rejects(omitted=[{"alt_id": "ALT-T2", "reason": "no_upper_grade"}])
    )

    def with_ratio(value: float) -> list[dict[str, Any]]:
        return [alts[0], alts[1] | {"eligibility": {"status": "meets", "ratio_vs_request": value}}, alts[2]]

    c.check(
        "판정 비율이 NaN·무한대면 거부(유한한 값만)",
        rejects(alternatives=with_ratio(float("nan"))) and rejects(alternatives=with_ratio(float("inf"))),
    )
    holds = [{"po_id": "PO-0002", "hold_days": 3}, {"po_id": "PO-0001", "hold_days": 5}]
    held = [alts[0], alts[1] | {"best": alts[1]["best"] | {"holds": holds}}, alts[2]]
    same = {"alt_id": "ALT-T1", "confirm_on": "2026-10-20", "holds": holds[::-1], "total": _amount(100, 100, 100)}
    c.check(
        "같은 금액을 범위 생략형·명시형으로, 같은 보류를 다른 순서로 적어도 권고 = 1위로 받음",
        CaseExpectation.model_validate(
            {"alternatives": body | {"alternatives": held, "recommendation": same}}
        ).alternatives
        is not None,
    )
    c.check(
        "새 부재 제작 공수 줄(C-02) ID를 받음",
        ExpectedLine.model_validate(
            {"line_id": "C-02:new_work:S-001:X-NEW-1", "amount": _amount(10), "formula": "W × Σ 공수 × 단가"}
        ).line_id.startswith("C-02"),
    )
    base: dict[str, Any] = {
        "case_id": "G3-001",
        "stage": 3,
        "title": "검사",
        "snapshot": {"generator_seed": 1, "snapshot_id": "G-0000000000000000"},
        "request": {
            "change": {
                "ecn_id": "T-3",
                "title": "검사",
                "ship_ids": ["S-001"],
                "intent": "strength",
                "ops": [{"op": "thickness", "part_ids": ["S-001:X-PL-001"], "from_mm": 12, "to_mm": 13.5}],
            },
            "as_of": "2026-10-20",
            "include_alternatives": True,
        },
        "computed_by": "검사",
        "computed_on": "2026-10-08",
    }
    c.check(
        "3단계 사례는 대안 기대값만으로 만들 수 있음(2단계 총액·일정·판정 없이)",
        GateCase.model_validate(base | {"expected": {"alternatives": _alt_body()}}).stage == 3,
    )
    off = base | {
        "request": base["request"] | {"include_alternatives": False},
        "expected": {"alternatives": _alt_body()},
    }
    c.check(
        "3단계 사례에 대안 기대값이 없거나 요청이 대안을 끄면 거부",
        c.raises(lambda: GateCase.model_validate(base | {"expected": _cost_case()}))
        and c.raises(lambda: GateCase.model_validate(off)),
    )


def _alt_cases(c: Checker) -> None:
    c.section("평가: 3단계 사례 입력과 채점")
    config = load_config()
    generated = generate(config)
    index = GraphIndex(generated.snapshot)
    inputs = alt_gate_inputs(generated.snapshot, generated.seed, config.scenario_date)
    c.check(
        "3단계 사례 입력 5건, ID는 G3-001부터 차례대로, 모두 대안을 켬",
        [i.case_id for i in inputs] == [f"G3-{n:03d}" for n in range(1, 6)]
        and all(i.stage == 3 and i.request.include_alternatives for i in inputs),
    )
    c.check(
        "같은 지도면 같은 3단계 사례 입력(결정적)",
        inputs == alt_gate_inputs(generated.snapshot, generated.seed, config.scenario_date),
    )
    targets = {p for i in inputs for op in i.request.change.ops for p in getattr(op, "part_ids", ())}
    targets |= {getattr(op, "attach_to_part_id", None) or "" for i in inputs for op in i.request.change.ops}
    c.check(
        "데모 사례의 블록(B31P·F11C)은 쓰지 않음",
        not any(":B31P-" in t or ":F11C-" in t for t in targets),
        sorted(targets),
    )
    settings = Settings.from_env({})
    book = load_rulebook(settings.rules_path)
    params = load_params(settings.params_path)
    strength = load_strength(settings.strength_path)
    results = [analyze(index, i.request, book, params, strength) for i in inputs]
    alts = [a for r in results for a in r.alternatives]
    c.check(
        "사례가 템플릿 다섯·판정 세 가지·요청 종류 셋(두께·강종·보강재 추가)을 모두 건드림",
        {a.alt_id for a in alts} == {"ALT-REQ", "ALT-T1", "ALT-T2", "ALT-T3", "ALT-T4", "ALT-T5"}
        and {a.eligibility.status.value for a in alts} == {"meets", "short", "designer"}
        and {op.op for i in inputs for op in i.request.change.ops} == {"thickness", "grade", "add_part"},
        sorted({(a.alt_id, a.eligibility.status.value) for a in alts}),
    )
    c.check(
        "보류가 든 최적 조합·요청안이 아닌 권고·구간이 바뀌는 사례·만들지 않은 대안(단가 없음)이 있음",
        any(a.best_holds for a in alts)
        and any(r.recommendation is not None and r.recommendation.alt_id != "ALT-REQ" for r in results)
        and any(len(r.cheapest_by_date) >= 2 for r in results)
        and any(omissions(r.notes) for r in results),
        [(r.recommendation.alt_id if r.recommendation else None, len(r.cheapest_by_date)) for r in results],
    )

    wanted = needles(inputs, {i.case_id: r for i, r in zip(inputs, results, strict=True)})
    short = inputs[0].request.change.ops[0].model_dump()["part_ids"][0].split(":")[-1]
    value = results[0].alternatives[0].total.value
    texts = {
        "docs/a.md": f"예: {short} 판",
        "docs/b.md": f"총 {value:,}원",
        "docs/c.md": f"약 {money(value)}",
        "docs/d.md": f"{short}2 다른 판, 1{value:,}원",
    }
    leaked = find_leaks(texts, wanted)
    c.check(
        "전달본 점검: 대상 부재 ID·엔진 금액(두 표기)을 찾고, 다른 ID·숫자의 일부는 세지 않음",
        {line.split(":")[0] for line in leaked} == {"docs/a.md", "docs/b.md", "docs/c.md"},
        leaked,
    )
    shipped = {f"docs/{name}": (PROJECT_ROOT / "docs" / name).read_text(encoding="utf-8") for name in _STAGE3_DOCS}
    shipped |= {
        f"rules/{name}": (PROJECT_ROOT / "rules" / name).read_text(encoding="utf-8")
        for name in ("propagation.yaml", "strength.yaml")
    }
    shipped["params/cost_v1.yaml"] = (PROJECT_ROOT / "params" / "cost_v1.yaml").read_text(encoding="utf-8")
    c.check(
        "지금 명세·규칙·파라미터에는 3단계 사례의 ECN 번호·대상·엔진 금액이 없음(계산자가 답을 미리 못 봄)",
        not find_leaks(shipped, wanted),
        find_leaks(shipped, wanted)[:3],
    )

    def case_of(n: int, body: dict[str, Any]) -> GateCase:
        return GateCase(
            **inputs[n].model_dump(),
            expected=CaseExpectation.model_validate(body),
            computed_by="검사",
            computed_on=date(2026, 10, 8),
        )

    exact = [exact_alt_expectation(r) for r in results]
    scores = [score_alt_case(case_of(n, body), results[n]) for n, body in enumerate(exact)]
    c.check(
        "결과를 그대로 옮긴 기대값이면 5건 모두 통과, 관문 통과",
        all(s.passed for s in scores) and score_cost_gate(scores, [i.case_id for i in inputs]).passed(),
        [str(m) for s in scores for m in s.mismatches][:3],
    )

    def items(n: int, body: dict[str, Any]) -> list[str]:
        return [m.item for m in score_alt_case(case_of(n, body), results[n]).mismatches]

    def variant(n: int) -> dict[str, Any]:
        inner = exact[n]["alternatives"]
        return {
            "alternatives": {
                **inner,
                "alternatives": [dict(a) for a in inner["alternatives"]],
                "recommendation": dict(inner["recommendation"]),
                "cheapest_by_date": [dict(s) for s in inner["cheapest_by_date"]],
            }
        }

    def where(n: int, alt_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        body = variant(n)
        return body, next(a for a in body["alternatives"]["alternatives"] if a["alt_id"] == alt_id)

    def find(alt_id: str, test: Any) -> int:
        return next(n for n, r in enumerate(results) for a in r.alternatives if a.alt_id == alt_id and test(a))

    # 판정 비율: ±0.001 밖이면 불일치, 상태만 바꿔도 불일치
    n = find("ALT-T1", lambda a: a.eligibility.ratio_vs_request is not None)
    for delta, should_fail in ((0.002, True), (0.0005, False)):
        body, alt = where(n, "ALT-T1")
        alt["eligibility"] = {**alt["eligibility"], "ratio_vs_request": alt["eligibility"]["ratio_vs_request"] + delta}
        found = items(n, body)
        ok = found == ["대안 ALT-T1 판정 비율"] if should_fail else not found
        c.check(f"판정 비율 {delta:+}: {'불일치' if should_fail else '±0.001 안이라 통과'}", ok, found)
    n = find("ALT-T2", lambda a: a.eligibility.status.value == "short")
    body, alt = where(n, "ALT-T2")
    alt["eligibility"] = {"status": "designer", "ratio_vs_request": None}
    c.check(
        "판정 상태만 바꾸면 판정·비율 불일치",
        items(n, body) == ["대안 ALT-T2 판정", "대안 ALT-T2 판정 비율"],
        items(n, body),
    )

    # 연산: 보강재 중량 0.001t 차이, 대안 빠짐
    n = find("ALT-T1", lambda a: a.eligibility.status.value == "meets")
    body, alt = where(n, "ALT-T1")
    alt["ops"] = [{**op, "qty": round(op["qty"] + 0.001, 3)} for op in alt["ops"]]
    c.check("보강재 중량(qty)이 0.001t 다르면 연산 불일치", items(n, body) == ["대안 ALT-T1 연산"], items(n, body))
    n = find("ALT-T5", lambda a: True)
    body = variant(n)
    body["alternatives"]["alternatives"] = [a for a in body["alternatives"]["alternatives"] if a["alt_id"] != "ALT-T5"]
    c.check("기대 대안 하나를 빼면 엔진의 그 대안이 '더한 대안'", items(n, body) == ["대안 ALT-T5"], items(n, body))

    # 금액·일정: 설계자 확인 대안도 총액·마감일·출구 지연을 채점
    n = find("ALT-T4", lambda a: a.eligibility.status.value == "designer")
    for factor, should_fail in ((1.015, True), (1.005, False)):
        body, alt = where(n, "ALT-T4")
        alt["total"] = _scale(alt["total"], factor)
        found = items(n, body)
        ok = bool(found) and all(i.startswith("대안 ALT-T4 총액") for i in found) if should_fail else not found
        c.check(f"설계자 확인 대안 총액 × {factor}: {'불일치' if should_fail else '통과'}", ok, found)
    body, alt = where(n, "ALT-T4")
    moved = date.fromisoformat(alt["deadline"]["last_day"]) + timedelta(days=1)
    alt["deadline"] = {**alt["deadline"], "last_day": moved.isoformat()}
    alt["max_exit_delay_days"] += 1
    c.check(
        "대안의 마감일·출구 지연을 하루 바꾸면 불일치",
        sorted(items(n, body)) == ["대안 ALT-T4 구역 출구 지연(일)", "대안 ALT-T4 추가손실 0 마감일"],
        items(n, body),
    )

    # 최적 조합: 2위 대안의 확정일, 1위 대안의 보류 일수(권고도 함께)
    n = find("ALT-REQ", lambda a: a.rank == 2)
    body, alt = where(n, "ALT-REQ")
    later = date.fromisoformat(alt["best"]["confirm_on"]) + timedelta(days=1)
    alt["best"] = {**alt["best"], "confirm_on": later.isoformat()}
    c.check(
        "2위 대안의 최적 확정일을 하루 바꾸면 불일치", items(n, body) == ["대안 ALT-REQ 최적 확정일"], items(n, body)
    )
    n = find("ALT-REQ", lambda a: a.rank == 1 and bool(a.best_holds))
    body, alt = where(n, "ALT-REQ")
    held = [{**h, "hold_days": h["hold_days"] + 1} for h in alt["best"]["holds"]]
    alt["best"] = {**alt["best"], "holds": held}
    body["alternatives"]["recommendation"]["holds"] = held
    c.check(
        "최적 보류 일수를 하루 바꾸면 대안과 권고 모두 불일치",
        items(n, body) == ["대안 ALT-REQ 최적 보류", "권고 보류"],
        items(n, body),
    )

    # 권고: 1·2위를 맞바꾸고 권고도 바꾼 기대값(계약은 통과, 채점은 불일치)
    n = next(i for i, r in enumerate(results) if r.recommendation and r.recommendation.alt_id != "ALT-REQ")
    body = variant(n)
    listed = body["alternatives"]["alternatives"]
    first = next(a for a in listed if a["rank"] == 1)
    second = next(a for a in listed if a["rank"] == 2)
    first["rank"], second["rank"] = 2, 1
    body["alternatives"]["recommendation"] = {"alt_id": second["alt_id"], **second["best"]}
    found = items(n, body)
    c.check(
        "권고 대안이 다르면 순위·권고가 불일치",
        {f"대안 {first['alt_id']} 순위", f"대안 {second['alt_id']} 순위", "권고 대안·확정일"} <= set(found),
        found,
    )

    # 날짜별 구간: 시작일 총액, 경계 하루
    n = next(i for i, r in enumerate(results) if len(r.cheapest_by_date) >= 2)
    for factor, should_fail in ((1.02, True), (1.005, False)):
        body = variant(n)
        first_span = body["alternatives"]["cheapest_by_date"][0]
        first_span["total"] = _scale(first_span["total"], factor)
        found = items(n, body)
        ok = bool(found) and all(i.startswith("구간 ") for i in found) if should_fail else not found
        c.check(f"구간 시작일 총액 × {factor}: {'불일치' if should_fail else '통과'}", ok, found)
    body = variant(n)
    spans = body["alternatives"]["cheapest_by_date"]
    shifted = date.fromisoformat(spans[0]["end"]) - timedelta(days=1)
    spans[0]["end"] = shifted.isoformat()
    spans[1]["start"] = (shifted + timedelta(days=1)).isoformat()
    c.check("구간 경계를 하루 바꾸면 불일치", items(n, body) == ["날짜별 최저 비용 대안 구간"], items(n, body))

    # 만들지 않은 대안과 이유, 채점기가 찾는 엔진 문구
    n = next(i for i, r in enumerate(results) if omissions(r.notes))
    body = variant(n)
    body["alternatives"]["omitted"] = []
    c.check("만들지 않은 대안을 빠뜨리면 불일치", items(n, body) == ["만들지 않은 대안"], items(n, body))
    engine_dir = PROJECT_ROOT / "ripple" / "engine" / "alternatives"
    templates_src = (engine_dir / "templates.py").read_text(encoding="utf-8")
    compare_src = (engine_dir / "compare.py").read_text(encoding="utf-8")
    c.check(
        "채점기가 찾는 안내 문구·대안 라벨이 엔진 코드에 그대로 있음(문구가 바뀌면 이 검사가 알림)",
        all(pattern.search(templates_src) for pattern, _, _ in SKIPPED)
        and ": 지도와 맞지 않아 제외" in compare_src
        and all(f'label=f"{prefix}(' in templates_src for prefix, _ in LABEL_PREFIXES),
    )
    other = case_of(0, exact[0])
    n = find("ALT-T1", lambda a: a.eligibility.ratio_vs_request is not None)
    nan_check = {"ratio_vs_request": float("nan")}
    nan_ratio = results[n].model_copy(
        update={
            "alternatives": tuple(
                a.model_copy(update={"eligibility": a.eligibility.model_copy(update=nan_check)})
                if a.alt_id == "ALT-T1"
                else a
                for a in results[n].alternatives
            )
        }
    )
    found = [m.item for m in score_alt_case(case_of(n, exact[n]), nan_ratio).mismatches]
    c.check(
        "엔진 판정 비율이 NaN이면 불일치(허용 오차 비교를 그냥 통과하지 않음)",
        found == ["대안 ALT-T1 판정 비율"],
        found,
    )
    c.check("다른 요청으로 계산한 결과는 채점하지 않음", c.raises(lambda: score_alt_case(other, results[1])))
