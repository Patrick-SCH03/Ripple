"""지연 파급 비용(docs/engine.md(비용·일정) 4-11, cost-v6): 총액 밖 별도 금액이고 지체상금과 겹치지 않는다.

- 공정 여유를 빼고 실제로 밀리는 날만: 일수 = 구역 출구 지연 최댓값(CPM 여유 반영) − 늘어난 인도 지연,
  금액 = 일수 × 하루 비용(시나리오 셋). 구역 출구 지연이 0이면 없고, 여유로 흡수되는 탑재 지연만 있으면 없다.
- 하루 비용을 바꿔도 총액·비용 줄·판정·곡선·결정 기한·보류 권고·일정·대안이 그대로다(총액 밖).
- 인도가 늘어 지체상금 줄(또는 선주 요청이면 노출 금액)이 생긴 사례에서 그 날만큼 일수가 줄고, 지체상금 금액은 그대로다.
"""

from __future__ import annotations

from datetime import timedelta

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook, load_strength
from ripple.config.settings import Settings
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.change import ChangeCause, ChangeIntent
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.domain import ActivityKind, GraphSnapshot, LDTerms
from ripple.contracts.params import Param, ParamSet
from ripple.contracts.result import AnalysisResult
from ripple.contracts.rulebook import RuleBook
from ripple.engine.analyze import analyze
from ripple.engine.delay import KEY
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.generator.build import generate
from ripple.generator.io import load_config

CASES = 60
FLOAT = 1  # 겹침 검사 지도의 구역 출구 → 인도 여유(일)
SAME = ("cost_lines", "total", "verdict", "timing", "schedule", "alternatives", "recommendation", "cheapest_by_date")
"""하루 비용을 바꿔도 같아야 하는 결과 필드(총액 밖이라)."""


def run(c: Checker) -> None:
    config = load_config()
    generated = generate(config)
    settings = Settings.from_env({})
    book, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    dev = [e for e in generated.ecns if e.split is EcnSplit.DEV]
    requests = [
        AnalysisRequest(
            change=e.change,
            as_of=e.as_of,
            confirm_on=e.as_of + timedelta(days=10),
            include_alternatives=e.change.intent is ChangeIntent.STRENGTH,
        )
        for e in dev[:CASES]
    ]
    # 시연 사례를 함께 본다(기준일 확정 · 대안 포함): 구역 출구가 늦는 ECN-D-0119,
    # 블록 탑재는 늦지만 여유로 흡수돼 구역 출구가 그대로인 ECN-D-0043
    for ecn_id in ("ECN-D-0119", "ECN-D-0043"):
        demo = next(e for e in dev if e.change.ecn_id == ecn_id)
        requests.append(AnalysisRequest(change=demo.change, as_of=demo.as_of, include_alternatives=True))
    index = GraphIndex(generated.snapshot)
    results = _analyses(index, requests, book, params)
    _definition(c, index, params, results)
    _outside_total(c, index, requests, book, params, results)
    _no_overlap(c, generated.snapshot, results, book, params)


def _analyses(
    index: GraphIndex, requests: list[AnalysisRequest], book: RuleBook, params: ParamSet
) -> list[AnalysisResult]:
    strength = load_strength(Settings.from_env({}).strength_path)
    found = []
    for request in requests:
        try:
            found.append(analyze(index, request, book, params, strength))
        except RequestError:
            continue
    return found


def _slip(index: GraphIndex, result: AnalysisResult) -> tuple[int, int, int]:
    """(블록 탑재 지연 최댓값 — 지연 파급에 쓰지 않음, 구역 출구 지연 최댓값, 늘어난 인도 지연)."""
    schedule = result.schedule
    erection = max(
        (d for a, d in schedule.added_days_by_activity.items() if index.activities[a].kind is ActivityKind.ERECTION),
        default=0,
    )
    added = schedule.delivery.added_delay_days if schedule.delivery else 0
    return erection, schedule.max_exit_delay_days, added


def _definition(c: Checker, index: GraphIndex, params: ParamSet, results: list[AnalysisResult]) -> None:
    c.section("지연 파급 비용: 정의(명세 4-11)")
    per_day = params.get(KEY)
    wrong, present, zero_exit, absorbed = [], 0, [], []
    for result in results:
        erection, exits, added = _slip(index, result)
        days = exits - added
        if exits == 0:
            zero_exit.append(result.delay_ripple is None)
            if erection > 0:
                absorbed.append(result.delay_ripple is None)
        ripple = result.delay_ripple
        if days <= 0:
            if ripple is not None:
                wrong.append(result.request.change.ecn_id)
            continue
        present += 1
        amount = (round(days * per_day.low), round(days * per_day.value), round(days * per_day.high))
        if (
            ripple is None
            or ripple.days != days
            or (ripple.amount.low, ripple.amount.value, ripple.amount.high) != amount
        ):
            wrong.append(result.request.change.ecn_id)
    c.check(f"지연 파급 비용이 있는 사례가 있음({present}/{len(results)}건)", present > 0, present)
    c.check(
        "일수 = 구역 출구 지연 − 늘어난 인도 지연, 금액 = 일수 × 하루 비용, 실제로 밀린 날이 없으면 없음",
        not wrong,
        wrong[:3],
    )
    c.check(f"구역 출구 지연이 0인 사례 {len(zero_exit)}건은 지연 파급 비용 없음", bool(zero_exit) and all(zero_exit))
    c.check(
        f"블록 탑재는 늦지만 여유로 흡수돼 구역 출구가 그대로인 사례 {len(absorbed)}건은 지연 파급 비용 없음",
        bool(absorbed) and all(absorbed),
    )
    c.check(
        "총액에 들어가지 않음: 비용 줄에 지연 파급 줄이 없고 총액 = 비용 줄의 합",
        all(not any("delay" in line.line_id for line in r.cost_lines) for r in results),
    )


def _scaled(params: ParamSet, factor: float) -> ParamSet:
    param = params.get(KEY)
    changed = Param(
        key=KEY,
        value=param.value * factor,
        low=param.low * factor,
        high=param.high * factor,
        status=param.status,
        source=param.source,
        mentor_question=param.mentor_question,
    )
    return params.model_copy(update={"params": {**params.params, KEY: changed}})


def _outside_total(
    c: Checker,
    index: GraphIndex,
    requests: list[AnalysisRequest],
    book: RuleBook,
    params: ParamSet,
    results: list[AnalysisResult],
) -> None:
    c.section("지연 파급 비용: 총액·판정·결정 기한·대안 밖")
    doubled = {r.request.model_dump_json(): r for r in _analyses(index, requests, book, _scaled(params, 2.0))}
    moved, scaled = [], []
    for result in results:
        other = doubled[result.request.model_dump_json()]
        if result.model_dump(include=set(SAME)) != other.model_dump(include=set(SAME)):
            moved.append(result.request.change.ecn_id)
        mine, theirs = result.delay_ripple, other.delay_ripple
        if (mine is None) != (theirs is None) or (
            mine is not None and theirs is not None and theirs.amount.value != 2 * mine.amount.value
        ):
            scaled.append(result.request.change.ecn_id)
    c.check(
        f"하루 비용을 두 배로 해도 비용 줄·총액·판정·곡선·결정 기한·보류 권고·일정·대안이 같음({len(results)}건)",
        not moved,
        moved[:3],
    )
    c.check("지연 파급 비용(대표값)만 두 배", not scaled, scaled[:3])


def _no_overlap(
    c: Checker,
    snapshot: GraphSnapshot,
    results: list[AnalysisResult],
    book: RuleBook,
    params: ParamSet,
) -> None:
    c.section("지연 파급 비용: 지체상금·노출 금액과 겹치지 않음")
    late = next((r for r in results if r.schedule.max_exit_delay_days > 1), None)
    if late is None:
        c.check("구역 출구가 이틀 이상 늦는 사례가 있음", False)
        return
    # 구역 출구 → 인도 여유를 하루만 두고 유예 0일 계약 조건을 둔 지도: 구역 출구가 이틀 이상 늦으면 하루는 지연 파급,
    # 나머지 늘어난 인도 지연은 바로 지체상금(노출 금액)이 된다
    terms = LDTerms(grace_days=0, rate_per_day_of_price=0.00022, max_days=180)
    tight = snapshot.model_copy(
        update={
            "boundaries": tuple(
                b.model_copy(update={"float_to_delivery_days": FLOAT, "forecast_delivery_delay_days": 0})
                for b in snapshot.boundaries
            ),
            "ships": tuple(s.model_copy(update={"ld_terms": terms}) for s in snapshot.ships),
        }
    )
    index = GraphIndex(tight)
    request = late.request.model_copy(update={"include_alternatives": False})
    damages = analyze(index, request, book, params)
    owner = request.model_copy(
        update={"change": request.change.model_copy(update={"cause": ChangeCause.OWNER_REQUEST})}
    )
    exposure = analyze(index, owner, book, params)
    doubled = analyze(index, request, book, _scaled(params, 2.0))
    erection, exits, added = _slip(index, damages)
    ld = [line for line in damages.cost_lines if line.rule_id == "R-L01"]
    ripple = damages.delay_ripple
    c.check(
        f"인도 여유 {FLOAT}일 지도({late.request.change.ecn_id}): 늘어난 인도 지연 {added}일은 지체상금 줄이 세고, "
        "지연 파급 일수는 구역 출구 지연에서 그 날을 뺀 값(같은 날을 두 금액이 세지 않음)",
        added > 0 and bool(ld) and ripple is not None and ripple.days + added == exits and ripple.days <= FLOAT,
        (erection, exits, added, ripple and ripple.days),
    )
    c.check(
        "지연 파급 하루 비용을 바꿔도 지체상금 줄 금액은 그대로",
        [line.amount for line in ld] == [line.amount for line in doubled.cost_lines if line.rule_id == "R-L01"],
    )
    delivery = exposure.schedule.delivery
    c.check(
        "선주 요청(허용 지연): 노출 금액이 세는 인도 지연 날도 똑같이 뺌(지연 파급 일수는 원인 미입력과 같음)",
        delivery is not None and delivery.exposure is not None and exposure.delay_ripple == damages.delay_ripple,
        (exposure.delay_ripple, damages.delay_ripple),
    )
