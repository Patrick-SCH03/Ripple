"""변경 원인 허용 지연(docs/engine.md(비용·일정) 4-6)과 의장품 선상 설치(6-3·4-1-3·6-8).

허용 지연: 지체상금이 있는 요청(2단계 관문 2번과 같은 변경)을 원인별로 분석해 선주 요청만 지체상금 줄이 빠지고
노출 금액 = 원인 미입력의 지체상금. 선상 설치: 개발 설계변경에서 확정일에 선상 설치 수요가 있는 것 전부와 없는 것
일부를 두 방식으로 분석해 명세 10절 성질을 본다. 계약 검증 반례도 거부되는지 본다.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import timedelta

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.analysis import AnalysisRequest, Versions
from ripple.contracts.change import ChangeCause
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.identity import analysis_id, normalized_request
from ripple.contracts.params import ParamSet
from ripple.contracts.result import (
    Amount,
    AnalysisResult,
    CostLine,
    DeliveryImpact,
    OnboardDirection,
    OnboardOption,
    additional_loss_of,
)
from ripple.contracts.rulebook import RuleBook
from ripple.engine.analyze import analyze
from ripple.engine.cost.amounts import Params, Scenario
from ripple.engine.cost.onboard import RATIO, WORK
from ripple.engine.cost.rework import CREW
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.engine.timing import Evaluator
from ripple.engine.verdict import ON_BOARD, PERMISSIBLE
from ripple.eval.cost_gate_inputs import cost_gate_inputs
from ripple.generator.build import generate
from ripple.generator.io import load_config

PLAIN_SAMPLE = 20  # 선상 설치 수요가 없는 설계변경 중 두 방식을 비교할 수
LD_CASE = "G2-002"  # 탑재 뒤 확정·인도 지연·지체상금이 있는 2단계 관문 사례
SCENARIOS = (Scenario.LOW, Scenario.VALUE, Scenario.HIGH)


def run(c: Checker) -> None:
    config = load_config()
    generated = generate(config)
    index = GraphIndex(generated.snapshot)
    book = load_rulebook(PROJECT_ROOT / "rules" / "propagation.yaml")
    params = load_params(PROJECT_ROOT / "params" / "cost_v1.yaml")
    cases = {case.case_id: case for case in cost_gate_inputs(generated.snapshot, generated.seed, config.scenario_date)}
    ld_request = cases[LD_CASE].request
    _permissible(c, index, book, params, ld_request)
    dev = [AnalysisRequest(change=e.change, as_of=e.as_of) for e in generated.ecns if e.split is EcnSplit.DEV]
    _onboard(c, index, book, params, dev)
    _identity(c, ld_request)
    _contracts(c)


def _with_cause(request: AnalysisRequest, cause: ChangeCause | None) -> AnalysisRequest:
    return request.model_copy(update={"change": request.change.model_copy(update={"cause": cause})})


def _permissible(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, request: AnalysisRequest) -> None:
    c.section("허용 지연: 선주 요청은 지체상금 대신 인도일 조정·노출 금액(4-6)")
    bare, owner_request = _with_cause(request, None), _with_cause(request, ChangeCause.OWNER_REQUEST)
    plain, owner = analyze(index, bare, book, params), analyze(index, owner_request, book, params)
    ld = [line for line in plain.cost_lines if line.rule_id == "R-L01"]
    c.check("기준 사례에 지체상금 줄이 하나 있음(전제)", len(ld) == 1 and plain.schedule.delivery is not None)
    ev_plain, ev_owner = Evaluator(index, bare, book, params), Evaluator(index, owner_request, book, params)
    differs = []
    for point in plain.timing.curve:
        a, b = ev_plain.evaluate(point.confirm_on, ()), ev_owner.evaluate(point.confirm_on, ())
        rest = [(line.line_id, line.amount) for line in a.lines if line.rule_id != "R-L01"]
        if rest != [(line.line_id, line.amount) for line in b.lines]:
            differs.append(point.confirm_on.isoformat())
    c.check("곡선의 모든 날: 선주 요청이면 지체상금 줄만 빠지고 나머지 줄은 같음", not differs, differs[:3])
    delivery, before = owner.schedule.delivery, plain.schedule.delivery
    c.check(
        "선주 요청: 인도 지연·출구는 그대로, 허용 지연 표시와 노출 금액 = 원인 미입력의 지체상금",
        delivery is not None
        and before is not None
        and delivery.added_delay_days == before.added_delay_days
        and delivery.permissible
        and delivery.exposure == ld[0].amount
        and owner.schedule.zone_exits == plain.schedule.zone_exits,
        delivery,
    )
    c.check(
        "선주 요청 판정: '지체상금' 대신 '인도일 조정' 이유, 같은 수준",
        PERMISSIBLE in owner.verdict.reasons
        and not any("지체상금" in reason for reason in owner.verdict.reasons)
        and owner.verdict.level is plain.verdict.level,
        owner.verdict.reasons,
    )
    others = {cause: analyze(index, _with_cause(request, cause), book, params) for cause in ChangeCause}
    c.check(
        "선주 요청이 아닌 원인(선급·규정 포함)은 분석 ID·금액·판정이 원인 미입력과 같음",
        all(
            r.analysis_id == plain.analysis_id and r.total == plain.total and r.verdict == plain.verdict
            for cause, r in others.items()
            if cause is not ChangeCause.OWNER_REQUEST
        ),
    )
    risk = owner.schedule.risk
    c.check(
        "일정 위험의 인도 영향도 허용 지연 표시(대표와 같은 원인), 노출 금액은 싣지 않음(위험 평가의 비용은 버림, 6-6)",
        risk is not None and (risk.delivery is None or (risk.delivery.permissible and risk.delivery.exposure is None)),
    )
    body = owner.model_dump(mode="json")
    body["cost_lines"] = sorted([*body["cost_lines"], ld[0].model_dump(mode="json")], key=lambda x: x["line_id"])
    body["total"] = plain.total.model_dump()
    forged = plain.model_dump(mode="json")
    forged["schedule"]["delivery"] = (
        owner.schedule.delivery.model_dump(mode="json") if owner.schedule.delivery else None
    )
    c.check(
        "계약: 허용 지연 표시가 있는데 지체상금 줄이 있거나, 선주 요청이 아닌데 허용 지연 표시가 있으면 거부",
        _rejects(lambda: AnalysisResult.model_validate(body))
        and _rejects(lambda: AnalysisResult.model_validate(forged)),
    )


def _onboard(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, dev: list[AnalysisRequest]) -> None:
    c.section("의장품 선상 설치: 개발 설계변경(6-3·4-1-3·6-8)")
    selected: list[AnalysisRequest] = []
    plain: list[AnalysisRequest] = []
    for request in dev:
        try:
            ev = Evaluator(index, request, book, params)
        except RequestError:
            continue
        (selected if ev.evaluate(request.as_of, ()).onboard else plain).append(request)
    c.check("확정일에 선상 설치 수요가 있는 설계변경이 있음(전제)", len(selected) > 0, len(selected))
    changed: list[str] = []
    for request in plain[:PLAIN_SAMPLE]:
        # 곡선의 날마다 6-3을 다시 정하므로(4-1-3) 확정일에 없어도 다른 날에는 선상 설치 수요가 있을 수 있다
        ev = Evaluator(index, request, book, params)
        days = [request.as_of + timedelta(days=i) for i in range(request.horizon_days + 1)]
        selecting = {day for day in days if ev.evaluate(day, ()).onboard}
        wait = analyze(index, request, book, params)
        board = analyze(index, request.model_copy(update={"outfit_on_board": True}), book, params)
        body = (wait.cost_lines, wait.total, wait.schedule, wait.verdict, wait.onboard)
        same_day = body == (board.cost_lines, board.total, board.schedule, board.verdict, board.onboard)
        # 사건(8-1)은 전날과 비교하므로 전날에 수요가 있던 날도 뺀다
        quiet = {day for day in days if day not in selecting and day - timedelta(days=1) not in selecting}
        pairs = zip(wait.timing.curve, board.timing.curve, strict=True)
        same_curve = all(a == b for a, b in pairs if a.confirm_on in quiet)
        if not same_day or not same_curve or (not selecting and wait.timing != board.timing):
            changed.append(request.change.ecn_id)
    c.check(
        "선상 설치 수요가 없으면 두 방식의 결과가 같음(분석 ID만 다름 — 확정일 결과, 수요가 없는 날의 곡선 점, "
        f"어느 날도 없으면 확정 시점 전체) — {min(len(plain), PLAIN_SAMPLE)}건",
        not changed,
        changed[:3],
    )
    problems = [problem for request in selected for problem in _compare(index, book, params, request)]
    c.check(f"선상 설치 성질(탑재·출구 제약·할증 산식·선택지·판정) — {len(selected)}건", not problems, problems[:5])


def _compare(index: GraphIndex, book: RuleBook, params: ParamSet, request: AnalysisRequest) -> list[str]:
    """기다림·선상 설치 두 분석과 확정일 평가로 명세 10절 성질을 본다. 어긋난 것을 문장으로 돌려준다."""
    ecn = request.change.ecn_id
    on = request.model_copy(update={"outfit_on_board": True})
    wait, board = analyze(index, request, book, params), analyze(index, on, book, params)
    ev = Evaluator(index, on, book, params)
    final = ev.evaluate(on.effective_confirm_on, ())
    p = Params(params)
    added = board.schedule.added_days_by_activity
    out: list[str] = []
    for block_id, block in final.onboard.items():
        erection = block.erection
        if added.get(erection, 0) > wait.schedule.added_days_by_activity.get(erection, 0):
            out.append(f"{ecn} {block_id}: 선상 설치인데 탑재가 기다릴 때보다 늦음")
        schedule = ev.baseline.ships[index.blocks[block_id].ship_id]
        net, base = schedule.network, schedule.base
        finished = base.ef[erection] + timedelta(days=added.get(erection, 0))
        ready = max(d.arrival for d in block.demands if d.arrival is not None) + timedelta(days=1)
        delayed = {z.exit_activity_id: z.delay_days for z in board.schedule.zone_exits}
        margins = {m.exit_activity_id: m.margin_days for m in board.schedule.exit_margins}
        for exit_id, lag in net.succs.get(erection, ()):
            start = base.es[exit_id] + timedelta(days=delayed.get(exit_id, 0))  # 출구 이정표는 기간 0
            bound = max(ready, finished + timedelta(days=lag)) + timedelta(days=block.days)
            if start < bound:
                out.append(f"{ecn} {exit_id}: 출구가 탑재 완료·자재 도착 + 선상 설치일보다 이름")
            # 늦어지지 않은 출구의 여유(6-7)는 탑재 완료 + 선상 설치 하한까지 본 값이어야 한다
            if exit_id in margins and start - timedelta(days=margins[exit_id]) < bound:
                out.append(f"{ecn} {exit_id}: 출구 여유가 선상 설치 하한을 빼먹어 큼")
        out += _premium(ecn, block_id, block.days, board.cost_lines, p)
    if board.verdict.level.value == "review" and ON_BOARD not in board.verdict.reasons:
        out.append(f"{ecn}: 검토 필요인데 선상 설치 이유 없음")
    back, forward = board.onboard, wait.onboard
    if back is not None:
        flipped = board.model_dump(mode="json")
        flipped["onboard"]["direction"] = OnboardDirection.TO_ON_BOARD.value
        if not _rejects(lambda: AnalysisResult.model_validate(flipped)):
            out.append(f"{ecn}: 요청 방식과 같은 방향의 선택지를 계약이 받음")
    if back is None or back.direction is not OnboardDirection.TO_WAIT:
        out.append(f"{ecn}: 선상 설치 요청에 되돌리기 선택지 없음")
    elif back.total_change != additional_loss_of(wait.total, board.total):
        out.append(f"{ecn}: 되돌리기 총액 차이가 두 분석의 차이와 다름")
    if forward is not None and (
        forward.total_change != additional_loss_of(board.total, wait.total)
        or forward.exit_delay_then_days != board.schedule.max_exit_delay_days
    ):
        out.append(f"{ecn}: 선상 설치 선택지의 '바꾸면' 값이 선상 설치 분석과 다름")
    return out


def _premium(ecn: str, block_id: str, days: int, lines: tuple[CostLine, ...], p: Params) -> list[str]:
    """C-03 금액 = 중량 × 톤당 공수(선행의장) × (배수 − 1) × 단가(시나리오끼리), 설치 일수 = ⌈전체 공수 / 하루 공수⌉."""
    line = next((x for x in lines if x.line_id == f"C-03:onboard:{block_id}"), None)
    if line is None:
        return [f"{ecn} {block_id}: C-03 줄 없음"]
    tons = float(line.inputs["weight_t"])
    rate = next(k for k in line.param_keys if k.startswith("labor_rate_per_hour."))
    expected = tuple(round(tons * p.get(WORK, sc) * (p.get(RATIO, sc) - 1) * p.get(rate, sc)) for sc in SCENARIOS)
    out = []
    if (line.amount.low, line.amount.value, line.amount.high) != expected:
        out.append(f"{ecn} {block_id}: C-03 금액 {line.amount} ≠ 산식 {expected}")
    want = max(1, math.ceil(tons * p.value(WORK) * p.value(RATIO) / p.value(CREW)))
    if line.inputs["days"] != want or days != want:
        out.append(f"{ecn} {block_id}: 선상 설치 일수 {line.inputs['days']} ≠ {want}")
    return out


def _identity(c: Checker, request: AnalysisRequest) -> None:
    c.section("분석 ID: 선주 요청·선상 설치는 결과가 달라질 때만(1.29.0), 옛 판 기록은 그대로")
    owner = _with_cause(request, ChangeCause.OWNER_REQUEST)
    rule = _with_cause(request, ChangeCause.CLASS_RULE)
    board = request.model_copy(update={"outfit_on_board": True})
    c.check(
        "정규형에 허용 지연 표시는 선주 요청에만, 선상 설치는 켰을 때만(끈 요청은 필드 없던 정규형 그대로)",
        normalized_request(owner).get("permissible_delay") is True
        and "permissible_delay" not in normalized_request(rule)
        and normalized_request(board).get("outfit_on_board") is True
        and "outfit_on_board" not in normalized_request(request),
    )
    old = Versions(contract="1.28.0", snapshot_id="G-0", rules="rules-v3", params="cost-v4", engine="0.8.0")
    now = old.model_copy(update={"contract": "1.29.0"})
    c.check(
        "1.28.0 판의 분석 ID는 원인과 상관없이 같고(옛 기록이 읽힘), 1.29.0부터 선주 요청만 다름",
        analysis_id(old, owner) == analysis_id(old, request) and analysis_id(now, owner) != analysis_id(now, request),
    )


def _rejects(build: Callable[[], object]) -> bool:
    try:
        build()
    except ValueError:
        return True
    return False


def _contracts(c: Checker) -> None:
    c.section("계약: 허용 지연·선상 설치 선택지 반례 거부(1.29.0)")
    amount = Amount(value=100, low=50, high=150)
    c.check(
        "노출 금액은 허용 지연에만, 인도 지연이 늘었을 때만",
        _rejects(lambda: DeliveryImpact.of(0, 5, permissible=False, exposure=amount))
        and _rejects(lambda: DeliveryImpact.of(3, 3, permissible=True, exposure=amount))
        and DeliveryImpact.of(0, 5, permissible=True, exposure=amount).exposure == amount,
    )
    option = {
        "direction": "to_on_board",
        "block_ids": ["S-001:B"],
        "part_ids": ["P-1", "P-2"],
        "on_board_days": 1,
        "total_change": amount.model_dump(),
        "erection_delay_now_days": 3,
        "erection_delay_then_days": 0,
        "exit_delay_now_days": 0,
        "exit_delay_then_days": 0,
    }
    c.check(
        "선택지의 블록·부재는 ID 순으로 겹치지 않고, 선상 설치는 하루 이상",
        _rejects(lambda: OnboardOption.model_validate({**option, "part_ids": ["P-2", "P-1"]}))
        and _rejects(lambda: OnboardOption.model_validate({**option, "on_board_days": 0}))
        and OnboardOption.model_validate(option).block_ids == ("S-001:B",),
    )
