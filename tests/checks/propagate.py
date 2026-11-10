"""영향 탐색 엔진의 성질(docs/engine.md(전파) 8절)과 규칙별 판정.

합성 지도(시드 20261020)와 그 설계변경 300건을 쓴다. 규칙별 기대값은 엔진이 아니라 지도 자료에서 따로 계산한다.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from datetime import date, timedelta

from harness import Checker, nominal

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import Settings
from ripple.contracts.analysis import AnalysisRequest, HoldAction
from ripple.contracts.change import (
    AddPart,
    AddPenetration,
    ChangeIntent,
    ChangeOp,
    ChangeRequest,
    EquipmentSpecChange,
    GradeChange,
    RemovePart,
    ReroutePipe,
    ThicknessChange,
)
from ripple.contracts.domain import BlockStage, Connection, ConnectionKind, PartKind, POStatus, Relation
from ripple.contracts.identity import canonical_json, normalized_op
from ripple.contracts.result import Impact, ImpactType, UnresolvedKind
from ripple.contracts.rulebook import RuleBook
from ripple.engine.index import GraphIndex
from ripple.engine.overlay import ChangeView
from ripple.engine.propagate import Propagation, RequestError, impact_report, propagate
from ripple.engine.state import StateModel
from ripple.generator.build import Generated, generate
from ripple.generator.io import load_config

SHIP = "S-001"


def run(c: Checker) -> None:
    settings = Settings.from_env({})
    book = load_rulebook(settings.rules_path)
    params_version = load_params(settings.params_path).version
    generated = generate(load_config())
    index = GraphIndex(generated.snapshot)
    as_of = generated.ecns[0].as_of
    _all_ecns(c, generated, index, book, params_version)
    _order(c, generated, index, book)
    _monotone(c, generated, book)
    _missing_relations(c, generated, book)
    _structure(c, index, book, as_of)
    _procurement(c, generated, index, book, as_of)
    _piping(c, index, book, as_of)
    _additions(c, index, book, as_of)
    _validation(c, index, book, as_of)


def _request(
    as_of: date, *ops: ChangeOp, confirm_on: date | None = None, holds: Sequence[HoldAction] = ()
) -> AnalysisRequest:
    change = ChangeRequest(ecn_id="T-1", title="검사", ship_ids=(SHIP,), intent=ChangeIntent.STRENGTH, ops=ops)
    return AnalysisRequest(change=change, as_of=as_of, confirm_on=confirm_on, holds=tuple(holds))


def _keys(result: Propagation, exclude: str | None = None) -> set[tuple[str, str, str, str]]:
    return {i.key for i in result.impacts if i.rule_id != exclude}


def _of(result: Propagation, rule_id: str, impact_type: ImpactType | None = None) -> list[Impact]:
    return [i for i in result.impacts if i.rule_id == rule_id and (impact_type is None or i.impact_type is impact_type)]


# ---------- 생성기 설계변경 전부 ----------


def _all_ecns(c: Checker, generated: Generated, index: GraphIndex, book: RuleBook, params_version: str) -> None:
    c.section("전파 엔진: 생성기 설계변경 300건")
    reports, again = [], []
    for ecn in generated.ecns:
        request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of)
        reports.append(impact_report(index, request, book, params_version))
        again.append(impact_report(index, request, book, params_version))
    c.check("300건 모두 계산되고 보고서 계약을 통과", len(reports) == len(generated.ecns) == 300)
    c.check(
        "같은 입력이면 바이트 단위로 같은 보고서",
        all(a.model_dump_json() == b.model_dump_json() for a, b in zip(reports, again, strict=True)),
    )
    effects = {rule.id: set(rule.effect) for rule in book.rules}
    starts_ok = ships_ok = effects_ok = exists_ok = graph_ok = True
    for report in reports:
        view = ChangeView(index, report.request.change)
        targets = {t for planned in view.ops for t in planned.targets()}
        for impact in report.impacts:
            start = impact.path[0].src if impact.path else impact.entity_id
            starts_ok &= start in targets and all(h.rule_id in effects for h in impact.path)
            effects_ok &= impact.impact_type in effects.get(impact.rule_id, set())
            ships_ok &= impact.ship_id in report.request.change.ship_ids
            exists_ok &= view.exists(impact.entity_id)
        graph = report.graph
        graph_ok &= {n.id for n in graph.nodes if n.virtual} == set(view.new_parts) and all(
            e.virtual == (e.target not in index.out(e.source, e.relation)) for e in graph.edges
        )
    c.check("모든 근거 경로는 대상 부재에서 시작하고 규칙표의 규칙만 씀", starts_ok)
    c.check("모든 영향 종류가 그 규칙의 규칙표 영향 안", effects_ok)
    c.check("요청 호선 밖 엔터티는 나오지 않음", ships_ok)
    c.check("영향 엔터티는 지도에 있거나 이번 변경으로 생긴 부재", exists_ok)
    c.check("영향 그래프의 점선 노드 = 이번 변경으로 생긴 부재, 원본 연결은 실선", graph_ok)
    counted = {i.rule_id for report in reports for i in report.impacts}
    c.check(
        "1단계 규칙 대부분이 실제로 쓰임(R-X01 제외)",
        {"R-T01", "R-M02", "R-T02", "R-T03", "R-T04", "R-P01", "R-P02", "R-P03", "R-M01", "R-B01", "R-D01"} <= counted,
        sorted(counted),
    )
    c.check(
        "일정·보류·인도 규칙은 아직 계산하지 않는다고 적음", reports[0].pending_rules == ("R-S01", "R-H01", "R-L01")
    )
    c.check("연결이 완비된 생성기 지도에서는 300건 어디에도 R-X01이 없음", "R-X01" not in counted)
    t01 = [(i.entity_id, i.impact_type) for r in reports for i in r.impacts if i.rule_id == "R-T01"]
    c.check(
        "R-T01은 발주 변경·취소와 새 규격 발주를 함께 냄",
        {e for e, t in t01 if t is ImpactType.PO_CHANGE} == {e for e, t in t01 if t is ImpactType.REORDER},
    )


def _order(c: Checker, generated: Generated, index: GraphIndex, book: RuleBook) -> None:
    c.section("전파 엔진: 연산 순서")
    rng = random.Random(7)
    tried = same = 0
    ecns = list(generated.ecns)
    while tried < 40:
        ops = tuple(op for ecn in rng.sample(ecns, 3) for op in ecn.change.ops)
        shuffled = tuple(rng.sample(ops, len(ops)))
        first, second = _request(ecns[0].as_of, *ops), _request(ecns[0].as_of, *shuffled)
        try:
            a, b = propagate(index, first, book), propagate(index, second, book)
        except RequestError:
            continue
        tried += 1
        same += (
            a == b
            and impact_report(index, first, book, "p").analysis_id
            == impact_report(index, second, book, "p").analysis_id
        )
    c.check("연산 순서를 섞어도 분석 ID와 계산 결과가 같음(3연산 요청 40건)", same == tried == 40, (same, tried))
    op = generated.ecns[0].change.ops[0]
    renamed = ChangeRequest(
        ecn_id="다른-번호", title="다른 제목", ship_ids=(SHIP,), intent=ChangeIntent.WEIGHT, ops=(op,)
    )
    c.check(
        "ECN 번호·제목이 달라도 같은 연산이면 같은 임시 ID",
        ChangeView(index, renamed).new_parts.keys() == ChangeView(index, generated.ecns[0].change).new_parts.keys(),
    )


def _monotone(c: Checker, generated: Generated, book: RuleBook) -> None:
    c.section("전파 엔진: 연결을 더하면")
    rng = random.Random(11)
    snapshot = generated.snapshot
    parts = [p.part_id for p in snapshot.parts]
    extra: list[Connection] = []
    while len(extra) < 120:
        a, b = rng.sample(parts, 2)
        kind = rng.choice(list(ConnectionKind))
        extra.append(Connection(a=a, b=b, kind=kind))
    richer = GraphIndex(snapshot.model_copy(update={"connections": snapshot.connections + tuple(extra)}))
    base = GraphIndex(snapshot)
    grows = True
    for ecn in generated.ecns[::3]:
        request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of)
        grows &= _keys(propagate(base, request, book), "R-X01") <= _keys(propagate(richer, request, book), "R-X01")
    c.check("지도에 연결을 더해도 영향 키(R-X01 제외)가 줄지 않음(100건)", grows)


def _missing_relations(c: Checker, generated: Generated, book: RuleBook) -> None:
    c.section("전파 엔진: 연결이 통째로 없을 때")
    snapshot = generated.snapshot
    ecn = next(e for e in generated.ecns if e.change.ops[0].op == "thickness")
    op = ecn.change.ops[0]
    assert isinstance(op, ThicknessChange)
    target = op.part_ids[0]
    no_butt = tuple(x for x in snapshot.connections if not (x.kind == "butt_weld" and target in (x.a, x.b)))
    no_line = tuple(
        line.model_copy(update={"part_ids": tuple(p for p in line.part_ids if p != target)})
        for line in snapshot.po_lines
    )
    request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of)
    for label, update, relation in (
        ("맞대기 용접", {"connections": no_butt}, Relation.BUTT_WELD),
        ("공급 발주 품목", {"po_lines": no_line}, Relation.SUPPLIED_BY),
    ):
        result = propagate(GraphIndex(snapshot.model_copy(update=update)), request, book)
        flagged = [i for i in _of(result, "R-X01") if i.entity_id == target]
        reasons = [u for u in result.unresolved if u.kind is UnresolvedKind.CONNECTION and u.entity_id == target]
        c.check(
            f"{label} 관계를 통째로 지우면 R-X01 확인 필요와 이유가 남음",
            len(flagged) == 1 and label in flagged[0].note and bool(reasons),
            [i.note for i in flagged],
        )
        gone = not [i for i in result.impacts if i.path and i.path[0].src == target and i.path[0].relation is relation]
        c.check(f"{label} 관계가 없으면 그 관계로 번지는 영향도 없음", gone)
    part = generated.snapshot.parts[[p.part_id for p in snapshot.parts].index(target)]
    graded = GradeChange(
        part_ids=(target,), from_grade=part.grade or "AH36", to_grade="EH36" if part.grade != "EH36" else "DH36"
    )
    no_butt_map = GraphIndex(snapshot.model_copy(update={"connections": no_butt}))
    c.check(
        "강종 변경은 맞대기 용접을 따라가지 않으므로 그 관계가 없어도 R-X01 없음(연산 범위)",
        not _of(propagate(no_butt_map, _request(ecn.as_of, graded), book), "R-X01"),
    )
    intact = propagate(GraphIndex(snapshot), request, book)
    c.check("생성기 지도(연결 완비)에서는 R-X01이 없음", not _of(intact, "R-X01"))


# ---------- 규칙별 판정 ----------


def _structure(c: Checker, index: GraphIndex, book: RuleBook, as_of: date) -> None:
    c.section("전파 엔진: 구조 규칙")
    plates = [p for p in index.parts.values() if p.kind is PartKind.PLATE and p.block_id.endswith(":T31C")]
    pair = next(
        (p, n)
        for p in sorted(plates, key=lambda x: x.part_id)
        for n in index.out(p.part_id, Relation.BUTT_WELD)
        if index.parts[n].thickness_mm == p.thickness_mm
    )
    a, b = pair[0], index.parts[pair[1]]
    t = a.thickness_mm or 0.0
    alone = propagate(index, _request(as_of, ThicknessChange(part_ids=(a.part_id,), from_mm=t, to_mm=t + 4)), book)
    both = propagate(
        index, _request(as_of, ThicknessChange(part_ids=(a.part_id, b.part_id), from_mm=t, to_mm=t + 4)), book
    )
    tapered = {i.entity_id for i in _of(alone, "R-T02")}
    c.check("한 판만 4mm 두꺼워지면 같은 두께였던 이웃 판에 테이퍼", b.part_id in tapered)
    c.check(
        "맞댄 두 판을 함께 바꾸면 최종 두께로 판정(서로에게 테이퍼 없음)",
        not {a.part_id, b.part_id} & {i.entity_id for i in _of(both, "R-T02")},
    )
    expected = {
        n
        for p in (a.part_id, b.part_id)
        for n in index.out(p, Relation.BUTT_WELD)
        if n not in (a.part_id, b.part_id)
        and abs((index.parts[n].thickness_mm or 0) - (t + 4))
        >= (3 if min(index.parts[n].thickness_mm or 0, t + 4) <= 10 else 4)
    }
    c.check("테이퍼 이웃 = 지도에서 따로 센 문턱 이상 이웃", {i.entity_id for i in _of(both, "R-T02")} == expected)
    fillets = set(index.out(a.part_id, Relation.FILLET_WELD))
    c.check("필릿 용접 이웃은 모두 용접 재검토", {i.entity_id for i in _of(alone, "R-T03")} == fillets)
    own = [i for i in _of(alone, "R-B01") if i.entity_id == a.block_id]
    c.check(
        "조립 중 T31C 판을 바꾸면 블록 재작업(근거), 대상 블록은 가장 짧은 한 단계 경로",
        len(own) == 1 and len(own[0].path) == 1 and "근거" in own[0].note,
    )

    model = StateModel(index, as_of)
    near, far = next(
        (p, index.parts[n])
        for p in sorted(plates, key=lambda x: x.part_id)
        for n in index.out(p.part_id, Relation.BUTT_WELD)
        if index.parts[n].block_id != p.block_id
        and model.block_stage_on(index.parts[n].block_id, as_of).at_least(BlockStage.SUB_ASSEMBLY)
    )
    thicker = ThicknessChange(
        part_ids=(near.part_id,), from_mm=near.thickness_mm or 0, to_mm=(far.thickness_mm or 0) + 5
    )
    across = propagate(index, _request(as_of, thicker), book)
    far_block = [i for i in _of(across, "R-B01") if i.entity_id == far.block_id]
    c.check(
        "블록 이음 너머 이웃 판의 테이퍼가 그 블록 재작업으로 이어짐(대상 → 이웃 판 → 블록 두 단계)",
        far.part_id in {i.entity_id for i in _of(across, "R-T02")}
        and len(far_block) == 1
        and [h.rule_id for h in far_block[0].path] == ["R-T02", "R-B01"],
        [i.path for i in far_block],
    )


def _procurement(c: Checker, generated: Generated, index: GraphIndex, book: RuleBook, as_of: date) -> None:
    c.section("전파 엔진: 조달 규칙")
    model = StateModel(index, as_of)
    valve = next(
        p
        for p in sorted(index.parts.values(), key=lambda x: x.part_id)
        if p.kind is PartKind.VALVE and p.block_id.endswith(":P11C")
    )
    line_id = index.line_of_part[valve.part_id]
    planned = index.orders[index.lines[line_id].po_id].planned_order_date
    assert planned is not None
    other = next(s for s in sorted(index.specs) if s.startswith("VL-") and s != valve.spec_id)
    change = EquipmentSpecChange(part_ids=(valve.part_id,), from_spec_id=valve.spec_id, to_spec_id=other)
    now = propagate(index, _request(as_of, change), book)
    later_day = planned + timedelta(days=5)
    later = propagate(index, _request(as_of, change, confirm_on=later_day), book)
    held = propagate(
        index,
        _request(
            as_of, change, confirm_on=later_day, holds=[HoldAction(po_id=index.lines[line_id].po_id, hold_days=60)]
        ),
        book,
    )
    c.check(
        "P11C 밸브는 기준일에 미발주라 사양을 바꿔도 발주 영향 없음",
        model.line_stage_on(line_id, as_of).likely is POStatus.NOT_ORDERED and not _of(now, "R-T01"),
    )
    c.check(
        "계획 발주일 뒤에 확정하면 같은 변경에 발주 변경·취소가 생김(계획 추정)",
        {i.impact_type for i in _of(later, "R-T01")} == {ImpactType.PO_CHANGE, ImpactType.REORDER}
        and "계획 추정" in _of(later, "R-T01")[0].note,
    )
    c.check("그 발주를 보류하면 같은 확정일에도 발주 영향이 없음", not _of(held, "R-T01"))
    c.check("확정일이 기준일 뒤면 추정이라는 안내가 붙음", len(later.notes) == 2 and len(now.notes) == 1)

    vague = next(
        p
        for p in sorted(index.parts.values(), key=lambda x: x.part_id)
        if p.kind is PartKind.PLATE
        and p.part_id in index.line_of_part
        and model.line_stage_on(index.line_of_part[p.part_id], as_of).likely is None
    )
    thickness = vague.thickness_mm or 0
    vague_op = ThicknessChange(part_ids=(vague.part_id,), from_mm=thickness, to_mm=thickness + 1)
    unknown = propagate(index, _request(as_of, vague_op), book)
    vague_line = index.line_of_part[vague.part_id]
    c.check(
        "품목 단계를 모르면 발주 영향을 내고 '판단 불가' 이유(po_state)를 남김",
        {i.entity_id for i in _of(unknown, "R-T01")} == {vague_line}
        and any(u.kind is UnresolvedKind.PO_STATE and u.entity_id == vague_line for u in unknown.unresolved),
    )

    ordered = next(
        p
        for p in sorted(index.parts.values(), key=lambda x: x.part_id)
        if p.kind is PartKind.STIFFENER
        and p.part_id in index.line_of_part
        and model.line_stage_on(index.line_of_part[p.part_id], as_of).at_least(POStatus.ORDERED)
    )
    removed = propagate(index, _request(as_of, RemovePart(part_ids=(ordered.part_id,))), book)
    c.check(
        "발주된 부재를 빼면 그 품목에 발주 변경·취소(R-M02)",
        [i.entity_id for i in _of(removed, "R-M02")] == [index.line_of_part[ordered.part_id]],
    )

    t31c = sorted(
        (p for p in index.parts.values() if p.block_id.endswith(":T31C") and p.kind is PartKind.PLATE),
        key=lambda x: x.part_id,
    )
    lot = next(s for s in sorted(index.stock.values(), key=lambda s: s.lot_id) if s.reserved_block_id is not None)
    lot_spec = index.specs[lot.spec_id]
    plate = next(p for p in t31c if p.grade == lot_spec.grade and p.thickness_mm != lot_spec.thickness_mm)
    to_lot = ThicknessChange(
        part_ids=(plate.part_id,), from_mm=plate.thickness_mm or 0, to_mm=lot_spec.thickness_mm or 0
    )
    stock = {i.entity_id for i in _of(propagate(index, _request(as_of, to_lot), book), "R-M01")}
    same = {
        s.lot_id
        for s in index.stock.values()
        if index.specs[s.spec_id].grade == plate.grade
        and index.specs[s.spec_id].thickness_mm == lot_spec.thickness_mm
        and s.reserved_block_id != plate.block_id
        and not s.processed
    }
    c.check("변경 뒤 규격과 같은 다른 블록용 재고를 전용 후보로 찾음(R-M01 가)", lot.lot_id in stock and stock == same)
    reserved = tuple(
        s.model_copy(update={"reserved_block_id": plate.block_id}) if s.lot_id == lot.lot_id else s
        for s in generated.snapshot.stock
    )
    mine = GraphIndex(generated.snapshot.model_copy(update={"stock": reserved}))
    c.check(
        "대상 블록용으로 이미 예약된 재고는 전용 후보가 아님",
        lot.lot_id not in {i.entity_id for i in _of(propagate(mine, _request(as_of, to_lot), book), "R-M01")},
    )

    surplus_case = _surplus_snapshot(generated, model, as_of)
    c.check("남는 입고 자재 사례를 만들 수 있음", surplus_case is not None)
    if surplus_case is not None:
        richer, part_id, demand_line = surplus_case
        part = richer.parts[part_id]
        op = RemovePart(part_ids=(part.part_id,))
        found = _of(propagate(richer, _request(as_of, op), book), "R-M01")
        c.check(
            "남는 입고·가공 전 자재와 같은 규격의 다른 블록 수요를 찾음(R-M01 나)",
            [i.entity_id for i in found] == [demand_line] and len(found[0].path) == 2,
            [i.entity_id for i in found],
        )


def _surplus_snapshot(generated: Generated, model: StateModel, as_of: date) -> tuple[GraphIndex, str, str] | None:
    """입고(가공 전) 품목 하나와 같은 규격이 되도록 다른 블록의 미입고 품목 규격을 바꾼 지도."""
    index = model.index
    for line_id in sorted(index.lines):
        if model.line_stage_on(line_id, as_of).likely is not POStatus.RECEIVED or not index.lines[line_id].part_ids:
            continue
        line = index.lines[line_id]
        block = index.parts[line.part_ids[0]].block_id
        for other_id in sorted(index.lines):
            other = index.lines[other_id]
            consumer = other.consumed_by_activity_id
            if other_id == line_id or consumer is None or not other.part_ids:
                continue
            if index.parts[other.part_ids[0]].block_id == block:
                continue
            start = model.start_of(consumer).expected
            if model.line_stage_on(other_id, as_of).at_least(
                POStatus.RECEIVED
            ) is False and as_of < start <= as_of + timedelta(days=60):
                lines = tuple(
                    x.model_copy(update={"spec_id": line.spec_id}) if x.line_id == other_id else x
                    for x in generated.snapshot.po_lines
                )
                return GraphIndex(generated.snapshot.model_copy(update={"po_lines": lines})), line.part_ids[0], other_id
    return None


def _piping(c: Checker, index: GraphIndex, book: RuleBook, as_of: date) -> None:
    c.section("전파 엔진: 배관 규칙")
    valves = sorted((p for p in index.parts.values() if p.kind is PartKind.VALVE), key=lambda x: x.part_id)
    valve = valves[0]
    spec = index.specs[valve.spec_id]
    same_joint = next(
        s.spec_id
        for s in index.specs.values()
        if s.category == "valve"
        and s.spec_id != spec.spec_id
        and (s.nominal_diameter_dn, s.pressure_class) == (spec.nominal_diameter_dn, spec.pressure_class)
    )
    other_joint = next(
        s.spec_id
        for s in index.specs.values()
        if s.category == "valve"
        and (s.nominal_diameter_dn, s.pressure_class) != (spec.nominal_diameter_dn, spec.pressure_class)
    )
    neighbours = set(index.out(valve.part_id, Relation.PIPE_JOINT))

    def p01(to_spec: str) -> Propagation:
        op = EquipmentSpecChange(part_ids=(valve.part_id,), from_spec_id=valve.spec_id, to_spec_id=to_spec)
        return propagate(index, _request(as_of, op), book)

    c.check("연결 규격(구경·압력 등급)이 같으면 인접 배관 수정 없음", not _of(p01(same_joint), "R-P01"))
    c.check(
        "연결 규격이 다르면 배관 연결 이웃 모두 수정",
        {i.entity_id for i in _of(p01(other_joint), "R-P01")} == neighbours,
    )
    unknown = p01("VL-UNKNOWN-NEW")
    c.check(
        "새 사양이 지도에 없으면 수정으로 표시하고 연결 규격 이유를 남김",
        {i.entity_id for i in _of(unknown, "R-P01")} == neighbours
        and any(u.kind is UnresolvedKind.CONNECTION and u.entity_id == valve.part_id for u in unknown.unresolved),
    )

    model = StateModel(index, as_of)
    support = next(
        p
        for p in sorted(index.parts.values(), key=lambda x: x.part_id)
        if p.kind is PartKind.PIPE_SUPPORT and model.block_stage_on(p.block_id, as_of).at_least(BlockStage.SUB_ASSEMBLY)
    )
    spool = index.out(support.part_id, Relation.SUPPORT)[0]
    reroute = ReroutePipe(removed_part_ids=(spool,), added_spool_spec_ids=(index.parts[spool].spec_id,))
    result = propagate(index, _request(as_of, reroute), book)
    held_by = {s for s in index.out(spool, Relation.SUPPORT)}
    c.check(
        "빼는 스풀을 받치던 서포트에 부재 수정(R-P03, 원본 연결로 찾음)",
        {i.entity_id for i in _of(result, "R-P03")} == held_by,
    )
    view = ChangeView(index, _request(as_of, reroute).change)
    new_id = next(iter(view.new_parts))
    ends = set(index.out(spool, Relation.PIPE_JOINT))
    c.check(
        "새 스풀은 빼는 스풀의 양 끝에 배관 연결로 이어짐", set(view.neighbours(new_id, Relation.PIPE_JOINT)) == ends
    )
    c.check(
        "빠지는 스풀은 다른 부재의 이웃으로 나오지 않음",
        all(spool not in view.neighbours(e, Relation.PIPE_JOINT) for e in ends),
    )
    c.check(
        "착수한 블록의 서포트가 수정되면 그 블록 재작업(빼는 스풀의 블록과 같으면 한 단계 경로)",
        any(i.entity_id == support.block_id for i in _of(result, "R-B01")),
    )


def _additions(c: Checker, index: GraphIndex, book: RuleBook, as_of: date) -> None:
    c.section("전파 엔진: 더하는 연산")
    plate = sorted((p for p in index.parts.values() if p.kind is PartKind.PLATE), key=lambda x: x.part_id)[0]
    section = next(s for s in sorted(index.specs) if index.specs[s].category == "section")
    attached = AddPart(
        block_id=plate.block_id, kind=PartKind.STIFFENER, spec_id=section, qty=0.2, attach_to_part_id=plate.part_id
    )
    result = propagate(index, _request(as_of, attached), book)
    new_id = next(n.id for n in result.graph.nodes if n.virtual)
    digest = hashlib.sha256(canonical_json(normalized_op(attached))).hexdigest()[:8]
    c.check("새 부재 임시 ID = NEW:<연산 정규형 SHA-256 앞 8자리>:<순번>", new_id == f"NEW:{digest}:1", new_id)
    c.check(
        "새 부재는 붙는 판의 도면을 이어받아 그 도면 개정",
        [i.entity_id for i in _of(result, "R-D01")] == [index.drawing_of(plate)],
    )
    edges = {(e.source, e.target, e.relation) for e in result.graph.edges if e.virtual}
    c.check(
        "변경 그래프에 새 부재와 붙는 판 사이 필릿 용접이 있고, 모든 연결이 새 부재에서 나옴",
        (new_id, plate.part_id, Relation.FILLET_WELD) in edges and all(new_id in (a, b) for a, b, _ in edges),
        sorted(edges),
    )
    floating = AddPart(block_id=plate.block_id, kind=PartKind.STIFFENER, spec_id=section, qty=0.2)
    c.check(
        "붙는 위치 없이 더하면 새 부재가 확인 필요(R-X01)",
        [i.impact_type for i in propagate(index, _request(as_of, floating), book).impacts if i.rule_id == "R-X01"]
        == [ImpactType.NEEDS_CONFIRMATION],
    )
    spool = sorted((p for p in index.parts.values() if p.kind is PartKind.PIPE_SPOOL), key=lambda x: x.part_id)[0]
    target = next(
        p
        for p in sorted(index.parts.values(), key=lambda x: x.part_id)
        if p.kind is PartKind.PLATE and spool.part_id not in index.out(p.part_id, Relation.PENETRATION)
    )
    hole = AddPenetration(plate_part_id=target.part_id, pipe_part_id=spool.part_id, diameter_mm=150)
    pierced = propagate(index, _request(as_of, hole), book)
    c.check(
        "관통부 추가는 배관에 칼라(R-T04)를 내고 새 관통 연결을 영향 그래프에 점선으로 담음",
        [i.entity_id for i in _of(pierced, "R-T04")] == [spool.part_id]
        and any(e.relation is Relation.PENETRATION and e.virtual for e in pierced.graph.edges),
    )


def _validation(c: Checker, index: GraphIndex, book: RuleBook, as_of: date) -> None:
    c.section("전파 엔진: 요청 검증")
    plate = sorted((p for p in index.parts.values() if p.kind is PartKind.PLATE), key=lambda x: x.part_id)[0]
    t = plate.thickness_mm or 0.0
    good = ThicknessChange(part_ids=(plate.part_id,), from_mm=t, to_mm=t + 2)
    cases: list[tuple[str, tuple[ChangeOp, ...]]] = [
        ("없는 부재", (ThicknessChange(part_ids=("S-001:없음",), from_mm=t, to_mm=t + 2),)),
        ("변경 전 두께가 지도와 다름", (ThicknessChange(part_ids=(plate.part_id,), from_mm=t + 1, to_mm=t + 2),)),
        ("같은 연산 두 번", (good, good)),
        ("같은 부재 두께를 두 번", (good, ThicknessChange(part_ids=(plate.part_id,), from_mm=t, to_mm=t + 3))),
        ("빼는 부재를 다른 연산이 가리킴", (good, RemovePart(part_ids=(plate.part_id,)))),
        (
            "관통하는 판이 있는데 더하는 스풀이 없음",
            (
                ReroutePipe(
                    removed_part_ids=(next(p for p in sorted(index.parts) if "-SP" in p),),
                    crosses_part_ids=(plate.part_id,),
                ),
            ),
        ),
    ]
    stiffener = next(p for p in sorted(index.parts.values(), key=lambda x: x.part_id) if p.kind is PartKind.STIFFENER)
    spool = next(p for p in sorted(index.parts) if "-SP" in p)
    cases += [
        (
            "새 경로가 관통하는 부재가 판이 아님",
            (
                ReroutePipe(
                    removed_part_ids=(spool,),
                    added_spool_spec_ids=(index.parts[spool].spec_id,),
                    crosses_part_ids=(stiffener.part_id,),
                ),
            ),
        ),
    ]
    for label, ops in cases:
        try:
            propagate(index, _request(as_of, *ops), book)
            problems: tuple[str, ...] = ()
        except RequestError as error:
            problems = error.problems
        c.check(f"요청 거부: {label}", bool(problems) and all(nominal(p) for p in problems), problems)
    other_ship = ChangeRequest(ecn_id="T", title="T", ship_ids=("S-999",), intent=ChangeIntent.STRENGTH, ops=(good,))
    c.check(
        "요청 호선 밖 부재는 거부",
        c.raises(lambda: propagate(index, AnalysisRequest(change=other_ship, as_of=as_of), book), RequestError),
    )
    section = next(s for s in sorted(index.specs) if index.specs[s].category == "section")
    foreign = AddPart(block_id=plate.block_id, kind=PartKind.STIFFENER, spec_id=section, qty=0.1)
    try:
        propagate(index, AnalysisRequest(change=other_ship.model_copy(update={"ops": (foreign,)}), as_of=as_of), book)
        reasons: tuple[str, ...] = ()
    except RequestError as error:
        reasons = error.problems
    c.check("요청 호선 밖 블록에 부재를 더하면 거부", any("블록" in r and "밖" in r for r in reasons), reasons)
    # 해시 앞 8자리가 같은 두 부재 추가: 덮어쓰지 않고 거부
    clash = (
        AddPart(block_id="S-001:F11C", kind=PartKind.BRACKET, spec_id="HP200x10-A", qty=1.200476),
        AddPart(
            block_id="S-001:T31C",
            kind=PartKind.STIFFENER,
            spec_id="HP200x10-A",
            qty=1.229275,
            attach_to_part_id="S-001:T31C-PL-001",
        ),
    )
    try:
        propagate(index, _request(as_of, *clash), book)
        collided: tuple[str, ...] = ()
    except RequestError as error:
        collided = error.problems
    c.check(
        "임시 ID가 겹치는 두 부재 추가는 거부(새 부재 덮어쓰기 방지)", any("임시 ID" in r for r in collided), collided
    )

    # 두 호선 지도: 경로 변경 하나가 두 호선에 걸치면 거부, 관통 판 순서는 결과를 바꾸지 않음
    snapshot = index.snapshot
    ship = snapshot.ships[0].model_copy(update={"ship_id": "S-002"})
    zone = snapshot.zones[0].model_copy(update={"zone_id": "S-002:ZCT", "ship_id": "S-002"})
    block = snapshot.blocks[0].model_copy(update={"block_id": "S-002:X", "ship_id": "S-002", "zone_id": "S-002:ZCT"})
    twin = plate.model_copy(update={"part_id": "S-002:X-PL-001", "ship_id": "S-002", "block_id": "S-002:X"})
    sisters = GraphIndex(
        snapshot.model_copy(
            update={
                "ships": (*snapshot.ships, ship),
                "zones": (*snapshot.zones, zone),
                "blocks": (*snapshot.blocks, block),
                "parts": (*snapshot.parts, twin),
            }
        )
    )
    spool_spec = next(s for s in sorted(index.specs) if index.specs[s].category == "pipe")

    def sister_request(*crosses: str) -> AnalysisRequest:
        op = ReroutePipe(added_spool_spec_ids=(spool_spec,), crosses_part_ids=crosses)
        change = ChangeRequest(
            ecn_id="T", title="T", ship_ids=("S-001", "S-002"), intent=ChangeIntent.INTERFERENCE, ops=(op,)
        )
        return AnalysisRequest(change=change, as_of=as_of)

    try:
        propagate(sisters, sister_request(plate.part_id, twin.part_id), book)
        spanning: tuple[str, ...] = ()
    except RequestError as error:
        spanning = error.problems
    c.check("배관 경로 변경 하나가 여러 호선에 걸치면 거부", any("여러 호선" in r for r in spanning), spanning)
    neighbour = next(n for n in index.out(plate.part_id, Relation.BUTT_WELD))
    forward = propagate(sisters, sister_request(plate.part_id, neighbour), book)
    backward = propagate(sisters, sister_request(neighbour, plate.part_id), book)
    c.check("관통 판 순서를 바꿔도 같은 결과(새 스풀 호선 포함)", forward == backward)
