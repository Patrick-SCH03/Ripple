"""비용 엔진(docs/engine.md(비용·일정) 2·4절): 금액 시나리오, 산식 재계산, 항등식, 판정일 단조성."""

from __future__ import annotations

import random
from collections import Counter
from datetime import date, timedelta
from math import ceil

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.base import Frozen
from ripple.contracts.change import (
    AddPart,
    ChangeRequest,
    EquipmentSpecChange,
    GradeChange,
    RemovePart,
    ThicknessChange,
)
from ripple.contracts.dataset import EcnSplit, GeneratedEcn
from ripple.contracts.domain import BLOCK_ACTIVITY_ORDER, DIRECT_PERFORMER, Block, PartKind, POStatus
from ripple.contracts.params import ParamSet
from ripple.contracts.result import Amount, CostLine, Determinacy, ImpactType, UnresolvedKind
from ripple.contracts.rulebook import RuleBook
from ripple.engine.analyze import analyze
from ripple.engine.cost import amount_of, difference, round_won, worst_case
from ripple.engine.cost.amounts import Scenario, mixed
from ripple.engine.index import GraphIndex
from ripple.engine.overlay import op_key
from ripple.engine.propagate import RequestError
from ripple.engine.state import rank
from ripple.engine.timing import Evaluation, Evaluator
from ripple.generator.build import generate
from ripple.generator.io import load_config

T31C_PLATE = "S-001:T31C-PL-007"
P11C_VALVE = "S-001:P11C-VLCS-001"
F11C_STIFFENER = "S-001:F11C-ST-003"
BLOCK_KINDS = tuple(kind.value for kind in BLOCK_ACTIVITY_ORDER)  # 소조립 → … → 선행도장 → PE → 탑재


def run(c: Checker) -> None:
    _amounts(c)
    config = load_config()
    generated = generate(config)
    index = GraphIndex(generated.snapshot)
    book = load_rulebook(PROJECT_ROOT / "rules" / "propagation.yaml")
    params = load_params(PROJECT_ROOT / "params" / "cost_v1.yaml")
    as_of = config.scenario_date
    _recompute_plate(c, index, book, params, as_of)
    _recompute_valve(c, index, book, params, as_of)
    _identity(c, index, book, params, as_of, generated.ecns)
    _same_request_demand(c, index, book, params, as_of)
    _same_line_sweep(c, index, book, params, as_of)
    _monotone(c, index, book, params, generated.ecns)
    _unknown_stage(c, index, book, params, generated.ecns)
    _grade_ratio_range(c, index, book, params, as_of)
    _new_work(c, index, book, params, as_of, generated.ecns)


def request_of(as_of: date, *ops: Frozen, confirm_on: date | None = None) -> AnalysisRequest:
    change = ChangeRequest.model_validate(
        {
            "ecn_id": "T-1",
            "title": "검사",
            "ship_ids": ["S-001"],
            "intent": "strength",
            "ops": [o.model_dump() for o in ops],
        }
    )
    return AnalysisRequest(change=change, as_of=as_of, confirm_on=confirm_on)


def _lines(ev: Evaluation) -> dict[str, CostLine]:
    return {line.line_id: line for line in ev.lines}


def _qty(line: CostLine) -> float:
    return float(line.inputs.get("qty", 0.0))


# ---------- 금액 시나리오 ----------


def _amounts(c: Checker) -> None:
    c.section("비용: 금액 시나리오")
    c.check(
        "원 단위 반올림은 0.5를 0에서 먼 쪽으로",
        (round_won(2.5), round_won(-2.5), round_won(2.4999), round_won(-0.4)) == (3, -3, 2, 0),
    )
    a = amount_of(lambda s: {Scenario.LOW: 1.0, Scenario.VALUE: 2.0, Scenario.HIGH: 4.0}[s])
    c.check("세 시나리오 금액은 low·value·high에 그대로 들어감", (a.low, a.value, a.high) == (1, 2, 4))
    w = worst_case([Amount(value=5, low=2, high=6), Amount(value=7, low=0, high=9)])
    c.check("단계를 모르면 low는 최솟값, value·high는 최댓값", (w.low, w.value, w.high) == (0, 7, 9))
    d = difference(Amount(value=10, low=4, high=30), Amount(value=3, low=3, high=3))
    c.check("날짜 차이는 같은 시나리오끼리 뺀 값의 최소~최대", (d.low, d.value, d.high) == (1, 7, 27))
    m = mixed(lambda s: {Scenario.LOW: 10.0, Scenario.VALUE: 20.0, Scenario.HIGH: 30.0}[s], lambda s: 5.0)
    c.check("절감액은 이득 low − 비용 high ~ 이득 high − 비용 low", (m.low, m.value, m.high) == (5, 15, 25))


# ---------- 산식 재계산 ----------


def _p(params: ParamSet, key: str) -> tuple[float, float, float]:
    param = params.get(key)
    return param.low, param.value, param.high


def _cancel(params: ParamSet, index: GraphIndex, line_id: str, stage: POStatus) -> tuple[float, float, float]:
    """명세 4-2 취소·변경률(최소·대표·최대): 강재(판·형강) 품목은 시나리오마다
    steel.max_cancel_loss_ratio를 넘지 않음."""
    ratio = _p(params, f"po_cancel_ratio.{stage.value}")
    if index.specs[index.lines[line_id].spec_id].category not in ("plate", "section"):
        return ratio
    cap = _p(params, "steel.max_cancel_loss_ratio")
    low, value, high = (min(r, k) for r, k in zip(ratio, cap, strict=True))
    return low, value, high


def _difficulty(params: ParamSet, block: Block) -> float:
    """명세 4-4 블록 난이도 계수(문서 산식만으로): 형상 × 의장 밀도 × 전장품(넷째 자리), 상한(여섯째 자리)."""
    if block.shape is None and block.outfit_items is None and block.electric_items is None:
        return 1.0
    shape = round(params.value(f"difficulty.shape.{block.shape.value}"), 4) if block.shape is not None else 1.0

    def density(items: int | None, name: str) -> float:
        if items is None:
            return 1.0
        top, full = params.value(f"difficulty.{name}_max"), params.value(f"difficulty.{name}_full_per_t")
        return round(1 + (top - 1) * min(1.0, items / block.steel_weight_t / full), 4)

    product = shape * density(block.outfit_items, "outfit") * density(block.electric_items, "electric")
    return round(min(product, params.value("difficulty.cap")), 6)


def _rework_parts(
    index: GraphIndex,
    params: ParamSet,
    block_id: str,
    kinds: tuple[str, ...],
    scaled_weight: float,
    multiplier: tuple[float, float, float],
) -> tuple[int, int, int]:
    """명세 4-4·4-4-1: 공정마다 (중량 × 난이도) × 공수 × 배수 × 그 공정 수행 주체 단가를 원 단위로 반올림해 더함."""
    sums = [0, 0, 0]
    for kind in kinds:
        activity = next(a for a in index.activities.values() if a.block_id == block_id and a.kind.value == kind)
        performer = activity.performer
        labor = "prime" if performer in (None, DIRECT_PERFORMER) else "crew"
        rate = _p(params, f"labor_rate_per_hour.{labor}")
        hours = _p(params, f"base_work_hours_per_t.{kind}")
        for i in range(3):
            sums[i] += round_won(scaled_weight * hours[i] * multiplier[i] * rate[i])
    return sums[0], sums[1], sums[2]


def _close(line: CostLine | None, expected: tuple[float, ...]) -> bool:
    low, value, high = (round_won(x) for x in expected)
    return line is not None and (line.amount.low, line.amount.value, line.amount.high) == (low, value, high)


def _recompute_plate(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, as_of: date) -> None:
    """데모 2: T31C(조립 중) 이음부 판 15 → 16.5mm, 가공 끝난 발주, 같은 규격 재고 LOT-04."""
    c.section("비용: 산식 다시 계산(T31C 판 두께, 문서 산식만으로)")
    part = index.parts[T31C_PLATE]
    request = request_of(as_of, ThicknessChange(part_ids=(T31C_PLATE,), from_mm=15.0, to_mm=16.5))
    ev = Evaluator(index, request, book, params)
    result = ev.evaluate(as_of, ())
    lines = _lines(result)
    line_id = index.line_of_part[T31C_PLATE]
    price = index.lines[line_id].unit_price_krw
    q, q_new = part.qty, part.qty * 16.5 / 15.0
    stage = ev.state(()).line_stage_on(line_id, as_of).likely
    block_stage = ev.state(()).block_stage_on(part.block_id, as_of).likely
    assert stage is not None and block_stage is not None
    cover = min(index.stock["LOT-04"].qty, q_new)
    ratio = _cancel(params, index, line_id, stage)
    handling = _p(params, "stock.reallocation_handling_per_t")
    premium = _p(params, "reorder.expedite_premium_ratio")
    kinds = BLOCK_KINDS[: rank(block_stage) - 1]
    base = [sum(_p(params, f"base_work_hours_per_t.{k}")[i] for k in kinds) for i in range(3)]
    multiplier = _p(params, f"rework_multiplier.{block_stage.value}")
    design = _p(params, "labor_rate_per_hour.design")
    weight = (part.weight_kg or 0) / 1000
    difficulty = _difficulty(params, index.blocks[part.block_id])
    rework_expected = _rework_parts(index, params, part.block_id, kinds, weight * difficulty, multiplier)
    rework = [line for line in result.lines if line.rule_id == "R-B01" and line.entity_id == part.block_id]
    drawing_hours = _p(params, "minor_work_hours.drawing_revision_per_drawing")
    drawing = next((v for k, v in lines.items() if k.startswith("R-D01:drawing_revision:")), None)
    checks = {
        "자재비 차이 = 새 수량 × 단가 − 원래 수량 × 단가": _close(
            lines.get(f"C-01:material:{T31C_PLATE}"), (q_new * price - q * price,) * 3
        ),
        f"발주 변경·취소 = 취소율[{stage.value}] × 수량 × 단가": _close(
            lines.get(f"R-T01:po_change:{line_id}"), tuple(r * q * price for r in ratio)
        ),
        "재고 전용 = 충당 × 취급비 − 충당 × 새 단가": _close(
            lines.get(f"R-M01:stock:LOT-04:{T31C_PLATE}"), tuple(cover * h - cover * price for h in handling)
        ),
        "새 규격 할증 = 할증률 × (새 수량 − 재고 충당) × 새 단가": _close(
            lines.get(f"R-T01:reorder:{line_id}"), tuple(p * (q_new - cover) * price for p in premium)
        ),
        f"블록 재작업(작업반 몫 줄 포함) = 공정마다 원 단위 반올림한 중량 × 공수 × 배수[{block_stage.value}]"
        " × 난이도 × 수행 주체 단가의 합": bool(rework)
        and tuple(sum(getattr(line.amount, f) for line in rework) for f in ("low", "value", "high")) == rework_expected,
        "도면 개정 = 도면 공수 × 설계 단가": _close(
            drawing, tuple(h * r for h, r in zip(drawing_hours, design, strict=True))
        ),
    }
    for name, ok in checks.items():
        c.check(name, ok, [(k, v.amount) for k, v in lines.items()])
    weld = [line for line in result.lines if line.rule_id == "R-T03"]
    weld_hours = _p(params, "minor_work_hours.weld_recheck_per_joint")
    weld_each = tuple(h * r for h, r in zip(weld_hours, design, strict=True))
    c.check(
        "용접 재검토 = 이음 하나 × 공수 × 설계 단가(이웃 보강재·브라켓마다)",
        bool(weld) and all(_close(line, weld_each) for line in weld),
        len(weld),
    )
    days = ceil(weight * base[1] * multiplier[1] * difficulty / params.value("rework.crew_hours_per_day"))
    c.check(
        "재작업 일수 = ⌈대표 공수 / 하루 투입 공수⌉, 운반 공정(진행 중인 조립)이 그만큼 늘어남",
        result.schedule.added_days_by_activity.get(f"{part.block_id}:assembly") == days,
        (days, result.schedule.added_days_by_activity),
    )
    c.check("총액 = 줄의 합", result.total == Amount.total([line.amount for line in result.lines]))


def _recompute_valve(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, as_of: date) -> None:
    """데모 1: P11C(미착수) 밸브 사양 변경, 밸브 발주는 미발주 → 자재비 차이 + 도면만."""
    c.section("비용: 산식 다시 계산(P11C 밸브 사양 변경)")
    part = index.parts[P11C_VALVE]
    new_spec = "VL-BALL-DN100-16K"
    op = EquipmentSpecChange(part_ids=(P11C_VALVE,), from_spec_id=part.spec_id, to_spec_id=new_spec)
    result = Evaluator(index, request_of(as_of, op), book, params).evaluate(as_of, ())
    lines = _lines(result)
    old_price = index.lines[index.line_of_part[P11C_VALVE]].unit_price_krw
    expected = part.qty * (index.specs[new_spec].unit_price_krw - old_price)
    c.check(
        "자재비 차이 = 수량 × (새 규격 단가 − 원래 단가)",
        _close(lines.get(f"C-01:material:{P11C_VALVE}"), (expected,) * 3),
    )
    c.check(
        "미발주라 발주 변경·할증·재작업 줄이 없음(도면 개정 + 자재비 차이만)",
        {line.rule_id for line in result.lines} == {"C-01", "R-D01"},
        sorted(lines),
    )
    c.check("같은 리드타임으로 발주 예정일에 발주하므로 일정 지연 없음", not result.schedule.added_days_by_activity)
    po_id = index.lines[index.line_of_part[P11C_VALVE]].po_id
    ev = Evaluator(index, request_of(as_of, op), book, params)
    planned = next(w.estimate for w in ev.state(()).windows(po_id) if w.stage is POStatus.ORDERED)
    demand = next(d for d in ev.evaluate(as_of, ()).demands if d.part_id == P11C_VALVE)
    c.check(
        "미발주 품목의 새 자재는 원래 발주 예정일(대표 진입일)에 새 규격 리드타임으로 발주",
        planned is not None
        and planned > as_of
        and demand.arrival == planned + timedelta(days=index.orders[po_id].lead_time_days),
        (planned, demand.arrival),
    )
    reserved = Evaluator(
        index, request_of(as_of, ThicknessChange(part_ids=(T31C_PLATE,), from_mm=15.0, to_mm=17.5)), book, params
    ).evaluate(as_of, ())
    found = {i.entity_id for i in reserved.impacts if i.rule_id == "R-M01" and i.entity_id.startswith("LOT-")}
    c.check(
        "다른 블록용으로 예약된 재고는 영향으로만 보이고 쓰지 않음(17.5mm: LOT-01·LOT-03)",
        bool(found)
        and all(index.stock[lot].reserved_block_id for lot in found)
        and not reserved.reallocations
        and not any(line.line_id.startswith("R-M01:stock:") for line in reserved.lines),
        sorted(found),
    )


# ---------- 항등식(4-3) ----------


def _identity(
    c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, as_of: date, ecns: tuple[GeneratedEcn, ...]
) -> None:
    c.section("비용: 항등식(발주 품목 단위, 재고 충당·다른 블록 전용 포함)")
    cases: list[AnalysisRequest] = [
        request_of(as_of, ThicknessChange(part_ids=(T31C_PLATE,), from_mm=15.0, to_mm=16.5)),
        request_of(
            as_of,
            GradeChange(part_ids=(F11C_STIFFENER,), from_grade="AH36", to_grade="DH36"),
            confirm_on=date(2026, 12, 19),
        ),
    ]
    rng = random.Random(11)
    for ecn in rng.sample(list(ecns), 120):
        request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of)
        if any(isinstance(op, ThicknessChange | GradeChange | EquipmentSpecChange) for op in request.change.ops):
            cases.append(request)
            cases.append(request.model_copy(update={"confirm_on": request.as_of + timedelta(days=rng.randint(10, 60))}))
    checked = stock_cases = surplus_cases = 0
    failures: list[str] = []
    p, h = params.value("reorder.expedite_premium_ratio"), params.value("stock.reallocation_handling_per_t")
    for request in cases:
        try:
            ev = Evaluator(index, request, book, params)
        except RequestError:
            continue
        result = ev.evaluate(request.effective_confirm_on, ())
        lines = _lines(result)
        stock_cases += any(k.startswith("R-M01:stock:") for k in lines)
        surplus_cases += any(k.startswith("R-M01:handling:") for k in lines)
        for line_id in sorted({ch.line_id for ch in ev.changes if ch.line_id}):
            parts = [ch for ch in ev.changes if ch.line_id == line_id]
            loss = lines.get(f"R-T01:po_change:{line_id}")
            if loss is None or loss.determinacy is Determinacy.STATE_UNKNOWN:
                continue
            checked += 1
            stage = ev.state(()).line_stage_on(line_id, request.effective_confirm_on).likely
            assert stage is not None
            r = _cancel(params, index, line_id, stage)[1]
            price = index.lines[line_id].unit_price_krw
            stock = {k: v for k, v in lines.items() if k.startswith("R-M01:stock:")}
            covered = {
                ch.part_id: sum(_qty(v) for k, v in stock.items() if k.endswith(f":{ch.part_id}")) for ch in parts
            }
            handling = [v for k, v in lines.items() if k.startswith(f"R-M01:handling:{line_id}:")]
            moved = sum(_qty(v) for v in handling)
            q = sum(ch.q for ch in parts)
            o = 1 if rank(stage) >= rank(POStatus.ORDERED) else 0
            bought = sum((ch.q_new - covered[ch.part_id]) * ch.price_new for ch in parts)
            expected = (
                o * (r * (q - moved) * price + p * bought) + bought - q * price + (sum(covered.values()) + moved) * h
            )
            own = [f"C-01:material:{ch.part_id}" for ch in parts] + [
                f"R-T01:po_change:{line_id}",
                f"R-T01:reorder:{line_id}",
            ]
            got = sum(lines[k].amount.value for k in own if k in lines)
            got += sum(v.amount.value for k, v in stock.items() if any(k.endswith(f":{ch.part_id}") for ch in parts))
            got += sum(v.amount.value for v in handling)
            if abs(got - expected) > 2 * len(parts) + 4:  # 줄마다 원 단위 반올림
                failures.append(f"{request.change.ecn_id} {line_id}: {got} ≠ {expected:.0f}")
    c.check(
        f"발주 변경 품목 {checked}개: 자재비 차이 + 손실 + 할증 + 재고 + 전용 취급비 = 원래 계획 대비 증가분",
        checked >= 20 and not failures,
        (checked, failures[:3]),
    )
    c.check(
        "재고 충당 사례와 다른 블록 전용 사례를 모두 포함",
        stock_cases >= 1 and surplus_cases >= 1,
        (stock_cases, surplus_cases),
    )


def _same_request_demand(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, as_of: date) -> None:
    """4-7 (나): 받는 품목의 남은 수량은 이 요청이 빼거나 규격을 바꾸는 부재를 뺀 것, 같은 L → O는 취급비 줄 하나."""
    c.section("비용: 같은 요청 안의 삭제·규격 변경과 다른 블록 전용")
    confirm = date(2026, 12, 19)
    source, target = "PO-0104#2", "PO-0126#1"
    removed, changed, receiver = "S-001:F11C-ST-003", "S-001:F11C-ST-014", "S-001:F31C-ST-018"
    grade = {"from_grade": "AH36", "to_grade": "DH36"}
    c.check(
        "전제: 두 보강재는 같은 발주 품목, 받는 품목의 소비 부재는 하나",
        index.line_of_part.get(removed) == source == index.line_of_part.get(changed)
        and sorted(p for p, line in index.line_of_part.items() if line == target) == [receiver],
    )

    both = analyze(
        index,
        request_of(
            as_of,
            RemovePart(part_ids=(removed,)),
            GradeChange(part_ids=(changed,), **grade),
            confirm_on=confirm,
        ),
        book,
        params,
    )
    handling = [line for line in both.cost_lines if line.line_id.startswith("R-M01:handling:")]
    q = index.parts[removed].qty + index.parts[changed].qty
    c.check(
        "같은 품목의 삭제와 규격 변경이 같은 곳으로 전용되면 취급비 줄은 하나, 수량 = min(두 수량 합, 받는 품목 수량)",
        [line.line_id for line in handling] == [f"R-M01:handling:{source}:{target}"]
        and abs(_qty(handling[0]) - min(q, index.lines[target].qty)) < 1e-9,
        [(line.line_id, line.inputs) for line in handling],
    )

    alone = request_of(as_of, GradeChange(part_ids=(removed,), **grade), confirm_on=confirm)
    with_gone = request_of(
        as_of, GradeChange(part_ids=(removed,), **grade), RemovePart(part_ids=(receiver,)), confirm_on=confirm
    )
    alone_result = analyze(index, alone, book, params)
    gone_result = analyze(index, with_gone, book, params)
    stage = Evaluator(index, with_gone, book, params).state(()).line_stage_on(source, confirm).likely
    assert stage is not None
    loss = next(line for line in gone_result.cost_lines if line.line_id == f"R-T01:po_change:{source}")
    expected = _cancel(params, index, source, stage)[1] * index.parts[removed].qty * index.lines[source].unit_price_krw
    c.check(
        "받는 품목의 유일한 소비 부재를 같은 요청에서 빼면 전용·손실 공제가 없음(빼지 않으면 전용함)",
        any(line.line_id == f"R-M01:handling:{source}:{target}" for line in alone_result.cost_lines)
        and not any(line.line_id.startswith("R-M01:handling:") for line in gone_result.cost_lines)
        and not any(i.entity_id == target and i.impact_type is ImpactType.REALLOCATE_STOCK for i in gone_result.impacts)
        and abs(loss.amount.value - expected) <= 1,
        (loss.amount.value, round(expected)),
    )

    # 받는 부재를 빼는 대신 강종을 바꿔도(규격 ID는 그대로) 받을 수요가 아니다
    regraded = analyze(
        index,
        request_of(
            as_of,
            GradeChange(part_ids=(removed,), **grade),
            GradeChange(part_ids=(receiver,), **grade),
            confirm_on=confirm,
        ),
        book,
        params,
    )
    c.check(
        "받는 품목의 유일한 소비 부재를 같은 요청에서 강종 변경하면 그 품목으로 전용하지 않음(영향도 없음)",
        not any(line.line_id.startswith("R-M01:handling:") for line in regraded.cost_lines)
        and not any(i.entity_id == target and i.impact_type is ImpactType.REALLOCATE_STOCK for i in regraded.impacts),
        [(i.impact_type.value, i.rule_id) for i in regraded.impacts if i.entity_id == target],
    )

    # 미발주 품목은 발주 변경 영향이 없어도, 이 요청이 빼는 부재만큼 받을 수요가 줄어든다
    unordered, kept = "PO-0123#3", "S-001:F31C-ST-007"
    late = date(2026, 11, 2)
    partial = request_of(
        as_of,
        GradeChange(part_ids=tuple(f"S-001:A11C-ST-{n}" for n in ("001", "013", "014")), **grade),
        RemovePart(part_ids=("S-001:F31C-ST-001",)),
        confirm_on=late,
    ).model_copy(update={"horizon_days": 120})
    stage = Evaluator(index, partial, book, params).state(()).line_stage_on(unordered, late).likely
    moved = sum(
        _qty(line)
        for line in analyze(index, partial, book, params).cost_lines
        if line.line_id.endswith(f":{unordered}") and line.line_id.startswith("R-M01:handling:")
    )
    c.check(
        "미발주 받는 품목의 일부 부재를 같은 요청에서 빼면 남은 부재 수량까지만 전용(0.346t가 아니라 0.146t)",
        stage is not None
        and rank(stage) < rank(POStatus.ORDERED)
        and sorted(p for p, line in index.line_of_part.items() if line == unordered) == ["S-001:F31C-ST-001", kept]
        and 0 < moved <= index.parts[kept].qty + 1e-9,
        (stage, moved, index.parts[kept].qty),
    )


def _same_line_sweep(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, as_of: date) -> None:
    """같은 품목의 두 부재에 삭제 + 강종 변경을 거는 요청을, 같은 규격 품목이 따로 있는 품목마다 확정일 2개로 훑는다.

    취급비 줄 ID 충돌을 잡는 검사다(무작위로 두 건을 합친 요청으로는 잡히지 않는 경우).
    """
    c.section("비용: 같은 품목에 삭제와 강종 변경을 함께 건 요청")
    shared = Counter(line.spec_id for line in index.lines.values())
    analyzed = rejected = 0
    failures: list[str] = []
    for line_id, line in sorted(index.lines.items()):
        steel = [p for p in line.part_ids if p in index.parts and index.parts[p].grade]
        if shared[line.spec_id] < 2 or len(steel) < 2:
            continue
        first, second = steel[0], steel[1]
        grade = index.parts[second].grade or ""
        ops = (
            RemovePart(part_ids=(first,)),
            GradeChange(part_ids=(second,), from_grade=grade, to_grade="DH36" if grade != "DH36" else "AH36"),
        )
        for offset in (30, 60):
            request = request_of(as_of, *ops, confirm_on=as_of + timedelta(days=offset))
            try:
                analyze(index, request, book, params)
                analyzed += 1
            except RequestError:
                rejected += 1
            except Exception as error:  # 계약 위반·예상 못 한 오류는 요청 거절이 아니라 결함으로 센다
                failures.append(f"{line_id}+{offset}: {type(error).__name__} {str(error)[:120]}")
    c.check(
        f"품목 {analyzed // 2}개 × 확정일 2개: 분석 {analyzed} · 요청 거절 {rejected}, 그 밖의 오류 없음",
        analyzed >= 200 and not failures,
        failures[:3],
    )


# ---------- 판정일 단조성 ----------


def _monotone(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, ecns: tuple[GeneratedEcn, ...]) -> None:
    c.section("비용: 판정일이 늦어져도 단계 비용은 줄지 않음")
    rng = random.Random(5)
    tried = ok = 0
    for ecn in rng.sample(list(ecns), 40):
        request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of)
        try:
            ev = Evaluator(index, request, book, params)
        except RequestError:
            continue
        tried += 1
        previous: dict[str, int] | None = None
        steady = True
        for offset in range(0, 61, 4):
            result = ev.evaluate(request.as_of + timedelta(days=offset), ())
            if result.reallocations:
                previous = None
                continue
            current = {
                line.line_id: line.amount.value
                for line in result.lines
                if line.rule_id in ("R-T01", "R-M02", "R-B01") and line.determinacy is Determinacy.KNOWN
            }
            if previous is not None:
                steady &= all(current.get(k, 0) >= v for k, v in previous.items())
            previous = current
        ok += steady
    c.check(
        f"설계변경 {tried}건 × 판정일 16개: 발주 손실·할증·재작업 줄이 줄지 않음(전용 없는 날)",
        ok == tried,
        (ok, tried),
    )


def _unknown_stage(
    c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, ecns: tuple[GeneratedEcn, ...]
) -> None:
    c.section("비용: 단계를 모를 때")
    found = 0
    good = True
    for ecn in ecns:
        request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of)
        try:
            result = Evaluator(index, request, book, params).evaluate(request.as_of, ())
        except RequestError:
            continue
        unknown = {u.entity_id for u in result.unresolved if u.kind is UnresolvedKind.PO_STATE}
        for line in result.lines:
            if line.entity_id in unknown and line.rule_id in ("R-T01", "R-M02"):
                found += 1
                good &= line.determinacy is Determinacy.STATE_UNKNOWN
        if found >= 5:
            break
    c.check(
        "품목 단계를 모르는 발주 줄은 '판단 불가'로 표시하고 가능한 단계 범위 전체를 금액 범위로 냄",
        found >= 1 and good,
        found,
    )


def _grade_ratio_range(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, as_of: date) -> None:
    c.section("비용: 파라미터 검사")
    ratio = params.get("steel.grade_price_ratio.EH36")
    broken = params.model_copy(
        update={
            "params": {
                **params.params,
                "steel.grade_price_ratio.EH36": ratio.model_copy(update={"low": ratio.value - 0.01}),
            }
        }
    )
    request = request_of(as_of, ThicknessChange(part_ids=(T31C_PLATE,), from_mm=15.0, to_mm=16.5))
    c.check(
        "강종 단가 비율에 범위를 두면 거부(분모에도 쓰여 방향이 정해지지 않음)",
        c.raises(lambda: Evaluator(index, request, book, broken)),
    )


# ---------- 새 부재의 정상 제작 공수(C-02) ----------


def _new_work(
    c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, as_of: date, ecns: tuple[GeneratedEcn, ...]
) -> None:
    """docs/engine.md(비용·일정) 4-1-2: 강재 부재 추가마다 W × 블록 공정 6개 공수 합 × 생산 단가, 판정일과 무관."""
    c.section("비용: 새 부재의 정상 제작 공수(C-02)")
    adds = [e for e in ecns if e.split is EcnSplit.DEV and any(isinstance(op, AddPart) for op in e.change.ops)]
    wrong: list[str] = []
    stray: list[str] = []
    moving: list[str] = []
    checked = 0
    for ecn in adds:
        request = AnalysisRequest(change=ecn.change, as_of=as_of)
        try:
            result = analyze(index, request, book, params)
        except RequestError:
            continue
        found = {line.line_id: line for line in result.cost_lines if line.rule_id == "C-02"}
        expected: set[str] = set()
        for op in ecn.change.ops:
            if not isinstance(op, AddPart):
                continue
            spec = index.specs[op.spec_id]
            if spec.unit != "t" or spec.category not in ("plate", "section"):
                continue
            line_id = f"C-02:new_work:NEW:{op_key(op)}:1"
            expected.add(line_id)
            crew = "subcontractor" if index.blocks[op.block_id].fabricator_id else "prime"
            hours = [sum(_p(params, f"base_work_hours_per_t.{k}")[i] for k in BLOCK_KINDS) for i in range(3)]
            rate = _p(params, f"labor_rate_per_hour.{crew}")
            if not _close(found.get(line_id), tuple(op.qty * hours[i] * rate[i] for i in range(3))):
                wrong.append(f"{ecn.change.ecn_id}:{line_id}")
            checked += 1
        stray += [f"{ecn.change.ecn_id}:{line_id}" for line_id in set(found) - expected]
        amounts = {
            point.confirm_on: {
                line.line_id: line.amount
                for line in Evaluator(index, request, book, params).evaluate(point.confirm_on, ()).lines
                if line.rule_id == "C-02"
            }
            for point in result.timing.curve[:: max(1, len(result.timing.curve) // 4)]
        }
        if len({tuple(sorted(a.items())) for a in amounts.values()}) > 1:
            moving.append(ecn.change.ecn_id)
    c.check(
        f"강재 부재 추가마다 C-02 줄 = 문서 산식(공수 합 × 생산 단가, 시나리오 셋) — {checked}건",
        checked > 0 and not wrong,
        wrong[:3],
    )
    c.check("강재가 아닌 새 부재·다른 연산에는 C-02 줄이 없음", not stray, stray[:3])
    c.check("C-02 금액은 판정일과 무관(곡선의 여러 날에서 같음)", not moving, moving[:3])
    others = [e for e in ecns if e.split is EcnSplit.DEV and not any(isinstance(op, AddPart) for op in e.change.ops)][
        :40
    ]
    leaked = [
        e.change.ecn_id
        for e in others
        if any(
            line.rule_id == "C-02"
            for line in analyze(index, AnalysisRequest(change=e.change, as_of=as_of), book, params).cost_lines
        )
    ]
    c.check("부재 추가가 없는 설계변경 40건에는 C-02 줄이 없음", not leaked, leaked[:3])
    valve = AddPart(block_id="S-001:E21C", kind=PartKind.VALVE, spec_id="VL-BALL-DN100-16K", qty=1)
    plate = AddPart(block_id="S-001:E21C", kind=PartKind.BRACKET, spec_id="BR-AH36-10.0", qty=0.05)
    both = analyze(index, request_of(as_of, valve, plate), book, params)
    kinds = sorted(line.entity_id for line in both.cost_lines if line.rule_id == "C-02")
    c.check(
        "밸브(개수 단위) 추가에는 C-02가 없고 함께 더한 강재 브라켓에만 있음",
        kinds == [f"NEW:{op_key(plate)}:1"],
        kinds,
    )
