"""비용 구분: 추가 공수 · 추가 재료비(docs/engine.md(비용·일정) 4-12, 계약 1.35.0). 새 계산은 없다.

- 모든 비용 줄에 구분·세부 구분이 있고(빠진 줄 없음), 세부 구분이 규칙 표(명세 4-12 표)와 맞는다.
- 공수 줄에만 공수(MH)가 있다.
- 공수(MH)는 그 줄 금액을 만든 시간: 입력 hours가 있는 줄은 대표값이 그 값과 같고, 인건비 키가 하나인 줄은
  시나리오마다 공수 × 같은 시나리오 단가 = 금액(반올림 오차 안). 금액 ÷ 임률 역산이 아니라 계산 경로의 시간이다
  (재작업은 공정마다 단가가 달라도 입력 hours와 같다).
- 공수 + 재료비 + 지체상금 = 총액(최소·대표·최대), 지체상금 줄이 없으면 공수 + 재료비 = 총액. 재료비 = 자재 차이 + 구매.
- 확정일을 늦춰 단계가 진행된 경우·단계를 모르는 줄(판단 불가)에도 같은 성질.
- 옛 기록(1.34.0 — 필드 없음)이 읽히고 None, 다시 직렬화해도 필드가 생기지 않아 기록 ID가 그대로다.
- 계약 검사가 어긋난 구분·합을 거절한다. 화면·엑셀 이름표가 같은 말이다.
"""

from __future__ import annotations

import json
from datetime import timedelta

from harness import Checker

from checks.labels import ts_record
from ripple.brief.lines import change_line
from ripple.brief.text import hours_text
from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import Settings
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.params import ParamSet
from ripple.contracts.result import (
    COST_ITEM_KIND,
    PURCHASE_ITEMS,
    Amount,
    AnalysisResult,
    CostItem,
    CostKind,
    CostLine,
    Determinacy,
    WorkHours,
)
from ripple.engine.analyze import analyze
from ripple.engine.cost.amounts import worst_case, worst_hours
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.explain.format import money
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.ingest.out_labels import COST_ITEM, COST_KIND
from ripple.store.records.identity import text_record_id

CASES = 120
LATER_DAYS = 45  # 확정일을 늦춘 두 번째 묶음(단계가 진행돼 재작업·도장 뒤·판단 불가 줄이 생기게)
RATE = "labor_rate_per_hour."
EXPECTED_ITEM: dict[tuple[str, str], CostItem] = {
    ("R-B01", "rework"): CostItem.REWORK,
    ("C-02", "new_work"): CostItem.NEW_WORK,
    ("C-03", "onboard"): CostItem.ONBOARD,
    ("C-04", "after_paint"): CostItem.AFTER_PAINT,
    ("R-T02", "taper"): CostItem.MACHINING,
    ("R-T04", "collar_resize"): CostItem.MACHINING,
    ("R-P02", "collar_resize"): CostItem.MACHINING,
    ("R-P01", "modify_part"): CostItem.MACHINING,
    ("R-P02", "modify_part"): CostItem.MACHINING,
    ("R-P03", "modify_part"): CostItem.MACHINING,
    ("R-T03", "weld_recheck"): CostItem.WELD,
    ("R-D01", "drawing_revision"): CostItem.DRAWING,
    ("C-01", "material"): CostItem.MATERIAL_DIFF,
    ("R-M01", "stock"): CostItem.STOCK,
    ("R-T01", "po_change"): CostItem.PO_CHANGE,
    ("R-M02", "po_change"): CostItem.PO_CHANGE,
    ("R-T01", "reorder"): CostItem.REORDER,
    ("R-M01", "handling"): CostItem.TRANSFER,
    ("R-L01", "ld"): CostItem.LIQUIDATED_DAMAGES,
}
"""(규칙, 줄 ID 둘째 칸) → 세부 구분(명세 4-12 표를 손으로 옮긴 것 — 엔진 코드를 읽지 않음)."""


def run(c: Checker) -> None:
    c.section("비용 구분: 추가 공수 · 추가 재료비(명세 4-12)")
    generated = generate(load_config())
    settings = Settings.from_env({})
    book, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    index = GraphIndex(generated.snapshot)
    results: list[AnalysisResult] = []
    for ecn in generated.ecns[:CASES]:
        for later, on_board in ((0, False), (LATER_DAYS, False), (0, True)):
            request = AnalysisRequest(
                change=ecn.change,
                as_of=ecn.as_of,
                confirm_on=ecn.as_of + timedelta(days=later),
                outfit_on_board=on_board,
            )
            try:
                results.append(analyze(index, request, book, params))
            except RequestError:
                continue
    lines = [line for r in results for line in r.cost_lines]
    _items(c, lines)
    _hours(c, lines, params)
    _sums(c, results)
    _coverage(c, lines)
    _compat(c, results)
    _brief(c, results)
    _contract(c)
    _labels(c)


def _items(c: Checker, lines: list[CostLine]) -> None:
    missing = [line.line_id for line in lines if line.kind is None or line.item is None]
    c.check("모든 비용 줄에 구분·세부 구분 있음(빠진 줄 없음)", not missing, missing[:3])
    wrong = [
        (line.line_id, line.item)
        for line in lines
        if EXPECTED_ITEM.get((line.rule_id, line.line_id.split(":")[1])) is not line.item
        or (line.item is not None and COST_ITEM_KIND[line.item] is not line.kind)
    ]
    c.check("세부 구분 = 명세 4-12 표(규칙·줄 종류별), 구분 = 세부 구분의 구분", not wrong, wrong[:3])
    hours_wrong = [line.line_id for line in lines if (line.hours is not None) != (line.kind is CostKind.LABOR)]
    c.check("공수(MH)는 공수 줄에만", not hours_wrong, hours_wrong[:3])


def _hours(c: Checker, lines: list[CostLine], params: ParamSet) -> None:
    labor = [line for line in lines if line.hours is not None]
    written = [
        line.line_id
        for line in labor
        if isinstance(line.inputs.get("hours"), int | float)
        and line.hours is not None
        and line.hours.value != line.inputs["hours"]
    ]
    c.check("입력 hours가 있는 공수 줄: 공수 대표값 = 그 줄 계산에 쓴 시간(inputs.hours)", not written, written[:3])
    checked, off = 0, []
    for line in labor:
        rates = [key for key in line.param_keys if key.startswith(RATE)]
        if len(rates) != 1 or line.hours is None:
            continue
        rate = params.get(rates[0])
        checked += 1
        for hours, rate_value, amount in (
            (line.hours.low, rate.low, line.amount.low),
            (line.hours.value, rate.value, line.amount.value),
            (line.hours.high, rate.high, line.amount.high),
        ):
            # 공수는 셋째 자리 반올림, 금액은 공정 몫마다 원 단위 반올림(재작업은 공정 일곱 몫까지)
            if abs(hours * rate_value - amount) > 0.0005 * rate_value + 8:
                off.append((line.line_id, hours, rate_value, amount))
    c.check(
        f"인건비 키가 하나인 공수 줄 {checked}개: 시나리오마다 공수 × 같은 시나리오 단가 = 금액(반올림 오차 안)",
        checked > 0 and not off,
        off[:3],
    )
    ordered = [
        line.line_id for line in labor if line.hours and not line.hours.low <= line.hours.value <= line.hours.high
    ]
    c.check("공수 최소 ≤ 대표 ≤ 최대", not ordered, ordered[:3])


def _sums(c: Checker, results: list[AnalysisResult]) -> None:
    wrong: list[str | None] = []
    plain = 0
    for r in results:
        s = r.cost_split
        if s is None:
            wrong.append(r.request.change.ecn_id)
            continue
        if Amount.total([s.labor, s.material, s.damages]) != r.total or s.material != Amount.total(
            [s.material_diff, s.purchase]
        ):
            wrong.append(r.request.change.ecn_id)
        if s.damages == Amount.exact(0):
            plain += 1
            if Amount.total([s.labor, s.material]) != r.total:
                wrong.append(r.request.change.ecn_id)
        labor = Amount.total([line.amount for line in r.cost_lines if line.kind is CostKind.LABOR])
        purchase = Amount.total([line.amount for line in r.cost_lines if line.item in PURCHASE_ITEMS])
        hours = sum(line.hours.value for line in r.cost_lines if line.hours is not None)
        if (
            labor != s.labor
            or purchase != s.purchase
            or abs(hours - s.labor_hours.value) > 0.001 * len(r.cost_lines) + 0.001
        ):
            wrong.append(r.request.change.ecn_id)
    c.check(
        f"분석 {len(results)}건: 공수 + 재료비 + 지체상금 = 총액(최소·대표·최대) · 재료비 = 자재 차이 + 구매 · "
        f"지체상금 없는 {plain}건은 공수 + 재료비 = 총액 · 공수(MH) = 공수 줄 합",
        bool(results) and not wrong,
        wrong[:3],
    )


def _coverage(c: Checker, lines: list[CostLine]) -> None:
    """묶음이 실제로 여러 세부 구분·판단 불가 공수 줄을 지나갔나(검사가 빈 집합에서 통과하지 않게)."""
    seen = {line.item for line in lines}
    unknown = [line for line in lines if line.hours is not None and line.determinacy is Determinacy.STATE_UNKNOWN]
    need = {CostItem.REWORK, CostItem.MACHINING, CostItem.WELD, CostItem.DRAWING, CostItem.MATERIAL_DIFF}
    need |= {CostItem.PO_CHANGE, CostItem.REORDER}
    c.check(
        f"검사 묶음이 세부 구분 {len(seen)}가지·판단 불가 공수 줄 {len(unknown)}개를 지남"
        "(재작업·가공·용접·도면·자재 차이·발주 변경·할증 포함)",
        need <= seen,
        sorted(str(i) for i in need - seen),
    )


def _compat(c: Checker, results: list[AnalysisResult]) -> None:
    """옛 기록(1.34.0 — 줄 구분·공수·구분별 합 없음): 읽히면 None, 다시 직렬화해도 필드가 생기지 않아 기록 ID가 같다."""
    sample = next(r for r in results if r.cost_split is not None and r.cost_lines)
    body = json.loads(sample.model_dump_json())
    body.pop("cost_split")
    for line in body["cost_lines"]:
        for key in ("kind", "item", "hours"):
            line.pop(key, None)
    old = AnalysisResult.model_validate(body)
    again = json.loads(old.model_dump_json())
    c.check(
        "옛 기록(구분 필드 없음)이 읽히고 None · 다시 직렬화해도 필드가 생기지 않음",
        old.cost_split is None
        and all(line.kind is None and line.hours is None for line in old.cost_lines)
        and again == body,
    )
    # 기록 ID = 저장된 본문 글자의 정규 JSON 해시: 옛 본문과 새 코드로 읽어 다시 쓴 본문의 해시가 같아야 한다
    c.check(
        "옛 본문의 기록 ID = 새 코드로 읽어 다시 직렬화한 본문의 기록 ID",
        text_record_id(json.dumps({"result": body}, ensure_ascii=False))
        == text_record_id(json.dumps({"result": again}, ensure_ascii=False)),
    )
    schema = AnalysisResult.model_json_schema(mode="serialization")
    line_schema = schema["$defs"]["CostLine"]
    c.check(
        "응답 스키마: cost_split·줄 kind·item·hours는 필수도 기본값도 아님(화면 타입에서 '없을 수 있음')",
        "cost_split" not in schema.get("required", [])
        and "default" not in schema["properties"]["cost_split"]
        and all(
            name not in line_schema.get("required", []) and "default" not in line_schema["properties"][name]
            for name in ("kind", "item", "hours")
        ),
    )


def _brief(c: Checker, results: list[AnalysisResult]) -> None:
    """결정 도우미 '바뀌는 것' 줄: 총변경비용 뒤 고정 문장 '추가 공수 n MH · 재료비 ○○만원'
    (옛 기록은 총변경비용까지)."""
    sample = results[0]
    split = sample.cost_split
    text = change_line(sample).text
    old = sample.model_copy(update={"cost_split": None})
    c.check(
        "결정 도우미 바뀌는 것 줄: '… · 총변경비용 … · 추가 공수 n MH · 재료비 ○○만원'(값 = 구분별 합) · "
        "옛 기록은 총변경비용까지",
        split is not None
        and text.endswith(
            f" · 추가 공수 {hours_text(split.labor_hours.value)} MH · 재료비 {money(split.material.value)}"
        )
        and "추가 공수" not in change_line(old).text,
        text,
    )
    c.check(
        "공수 표기: 100 이상은 정수(쉼표) · 그 아래는 소수 첫째 자리(화면 formatHours와 같은 규칙)",
        (hours_text(806.861), hours_text(1660.719), hours_text(21.265), hours_text(16.0), hours_text(0.5))
        == ("807", "1,661", "21.3", "16", "0.5"),
    )


def _contract(c: Checker) -> None:
    base = {
        "line_id": "R-T03:weld_recheck:P1",
        "rule_id": "R-T03",
        "entity_id": "P1",
        "label": "용접 재검토",
        "formula": "0.5시간 × 인건비",
        "inputs": {"count": 1},
        "amount": {"value": 21000, "low": 10500, "high": 42000},
    }
    hours = {"value": 0.5, "low": 0.25, "high": 1.0}
    rejected = 0
    for broken in (
        {**base, "kind": "labor"},  # 세부 구분 없음
        {**base, "kind": "material", "item": "weld", "hours": hours},  # 세부 구분과 구분 불일치
        {**base, "kind": "labor", "item": "weld"},  # 공수 줄인데 공수 없음
        {**base, "kind": "material", "item": "po_change", "hours": hours},  # 재료비 줄에 공수
    ):
        try:
            CostLine.model_validate(broken)
        except ValueError:
            rejected += 1
    good = CostLine.model_validate({**base, "kind": "labor", "item": "weld", "hours": hours})
    try:
        WorkHours(value=1.0, low=2.0, high=3.0)
    except ValueError:
        rejected += 1
    c.check(
        "계약 검사: 구분만·세부 구분 불일치·공수 없는 공수 줄·재료비 줄의 공수·순서 틀린 공수는 거절, 맞으면 받음",
        rejected == 5 and good.hours is not None,
        rejected,
    )
    # 단계를 모르는 공수 줄(합성 지도에는 거의 없음): 금액 worst_case와 같은 짝 — 대표 = 금액 대표값을 만든 단계의 공수,
    # 최소 = 단계별 최소의 최솟값, 최대 = 단계별 최대의 최댓값
    early, late = WorkHours(value=1.0, low=0.5, high=2.0), WorkHours(value=3.0, low=1.0, high=6.0)
    early_won, late_won = Amount(value=50, low=25, high=100), Amount(value=150, low=50, high=300)
    money, work = worst_case([early_won, late_won]), worst_hours([early, late], late)
    c.check(
        "판단 불가 공수 = 금액 판단 불가 규칙과 같은 짝(대표 = 금액 대표값의 단계 · 최소의 최솟값 · 최대의 최댓값)",
        (work.value, work.low, work.high) == (3.0, 0.5, 6.0) and (money.value, money.low, money.high) == (150, 25, 300),
        work,
    )


def _labels(c: Checker) -> None:
    web_kinds = ts_record("costSplit.ts", "COST_KIND_NAMES")
    web_items = ts_record("costSplit.ts", "COST_ITEM_NAMES")
    c.check(
        "이름표: 구분·세부 구분 이름이 계약 값을 모두 덮고 엑셀(out_labels)과 화면 lib/costSplit.ts가 같음",
        set(COST_KIND) == {k.value for k in CostKind}
        and set(COST_ITEM) == {i.value for i in CostItem}
        and web_kinds == COST_KIND
        and web_items == COST_ITEM,
        (web_kinds, web_items),
    )
