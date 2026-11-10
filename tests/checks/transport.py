"""외자재 운송 리드타임(계약 1.33.0 · 엔진 0.11.0 · cost-v7 · 생성기 v4 · actuals-v4).

명세는 docs/engine.md(비용·일정) 5절·6-6.

- 계약: 운송 방식은 외자재 규격에만(외자재면 꼭), 비면 지도 ID 정규형에서 뺀다.
- 엔진: 새 발주 LT'가 생산 리드타임(새 규격 표준·파라미터)이고 사는 규격이 외자재일 때만 운송 일수를 더한다. 원래 발주의
  리드타임은 운송 포함이라 더하지 않는다. 급발주 배율·일정 위험 배율은 생산분에만, 일정 위험은 운송 범위 끝을 더한다.
- 숨긴 모델: 같은 규칙(참 운송 일수, 리드타임 변동은 생산분에만).
- 생성기 v4: 평형수 밸브·두 계통 펌프 규격만 외자재, 화물 스트리핑 밸브(관문 2단계·시연 1)는 국산, 그 밖은 v3 그대로.
"""

from __future__ import annotations

import io
import math
from collections import defaultdict
from dataclasses import replace
from datetime import date, timedelta

from fixtures import snapshot, snapshot_body
from harness import Checker

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.change import AddPart, ChangeRequest, EquipmentSpecChange, ThicknessChange
from ripple.contracts.domain import ASSUMED_TRANSPORT_NOTE, GraphSnapshot, MaterialSpec, Part, PartKind
from ripple.contracts.identity import snapshot_id
from ripple.contracts.ingest import IssueSeverity
from ripple.contracts.params import ParamSet
from ripple.contracts.result import TransportLeg
from ripple.contracts.rulebook import RuleBook
from ripple.engine.analyze import analyze
from ripple.engine.cost.amounts import Params
from ripple.engine.cost.demand import lead_ratios, transport_days
from ripple.engine.index import GraphIndex
from ripple.engine.timing import Evaluator
from ripple.generator.actuals import HiddenModel
from ripple.generator.actuals.material import material_change
from ripple.generator.actuals.schedule import demand_dates
from ripple.generator.build import Generated, generate
from ripple.generator.io import load_config
from ripple.ingest.build import build
from ripple.ingest.export import to_bytes, to_workbook
from ripple.ingest.workbook import read_workbook

PARAMS_PATH = PROJECT_ROOT / "params" / "cost_v1.yaml"
SEA, AIR = (30, 35), (10, 14)  # (대표, 범위 끝) — params transport_days


def run(c: Checker) -> None:
    _contract(c)
    generated = generate(load_config())
    params = load_params(PARAMS_PATH)
    book = load_rulebook(PROJECT_ROOT / "rules" / "propagation.yaml")
    _engine(c, generated, params, book)
    _matching(c, generated, params, book)
    _assumed(c, generated, params, book)
    _hidden(c, generated)
    _generator(c, generated)


def _blank(snap: GraphSnapshot, spec_id: str) -> GraphSnapshot:
    """외자재 규격 하나의 운송 방식만 비운 지도(원산지 외자재는 그대로)."""
    specs = tuple(s.model_copy(update={"transport": None}) if s.spec_id == spec_id else s for s in snap.specs)
    draft = snap.model_copy(update={"specs": specs})
    return draft.model_copy(update={"snapshot_id": snapshot_id(draft)})


def _assumed(c: Checker, generated: Generated, params: ParamSet, book: RuleBook) -> None:
    c.section("외자재: 운송 방식이 빈 외자재는 선박으로 가정 — 비용 줄·일정 위험·안내·가져오기 경고에 남김")
    snap = generated.snapshot
    valve, other, _ = _targets(snap)
    blank = _blank(snap, other)
    op = EquipmentSpecChange(part_ids=(valve.part_id,), from_spec_id=valve.spec_id, to_spec_id=other)
    request = AnalysisRequest(change=_change("T-BLANK", op), as_of=generated.ecns[0].as_of)
    sea_index, blank_index = GraphIndex(snap), GraphIndex(blank)
    shown, assumed = analyze(sea_index, request, book, params), analyze(blank_index, request, book, params)
    line = next((ln for ln in assumed.cost_lines if ln.line_id == f"C-01:material:{valve.part_id}"), None)
    legs = (
        shown.schedule.risk.transport if shown.schedule.risk else (),
        assumed.schedule.risk.transport if assumed.schedule.risk else (),
    )
    c.check(
        "운송 방식이 비면 선박과 같은 도착일(대표·위험), 일정 위험 운송 일수에 '가정' 표시, 자재비 줄 이유·안내에 "
        f"'{ASSUMED_TRANSPORT_NOTE}'(적어 둔 선박이면 없음)",
        _arrival(blank_index, request, book, params, False) == _arrival(sea_index, request, book, params, False)
        and _arrival(blank_index, request, book, params, True) == _arrival(sea_index, request, book, params, True)
        and legs == ((TransportLeg(mode="sea", days=SEA[1]),), (TransportLeg(mode="sea", days=SEA[1], assumed=True),))
        and line is not None
        and ASSUMED_TRANSPORT_NOTE in (line.reason or "")
        and any(ASSUMED_TRANSPORT_NOTE in note for note in assumed.notes)
        and not any(ASSUMED_TRANSPORT_NOTE in note for note in shown.notes)
        and all(ASSUMED_TRANSPORT_NOTE not in (ln.reason or "") for ln in shown.cost_lines),
        (legs, None if line is None else line.reason),
    )
    raw = read_workbook(to_bytes(blank))
    got, summary = build(raw, "blank.xlsx")
    warned = [i for i in summary.issues if i.severity is IssueSeverity.WARNING and i.column == "운송 방식"]
    c.check(
        "엑셀 가져오기: 원산지 외자재·운송 방식 빈칸이면 막지 않고(지도 만듦) 그 행에 '선박으로 가정' 경고 한 줄",
        got is not None
        and len(warned) == 1
        and other in warned[0].message
        and "선박" in warned[0].message
        and got.specs == blank.specs,
        [i.message for i in summary.issues if i.severity is IssueSeverity.ERROR][:2],
    )
    hidden = [
        _hidden_arrivals(replace(generated, snapshot=world), _change("T-BLANK", op), True) for world in (snap, blank)
    ]
    c.check(
        "숨긴 모델도 운송 방식이 빈 외자재를 선박으로(확인 모드 도착일이 선박과 같음)", hidden[0] == hidden[1], hidden
    )
    _not_waited(c, blank, valve.part_id, request, book, params)
    _origin_blank(c, snap, other, request, book, params)


def _not_waited(
    c: Checker, blank: GraphSnapshot, part_id: str, request: AnalysisRequest, book: RuleBook, params: ParamSet
) -> None:
    """운송 문구는 도착일을 실제로 계산한 수요에서만(E3): 공급 발주 품목이 없어 일정 제약을 두지 않은 부재는 가정
    문장·안내가 없다. 운송 일수 파라미터가 빠지면 평가기를 만들 때 바로 막는다(E-제안1)."""
    lines = tuple(ln for ln in blank.po_lines if part_id not in ln.part_ids)
    draft = blank.model_copy(update={"po_lines": lines})
    loose = draft.model_copy(update={"snapshot_id": snapshot_id(draft)})
    result = analyze(GraphIndex(loose), request, book, params)
    line = next((ln for ln in result.cost_lines if ln.line_id == f"C-01:material:{part_id}"), None)
    c.check(
        "운송 방식이 빈 외자재라도 공급 발주 품목이 없어 도착일을 계산하지 않은 부재는 자재비 줄 이유·안내에 "
        f"'{ASSUMED_TRANSPORT_NOTE}'·'운송 일수 가산'이 없음(일정 위험 운송 일수도 없음)",
        line is not None
        and "운송 일수" not in (line.reason or "")
        and not any(ASSUMED_TRANSPORT_NOTE in note for note in result.notes)
        and any("일정 제약 미적용" in note for note in result.notes)
        and (result.schedule.risk is None or result.schedule.risk.transport == ()),
        (None if line is None else line.reason, result.notes),
    )
    sea_less = params.model_copy(
        update={"params": {k: v for k, v in params.params.items() if k != "transport_days.sea"}}
    )
    refused = c.raises(lambda: Evaluator(GraphIndex(blank), request, book, sea_less), ValueError)
    c.check(
        "파라미터에 transport_days.sea가 없으면 평가기를 만들 때 ValueError(외자재 수요를 만나서야 KeyError가 아니라)",
        refused,
    )


def _spec_cells(snap: GraphSnapshot, spec_id: str, origin: str | None) -> bytes:
    """지정 양식 엑셀에서 규격 하나의 '원산지 구분' 칸만 바꾼 파일(None = 빈칸)."""
    workbook = to_workbook(snap)
    sheet = workbook["규격"]
    titles = [cell.value for cell in sheet[1]]
    column = titles.index("원산지 구분") + 1
    row = next(
        r for r in range(2, sheet.max_row + 1) if sheet.cell(row=r, column=titles.index("규격ID") + 1).value == spec_id
    )
    sheet.cell(row=row, column=column).value = origin
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _origin_blank(
    c: Checker, snap: GraphSnapshot, spec_id: str, request: AnalysisRequest, book: RuleBook, params: ParamSet
) -> None:
    """원산지가 비고 운송 방식만 있으면 외자재로 읽음(경고), 국산인데 운송 방식이 있으면 오류 그대로."""
    got, summary = build(read_workbook(_spec_cells(snap, spec_id, None)), "origin-blank.xlsx")
    warned = [i for i in summary.issues if i.severity is IssueSeverity.WARNING and i.column == "원산지 구분"]
    spec = None if got is None else next(s for s in got.specs if s.spec_id == spec_id)
    c.check(
        "엑셀 가져오기: 원산지 빈칸·운송 방식 선박이면 막지 않고 외자재로 읽음 + 그 행에 '원산지 없음 → "
        "운송 방식이 있어 외자재로 간주' 경고 한 줄, 계산 결과(도착일·일정 위험)는 원산지를 적은 지도와 같음",
        got is not None
        and spec is not None
        and (spec.origin, spec.transport) == ("import", "sea")
        and len(warned) == 1
        and "원산지 없음 → 운송 방식이 있어 외자재로 간주" in warned[0].message
        and _arrival(GraphIndex(got), request, book, params, False)
        == _arrival(GraphIndex(snap), request, book, params, False)
        and _arrival(GraphIndex(got), request, book, params, True)
        == _arrival(GraphIndex(snap), request, book, params, True),
        [i.message for i in summary.issues if i.severity is IssueSeverity.ERROR][:2],
    )
    refused, problem = build(read_workbook(_spec_cells(snap, spec_id, "국산")), "domestic-shipped.xlsx")
    errors = [i for i in problem.issues if i.severity is IssueSeverity.ERROR]
    wrong = [i for i in errors if "운송 방식은 외자재 규격에만" in i.message]
    c.check(
        "국산인데 운송 방식이 적힌 규격 행은 그대로 오류(지도를 만들지 않음) — 문구에 pydantic 접두"
        "('Value error,') 없이 '운송 방식' 열을 짚음(점검 D-4)",
        refused is None
        and len(wrong) == 1
        and wrong[0].column == "운송 방식"
        and wrong[0].row is not None
        and "Value error" not in wrong[0].message
        and "(행:" not in wrong[0].message,
        [(i.column, i.message) for i in errors][:2],
    )


# ---------- 계약 · 지도 ID ----------


def _contract(c: Checker) -> None:
    c.section("외자재: 계약 1.33.0(규격 원산지·운송 방식)과 지도 ID")
    base = {"spec_id": "VL-X", "category": "valve", "description": "밸브", "unit": "ea", "unit_price_krw": 1}
    blank = MaterialSpec.model_validate({**base, "origin": "import"})
    air = MaterialSpec.model_validate({**base, "origin": "import", "transport": "air"})
    domestic = MaterialSpec.model_validate({**base, "origin": "domestic"})
    c.check(
        "운송 방식은 외자재 규격에만 · 외자재인데 비면 막지 않고 선박으로 가정(더 긴 쪽) · 국산·모름은 운송 없음",
        c.raises(lambda: MaterialSpec.model_validate({**base, "transport": "sea"}))
        and c.raises(lambda: MaterialSpec.model_validate({**base, "origin": "domestic", "transport": "air"}))
        and (blank.import_transport, blank.transport_assumed) == ("sea", True)
        and (air.import_transport, air.transport_assumed) == ("air", False)
        and (domestic.import_transport, domestic.transport_assumed) == (None, False),
    )
    first = snapshot_id(snapshot())
    spec = snapshot_body()["specs"][0]
    c.check(
        "원산지·운송 방식을 비워 적은 지도는 그 칸이 없던 지도와 같은 ID, 채우면 다른 ID",
        snapshot_id(snapshot(specs=[{**spec, "origin": None, "transport": None}])) == first
        and snapshot_id(snapshot(specs=[{**spec, "origin": "domestic"}])) != first
        and snapshot_id(snapshot(specs=[{**spec, "origin": "import", "transport": "sea"}]))
        != snapshot_id(snapshot(specs=[{**spec, "origin": "import", "transport": "air"}])),
    )
    values = Params(load_params(PARAMS_PATH))
    c.check(
        "운송 일수(cost-v7): 선박 30일(위험 35) · 항공 10일(위험 14) · 운송 없음 0",
        (transport_days(values, "sea", risk=False), transport_days(values, "sea", risk=True)) == SEA
        and (transport_days(values, "air", risk=False), transport_days(values, "air", risk=True)) == AIR
        and transport_days(values, None, risk=True) == 0,
    )


def _domestic(snap: GraphSnapshot) -> GraphSnapshot:
    """외자재 표시만 지운 지도(생산 표준 리드타임은 그대로) — 운송 일수만 빠진 비교 대상."""
    specs = tuple(
        s.model_copy(update={"origin": None, "transport": None}) if s.origin == "import" else s for s in snap.specs
    )
    draft = snap.model_copy(update={"specs": specs})
    return draft.model_copy(update={"snapshot_id": snapshot_id(draft)})


# ---------- 엔진 ----------


def _change(ecn_id: str, op: EquipmentSpecChange | AddPart | ThicknessChange) -> ChangeRequest:
    return ChangeRequest(ecn_id=ecn_id, title=ecn_id, ship_ids=("S-001",), ops=(op,))


def _targets(snap: GraphSnapshot) -> tuple[Part, str, str]:
    """(외자재 규격 밸브 하나, 같은 외자재 밸브 규격 중 다른 것, 국산·모름 밸브 규격 하나)."""
    specs = {s.spec_id: s for s in snap.specs}
    valve = next(p for p in snap.parts if p.kind is PartKind.VALVE and specs[p.spec_id].origin == "import")
    other = next(
        s for s, x in sorted(specs.items()) if s != valve.spec_id and x.origin == "import" and x.category == "valve"
    )
    local = next(s for s, x in sorted(specs.items()) if x.category == "valve" and x.origin is None)
    return valve, other, local


def _arrival(index: GraphIndex, request: AnalysisRequest, book: RuleBook, params: ParamSet, risk: bool) -> date:
    """요청 하나의 새 자재 수요 도착일(수요가 하나인 요청) — 대표 또는 일정 위험 평가."""
    evaluator = Evaluator(index, request, book, params)
    ratios = lead_ratios(evaluator.params) if risk else None
    ev = evaluator.evaluate(request.effective_confirm_on, request.holds, lead_ratios=ratios)
    arrivals = [d.arrival for d in ev.demands if d.arrival is not None]
    assert len(arrivals) == 1, arrivals
    return arrivals[0]


def _expedited(params: ParamSet, ratio: float) -> ParamSet:
    key = "reorder.expedite_lead_time_ratio"
    changed = params.params[key].model_copy(update={"value": ratio, "low": ratio, "high": ratio})
    return params.model_copy(update={"params": {**params.params, key: changed}})


def _engine(c: Checker, generated: Generated, params: ParamSet, book: RuleBook) -> None:
    c.section("외자재: 새 발주 리드타임 LT' + 운송 일수(엔진 0.11.0, 5절·6-6)")
    snap = generated.snapshot
    index, domestic = GraphIndex(snap), GraphIndex(_domestic(snap))
    valve, other, local = _targets(snap)
    as_of = generated.ecns[0].as_of
    to_import = _change(
        "T-IMPORT", EquipmentSpecChange(part_ids=(valve.part_id,), from_spec_id=valve.spec_id, to_spec_id=other)
    )
    to_local = _change(
        "T-LOCAL", EquipmentSpecChange(part_ids=(valve.part_id,), from_spec_id=valve.spec_id, to_spec_id=local)
    )
    std = index.specs[other].std_lead_time_days or 0
    imported = Evaluator(index, AnalysisRequest(change=to_import, as_of=as_of), book, params).changes[0]
    kept = Evaluator(index, AnalysisRequest(change=to_local, as_of=as_of), book, params).changes[0]
    c.check(
        f"외자재 새 규격(표준 {std}일)으로: LT' = 생산 표준, 운송 선박을 더함 · 국산 새 규격(표준 없음)이면 "
        "원래 발주의 리드타임(운송 포함)이라 더하지 않음",
        imported.lead_time_days == std > 0
        and imported.transport == "sea"
        and imported.lead_time_basis.startswith("새 규격")
        and kept.transport is None
        and kept.lead_time_basis == "원래 발주의 리드타임",
        (imported, kept),
    )
    request = AnalysisRequest(change=to_import, as_of=as_of)
    rep, dom = _arrival(index, request, book, params, False), _arrival(domestic, request, book, params, False)
    risk, dom_risk = _arrival(index, request, book, params, True), _arrival(domestic, request, book, params, True)
    start = dom - timedelta(days=std)  # 발주일(판정일 또는 원래 발주 예정일, 급발주 배율 1)
    c.check(
        "대표 일정: 도착 = 발주일 + 생산 표준 + 선박 30일 · 일정 위험: 발주일 + ⌈생산 × 밸브 배율 3⌉ "
        "+ 선박 범위 끝 35일(배율은 운송에 곱하지 않음)",
        (rep - dom).days == SEA[0]
        and (risk - dom_risk).days == SEA[1]
        and (dom_risk - start).days == math.ceil(std * 3)
        and (risk - start).days == math.ceil(std * 3) + SEA[1],
        ((rep - dom).days, (risk - dom_risk).days, (risk - start).days),
    )
    later = as_of.replace(year=as_of.year + 1)  # 발주 이상으로 정해진 뒤 다시 발주(급발주 배율이 붙는 경우)
    again = AnalysisRequest(change=to_import, as_of=as_of, confirm_on=later, horizon_days=1)
    doubled = _expedited(params, 2.0)
    fast, slow = _arrival(index, again, book, params, False), _arrival(index, again, book, doubled, False)
    c.check(
        "급발주 배율은 생산분에만: 배율 2면 도착이 생산 표준만큼 늦어짐(운송 일수는 그대로)",
        (slow - fast).days == std and (slow - later).days == 2 * std + SEA[0],
        ((slow - fast).days, (slow - later).days),
    )
    block = valve.block_id
    added = AnalysisRequest(
        change=_change("T-ADD", AddPart(block_id=block, kind=PartKind.VALVE, spec_id=other, qty=1.0)), as_of=as_of
    )
    new_rep, new_dom = _arrival(index, added, book, params, False), _arrival(domestic, added, book, params, False)
    c.check(
        "부재 추가의 외자재 새 부재: 도착 = 판정일 + 생산 표준 + 운송(국산 표시면 운송 없음)",
        (new_dom - as_of).days == std and (new_rep - new_dom).days == SEA[0],
        ((new_dom - as_of).days, (new_rep - new_dom).days),
    )


PICK_NOTE = "새 규격 후보 여럿"
"""두께·강종 변경의 새 규격을 ①②로 하나로 줄이지 못해 ID 순으로 골랐을 때의 가정 문구 조각."""


def _plate_spec(spec_id: str, thickness: float, lead: int, transport: str) -> MaterialSpec:
    """두께·강종 변경 후보로 더하는 외자재 판 분류 규격(강종 AH36)."""
    return MaterialSpec.model_validate(
        {
            "spec_id": spec_id,
            "category": "plate",
            "description": f"AH36 {thickness:.1f}mm",
            "grade": "AH36",
            "thickness_mm": thickness,
            "unit": "t",
            "unit_price_krw": 1_200_000,
            "std_lead_time_days": lead,
            "origin": "import",
            "transport": transport,
        }
    )


def _twin_map(snap: GraphSnapshot) -> GraphSnapshot:
    """점검자 재현(D-1)의 합성 지도: 판 PL-AH36-12.0을 외자재(선박·표준 20일)로, 쌍둥이 브라켓 규격 BR-AH36-12.0을
    외자재(항공·표준 15일)로 바꾸고, 아무 부재도 쓰지 않는 두께 13.3(PL·AA 접두)·13.9(AB·AC 접두) 규격을 더한다."""
    changed = {
        "PL-AH36-12.0": {"origin": "import", "transport": "sea", "std_lead_time_days": 20},
        "BR-AH36-12.0": {"origin": "import", "transport": "air", "std_lead_time_days": 15},
    }
    assert set(changed) <= {s.spec_id for s in snap.specs}, "생성기 지도에 PL·BR 쌍둥이 규격이 있어야 해요"
    extra = (
        _plate_spec("PL-AH36-13.3", 13.3, 25, "air"),
        _plate_spec("AA-AH36-13.3", 13.3, 40, "sea"),
        _plate_spec("AB-AH36-13.9", 13.9, 11, "air"),
        _plate_spec("AC-AH36-13.9", 13.9, 12, "sea"),
    )
    specs = tuple(s.model_copy(update=changed[s.spec_id]) if s.spec_id in changed else s for s in snap.specs)
    draft = snap.model_copy(update={"specs": (*specs, *extra)})
    return draft.model_copy(update={"snapshot_id": snapshot_id(draft)})


def _matching(c: Checker, generated: Generated, params: ParamSet, book: RuleBook) -> None:
    c.section("두께·강종 변경의 새 규격: 같은 부재 종류 → 같은 ID 접두 → ID 순(가정 문구), 4-0·5절")
    world = _twin_map(generated.snapshot)
    index = GraphIndex(world)
    as_of = generated.ecns[0].as_of
    supplied = {p for line in world.po_lines for p in line.part_ids}
    plate = next(
        p
        for p in world.parts
        if p.kind is PartKind.PLATE and p.grade == "AH36" and p.thickness_mm not in (12.0, 13.3, 13.9)
        if p.part_id in supplied
    )
    bracket = next(
        p for p in world.parts if p.kind is PartKind.BRACKET and p.grade == "AH36" and p.thickness_mm != 12.0
    )

    def picked(part: Part, to_mm: float) -> tuple[int, str | None, str, tuple[str, ...]]:
        assert part.thickness_mm is not None
        op = ThicknessChange(part_ids=(part.part_id,), from_mm=part.thickness_mm, to_mm=to_mm)
        request = AnalysisRequest(change=_change(f"T-PICK-{to_mm}", op), as_of=as_of)
        change = Evaluator(index, request, book, params).changes[0]
        notes = tuple(n for n in analyze(index, request, book, params).notes if PICK_NOTE in n)
        return change.lead_time_days, change.transport, change.lead_time_basis, notes

    plate_12, bracket_12 = picked(plate, 12.0), picked(bracket, 12.0)
    c.check(
        "점검자 재현: 판 두께 → 12.0이면 쌍둥이 브라켓 규격(BR, ID 순 첫째)이 아니라 판이 쓰는 PL-AH36-12.0 — "
        "외자재 표준 20일 + 선박 운송, 브라켓 두께 → 12.0이면 브라켓이 쓰는 BR-AH36-12.0(표준 15일 + 항공), "
        "같은 부재 종류로 하나로 줄면 가정 문구 없음",
        plate_12[:2] == (20, "sea")
        and "PL-AH36-12.0" in plate_12[2]
        and bracket_12[:2] == (15, "air")
        and "BR-AH36-12.0" in bracket_12[2]
        and not plate_12[3]
        and not bracket_12[3],
        (plate.part_id, plate_12, bracket.part_id, bracket_12),
    )
    prefix, order = picked(plate, 13.3), picked(plate, 13.9)
    c.check(
        "같은 부재 종류가 쓰는 후보가 없으면 옛 규격과 같은 ID 접두(PL-AH36-13.3, ID 순 첫째 AA가 아님)로 "
        "가정 문구 없이, 그것도 없으면 ID 순 첫째(AB-AH36-13.9)를 고르고 분석 안내에 후보와 고른 규격을 가정으로 남김",
        prefix[:2] == (25, "air")
        and not prefix[3]
        and order[:2] == (11, "air")
        and len(order[3]) == 1
        and all(s in order[3][0] for s in ("AB-AH36-13.9", "AC-AH36-13.9", "가정")),
        (prefix, order),
    )


# ---------- 숨긴 모델 ----------


def _hidden_arrivals(generated: Generated, change: ChangeRequest, oracle: bool) -> list[date]:
    model = HiddenModel(generated, PARAMS_PATH, oracle=oracle)
    as_of = generated.ecns[0].as_of
    case = model._case(change, as_of, as_of, None)
    materials = material_change(model.world, change).materials
    return [
        d.arrival
        for d in demand_dates(model.world, case, materials, defaultdict(float), model._lead_days, planned_orders=True)
    ]


def _hidden(c: Checker, generated: Generated) -> None:
    c.section("외자재: 숨긴 모델(actuals-v4)도 같은 규칙 — 참 운송 일수, 리드타임 변동은 생산분에만")
    snap = generated.snapshot
    valve, other, _ = _targets(snap)
    domestic = replace(generated, snapshot=_domestic(snap))
    swap = _change(
        "T-IMPORT", EquipmentSpecChange(part_ids=(valve.part_id,), from_spec_id=valve.spec_id, to_spec_id=other)
    )
    add = _change("T-ADD", AddPart(block_id=valve.block_id, kind=PartKind.VALVE, spec_id=other, qty=1.0))
    sampled = round(HiddenModel(generated, PARAMS_PATH).param("transport_days.sea"))
    gaps = {
        (name, oracle): [
            (a - b).days
            for a, b in zip(
                _hidden_arrivals(generated, ch, oracle), _hidden_arrivals(domestic, ch, oracle), strict=True
            )
        ]
        for name, ch in (("swap", swap), ("add", add))
        for oracle in (True, False)
    }
    c.check(
        "규격 변경·부재 추가 모두 외자재 표시만 다른 세계와의 도착 차이 = 운송 일수"
        f"(확인 모드 30일, 참값 {sampled}일 ∈ [25, 35])",
        all(gaps[(name, True)] == [SEA[0]] for name in ("swap", "add"))
        and all(gaps[(name, False)] == [sampled] for name in ("swap", "add"))
        and 25 <= sampled <= 35,
        gaps,
    )


# ---------- 생성기 v4 ----------


def _generator(c: Checker, generated: Generated) -> None:
    c.section("외자재: 생성기 v4(평형수 밸브·두 계통 펌프 규격만 외자재, 그 밖은 v3 그대로)")
    config = load_config()
    snap = generated.snapshot
    specs = {s.spec_id: s for s in snap.specs}
    systems = {s.code: s for s in config.piping.systems}
    assert config.imports is not None
    expected: dict[str, str] = {}
    for item in config.imports.specs:
        system = systems[item.system]
        kind = PartKind.VALVE if item.kind == "valve" else PartKind.EQUIPMENT
        for p in snap.parts:
            if p.kind is kind and p.system == system.name and p.block_id.endswith(f":{system.block}"):
                expected[p.spec_id] = item.transport
    actual = {s.spec_id: s.transport for s in snap.specs if s.origin == "import"}
    leads = {s.spec_id: s.std_lead_time_days for s in snap.specs if s.origin == "import"}
    c.check(
        "외자재 규격 = 설정의 (계통, 부재 종류)가 쓰는 규격 전부, 운송 방식·생산 표준 리드타임은 설정대로",
        bool(expected)
        and actual == expected
        and {"sea", "air"} <= set(actual.values())
        and all(
            leads[s] == config.imports.std_lead_days["valve" if specs[s].category == "valve" else "equipment"]
            for s in leads
        ),
        (actual, leads),
    )
    demo = next(s for s in config.piping.systems if s.block == config.demo.not_started_block)
    kept = {p.spec_id for p in snap.parts if p.kind is PartKind.VALVE and p.system == demo.name}
    c.check(
        f"{demo.label} 밸브(시연 1 미착수 블록 — 관문 2단계 사례가 쓰는 발주)의 규격은 국산·모름 그대로",
        bool(kept) and all(specs[s].origin is None and specs[s].std_lead_time_days is None for s in kept),
        sorted(kept),
    )
    v3 = generate(config.model_copy(update={"imports": None}))
    same = {
        name: getattr(v3.snapshot, name) == getattr(snap, name)
        for name in ("parts", "purchase_orders", "po_lines", "activities", "connections", "stock", "blocks")
    }
    cleared = {"origin": None, "transport": None, "std_lead_time_days": None}
    differs = sorted(
        s.spec_id
        for s in v3.snapshot.specs
        if s != (specs[s.spec_id].model_copy(update=cleared) if s.spec_id in actual else specs[s.spec_id])
    )
    c.check(
        "외자재 설정을 빼면 부재·발주·품목·공정·연결·재고·블록·설계변경 이력이 같고 "
        "규격은 외자재 표시·생산 표준만 다름",
        all(same.values())
        and v3.ecns == generated.ecns
        and not differs
        and v3.snapshot.snapshot_id != snap.snapshot_id,
        (same, differs),
    )
