"""분석(docs/engine.md(비용·일정) 1·6~8절): 생성기 설계변경 300건, 데모, 일정 경계, 보류 권고, 요약 판정."""

from __future__ import annotations

import random
import statistics
import time
from datetime import date, timedelta

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.analysis import MAX_HOLD_DAYS, AnalysisRequest, HoldAction
from ripple.contracts.change import AddPart, DimensionChange, EquipmentSpecChange, ThicknessChange
from ripple.contracts.dataset import GeneratedEcn
from ripple.contracts.domain import GraphSnapshot, PartKind, POStatus
from ripple.contracts.params import ParamSet
from ripple.contracts.result import Amount, CostLine, ImpactType, Unresolved, UnresolvedKind, VerdictLevel
from ripple.contracts.rulebook import RuleBook
from ripple.engine.analyze import analyze
from ripple.engine.cost.amounts import Params
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.engine.timing import Evaluator
from ripple.engine.verdict import (
    DAMAGES,
    ERECTION_DELAY,
    EXIT_DELAY,
    LATE_REWORK,
    OVER_LIMIT,
    PO_CHANGE,
    REWORK,
    RISK_EXIT,
    SMALL,
    THRESHOLD,
    UNKNOWN,
    verdict,
)
from ripple.generator.build import generate
from ripple.generator.io import load_config

from .cost import P11C_VALVE, T31C_PLATE, request_of


def run(c: Checker) -> None:
    config = load_config()
    generated = generate(config)
    snapshot = generated.snapshot
    index = GraphIndex(snapshot)
    book = load_rulebook(PROJECT_ROOT / "rules" / "propagation.yaml")
    params = load_params(PROJECT_ROOT / "params" / "cost_v1.yaml")
    as_of = config.scenario_date
    _all_ecns(c, index, book, params, generated.ecns)
    _demos(c, index, book, params, as_of)
    _late_material(c, snapshot, book, params, as_of)
    _after_erection(c, index, book, params, as_of)
    _added_parts(c, index, book, params, as_of)
    _missing_boundary(c, snapshot, book, params, as_of)
    _missing_consumer(c, generated.ecns, snapshot, book, params)
    _activity_ids(c, snapshot, book, params, as_of)
    _verdict_rules(c, params)
    _holds(c, index, book, params, as_of)
    _long_hold(c, snapshot, book, params, as_of)
    _holds_never_worse(c, index, book, params, generated.ecns)


# ---------- 생성기 설계변경 300건 ----------


def _all_ecns(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, ecns: tuple[GeneratedEcn, ...]) -> None:
    c.section("분석: 생성기 설계변경 300건")
    took: list[float] = []
    rejected = 0
    curve_ok = steady = True
    for ecn in ecns:
        request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of)
        started = time.perf_counter()
        try:
            result = analyze(index, request, book, params)
        except RequestError:
            rejected += 1
            continue
        took.append(time.perf_counter() - started)
        curve_ok &= len(result.timing.curve) == request.horizon_days + 1 and not result.pending_rules
        before = _before_erection(index, request, book, params)
        delays = [p.max_exit_delay_days for p in result.timing.curve if p.confirm_on < before]
        steady &= delays == sorted(delays)
    p95 = statistics.quantiles(took, n=20)[-1]
    c.check(
        f"{len(took)}건 모두 분석 결과 계약 검사 통과(요청 거부 {rejected}건), 곡선 61점·남은 규칙 없음",
        len(took) + rejected == len(ecns) and len(took) >= 280 and curve_ok,
        (len(took), rejected),
    )
    c.check("영향 블록이 모두 탑재 전인 구간에서 판정일만 늦추면 구역 출구 최대 지연이 줄지 않음", steady)
    c.check(
        f"1건(곡선 61일·보류 권고 포함) 평균 {statistics.fmean(took) * 1000:.0f}ms · p95 {p95 * 1000:.0f}ms"
        f" · 최대 {max(took) * 1000:.0f}ms ≤ 1초",
        max(took) <= 1.0,
    )
    rng = random.Random(3)
    sample = [AnalysisRequest(change=e.change, as_of=e.as_of) for e in rng.sample(list(ecns), 15)]
    same = 0
    for request in sample:
        try:
            dumped = analyze(index, request, book, params).model_dump_json()
        except RequestError:
            same += 1
            continue
        same += dumped == analyze(index, request, book, params).model_dump_json()
    c.check("같은 요청이면 바이트까지 같은 결과(15건)", same == len(sample))
    tried = equal = 0
    ecn_list = list(ecns)
    while tried < 15:
        ops = tuple(op for e in rng.sample(ecn_list, 2) for op in e.change.ops)
        base_change = ecn_list[0].change
        first = AnalysisRequest(change=base_change.model_copy(update={"ops": ops}), as_of=ecn_list[0].as_of)
        second = first.model_copy(update={"change": base_change.model_copy(update={"ops": tuple(reversed(ops))})})
        try:
            a, b = analyze(index, first, book, params), analyze(index, second, book, params)
        except RequestError:
            continue
        tried += 1
        equal += a.model_dump_json(exclude={"request"}) == b.model_dump_json(exclude={"request"})
    c.check("연산 순서를 바꿔도 분석 ID와 결과가 같음(2연산 요청 15건)", equal == tried, (equal, tried))


def _before_erection(index: GraphIndex, request: AnalysisRequest, book: RuleBook, params: ParamSet) -> date:
    """재작업·새 자재가 걸리는 블록 중 가장 이른 기준 탑재 착수일(탐색 기간 끝의 평가 기준)."""
    ev = Evaluator(index, request, book, params)
    last = ev.evaluate(request.as_of + timedelta(days=request.horizon_days), ())
    schedule = ev.baseline.ships["S-001"]
    blocks = {line.entity_id for line in last.lines if line.rule_id == "R-B01"}
    blocks |= {
        schedule.network.nodes[c].block_id or ""
        for c in (d.consumer for d in last.demands)
        if c and c in schedule.network.nodes
    }
    starts = [schedule.base.es[schedule.network.chains[b][-1]] for b in blocks if b in schedule.network.chains]
    return min(starts, default=date.max)


# ---------- 데모 ----------


def _demos(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, as_of: date) -> None:
    c.section("분석: 데모 1·2와 요약 판정")
    valve = index.parts[P11C_VALVE]
    demo1 = analyze(
        index,
        request_of(
            as_of,
            EquipmentSpecChange(part_ids=(P11C_VALVE,), from_spec_id=valve.spec_id, to_spec_id="VL-BALL-DN100-16K"),
        ),
        book,
        params,
    )
    c.check(
        "데모 1(P11C 밸브 사양, 미착수·미발주): 발주 변경·재작업 없이 대표 일정은 안 늦지만"
        " 밸브 리드타임 범위 끝(× 3)에서 구역 출구가 늦어 검토 필요(이유는 그 하나, 명세 8-4 검토 필요 4)",
        demo1.verdict.level is VerdictLevel.REVIEW
        and demo1.verdict.reasons == (RISK_EXIT,)
        and demo1.schedule.max_exit_delay_days == 0
        and demo1.schedule.risk is not None
        and demo1.schedule.risk.max_exit_delay_days > 0
        and not any(i.impact_type in (ImpactType.PO_CHANGE, ImpactType.REWORK) for i in demo1.impacts),
        demo1.verdict,
    )
    c.check(
        "데모 1: 확정을 미루면 발주 예정일부터 추가손실이 생겨 마감일이 기준일 뒤(발주 전날)",
        demo1.timing.deadline.last_day > as_of and bool(demo1.timing.holds),
        (demo1.timing.deadline, [h.po_id for h in demo1.timing.holds]),
    )
    stocked = analyze(
        index, request_of(as_of, ThicknessChange(part_ids=(T31C_PLATE,), from_mm=15.0, to_mm=16.5)), book, params
    )
    bought = analyze(
        index, request_of(as_of, ThicknessChange(part_ids=(T31C_PLATE,), from_mm=15.0, to_mm=17.0)), book, params
    )
    c.check(
        "데모 2: 판정 이유에 블록 탑재 지연과 조립 이후 재작업",
        all({ERECTION_DELAY, LATE_REWORK} <= set(r.verdict.reasons) for r in (stocked, bought)),
        (stocked.verdict.reasons, bought.verdict.reasons),
    )
    c.check(
        "데모 2(T31C 조립 중 판 두께 증가): 경고 + 발주 변경·재작업",
        all(
            r.verdict.level is VerdictLevel.WARN
            and {ImpactType.PO_CHANGE, ImpactType.REWORK} <= {i.impact_type for i in r.impacts}
            for r in (stocked, bought)
        ),
    )
    erection = "S-001:T31C:erection"
    held_up = bought.schedule.added_days_by_activity.get(erection, 0)
    c.check(
        "같은 규격 재고(LOT-04)가 있으면 재작업 일수만큼만, 없으면 재발주 도착을 기다려 T31C 탑재가 크게 늦어짐",
        bool(stocked.timing.reallocations)
        and not bought.timing.reallocations
        and stocked.schedule.added_days_by_activity.get(erection, 0) <= 2
        and held_up >= 30,
        (stocked.schedule.added_days_by_activity.get(erection), held_up),
    )


# ---------- 일정 경계 사례 ----------


def _late_material(c: Checker, snapshot: GraphSnapshot, book: RuleBook, params: ParamSet, as_of: date) -> None:
    """새 규격 리드타임이 길면(지도에 표준 리드타임 200일) 일정 지연 영향·인도 지연·지체상금이 생긴다."""
    c.section("분석: 긴 리드타임 새 규격(일정 지연·인도 지연·지체상금)")
    long_lead = "VL-BALL-DN100-16K"
    specs = tuple(
        s.model_copy(update={"std_lead_time_days": 200}) if s.spec_id == long_lead else s for s in snapshot.specs
    )
    index = GraphIndex(snapshot.model_copy(update={"specs": specs}))
    valve = index.parts[P11C_VALVE]
    op = EquipmentSpecChange(part_ids=(P11C_VALVE,), from_spec_id=valve.spec_id, to_spec_id=long_lead)
    result = analyze(index, request_of(as_of, op), book, params)
    delayed = [i for i in result.impacts if i.impact_type is ImpactType.SCHEDULE_DELAY]
    exits = result.schedule.zone_exits
    c.check(
        "구역 출구 지연에 지도의 구역 이름(화면이 코드 대신 현장 이름을 보임)",
        bool(exits) and all(e.zone_name == index.zones[e.zone_id].name and e.zone_name for e in exits),
        [(e.zone_id, e.zone_name) for e in exits],
    )
    c.check(
        "주 경로는 늦어진 구역 출구에서 끝나고 관문이 걸린 블록 탑재를 지남",
        bool(exits)
        and result.schedule.critical_path_after[-1] == exits[0].exit_activity_id
        and "S-001:P11C:erection" in result.schedule.critical_path_after,
        result.schedule.critical_path_after,
    )
    c.check(
        "새 자재를 받아 처리한 다음 날이 블록 탑재 기준일보다 늦으면 탑재 지연(R-S01, 부재 → 품목 → 공정 → 탑재)",
        len(delayed) == 1
        and delayed[0].entity_id == "S-001:P11C:erection"
        and [h.relation.value for h in delayed[0].path][:2] == ["supplied_by", "consumed_by"]
        and {h.relation.value for h in delayed[0].path[2:]} == {"precedes"},
        [(i.entity_id, i.note) for i in delayed],
    )
    delivery = result.schedule.delivery
    ld = next((line for line in result.cost_lines if line.rule_id == "R-L01"), None)
    ship = index.ships["S-001"]
    expected = None
    if delivery is not None:
        grace = params.value("liquidated_damages.grace_days")
        rate = params.value("liquidated_damages.rate_per_day_of_price")
        cap = params.value("liquidated_damages.max_days")
        after = min(max(delivery.forecast_delay_after_days - grace, 0), cap)
        before = min(max(delivery.forecast_delay_before_days - grace, 0), cap)
        expected = round(ship.contract_price_krw * rate * (after - before))
    c.check(
        "구역 출구 지연이 여유를 넘으면 인도 지연(R-L01)과 지체상금 = 선가 × 일당 비율 × (L(후) − L(전))",
        delivery is not None
        and delivery.added_delay_days > 0
        and ld is not None
        and ld.amount.value == expected
        and any(i.impact_type is ImpactType.DELIVERY_DELAY for i in result.impacts),
        (delivery, ld.amount if ld else None, expected),
    )
    c.check(
        "경고 판정 이유에 출구 지연·지체상금·블록 탑재 지연",
        result.verdict.level is VerdictLevel.WARN
        and {EXIT_DELAY, DAMAGES, ERECTION_DELAY} <= set(result.verdict.reasons),
        result.verdict.reasons,
    )
    _r_s01_boundary(c, snapshot, book, params, as_of)


def _r_s01_boundary(c: Checker, snapshot: GraphSnapshot, book: RuleBook, params: ParamSet, as_of: date) -> None:
    """새 자재 도착 + 처리 하루가 탑재 기준 착수일과 같으면 지연 없음, 하루 더 늦으면 R-S01(경계값)."""
    spec_id = "VL-BALL-DN100-16K"
    probe_index = GraphIndex(snapshot)
    valve = probe_index.parts[P11C_VALVE]
    op = EquipmentSpecChange(part_ids=(P11C_VALVE,), from_spec_id=valve.spec_id, to_spec_id=spec_id)
    probe = Evaluator(probe_index, request_of(as_of, op), book, params)
    po_id = probe_index.lines[probe_index.line_of_part[P11C_VALVE]].po_id
    ordered = next(w.estimate for w in probe.state(()).windows(po_id) if w.stage is POStatus.ORDERED)
    erection = probe.baseline.ships["S-001"].base.es["S-001:P11C:erection"]
    assert ordered is not None
    exact = (erection - ordered).days - 1  # 도착 + 1 = 탑재 기준 착수일

    def delays(lead: int) -> tuple[bool, int]:
        specs = tuple(
            s.model_copy(update={"std_lead_time_days": lead}) if s.spec_id == spec_id else s for s in snapshot.specs
        )
        index = GraphIndex(snapshot.model_copy(update={"specs": specs}))
        ev = Evaluator(index, request_of(as_of, op), book, params).evaluate(as_of, ())
        flagged = any(i.impact_type is ImpactType.SCHEDULE_DELAY for i in ev.impacts)
        return flagged, ev.schedule.added_days_by_activity.get("S-001:P11C:erection", 0)

    on_edge, past_edge = delays(exact), delays(exact + 1)
    c.check(
        "새 자재 도착 + 처리 하루 = 탑재 기준 착수일이면 지연 없음, 리드타임 하루 더면 R-S01과 탑재 1일 지연",
        on_edge == (False, 0) and past_edge == (True, 1),
        (exact, on_edge, past_edge),
    )


def _after_erection(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, as_of: date) -> None:
    c.section("분석: 탑재 뒤 확정한 재작업")
    probe = Evaluator(index, request_of(as_of, _dimension(index, "S-001:D31C")), book, params)
    schedule = probe.baseline.ships["S-001"]
    exit_id = "S-001:ZCT:exit"
    last = max(
        (p for p, _ in schedule.network.nodes[exit_id].preds), key=lambda a: (schedule.base.ef[a], a)
    )  # 구역 출구를 정하는 마지막 탑재
    block = schedule.network.nodes[last].block_id or ""
    confirm = schedule.base.ef[last]  # 탑재가 끝난 날: 운반 공정 없이 관문만
    request = request_of(as_of, _dimension(index, block), confirm_on=confirm)
    ev = Evaluator(index, request, book, params)
    result = ev.evaluate(confirm, ())
    rework = next((line for line in result.lines if line.rule_id == "R-B01"), None)
    days = int(rework.inputs.get("days", 0)) if rework else 0
    exit_start = schedule.base.es[exit_id] + timedelta(days=result.schedule.added_days_by_activity.get(exit_id, 0))
    expected = max(schedule.base.es[exit_id], confirm + timedelta(days=1 + days))
    c.check(
        "탑재가 끝난 블록의 재작업은 확정 다음 날부터 선상에서: 구역 출구 = max(기준 출구, 확정일 + 1 + 재작업 일수)",
        rework is not None
        and rework.inputs.get("stage") == "erected"
        and days >= 2
        and exit_start == expected
        and expected > schedule.base.es[exit_id],
        (block, days, exit_start, expected),
    )


def _dimension(index: GraphIndex, block: str) -> DimensionChange:
    plate = sorted(p.part_id for p in index.parts.values() if p.block_id == block and p.kind.value == "plate")[0]
    return DimensionChange(part_ids=(plate,), field="length_mm", from_value=1000.0, to_value=1100.0)


def _added_parts(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, as_of: date) -> None:
    c.section("분석: 부재 추가의 새 자재")
    plate = index.parts[T31C_PLATE]
    bracket = sorted(s for s in index.specs if s.startswith("BR-"))[0]
    steel = AddPart(
        block_id=plate.block_id, kind=PartKind.BRACKET, spec_id=bracket, qty=0.05, attach_to_part_id=T31C_PLATE
    )
    steel_ev = Evaluator(index, request_of(as_of, steel), book, params).evaluate(as_of, ())
    valve_spec = sorted(s for s in index.specs if index.specs[s].category == "valve")[0]
    fitting = AddPart(block_id="S-001:P11C", kind=PartKind.VALVE, spec_id=valve_spec, qty=1)
    valve_ev = Evaluator(index, request_of(as_of, fitting), book, params).evaluate(as_of, ())
    lead = round(params.value("lead_time_days.valve"))
    c.check(
        "강재 부재 추가는 야드 재고로 바로 쓰고(납기 대기 없음), 밸브 추가는 판정일 + 리드타임에 도착",
        not steel_ev.demands
        and len(valve_ev.demands) == 1
        and valve_ev.demands[0].arrival == as_of + timedelta(days=lead)
        and valve_ev.demands[0].consumer == "S-001:P11C:pre_outfitting",
        (steel_ev.demands, valve_ev.demands),
    )


def _missing_boundary(c: Checker, snapshot: GraphSnapshot, book: RuleBook, params: ParamSet, as_of: date) -> None:
    c.section("분석: 경계 조건이 없는 구역")
    bare = GraphIndex(snapshot.model_copy(update={"boundaries": ()}))
    request = request_of(as_of, _p11c_plate(bare), confirm_on=as_of + timedelta(days=60))
    result = analyze(bare, request, book, params)
    c.check(
        "경계 조건 없는 구역 출구가 늦어지면 인도 지연·지체상금은 계산 불가(이유 delivery)",
        result.schedule.delivery is None
        and any(u.kind is UnresolvedKind.DELIVERY for u in result.unresolved)
        and not any(line.rule_id == "R-L01" for line in result.cost_lines)
        and bool(result.schedule.zone_exits),
        result.schedule.zone_exits,
    )


def _missing_consumer(
    c: Checker, ecns: tuple[GeneratedEcn, ...], snapshot: GraphSnapshot, book: RuleBook, params: ParamSet
) -> None:
    """공급 품목의 소비 공정이 비면(엑셀 선택 열) 일정 영향이 0으로 숨지 않고 '연결 확인 필요'로 판정이 오른다(5절)."""
    c.section("분석: 소비 공정이 없는 공급 품목")
    ecn = next(e for e in ecns if e.change.ecn_id == "ECN-D-0045")
    request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of)
    plain = analyze(GraphIndex(snapshot), request, book, params)
    targets = {p for op in ecn.change.ops for p in getattr(op, "part_ids", ())}
    lines = {li.line_id for li in snapshot.po_lines if targets & set(li.part_ids)}
    bare_lines = tuple(
        li.model_copy(update={"consumed_by_activity_id": None}) if li.line_id in lines else li
        for li in snapshot.po_lines
    )
    bare = GraphIndex(snapshot.model_copy(update={"po_lines": bare_lines}))
    result = analyze(bare, request, book, params)
    flagged = {u.entity_id or "" for u in result.unresolved if u.kind is UnresolvedKind.CONNECTION}
    c.check(
        "원래 지도에서는 승인 가능, 대상 품목의 소비 공정을 지우면 품목마다 '연결 확인 필요'와 판정 '검토 필요'",
        plain.verdict.level is VerdictLevel.APPROVE
        and bool(lines)
        and lines <= flagged
        and result.verdict.level is VerdictLevel.REVIEW
        and UNKNOWN in result.verdict.reasons,
        (plain.verdict.level, sorted(lines), sorted(flagged), result.verdict.level, result.verdict.reasons),
    )
    c.check(
        "안내 문구가 남고, 지운 품목 때문에 생긴 일정 지연 영향(R-S01)은 없음",
        any("소비 공정이 지도에 없음" in note for note in result.notes)
        and not any(i.impact_type is ImpactType.SCHEDULE_DELAY for i in result.impacts),
        result.notes,
    )


def _activity_ids(c: Checker, snapshot: GraphSnapshot, book: RuleBook, params: ParamSet, as_of: date) -> None:
    """탑재 지연 판정은 공정 종류로 본다(8-4): 회사 공정 코드처럼 ID만 바꾼 지도에서도 판정·이유가 같다."""
    c.section("분석: 공정 ID 표기와 무관한 판정")
    long_lead = "VL-BALL-DN100-16K"
    specs = tuple(
        s.model_copy(update={"std_lead_time_days": 200}) if s.spec_id == long_lead else s for s in snapshot.specs
    )
    base = snapshot.model_copy(update={"specs": specs})
    rename = {a.activity_id: f"ACT-{n:04d}" for n, a in enumerate(base.activities)}
    activities = tuple(
        a.model_copy(
            update={
                "activity_id": rename[a.activity_id],
                "predecessors": tuple(
                    p.model_copy(update={"activity_id": rename[p.activity_id]}) for p in a.predecessors
                ),
            }
        )
        for a in base.activities
    )
    lines = tuple(
        li.model_copy(update={"consumed_by_activity_id": rename.get(li.consumed_by_activity_id or "")})
        for li in base.po_lines
    )
    bounds = tuple(b.model_copy(update={"exit_activity_id": rename[b.exit_activity_id]}) for b in base.boundaries)
    coded = base.model_copy(update={"activities": activities, "po_lines": lines, "boundaries": bounds})
    valve = snapshot.parts[[p.part_id for p in snapshot.parts].index(P11C_VALVE)]
    op = EquipmentSpecChange(part_ids=(P11C_VALVE,), from_spec_id=valve.spec_id, to_spec_id=long_lead)
    plain = analyze(GraphIndex(base), request_of(as_of, op), book, params)
    renamed = analyze(GraphIndex(coded), request_of(as_of, op), book, params)
    c.check(
        "공정 ID를 회사 코드(ACT-0001…)로 바꿔도 '블록 탑재가 늦어질 수 있어요'를 포함한 판정·이유가 같음",
        ERECTION_DELAY in plain.verdict.reasons and renamed.verdict == plain.verdict,
        (plain.verdict, renamed.verdict),
    )


def _p11c_plate(index: GraphIndex) -> ThicknessChange:
    plate = index.parts[sorted(p for p in index.parts if p.startswith("S-001:P11C-PL-"))[0]]
    thickness = plate.thickness_mm or 14.0
    return ThicknessChange(part_ids=(plate.part_id,), from_mm=thickness, to_mm=thickness + 2.5)


# ---------- 보류 권고 ----------


def _holds(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, as_of: date) -> None:
    c.section("분석: 발주 보류 권고")
    valve = index.parts[P11C_VALVE]
    op = EquipmentSpecChange(part_ids=(P11C_VALVE,), from_spec_id=valve.spec_id, to_spec_id="VL-BALL-DN100-16K")
    request = request_of(as_of, op)
    result = analyze(index, request, book, params)
    advice = result.timing.holds
    ev = Evaluator(index, request, book, params)
    safe = longer = True
    for item in advice:
        held = (HoldAction(po_id=item.po_id, hold_days=item.max_hold_days),)
        over = (HoldAction(po_id=item.po_id, hold_days=item.max_hold_days + 1),)
        for offset in range(0, request.horizon_days + 1, 6):
            day = as_of + timedelta(days=offset)
            plain, kept = ev.evaluate(day, ()), ev.evaluate(day, held)
            erections = [a for a in plain.schedule.added_days_by_activity if a.endswith(":erection")]
            safe &= kept.max_exit_delay == plain.max_exit_delay and all(
                kept.schedule.added_days_by_activity.get(a) == plain.schedule.added_days_by_activity.get(a)
                for a in {*erections, *(a for a in kept.schedule.added_days_by_activity if a.endswith(":erection"))}
            )
        beyond = ev.evaluate(as_of, over)
        longer &= any(a.endswith(":erection") for a in beyond.schedule.added_days_by_activity)
    c.check("보류 권고가 있음(데모 1: 미발주 밸브 발주)", bool(advice), advice)
    c.check("보류 가능 기간 안의 보류는 어느 판정일에도 탑재·구역 출구를 늦추지 않음", safe)
    c.check("보류 가능 기간을 하루 넘기면 탑재가 늦어짐(경계값)", longer)
    c.check(
        "보류하면 추가손실 0 마감일이 늦어지거나 같고, 피하는 손실 > 0",
        all(a.deadline_after.last_day >= result.timing.deadline.last_day and a.avoided.high > 0 for a in advice),
    )
    c.check(
        "보류 권고 발주의 공급 품목에 보류 영향(R-H01)",
        {i.entity_id.split("#")[0] for i in result.impacts if i.impact_type is ImpactType.PO_HOLD}
        == {a.po_id for a in advice},
    )


def _long_hold(c: Checker, snapshot: GraphSnapshot, book: RuleBook, params: ParamSet, as_of: date) -> None:
    """착수 전 공정·인도일을 400일 뒤로 미룬 지도: 보류 가능 기간이 요청 보류 상한(365일)을 넘어도 분석이 실패하지
    않고, 권고 기간은 상한으로 자른다(8-3)."""
    shift = timedelta(days=400)
    later = snapshot.model_copy(
        update={
            "activities": tuple(
                a if a.actual_start else a.model_copy(update={"planned_start": a.planned_start + shift})
                for a in snapshot.activities
            ),
            "ships": tuple(s.model_copy(update={"delivery_date": s.delivery_date + shift}) for s in snapshot.ships),
        }
    )
    index = GraphIndex(later)
    valve = index.parts[P11C_VALVE]
    op = EquipmentSpecChange(part_ids=(P11C_VALVE,), from_spec_id=valve.spec_id, to_spec_id="VL-BALL-DN100-16K")
    try:
        holds = analyze(index, request_of(as_of, op), book, params).timing.holds
        failure = None
    except ValueError as error:  # pydantic ValidationError도 ValueError
        holds, failure = (), str(error)[:200]
    c.check(
        "보류 가능 기간이 365일을 넘는 지도도 분석하고, 권고 기간은 요청 보류 상한 365일까지",
        failure is None and bool(holds) and all(1 <= h.max_hold_days <= MAX_HOLD_DAYS for h in holds),
        failure or [(h.po_id, h.max_hold_days) for h in holds],
    )


def _holds_never_worse(
    c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, ecns: tuple[GeneratedEcn, ...]
) -> None:
    """권고한 보류를 그대로 적용하면 탐색 기간 어느 날도 총비용 대표값·구역 출구 지연이 늘지 않는다(8-3)."""
    worse: list[str] = []
    advised = 0
    for ecn in ecns:
        request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of)
        try:
            result = analyze(index, request, book, params)
        except RequestError:
            continue
        ev = Evaluator(index, request, book, params)
        _, base = ev.curve(())
        for item in result.timing.holds:
            advised += 1
            _, held = ev.curve((HoldAction(po_id=item.po_id, hold_days=item.max_hold_days),))
            if any(
                held[d].total.value > b.total.value or held[d].max_exit_delay > b.max_exit_delay
                for d, b in base.items()
            ):
                worse.append(f"{ecn.change.ecn_id}:{item.po_id}")
    c.check(
        f"300건의 보류 권고 {advised}건 모두 어느 판정일에도 총비용·구역 출구 지연을 늘리지 않음",
        advised > 0 and not worse,
        worse[:10],
    )


# ---------- 요약 판정(명세 8-4) ----------


def _cost_line(line_id: str, value: int, stage: str | None = None, hull: float | None = None) -> CostLine:
    rule_id, _, entity_id = line_id.split(":", 2)
    inputs: dict[str, str | float] = {} if stage is None else {"stage": stage}
    if hull is not None:
        inputs["hull_weight_t"] = hull
    return CostLine(
        line_id=line_id,
        rule_id=rule_id,
        entity_id=entity_id,
        label="검사",
        formula="검사",
        inputs=inputs,
        amount=Amount.exact(value),
    )


def _verdict_rules(c: Checker, params: ParamSet) -> None:
    c.section("분석: 요약 판정 순수 함수(명세 8-4)")
    p = Params(params)
    limit = round(params.value(THRESHOLD))
    unknown = (Unresolved(kind=UnresolvedKind.PO_STATE, reason="검사", entity_id="PO-1#1"),)
    po_change = _cost_line("R-T01:po_change:PO-1#1", 0)

    def reasons(
        lines: tuple[CostLine, ...] = (),
        total: int = 0,
        exit_delay: int = 0,
        unresolved: tuple[Unresolved, ...] = (),
        erection: bool = False,
        risk: int = 0,
    ) -> tuple[str, tuple[str, ...]]:
        result = verdict(
            lines, Amount.exact(total), exit_delay, unresolved, p, erection_delayed=erection, risk_exit_delay=risk
        )
        return result.level.value, result.reasons

    c.check("아무 조건도 없으면 승인 가능", reasons() == ("approve", (SMALL,)))
    c.check(
        "대표 출구 0일·위험만 늦으면 검토 필요 이유 하나(8-4 검토 필요 4), 대표가 늦으면 경고만(위험 이유 없음)",
        reasons(risk=3) == ("review", (RISK_EXIT,))
        and reasons(exit_delay=2, risk=5) == ("warn", (EXIT_DELAY,))
        and reasons(risk=0) == ("approve", (SMALL,)),
    )
    c.check(
        "위험 이유는 승인 기준 다음·판단 불가 앞(명세 순서)",
        reasons(total=limit + 1, unresolved=unknown, risk=1) == ("review", (OVER_LIMIT, RISK_EXIT, UNKNOWN)),
    )
    c.check("발주 변경 줄은 0원이어도 검토 필요", reasons((po_change,)) == ("review", (PO_CHANGE,)))
    c.check(
        "총액 최대값이 문턱과 같으면 승인, 넘으면 검토 필요",
        reasons(total=limit)[0] == "approve" and reasons(total=limit + 1) == ("review", (OVER_LIMIT,)),
    )
    c.check("계산하지 못한 이유만 있어도 검토 필요", reasons(unresolved=unknown) == ("review", (UNKNOWN,)))
    c.check(
        "조립 전 재작업은 검토 필요, 조립 이후 재작업은 경고",
        reasons((_cost_line("R-B01:rework:S-1:B1", 10, "panel"),)) == ("review", (REWORK,))
        and reasons((_cost_line("R-B01:rework:S-1:B1", 10, "assembly"),)) == ("warn", (LATE_REWORK,)),
    )
    c.check(
        "의장품만 다시 다는 재작업(선체 중량 0)은 도장 전 검토 필요, 도장 시작 뒤 경고 · 0원 재작업 줄은 재작업 아님",
        reasons((_cost_line("R-B01:rework:S-1:B1", 10, "pre_outfitting", hull=0.0),)) == ("review", (REWORK,))
        and reasons((_cost_line("R-B01:rework:S-1:B1", 10, "pre_painting", hull=0.0),)) == ("warn", (LATE_REWORK,))
        and reasons((_cost_line("R-B01:rework:S-1:B1", 10, "pre_outfitting", hull=0.2),)) == ("warn", (LATE_REWORK,))
        and reasons((_cost_line("R-B01:rework:S-1:B1", 0, "assembly", hull=0.0),)) == ("approve", (SMALL,)),
    )
    c.check(
        "지체상금 줄의 최대값이 0이면 지체상금 이유가 아님",
        reasons((_cost_line("R-L01:ld:S-1", 0),)) == ("approve", (SMALL,)),
    )
    c.check(
        "경고가 있으면 검토 필요 이유는 넣지 않음",
        reasons((po_change,), total=limit + 1, exit_delay=2, unresolved=unknown) == ("warn", (EXIT_DELAY,)),
    )
    everything = (po_change, _cost_line("R-L01:ld:S-1", 5), _cost_line("R-B01:rework:S-1:B1", 10, "erected"))
    c.check(
        "경고 이유는 명세 순서(출구 → 지체상금 → 탑재 → 조립 이후 재작업)",
        reasons(everything, exit_delay=1, erection=True)
        == ("warn", (EXIT_DELAY, DAMAGES, ERECTION_DELAY, LATE_REWORK)),
    )
    c.check(
        "검토 필요 이유는 명세 순서(발주 변경 → 재작업 → 승인 기준 → 판단 불가)",
        reasons((po_change, _cost_line("R-B01:rework:S-1:B1", 10, "panel")), total=limit + 1, unresolved=unknown)
        == ("review", (PO_CHANGE, REWORK, OVER_LIMIT, UNKNOWN)),
    )
