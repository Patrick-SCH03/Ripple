"""단계 추정의 성질(docs/domain.md 3·4절).

무작위 발주는 '실제 진입일'을 먼저 정하고 거기서 확인된 진입일·관측·계획을 뽑아 만든다. 그래서
"실제 진입일은 늘 추정 범위 안"처럼 근거와 모순되지 않는지를 직접 검사할 수 있다.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from itertools import pairwise

from harness import Checker

from ripple.contracts.analysis import HoldAction
from ripple.contracts.domain import ActivityKind, BlockStage, POStatus, PurchaseOrder, StatusObservation
from ripple.engine.index import GraphIndex
from ripple.engine.state import (
    ENTRY_STAGES,
    ActivityStart,
    Basis,
    PlanClock,
    StageOn,
    StageWindow,
    StateModel,
    block_stage_on,
    hold_windows,
    line_stage_on,
    po_stage_on,
    rank,
    stage_windows,
)
from ripple.generator import ids
from ripple.generator.build import generate
from ripple.generator.io import load_config

AS_OF = date(2026, 10, 20)
DAYS = tuple(AS_OF + timedelta(days=offset) for offset in range(-150, 181, 5))
CASES = 400


@dataclass(frozen=True)
class Case:
    po: PurchaseOrder
    truth: dict[POStatus, date]  # 근거를 뽑아낸 실제 진입일


def run(c: Checker) -> None:
    rng = random.Random(20261020)
    cases = [_random_case(rng, n) for n in range(CASES)]
    _windows(c, cases)
    _days(c, cases)
    _holds(c, cases, rng)
    _reobservation(c, cases, rng)
    _rules(c)
    _lines_and_blocks(c)
    _generated(c)


# ---------- 무작위 발주 ----------


def _random_case(rng: random.Random, number: int) -> Case:
    lead = rng.randint(5, 150)
    secured = rng.randint(0, lead)
    fabrication = rng.randint(secured, lead)
    ordered = AS_OF + timedelta(days=rng.randint(-200, 40))
    material = ordered + timedelta(days=secured + rng.randint(0, 6))
    making = max(material, ordered + timedelta(days=fabrication + rng.randint(0, 6)))
    received = max(making, ordered + timedelta(days=lead + rng.randint(-3, 12)))
    truth = {
        POStatus.ORDERED: ordered,
        POStatus.MATERIAL_SECURED: material,
        POStatus.IN_FABRICATION: making,
        POStatus.RECEIVED: received,
    }
    entered = {stage: day for stage, day in truth.items() if rng.random() < 0.35}
    seen = sorted({AS_OF + timedelta(days=rng.randint(-150, 40)) for _ in range(rng.randint(0, 4))})
    observations = tuple(StatusObservation(status=_true_status(truth, day), observed_on=day) for day in seen)
    planned = None if rng.random() < 0.2 else ordered + timedelta(days=rng.randint(-10, 10))
    po = PurchaseOrder(
        po_id=f"PO-T{number:04d}",
        ship_id="S-001",
        supplier_id="SUP-ST1",
        planned_order_date=planned,
        material_secured_days=secured,
        fabrication_start_days=fabrication,
        lead_time_days=lead,
        entered_on=entered,
        observations=observations,
    )
    return Case(po=po, truth=truth)


def _true_status(truth: dict[POStatus, date], day: date) -> POStatus:
    status = POStatus.NOT_ORDERED
    for stage in ENTRY_STAGES:
        if truth[stage] <= day:
            status = stage
    return status


def _inside(day: date, lo: date | None, hi: date | None) -> bool:
    return (lo is None or lo <= day) and (hi is None or day <= hi)


def _not_before(a: date | None, b: date | None, none_is: str) -> bool:
    """a ≥ b. None은 하한이면 −∞, 상한이면 +∞로 본다."""
    if a is None or b is None:
        return (a is None and none_is == "high") or (b is None and none_is == "low") or a is b
    return a >= b


def _ranks(state: StageOn[POStatus]) -> tuple[int, int, int | None]:
    return rank(state.earliest), rank(state.latest), None if state.likely is None else rank(state.likely)


# ---------- 진입 범위 ----------


def _windows(c: Checker, cases: list[Case]) -> None:
    c.section("단계 추정: 진입 범위")
    all_windows = [(case, stage_windows(case.po, AS_OF)) for case in cases]
    c.check(
        "실제 진입일은 늘 추정 범위 안(근거와 모순 없음)",
        all(_inside(case.truth[w.stage], w.lo, w.hi) for case, windows in all_windows for w in windows),
    )
    c.check(
        "범위는 비지 않고 대표 진입일은 범위 안",
        all(
            (w.lo is None or w.hi is None or w.lo <= w.hi) and (w.estimate is None or _inside(w.estimate, w.lo, w.hi))
            for _, windows in all_windows
            for w in windows
        ),
    )
    c.check("범위와 대표 진입일은 단계 순서대로 늦어짐", all(_ordered(windows) for _, windows in all_windows))
    c.check(
        "대표 진입일이 없으면 '알 수 없음', 있으면 근거·계획·계획 이탈 중 하나",
        all((w.estimate is None) == (w.basis is Basis.UNKNOWN) for _, windows in all_windows for w in windows),
    )
    c.check(
        "확인된 진입일(기준일까지)은 그대로 나옴",
        all(
            (w.lo, w.hi, w.estimate, w.basis) == (case.po.entered_on[w.stage],) * 3 + (Basis.EVIDENCE,)
            for case, windows in all_windows
            for w in windows
            if case.po.entered_on.get(w.stage, AS_OF + timedelta(days=1)) <= AS_OF
        ),
    )
    c.check(
        "기준일 뒤 근거는 쓰지 않음(지워도 결과가 같음)",
        all(stage_windows(_trimmed(case.po), AS_OF) == windows for case, windows in all_windows),
    )

    blank = _po(planned=None)
    windows = stage_windows(blank, AS_OF)
    state = po_stage_on(windows, AS_OF)
    c.check(
        "근거도 계획도 없으면 알 수 없음",
        all(w == StageWindow(w.stage, None, None, None, Basis.UNKNOWN) for w in windows)
        and (state.earliest, state.latest, state.likely, state.basis)
        == (POStatus.NOT_ORDERED, POStatus.RECEIVED, None, Basis.UNKNOWN)
        and state.at_least(POStatus.ORDERED) is None,
    )

    planned = _po(planned=date(2026, 9, 1), entered_on={POStatus.ORDERED: date(2026, 9, 3)})
    by_stage = {w.stage: w for w in stage_windows(planned, AS_OF)}
    c.check(
        "앞 단계가 확인되면 대표 진입일 = 확인일 + 계획 간격 차이",
        by_stage[POStatus.MATERIAL_SECURED].estimate == date(2026, 9, 3) + timedelta(days=10)
        and by_stage[POStatus.RECEIVED].estimate == date(2026, 9, 3) + timedelta(days=60)
        and by_stage[POStatus.RECEIVED].basis is Basis.PLAN,
    )

    late = _po(planned=date(2026, 9, 1), observations=((POStatus.ORDERED, date(2026, 9, 20)),))
    by_stage = {w.stage: w for w in stage_windows(late, AS_OF)}
    secured = by_stage[POStatus.MATERIAL_SECURED]
    c.check(
        "계획이 관측 범위 밖이면 가까운 끝값을 쓰고 계획 이탈로 표시, 뒤 단계로 이어짐",
        secured.estimate == date(2026, 9, 21)
        and secured.basis is Basis.OFF_PLAN
        and by_stage[POStatus.IN_FABRICATION].estimate == date(2026, 9, 21) + timedelta(days=20)
        and by_stage[POStatus.IN_FABRICATION].basis is Basis.OFF_PLAN,
    )

    pinned = _po(
        planned=None,
        observations=((POStatus.ORDERED, date(2026, 9, 1)), (POStatus.MATERIAL_SECURED, date(2026, 9, 2))),
    )
    secured = {w.stage: w for w in stage_windows(pinned, AS_OF)}[POStatus.MATERIAL_SECURED]
    c.check(
        "이틀 연속 관측으로 진입일이 하루로 좁혀지면 근거로 정함",
        (secured.lo, secured.hi, secured.estimate, secured.basis)
        == (date(2026, 9, 2), date(2026, 9, 2), date(2026, 9, 2), Basis.EVIDENCE),
    )


def _ordered(windows: tuple[StageWindow, ...]) -> bool:
    for a, b in pairwise(windows):
        if not (_not_before(b.lo, a.lo, "low") and _not_before(b.hi, a.hi, "high")):
            return False
        if a.estimate is not None and b.estimate is not None and b.estimate < a.estimate:
            return False
    return True


def _trimmed(po: PurchaseOrder) -> PurchaseOrder:
    return po.model_copy(
        update={
            "entered_on": {stage: day for stage, day in po.entered_on.items() if day <= AS_OF},
            "observations": tuple(o for o in po.observations if o.observed_on <= AS_OF),
        }
    )


def _po(
    planned: date | None,
    entered_on: dict[POStatus, date] | None = None,
    observations: tuple[tuple[POStatus, date], ...] = (),
) -> PurchaseOrder:
    return PurchaseOrder(
        po_id="PO-HAND",
        ship_id="S-001",
        supplier_id="SUP-ST1",
        planned_order_date=planned,
        material_secured_days=10,
        fabrication_start_days=30,
        lead_time_days=60,
        entered_on=entered_on or {},
        observations=tuple(StatusObservation(status=s, observed_on=d) for s, d in observations),
    )


# ---------- 하루의 단계 ----------


def _days(c: Checker, cases: list[Case]) -> None:
    c.section("단계 추정: 날짜별 단계")
    states = [(case, [(day, po_stage_on(stage_windows(case.po, AS_OF), day)) for day in DAYS]) for case in cases]
    c.check(
        "실제 단계는 늘 [가장 이른 경우, 가장 늦은 경우] 안",
        all(
            rank(s.earliest) <= rank(_true_status(case.truth, day)) <= rank(s.latest)
            for case, series in states
            for day, s in series
        ),
    )
    c.check("날짜가 늦어지면 단계가 되돌아가지 않음", all(_monotone([s for _, s in series]) for _, series in states))
    c.check(
        "근거로 정해지면 대표 단계도 같고 '근거'로 표시",
        all(
            s.likely == s.earliest and s.basis is Basis.EVIDENCE
            for _, ss in states
            for _, s in ss
            if s.earliest == s.latest
        ),
    )
    c.check(
        "단계 범위가 어긋난 값은 만들 수 없음",
        Checker.raises(lambda: StageOn(POStatus.RECEIVED, POStatus.ORDERED, None, Basis.UNKNOWN))
        and Checker.raises(lambda: StageOn(POStatus.ORDERED, POStatus.RECEIVED, POStatus.PROCESSED, Basis.PLAN)),
    )


def _monotone[S: StrEnum](series: list[StageOn[S]]) -> bool:
    for a, b in pairwise(series):
        if rank(b.earliest) < rank(a.earliest) or rank(b.latest) < rank(a.latest):
            return False
        if a.likely is not None and b.likely is not None and rank(b.likely) < rank(a.likely):
            return False
    return True


# ---------- 보류 ----------


def _holds(c: Checker, cases: list[Case], rng: random.Random) -> None:
    c.section("단계 추정: 발주 보류")
    shifted_exactly = True
    never_ahead = True
    for case in cases:
        days = rng.randint(1, 90)
        base = stage_windows(case.po, AS_OF)
        held = hold_windows(base, AS_OF, days)
        for before, after in zip(base, held, strict=True):
            expected = before.estimate
            if expected is not None and expected > AS_OF:
                expected += timedelta(days=days)
            shifted_exactly &= after.estimate == expected
        for day in DAYS:
            a, b = _ranks(po_stage_on(base, day)), _ranks(po_stage_on(held, day))
            never_ahead &= b[0] <= a[0] and b[1] <= a[1] and (a[2] is None or b[2] is None or b[2] <= a[2])
    c.check("보류하면 기준일에 아직 안 들어간 단계만 보류 일수만큼 밀림", shifted_exactly)
    c.check("보류는 어느 날에도 단계를 앞당기지 않음", never_ahead)

    waiting = _po(planned=AS_OF - timedelta(days=20), observations=((POStatus.ORDERED, AS_OF),))
    held = hold_windows(stage_windows(waiting, AS_OF), AS_OF, 30)
    during = [po_stage_on(held, AS_OF + timedelta(days=d)) for d in range(31)]
    released = po_stage_on(held, AS_OF + timedelta(days=31))
    c.check(
        "보류 기간에는 기준일에 아직 안 들어간 단계로 넘어갈 수 없음",
        all(s.latest is POStatus.ORDERED for s in during) and released.possibly_at_least(POStatus.MATERIAL_SECURED),
    )


# ---------- 재관측 ----------


def _reobservation(c: Checker, cases: list[Case], rng: random.Random) -> None:
    c.section("단계 추정: 같은 상태 재관측")
    upper_kept = lower_raised = tried = 0
    for case in cases:
        earlier = [o for o in case.po.observations if o.observed_on < AS_OF]
        if not earlier:
            continue
        first = earlier[-1]
        again = first.observed_on + timedelta(days=rng.randint(1, 30))
        if again > AS_OF or _true_status(case.truth, again) is not first.status:
            continue
        if any(first.observed_on < o.observed_on <= again for o in case.po.observations):
            continue
        if any(first.observed_on < d <= again for d in case.po.entered_on.values()):
            continue
        observations = tuple(
            sorted(
                (*case.po.observations, StatusObservation(status=first.status, observed_on=again)),
                key=lambda o: o.observed_on,
            )
        )
        po = case.po.model_copy(update={"observations": observations})
        tried += 1
        before, after = stage_windows(case.po, AS_OF), stage_windows(po, AS_OF)
        reached = [(b, a) for b, a in zip(before, after, strict=True) if rank(b.stage) <= rank(first.status)]
        pending = [(b, a) for b, a in zip(before, after, strict=True) if rank(b.stage) > rank(first.status)]
        upper_kept += all(a.hi == b.hi for b, a in reached)
        lower_raised += all(_not_before(a.lo, b.lo, "low") and a.hi == b.hi for b, a in pending)
    c.check("재관측 사례가 충분함", tried >= 50, tried)
    c.check("같은 상태를 다시 관측해도 그 단계까지의 상한은 밀리지 않음", upper_kept == tried, (upper_kept, tried))
    c.check("다음 단계 이후는 하한만 오름", lower_raised == tried, (lower_raised, tried))


# ---------- 발주 품목·블록 ----------


def _rules(c: Checker) -> None:
    c.section("단계 추정: 문턱 질문")
    state = StageOn(POStatus.ORDERED, POStatus.RECEIVED, POStatus.IN_FABRICATION, Basis.PLAN)
    c.check(
        "확실하면 그대로, 범위 안이면 대표 단계로 답함",
        state.at_least(POStatus.ORDERED) is True
        and state.at_least(POStatus.MATERIAL_SECURED) is True
        and state.at_least(POStatus.RECEIVED) is False
        and state.at_least(POStatus.PROCESSED) is False,
    )
    unknown = StageOn(POStatus.ORDERED, POStatus.RECEIVED, None, Basis.UNKNOWN)
    c.check(
        "대표 단계가 없으면 범위 밖 질문만 답하고 나머지는 모름",
        unknown.at_least(POStatus.ORDERED) is True
        and unknown.at_least(POStatus.RECEIVED) is None
        and unknown.at_least(POStatus.PROCESSED) is False,
    )


def _lines_and_blocks(c: Checker) -> None:
    c.section("단계 추정: 발주 품목·블록")
    received = StageOn(POStatus.RECEIVED, POStatus.RECEIVED, POStatus.RECEIVED, Basis.EVIDENCE)
    making = StageOn(POStatus.IN_FABRICATION, POStatus.RECEIVED, POStatus.IN_FABRICATION, Basis.PLAN)
    started = ActivityStart(actual=AS_OF - timedelta(days=3), earliest=AS_OF - timedelta(days=3), expected=AS_OF)
    waiting = ActivityStart(actual=None, earliest=AS_OF + timedelta(days=5), expected=AS_OF + timedelta(days=5))
    c.check(
        "소비 공정이 착수했으면 가공(근거)",
        line_stage_on(making, None, started, AS_OF) == StageOn(*(POStatus.PROCESSED,) * 3, Basis.EVIDENCE),
    )
    c.check(
        "발주 근거가 가공이면 소비 공정을 몰라도 가공",
        line_stage_on(received, AS_OF - timedelta(days=1), None, AS_OF).earliest is POStatus.PROCESSED,
    )
    c.check(
        "소비 공정 착수 전이면 가공이 아님",
        line_stage_on(received, None, waiting, AS_OF).latest is POStatus.RECEIVED,
    )
    later = AS_OF + timedelta(days=5)
    c.check(
        "착수 예정일이 지나도 입고 전으로 보이면 가공으로 추정하지 않음",
        line_stage_on(received, None, waiting, later).likely is POStatus.PROCESSED
        and line_stage_on(making, None, waiting, later).likely is POStatus.IN_FABRICATION,
    )

    ordered = StageOn(POStatus.ORDERED, POStatus.ORDERED, POStatus.ORDERED, Basis.EVIDENCE)
    c.check(
        "강재 품목이 모두 입고돼야 '강재 입고'",
        block_stage_on([], [received, ordered], AS_OF).latest is BlockStage.NOT_STARTED
        and block_stage_on([], [received, received], AS_OF).earliest is BlockStage.STEEL_RECEIVED,
    )
    unknown_steel = block_stage_on([], [], AS_OF)
    c.check(
        "강재 품목이 없으면 미착수·강재 입고를 정하지 않지만 소조립 전인 것은 앎",
        unknown_steel.likely is None and unknown_steel.at_least(BlockStage.SUB_ASSEMBLY) is False,
    )
    activities = [(ActivityKind.SUB_ASSEMBLY, started), (ActivityKind.PANEL, waiting)]
    c.check(
        "착수한 가장 뒤 공정이 블록 단계, 착수 예정 공정은 가능성으로만",
        block_stage_on(activities, [received], AS_OF) == StageOn(*(BlockStage.SUB_ASSEMBLY,) * 3, Basis.EVIDENCE)
        and block_stage_on(activities, [received], later).latest is BlockStage.PANEL,
    )


def _generated(c: Checker) -> None:
    c.section("단계 추정: 합성 지도")
    config = load_config()
    snapshot = generate(config).snapshot
    index = GraphIndex(snapshot)
    as_of = config.scenario_date
    ship = config.ship.ship_id
    model = StateModel(index, as_of)

    exported = [p for p in snapshot.purchase_orders if any(o.observed_on == as_of for o in p.observations)]
    c.check(
        "발주대장 내보내기가 있는 발주는 기준일 단계가 근거로 정해짐",
        bool(exported) and all(_settled(model.po_stage_on(p.po_id, as_of)) for p in exported),
        len(exported),
    )
    blank = [
        p for p in snapshot.purchase_orders if p.planned_order_date is None and not p.observations and not p.entered_on
    ]
    c.check(
        "정보가 없는 발주는 판단 불가",
        bool(blank) and all(model.po_stage_on(p.po_id, as_of).basis is Basis.UNKNOWN for p in blank),
    )

    assembly = ids.block_id(ship, config.demo.assembly_block)
    sub_assembly = ids.activity_id(ship, config.demo.assembly_block, ActivityKind.SUB_ASSEMBLY)
    plate_lines = [li.line_id for li in snapshot.po_lines if li.consumed_by_activity_id == sub_assembly]
    block = model.block_stage_on(assembly, as_of)
    c.check(
        f"{config.demo.assembly_block}는 기준일에 조립 단계(근거)",
        (block.earliest, block.latest, block.basis) == (BlockStage.ASSEMBLY, BlockStage.ASSEMBLY, Basis.EVIDENCE),
    )
    c.check(
        f"{config.demo.assembly_block} 판 품목은 기준일에 가공",
        bool(plate_lines) and all(model.line_stage_on(li, as_of).earliest is POStatus.PROCESSED for li in plate_lines),
    )

    waiting = ids.block_id(ship, config.demo.not_started_block)
    outfitting = ids.activity_id(ship, config.demo.not_started_block, ActivityKind.PRE_OUTFITTING)
    valve_specs = {s.spec_id for s in snapshot.specs if s.category == "valve"}
    valve_lines = [
        li.line_id for li in snapshot.po_lines if li.consumed_by_activity_id == outfitting and li.spec_id in valve_specs
    ]
    c.check(
        f"{config.demo.not_started_block}는 기준일에 소조립 전",
        model.block_stage_on(waiting, as_of).at_least(BlockStage.SUB_ASSEMBLY) is False,
    )
    c.check(
        f"{config.demo.not_started_block} 밸브 품목은 기준일에 미발주(근거)",
        bool(valve_lines)
        and all(
            (s.latest, s.basis) == (POStatus.NOT_ORDERED, Basis.EVIDENCE)
            for s in (model.line_stage_on(li, as_of) for li in valve_lines)
        ),
    )
    control = [b.block_id for b in snapshot.blocks if b.zone_id == ids.zone_id(ship, config.demo.control_zone)]
    c.check(
        f"대조 구역 {config.demo.control_zone}의 블록은 기준일에 모두 소조립 전",
        all(model.block_stage_on(b, as_of).at_least(BlockStage.SUB_ASSEMBLY) is False for b in control),
    )

    horizon = [as_of + timedelta(days=d) for d in range(0, 241, 4)]
    blocks = [b.block_id for b in snapshot.blocks]
    c.check(
        "블록 단계는 날짜가 늦어져도 되돌아가지 않음",
        all(_monotone([model.block_stage_on(b, day) for day in horizon]) for b in blocks),
    )
    lines = [li.line_id for li in snapshot.po_lines]
    c.check(
        "발주 품목 단계는 날짜가 늦어져도 되돌아가지 않음",
        all(_monotone([model.line_stage_on(li, day) for day in horizon]) for li in lines),
    )

    steel_orders = sorted({index.lines[li].po_id for b in blocks for li in model.steel_lines(b)})
    held = StateModel(index, as_of, holds=[HoldAction(po_id=po, hold_days=45) for po in steel_orders])
    c.check(
        "강재 발주를 보류해도 블록 단계가 앞당겨지지 않음",
        all(
            rank(held.block_stage_on(b, day).latest) <= rank(model.block_stage_on(b, day).latest)
            and rank(held.block_stage_on(b, day).earliest) <= rank(model.block_stage_on(b, day).earliest)
            for b in blocks
            for day in horizon[::5]
        ),
    )

    clock = PlanClock(index.activities, as_of)
    starts = {a.activity_id: clock.start(a.activity_id) for a in snapshot.activities}
    c.check(
        "공정 시계: 착수 안 한 공정은 계획 착수일·기준일 다음 날보다 이르지 않음",
        all(
            s.actual is None and s.earliest >= max(a.planned_start, as_of + timedelta(days=1))
            if a.actual_start is None or a.actual_start > as_of
            else s.actual == s.earliest == s.expected == a.actual_start
            for a in snapshot.activities
            for s in (starts[a.activity_id],)
        ),
    )


def _settled(state: StageOn[POStatus]) -> bool:
    return state.earliest == state.latest and state.basis is Basis.EVIDENCE
