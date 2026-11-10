"""E7 결정 일치 도구의 성질(ripple/eval/decision_agreement.py): 엔진과 같은 두 단계 고르기 순서 · 손으로 센 지표 · 기준
경계 · 통제 왕복(실제 총액 = 엔진 총액이면 같은 조합 100%·후회 0) · 결정성.

전체 개발 분할 측정은 `scripts/eval_decision.py`(시간이 걸려 여기서는 앞쪽 사례만 쓴다). 확인 모드 숨긴 모델은 미래 발주
날짜가 엔진 추정과 달라 완전 일치를 보장하지 않으므로 왕복은 엔진 총액을 실제로 넣어 통제한다.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, timedelta

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook, load_strength
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.analysis import AnalysisRequest, HoldAction
from ripple.contracts.change import ChangeRequest
from ripple.contracts.dataset import EcnSplit
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.eval.decision_agreement import (
    Combo,
    DecisionAgreement,
    DecisionCase,
    Option,
    agreement,
    decision_case,
    decision_cases,
    hidden_total,
    pick,
)
from ripple.generator.actuals import HiddenModel
from ripple.generator.build import generate
from ripple.generator.io import load_config

DAY0 = date(2026, 10, 20)
HORIZON = 25  # 통제 왕복은 확정 가능일 +20일 ~ 탐색 끝 25일(6일)만 봐 계산을 줄인다


def _combo(alt: str, day: int, holds: int = 0, *, request: bool = False) -> Combo:
    return Combo(
        alt_id=alt,
        is_request=request,
        confirm_on=DAY0 + timedelta(days=day),
        holds=tuple((f"PO-{i:04d}", 5) for i in range(holds)),
    )


def _option(alt: str, cost: int, day: int, holds: int = 0, *, request: bool = False) -> Option:
    return Option(_combo(alt, day, holds, request=request), cost)


def _case(engine: Combo, best: Combo, engine_actual: int, best_actual: int, *, meets: int = 1) -> DecisionCase:
    return DecisionCase(
        ecn_id="E",
        earliest=DAY0,
        engine=engine,
        best=best,
        engine_actual=engine_actual,
        best_actual=best_actual,
        meets=meets,
        uncertain=False,
    )


def _summary(same: float | None, ratio: float | None, cases: int = 1) -> DecisionAgreement:
    return DecisionAgreement(
        cases=cases,
        excluded=0,
        same=same,
        regret_ratio=ratio,
        zero_regret=None,
        mean_regret=None,
        with_alternatives=0,
        engine_held=0,
        best_held=0,
        engine_later=0,
        uncertain=0,
    )


def run(c: Checker) -> None:
    c.section("E7 결정 일치 도구(두 단계 고르기·손으로 센 지표·기준 경계·통제 왕복·결정성)")
    # 대안 안: T1은 같은 금액이면 이른 날(3일, 보류 1)을 고름. 대안 사이: 같은 금액이면 보류가 적은 T2(4일, 보류 0)가
    # 날짜가 이른 T1을 이김 — 한 번에 (금액, 날짜, 보류 수)로 고르면 T1이 되어 엔진과 달라진다
    conflict = [
        _option("ALT-T1", 100, 5),
        _option("ALT-T1", 100, 3, holds=1),
        _option("ALT-T2", 100, 4),
    ]
    request_first = [_option("ALT-T1", 100, 0), _option("ALT-REQ", 100, 9, request=True)]
    cheaper = [_option("ALT-T1", 99, 9, holds=1), _option("ALT-REQ", 100, 0, request=True)]
    by_id = [_option("ALT-T2", 100, 1), _option("ALT-T1", 100, 1)]
    c.check(
        "고르기: 대안 안 (금액, 이른 날, 보류 수) → 대안 사이 (금액, 요청안 먼저, 보류 수, 날짜, ID), 빈 후보는 오류",
        pick(conflict).combo == _combo("ALT-T2", 4)
        and pick(request_first).combo.alt_id == "ALT-REQ"
        and pick(cheaper).combo.alt_id == "ALT-T1"
        and pick(by_id).combo.alt_id == "ALT-T1"
        and pick([_option("ALT-T1", 100, 2, holds=2), _option("ALT-T1", 100, 2)]).combo.holds == ()
        and c.raises(lambda: pick([])),
        pick(conflict),
    )
    req = _combo("ALT-REQ", 0, request=True)
    rows = [
        _case(req, req, 100, 100),
        _case(_combo("ALT-T1", 0, holds=1), _combo("ALT-T1", 0, holds=1), 200, 200, meets=2),
        _case(_combo("ALT-REQ", 5, request=True), req, 330, 300),  # 다른 조합, 후회 30
        _case(_combo("ALT-T1", 0), _combo("ALT-REQ", 0, holds=1, request=True), 400, 400, meets=2),  # 동률
    ]
    got = agreement(rows, excluded=2)
    c.check(
        "같은 조합 2/4 · 후회 30/1,000 · 후회 0 3/4 · 평균 후회 7.5원 · 대안 2개+ 2 · 보류 엔진 1·최선 2 · "
        "늦은 확정 1 · 미달",
        got.cases == 4
        and got.excluded == 2
        and got.same == 0.5
        and abs((got.regret_ratio or 0) - 0.03) < 1e-12
        and got.zero_regret == 0.75
        and got.mean_regret == 7.5
        and got.with_alternatives == 2
        and got.engine_held == 1
        and got.best_held == 2
        and got.engine_later == 1
        and not got.passed,
        got,
    )
    zero_best = agreement([_case(req, _combo("ALT-T1", 0), 10, 0)])
    c.check(
        "기준 경계: 같은 조합 80%·후회 5%는 합격, 바로 바깥·사례 없음은 미달, 최선이 모두 0원인데 후회면 무한대",
        _summary(0.8, 0.05).passed
        and not _summary(0.7999999, 0.05).passed
        and not _summary(0.8, 0.0500001).passed
        and not _summary(None, None, cases=0).passed
        and agreement([]).same is None
        and zero_best.regret_ratio == math.inf
        and not zero_best.passed,
        zero_best,
    )
    # 최선 −300원(엔진 −290원, 후회 10)과 +100원(후회 0): |최선|의 평균이면 10/400, 평균의 절댓값이면 10/200,
    # 부호 있는 평균이면 음수 — 정의(docs/evaluation.md)대로 |최선|의 평균만 2.5%
    mixed = agreement([_case(req, _combo("ALT-T1", 0), -290, -300), _case(req, req, 100, 100)])
    c.check(
        "후회 분모 = 실제 최선 총액 절댓값의 평균(부호가 섞여도): 후회 10 ÷ 400 = 2.5%, 모두 0원이고 후회 없으면 0",
        mixed.regret_ratio == 0.025 and agreement([_case(req, req, 0, 0)]).regret_ratio == 0.0,
        mixed,
    )
    config = load_config()
    generated = generate(config)
    settings = Settings.from_env({})
    rulebook, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    strength = load_strength(settings.strength_path)
    index = GraphIndex(generated.snapshot)
    as_of = config.scenario_date

    def engine_total(change: ChangeRequest, confirm_on: date, holds: Mapping[str, int]) -> int:
        request = AnalysisRequest(
            change=change,
            as_of=as_of,
            confirm_on=confirm_on,
            horizon_days=HORIZON,
            holds=tuple(HoldAction(po_id=po_id, hold_days=days) for po_id, days in sorted(holds.items())),
        )
        return analyze(index, request, rulebook, params).total.value

    # 대안 2개(엔진이 보강재 대안을 고름) · 대안 2개 + 보류 권고 · 보류 권고만 — 쉬운 사례만 보지 않게 골랐다
    # (강재 손실 상한(docs/engine.md(비용·일정) 4-2)으로 0017·0026의 보류 권고가 없어져
    # 보류 권고만인 사례를 0008·0018로 바꿈)
    changes = {e.change.ecn_id: e.change for e in generated.ecns if e.split is EcnSplit.DEV}
    controlled = [
        decision_case(index, engine_total, rulebook, params, strength, changes[ecn_id], as_of, 20, HORIZON)
        for ecn_id in ("ECN-D-0119", "ECN-D-0045", "ECN-D-0008", "ECN-D-0018")
    ]
    c.check(
        "통제 왕복: 실제 총액 = 엔진 총액이면 4건(+20일, 탐색 25일) 모두 같은 조합·후회 0, 대안·보류가 든 권고 포함",
        all(case.same and case.regret == 0 for case in controlled)
        and any(case.meets > 1 and not case.engine.is_request for case in controlled)
        and any(case.meets > 1 and case.engine.holds for case in controlled)
        and sum(bool(case.engine.holds) for case in controlled) >= 3,
        controlled,
    )
    hidden = HiddenModel(generated, PROJECT_ROOT / "params" / "cost_v1.yaml")
    actual = hidden_total(hidden, as_of)
    first = decision_cases(generated, actual, rulebook, params, strength, EcnSplit.DEV, as_of, shift=20, limit=3)
    second = decision_cases(generated, actual, rulebook, params, strength, EcnSplit.DEV, as_of, shift=20, limit=3)
    c.check(
        "개발 분할 앞 3건(+20일): 두 번 재도 같은 사례, ECN 번호 순, 후회 ≥ 0, 엔진 확정일 ≥ 확정 가능일",
        first == second
        and len(first[0]) + first[1] == 3
        and [case.ecn_id for case in first[0]] == sorted(case.ecn_id for case in first[0])
        and all(case.regret >= 0 and case.engine.confirm_on >= case.earliest for case in first[0]),
        first,
    )
