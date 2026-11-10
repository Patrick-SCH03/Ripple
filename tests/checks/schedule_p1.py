"""일정 보완(docs/engine.md(비용·일정) v1.14): 급발주 리드타임 배율(5절), 구역 출구 여유(6-7),
재작업 자재 대기 R-S01(7절 나)."""

from __future__ import annotations

from datetime import date

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.dataset import GeneratedEcn
from ripple.contracts.domain import POStatus
from ripple.contracts.params import ParamSet
from ripple.contracts.result import ExitMargin, ImpactType, ScheduleImpact, ZoneExitDelay
from ripple.contracts.rulebook import RuleBook
from ripple.engine.analyze import analyze
from ripple.engine.cost.demand import EXPEDITE
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.engine.timing import Evaluator
from ripple.generator.build import generate
from ripple.generator.io import load_config

SAMPLE = 60  # 급발주 배율 비교에 쓰는 설계변경 수(곡선까지 두 번 분석하므로 일부만)


def run(c: Checker) -> None:
    generated = generate(load_config())
    index = GraphIndex(generated.snapshot)
    book = load_rulebook(PROJECT_ROOT / "rules" / "propagation.yaml")
    params = load_params(PROJECT_ROOT / "params" / "cost_v1.yaml")
    requests = _requests(index, book, params, generated.ecns)
    _expedite(c, index, book, params, requests)
    _margins(c, index, book, params, requests)
    _rework_wait(c, index, book, params, generated.ecns)
    _margin_contract(c)


def _requests(
    index: GraphIndex, book: RuleBook, params: ParamSet, ecns: tuple[GeneratedEcn, ...]
) -> list[AnalysisRequest]:
    found = []
    for ecn in ecns:
        request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of)
        try:
            Evaluator(index, request, book, params)
        except RequestError:
            continue
        found.append(request)
    return found


def _with_ratio(params: ParamSet, ratio: float) -> ParamSet:
    current = params.params[EXPEDITE]
    changed = current.model_copy(update={"value": ratio, "low": ratio, "high": ratio})
    return params.model_copy(update={"params": {**params.params, EXPEDITE: changed}})


def _expedite(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, requests: list[AnalysisRequest]) -> None:
    c.section("일정 보완: 급발주 리드타임 배율(5절)")
    c.check("파라미터 cost-v3의 급발주 배율은 1.0(현업 확인 전, 결과 동일)", params.value(EXPEDITE) == 1.0)
    half = _with_ratio(params, 0.5)
    earlier = same_unknown = monotone = True
    pulled = 0
    for request in requests[:SAMPLE]:
        day = request.effective_confirm_on
        plain = Evaluator(index, request, book, params)
        fast = Evaluator(index, request, book, half)
        state = plain.state(())
        before = {d.part_id: d for d in plain.evaluate(day, ()).demands}
        after = fast.evaluate(day, ())
        for demand in after.demands:
            old = before.get(demand.part_id)
            if old is None or old.arrival is None or demand.arrival is None:
                continue
            certain = demand.line_id is not None and state.line_stage_on(demand.line_id, day).at_least(POStatus.ORDERED)
            if certain is True:
                earlier &= demand.arrival <= old.arrival
                pulled += demand.arrival < old.arrival
            else:
                same_unknown &= demand.arrival == old.arrival
        monotone &= after.max_exit_delay <= plain.evaluate(day, ()).max_exit_delay
    c.check(
        f"배율 0.5: 발주 이상으로 정해진 품목의 도착일만 당겨지고(당겨진 수요 {pulled}건),"
        " 판단 불가·미발주 품목은 그대로",
        earlier and same_unknown and pulled >= 1,
        pulled,
    )
    c.check("배율 0.5: 도착일이 당겨지기만 하므로 구역 출구 지연이 늘지 않음", monotone)


def _margins(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, requests: list[AnalysisRequest]) -> None:
    c.section("일정 보완: 구역 출구 여유(6-7)")
    with_margin = 0
    consistent = True
    for request in requests:
        result = analyze(index, request, book, params)
        schedule = result.schedule
        if not schedule.exit_margins:
            continue
        with_margin += 1
        delayed = {z.exit_activity_id for z in schedule.zone_exits}
        consistent &= all(
            m.margin_days >= 0
            and m.exit_activity_id not in delayed
            and index.activities[m.exit_activity_id].ship_id in request.change.ship_ids
            for m in schedule.exit_margins
        )
    c.check(
        f"여유가 줄어든 출구가 있는 설계변경 {with_margin}건: 여유 ≥ 0, 늦어진 출구와 겹치지 않음, 요청 호선의 출구",
        with_margin >= 1 and consistent,
        with_margin,
    )


def _rework_wait(
    c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, ecns: tuple[GeneratedEcn, ...]
) -> None:
    c.section("일정 보완: 재작업 자재 대기의 근거 경로(7절 나)")
    ecn = next(e for e in ecns if e.change.ecn_id == "ECN-D-0119")
    result = analyze(index, AnalysisRequest(change=ecn.change, as_of=ecn.as_of), book, params)
    waits = [
        i
        for i in result.impacts
        if i.rule_id == "R-S01" and i.impact_type is ImpactType.SCHEDULE_DELAY and i.note.startswith("재작업 자재")
    ]
    erection = "S-001:B31P:erection"
    c.check(
        "ECN-D-0119(소비 공정 착수 뒤 판 두께 변경): 탑재 지연에 R-S01 근거"
        " — 부재 →(공급) 품목 →(소비) 공정 →(선후행)… 탑재",
        any(
            i.entity_id == erection
            and [h.relation.value for h in i.path][:2] == ["supplied_by", "consumed_by"]
            and {h.relation.value for h in i.path[2:]} <= {"precedes"}
            and i.path[-1].dst == erection
            for i in waits
        )
        and result.schedule.added_days_by_activity.get(erection, 0) > 0,
        [(i.entity_id, i.note) for i in waits],
    )


def _margin_contract(c: Checker) -> None:
    c.section("일정 보완: 출구 여유 계약 검증(1.26.0)")
    exit_a, exit_b = "S-1:Z1:exit", "S-1:Z2:exit"
    delayed = ZoneExitDelay(
        zone_id="Z1",
        exit_activity_id=exit_a,
        base_date=date(2027, 1, 1),
        new_date=date(2027, 1, 3),
        delay_days=2,
    )

    def margin(exit_id: str, days: int = 3) -> ExitMargin:
        return ExitMargin(zone_id=exit_id.split(":")[1], exit_activity_id=exit_id, margin_days=days)

    c.check(
        "늦어진 출구와 같은 출구의 여유·출구 ID 역순·음수 여유를 거부",
        c.raises(lambda: ScheduleImpact(zone_exits=(delayed,), max_exit_delay_days=2, exit_margins=(margin(exit_a),)))
        and c.raises(lambda: ScheduleImpact(exit_margins=(margin(exit_b), margin(exit_a))))
        and c.raises(lambda: margin(exit_a, -1)),
    )
    c.check(
        "여유 목록이 비어 있어도(옛 결과) 그대로 읽힘",
        ScheduleImpact.model_validate({"zone_exits": [], "max_exit_delay_days": 0}).exit_margins == (),
    )
