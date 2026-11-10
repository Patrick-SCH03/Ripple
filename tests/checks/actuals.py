"""숨긴 실제 비용·지연 모델(docs/data.md(생성기) 6-1): 결정성, 엔진과의 차분(확인 모드), 잡음 모드 성질, 일정 검산."""

from __future__ import annotations

import random
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.change import AddPart, ChangeRequest, RemovePart, ThicknessChange
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.domain import ActivityKind, ConnectionKind, PartKind, POStatus, ZoneBoundary
from ripple.contracts.params import ParamSet
from ripple.contracts.result import Determinacy
from ripple.contracts.rulebook import RuleBook
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.engine.timing import Evaluator
from ripple.generator.actuals import (
    FACTORS,
    PLATE_DELAY_DAYS,
    ActualOutcome,
    Factor,
    HiddenModel,
    delivery_added,
    quantile_days,
)
from ripple.generator.build import Generated, generate
from ripple.generator.io import load_config


def run(c: Checker) -> None:
    c.section("숨긴 실제 비용·지연 모델")
    config = load_config()
    generated = generate(config)
    path = PROJECT_ROOT / "params" / "cost_v1.yaml"
    actual = HiddenModel(generated, path)
    oracle = HiddenModel(generated, path, oracle=True)
    dev = [e for e in generated.ecns if e.split is EcnSplit.DEV]
    as_of = config.scenario_date
    c.check(
        "참 발주 단계 날짜는 별도 보관하고 공개 진입일에는 기준일 뒤 날짜가 없다",
        all(len(generated.actual_po_stages[po.po_id]) == 4 for po in generated.snapshot.purchase_orders)
        and all(day <= as_of for po in generated.snapshot.purchase_orders for day in po.entered_on.values()),
    )
    c.check(
        "블록 공정 참 착수 하한은 계획일부터 0~3일이다",
        all(
            0 <= (generated.actual_activity_start_floor[a.activity_id] - a.planned_start).days <= 3
            for a in generated.snapshot.activities
            if a.kind is not ActivityKind.MILESTONE
        ),
    )

    repeated = [actual.outcome(e.change, as_of, as_of) == actual.outcome(e.change, as_of, as_of) for e in dev[:8]]
    c.check("같은 사례 여덟 건을 두 번 계산하면 결과가 같다", len(repeated) >= 5 and all(repeated))

    actuals = [actual.outcome(e.change, as_of, as_of) for e in dev]
    c.check(
        "모든 총액은 항목 합과 미반영 비용의 합이다",
        all(x.total_krw == sum(i.krw for i in x.items) + x.unmodeled_krw for x in actuals),
    )
    c.check(
        "출구 최대 지연은 출구별 참 지연의 최댓값이다",
        all(x.max_exit_delay_days == max(x.exit_delay_days.values(), default=0) for x in actuals),
    )
    c.check(
        "손실·할증·재작업·작은 작업·지체상금 항목은 음수가 아니다",
        all(i.krw >= 0 for x in actuals for i in x.items if i.family not in {"material_delta", "reallocation"}),
    )
    incidence = sum(x.unmodeled_krw > 0 for x in actuals) / len(actuals)
    c.check("개발 200건의 미반영 비용 빈도는 5~15%다", 0.05 <= incidence <= 0.15, incidence)
    c.check(
        "참 파라미터는 각 YAML 범위 안에 있다",
        all(param.low <= actual.param(key) <= param.high for key, param in actual.params.params.items()),
    )
    for group, stages in (
        ("po_cancel_ratio", ("not_ordered", "ordered", "material_secured", "in_fabrication", "received", "processed")),
        (
            "rework_multiplier",
            (
                "not_started",
                "steel_received",
                "sub_assembly",
                "panel",
                "assembly",
                "pre_outfitting",
                "pre_painting",
                "erected",
            ),
        ),
    ):
        values = [actual.param(f"{group}.{stage}") for stage in stages]
        c.check(f"{group} 참값이 단계 순서대로 감소하지 않는다", values == sorted(values), values)
    c.check(
        "확인 모드는 대표 파라미터와 미반영 비용 0을 쓴다",
        all(oracle.param(key) == param.value for key, param in oracle.params.params.items())
        and all(oracle.outcome(e.change, as_of, as_of).unmodeled_krw == 0 for e in dev[:5]),
    )

    index = GraphIndex(generated.snapshot)
    book = load_rulebook(PROJECT_ROOT / "rules" / "propagation.yaml")
    params = load_params(path)
    eligible = 0
    costs_ok = 0
    delays_ok = 0
    cost_mismatch: list[object] = []
    delay_mismatch: list[object] = []
    for e in dev:
        request = AnalysisRequest(change=e.change, as_of=as_of, confirm_on=as_of)
        try:
            result = Evaluator(index, request, book, params).evaluate(as_of, ())
        except RequestError:
            continue
        if result.unresolved or any(line.determinacy is not Determinacy.KNOWN for line in result.lines):
            continue
        eligible += 1
        hidden = oracle.outcome(e.change, as_of, as_of)
        engine_total = result.total.value
        if abs(hidden.total_krw - engine_total) <= max(1, abs(engine_total) * 0.01):
            costs_ok += 1
        else:
            cost_mismatch.append(
                (
                    e.change.ecn_id,
                    [(i.key, i.family, i.krw) for i in hidden.items],
                    hidden.total_krw,
                    [(line.line_id, line.amount.value) for line in result.lines],
                    engine_total,
                )
            )
        if hidden.max_exit_delay_days == result.schedule.max_exit_delay_days:
            delays_ok += 1
        else:
            delay_mismatch.append(
                (
                    e.change.ecn_id,
                    hidden.exit_delay_days,
                    hidden.max_exit_delay_days,
                    [(x.exit_activity_id, x.delay_days) for x in result.schedule.zone_exits],
                    result.schedule.max_exit_delay_days,
                )
            )
    c.check("차분 대상 사례가 한 건 이상이다", eligible > 0, eligible)
    cost_ratio = costs_ok / eligible if eligible else 0
    delay_ratio = delays_ok / eligible if eligible else 0
    c.check("확인 모드 총액 ±1% 일치 비율 90% 이상", cost_ratio >= 0.9, (cost_ratio, cost_mismatch))
    c.check("확인 모드 출구 최대 지연 일치 비율 90% 이상", delay_ratio >= 0.9, (delay_ratio, delay_mismatch))

    # 참값은 결정(확정일·보류)과 무관하다: 날짜와 상관없는 자재비 차이 항목과 미반영 비용 발생은
    # 확정일을 바꿔도 같다(E7 비교가 우연에 흔들리지 않게)
    same = 0
    for e in dev[:40]:
        now, later_day = (
            actual.outcome(e.change, as_of, as_of),
            actual.outcome(e.change, as_of, as_of + timedelta(days=20)),
        )
        materials = [{i.key: i.krw for i in x.items if i.family == "material_delta"} for x in (now, later_day)]
        same += materials[0] == materials[1] and (now.unmodeled_krw > 0) == (later_day.unmodeled_krw > 0)
    c.check("확정일을 바꿔도 자재비 차이 항목과 미반영 비용 발생이 같다(40건, 참값은 결정과 무관)", same == 40, same)

    monotone: list[bool] = []
    for e, earlier in zip(dev, actuals, strict=True):
        later = actual.outcome(e.change, as_of, as_of + timedelta(days=30))
        if any(i.family == "reallocation" for i in (*earlier.items, *later.items)):
            continue
        old = sum(i.krw for i in earlier.items if i.family in {"po_loss", "rework"})
        new = sum(i.krw for i in later.items if i.family in {"po_loss", "rework"})
        monotone.append(new >= old)
    c.check(
        "전용·보류가 없으면 30일 뒤 발주 손실과 재작업 합이 줄지 않는다",
        bool(monotone) and all(monotone),
        sum(monotone),
    )

    _schedule_checks(c, actual, generated, dev[0].change, as_of)
    _factor_checks(c, generated, actual, oracle, [e.change for e in dev], as_of)
    _combined(c, generated, actual, oracle, index, book, params, as_of)


def _factor_checks(
    c: Checker,
    generated: Generated,
    actual: HiddenModel,
    oracle: HiddenModel,
    changes: list[ChangeRequest],
    as_of: date,
) -> None:
    """요인별 고정(원인 분리 진단, scripts/eval_factors.py): 모두 고정 = 확인 모드, 요인마다 제 몫만 바꾼다."""
    path = PROJECT_ROOT / "params" / "cost_v1.yaml"
    later = as_of + timedelta(days=15)
    head = changes[:30]

    def same(a: HiddenModel, b: HiddenModel, cases: list[ChangeRequest]) -> bool:
        return all(a.outcome(x, as_of, day) == b.outcome(x, as_of, day) for x in cases for day in (as_of, later))

    c.check(
        "요인을 모두 고정하면 확인 모드와, 하나도 고정하지 않으면 평가 모드와 결과가 같다(30건 × 확정일 2개)",
        same(HiddenModel(generated, path, fixed=FACTORS), oracle, head)
        and same(HiddenModel(generated, path, fixed=()), actual, head),
    )
    c.check(
        "모르는 요인 이름은 거부한다",
        c.raises(lambda: HiddenModel(generated, path, fixed=("lead",))),  # type: ignore[arg-type]
    )
    c.check(
        "고정할 요인은 한 번만 읽히는 값으로 줘도 그대로 쓴다",
        HiddenModel(generated, path, fixed=(f for f in ("noise",))).fixed == frozenset({"noise"}),
    )

    base = {x.ecn_id: actual.outcome(x, as_of, as_of) for x in changes}

    def outcomes(fixed: Factor, cases: list[ChangeRequest]) -> list[tuple[ActualOutcome, ActualOutcome]]:
        model = HiddenModel(generated, path, fixed=(fixed,))
        return [(model.outcome(x, as_of, as_of), base[x.ecn_id]) for x in cases]

    noise = outcomes("noise", changes[:40])
    c.check(
        "항목 잡음만 고정하면 항목 금액만 바뀌고 출구 지연·미반영 비용 발생은 같다",
        any(a.items != b.items for a, b in noise)
        and all(
            a.exit_delay_days == b.exit_delay_days and (a.unmodeled_krw > 0) == (b.unmodeled_krw > 0) for a, b in noise
        ),
    )
    unmodeled = outcomes("unmodeled", changes[:40])
    c.check(
        "미반영 비용만 고정하면 미반영 비용이 0이 되고 항목·출구 지연은 같다",
        any(b.unmodeled_krw > 0 for _, b in unmodeled)
        and all(
            a.unmodeled_krw == 0 and a.items == b.items and a.exit_delay_days == b.exit_delay_days for a, b in unmodeled
        ),
    )
    params_fixed = HiddenModel(generated, path, fixed=("params",))
    c.check(
        "참 파라미터만 고정하면 대표값을 쓴다(평가 모드와는 다르다)",
        all(params_fixed.param(k) == p.value for k, p in params_fixed.params.params.items())
        and any(actual.param(k) != p.value for k, p in actual.params.params.items()),
    )
    floors = outcomes("start_floor", changes[:40])
    c.check(
        "착수 하한만 고정하면 공정 착수일이 바뀌고 미반영 비용 발생은 같다",
        any(a.activity_start_dates != b.activity_start_dates for a, b in floors)
        and all((a.unmodeled_krw > 0) == (b.unmodeled_krw > 0) for a, b in floors),
    )
    lead = outcomes("lead_time", changes)
    c.check(
        "리드타임 변동만 고정하면 출구 지연이 바뀌는 사례가 있고 미반영 비용 발생은 같다(개발 200건)",
        any(a.exit_delay_days != b.exit_delay_days for a, b in lead)
        and all((a.unmodeled_krw > 0) == (b.unmodeled_krw > 0) for a, b in lead),
        sum(a.exit_delay_days != b.exit_delay_days for a, b in lead),
    )
    _plate_delay(c, generated, path, changes[0])


def _plate_delay(c: Checker, generated: Generated, path: Path, change: ChangeRequest) -> None:
    """actuals-v2: 판 새 규격 입고 지연 분위수 표와 뽑기."""
    table = PLATE_DELAY_DAYS
    c.check(
        "판 입고 지연 분위수 표: 누적 확률 0 → 1 오름차순·일수 내림 없음, 끝값 −45·+22일, 중앙 +2·90백분위 +14일",
        table[0][0] == 0.0
        and table[-1][0] == 1.0
        and all(q0 < q1 and d0 <= d1 for (q0, d0), (q1, d1) in pairwise(table))
        and [quantile_days(table, u) for u in (0.0, 0.5, 0.9, 1.0)] == [-45, 2, 14, 22],
    )
    rng = random.Random(20261024)
    drawn = [quantile_days(table, rng.random()) for _ in range(20000)]
    late, over = sum(d > 0 for d in drawn) / len(drawn), sum(d > 14 for d in drawn) / len(drawn)
    c.check(
        "표에서 뽑은 지연이 집계와 같은 모양: 늦음 56%·14일 초과 9% 근처(±3%p)",
        abs(late - 0.564) <= 0.03 and abs(over - 0.086) <= 0.03,
        (round(late, 3), round(over, 3)),
    )
    model = HiddenModel(generated, path)
    fixed = HiddenModel(generated, path, fixed=("lead_time",))
    plates = [model._lead_days(change, f"SPEC-{i}", "plate", 70) - 70 for i in range(400)]
    others = [model._lead_days(change, f"SPEC-{i}", "valve", 90) for i in range(400)]
    c.check(
        "판은 리드타임 + 표의 지연(−45~+22일), 그 밖은 리드타임 × 0.9~1.2, 고정하면 리드타임 그대로"
        "(사례·규격마다 같은 값)",
        all(-45 <= d <= 22 for d in plates)
        and len(set(plates)) > 10
        and all(81 <= d <= 108 for d in others)
        and fixed._lead_days(change, "SPEC-1", "plate", 70) == 70
        and model._lead_days(change, "SPEC-1", "plate", 70) == model._lead_days(change, "SPEC-1", "plate", 70),
    )


def _schedule_checks(c: Checker, actual: HiddenModel, generated: Generated, change: ChangeRequest, as_of: date) -> None:
    order, nodes = actual._network(as_of, actual.generated.actual_activity_start_floor)
    _, base_ef = actual._forward(order, nodes, as_of, actual.generated.actual_activity_start_floor)
    exits = [a_id for a_id in order if nodes[a_id].kind is ActivityKind.MILESTONE]
    noncritical = False
    for a_id in order:
        a = nodes[a_id]
        if a.block_id is None or base_ef[a_id] <= as_of:
            continue
        _, changed_ef = actual._forward(order, nodes, as_of, actual.generated.actual_activity_start_floor, {a_id: 1})
        if changed_ef[a_id] > base_ef[a_id] and all(changed_ef[x] == base_ef[x] for x in exits):
            noncritical = True
            break
    c.check("비주경로 블록의 1일 지연은 구역 출구를 늦추지 않는다", noncritical)

    plan = date(2026, 1, 1)
    boundary = ZoneBoundary(zone_id="Z", exit_activity_id="exit", float_to_delivery_days=27)
    bounds = {"exit": boundary}
    planned = {"exit": plan}
    cases = (
        ({"exit": plan}, {"exit": plan + timedelta(days=28)}, 1),
        ({"exit": plan + timedelta(days=1)}, {"exit": plan + timedelta(days=29)}, 2),
        ({"exit": plan}, {"exit": plan + timedelta(days=20)}, 0),
    )
    c.check(
        "인도 지연은 여유 27일에서 28일·기존 1일 지연 뒤 28일 추가·20일을 각각 1·2·0일로 센다",
        all(delivery_added(before, after, planned, bounds) == expected for before, after, expected in cases),
    )
    c.check(
        "경계 없는 출구가 늦으면 인도 지연은 계산하지 않는다",
        delivery_added({"exit": plan}, {"exit": plan + timedelta(days=1)}, planned, {}) is None,
    )
    possible = [
        line
        for line in generated.snapshot.po_lines
        if line.consumed_by_activity_id is not None
        and line.consumed_by_activity_id in nodes
        and nodes[line.consumed_by_activity_id].actual_start is None
        and generated.actual_po_stages[line.po_id][POStatus.RECEIVED] > as_of
    ]
    if possible:
        line = possible[0]
        result = actual.outcome(change, as_of, as_of, {line.po_id: 20})
        arrival = generated.actual_po_stages[line.po_id][POStatus.RECEIVED] + timedelta(days=20)
        consumers: set[str] = set()
        for item in generated.snapshot.po_lines:
            consumer = item.consumed_by_activity_id
            if (
                item.po_id == line.po_id
                and consumer is not None
                and consumer in nodes
                and nodes[consumer].actual_start is None
            ):
                consumers.add(consumer)
        held_after_arrival = bool(consumers) and all(
            result.activity_start_dates[consumer] >= arrival for consumer in consumers
        )
    else:
        held_after_arrival = False
    c.check("보류 발주 품목의 미착수 소비 공정은 미뤄진 참 입고일 뒤에 시작한다", held_after_arrival)


def _combined(
    c: Checker,
    generated: Generated,
    actual: HiddenModel,
    oracle: HiddenModel,
    index: GraphIndex,
    book: RuleBook,
    params: ParamSet,
    as_of: date,
) -> None:
    """복합 요청: 변경 후 이웃(빼는 부재 제외·새 연결 포함)과 연산 순서 불변(docs/engine.md(전파) 2·3절)."""
    parts = {p.part_id: p for p in generated.snapshot.parts}
    pairs = []
    for edge in generated.snapshot.connections:
        if edge.kind is not ConnectionKind.FILLET_WELD:
            continue
        a, b = parts[edge.a], parts[edge.b]
        if a.kind is PartKind.PLATE and b.kind is PartKind.STIFFENER:
            pairs.append((a, b))
        elif b.kind is PartKind.PLATE and a.kind is PartKind.STIFFENER:
            pairs.append((b, a))
    plate, stiffener = sorted(pairs, key=lambda pair: (pair[0].part_id, pair[1].part_id))[0]

    def change(*ops: ThicknessChange | RemovePart | AddPart) -> ChangeRequest:
        return ChangeRequest(ecn_id="T-COMBINED", title="검사", ship_ids=("S-001",), ops=ops)

    before = plate.thickness_mm or 10
    thick = ThicknessChange(part_ids=(plate.part_id,), from_mm=before, to_mm=before + 2)
    remove = RemovePart(part_ids=(stiffener.part_id,))
    add = AddPart(
        block_id=plate.block_id,
        kind=PartKind.STIFFENER,
        spec_id=stiffener.spec_id,
        qty=0.2,
        attach_to_part_id=plate.part_id,
    )

    def engine_total(request_change: ChangeRequest) -> int:
        request = AnalysisRequest(change=request_change, as_of=as_of, confirm_on=as_of)
        return Evaluator(index, request, book, params).evaluate(as_of, ()).total.value

    removed_case = change(thick, remove)
    hidden = oracle.outcome(removed_case, as_of, as_of)
    c.check(
        "같은 요청에서 빼는 이웃 부재에는 용접 재검토 등 작업 비용을 매기지 않는다",
        not any(stiffener.part_id in item.key and item.family == "minor_work" for item in hidden.items),
        [item.key for item in hidden.items if stiffener.part_id in item.key],
    )
    added_case = change(thick, add)
    totals = {
        "빼는 이웃": (oracle.outcome(removed_case, as_of, as_of).total_krw, engine_total(removed_case)),
        "새로 붙인 보강재": (oracle.outcome(added_case, as_of, as_of).total_krw, engine_total(added_case)),
    }
    c.check(
        "복합 요청(두께 + 이웃 삭제, 두께 + 같은 판에 보강재 추가)도 확인 모드 총액 = 엔진 총액(±1%)",
        all(abs(h - e) <= max(1, abs(e) * 0.01) for h, e in totals.values()),
        totals,
    )
    forward = actual.outcome(change(add, thick), as_of, as_of)
    backward = actual.outcome(change(thick, add), as_of, as_of)
    c.check(
        "연산 순서만 바꾸면 잡음 모드 정답(항목·총액)이 같다(새 부재 ID = 연산 정규형 해시)",
        forward.items == backward.items and forward.total_krw == backward.total_krw,
        (forward.total_krw, backward.total_krw),
    )
