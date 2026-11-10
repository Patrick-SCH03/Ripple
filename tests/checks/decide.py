"""판단 계층의 성질: 보정은 확률을 맞추고, 문턱·집합은 약속한 오류율·포함률을 지킨다.

정답 확률을 아는 합성 사례로 잰다. 실제 확률은 softmax(z)이고, 점수기는 z를 부풀려(과신)
내도록 만든다. 그래서 맞는 온도는 부풀린 배수와 같다. 사례는 '쉬운 판단'(후보 하나가 뚜렷함)과
'어려운 판단'을 섞어 실제 점수기처럼 만든다. 난수는 시드를 고정한다.
"""

from __future__ import annotations

import random
from bisect import bisect_left
from collections.abc import Callable, Sequence
from itertools import pairwise
from math import comb

from harness import Checker

from ripple.config.loaders import load_decision_config
from ripple.config.settings import Settings
from ripple.contracts.decision import (
    GATE_TOPICS,
    NONE_OPTION,
    ChoiceQuestion,
    DecisionBackend,
    DecisionTopic,
    Gate,
    GateKind,
    Option,
    Route,
    TopicCalibration,
)
from ripple.decide.calibration import fit_temperature, negative_log_likelihood, softmax
from ripple.decide.conformal import conformal_qhat, prediction_set, ranked
from ripple.decide.metrics import coverage, expected_calibration_error
from ripple.decide.policy import (
    Decision,
    ScoredCase,
    Splits,
    Unit,
    calibrate_gate,
    probabilities,
    shows_set,
    unit_outcome,
)
from ripple.decide.risk import TopOutcome, binomial_cdf, clopper_pearson_lower, ltt_threshold, threshold_grid
from ripple.decide.router import decide_unit
from ripple.decide.scorer import Example, mean_log_loss, scores, train

OPTION_IDS = (*(f"c{i}" for i in range(6)), NONE_OPTION)
GRID = (0.999, 0.995, 0.99, 0.98, 0.97, 0.96, 0.95, 0.94, 0.92, 0.9, 0.88, 0.85, 0.8, 0.75, 0.7, 0.6, 0.5)
REQUEST_TOPICS = GATE_TOPICS[GateKind.REQUEST]


def scored(rng: random.Random, easy: float = 0.0, inflate: float = 2.0) -> ScoredCase:
    if rng.random() < easy:  # 쉬운 판단: 실제 후보 하나가 뚜렷함
        z = [rng.gauss(0, 1.0) for _ in OPTION_IDS]
        z[rng.randrange(len(OPTION_IDS) - 1)] += 7.0
    else:  # 어려운 판단
        z = [rng.gauss(0, 2.5) for _ in OPTION_IDS]
    label = rng.choices(OPTION_IDS, weights=softmax(z))[0]
    return ScoredCase(option_ids=OPTION_IDS, scores=tuple(inflate * v for v in z), label=label)


def cases(rng: random.Random, n: int, easy: float = 0.0, inflate: float = 2.0) -> list[ScoredCase]:
    return [scored(rng, easy, inflate) for _ in range(n)]


def request_units(rng: random.Random, n: int) -> list[Unit]:
    """대상은 어려운 판단이 더 많고 연산은 대부분 쉬운 요청 단위(변경 사유는 사유 문으로 따로)."""
    easy = {DecisionTopic.TARGET_PART: 0.7, DecisionTopic.CHANGE_OP: 0.9}
    return [Unit(tuple(Decision(topic, scored(rng, easy[topic])) for topic in REQUEST_TOPICS)) for _ in range(n)]


def labeled(items: Sequence[ScoredCase]) -> list[tuple[Sequence[float], int]]:
    return [(c.scores, c.option_ids.index(c.label)) for c in items]


def question_for(topic: DecisionTopic, option_ids: Sequence[str] = OPTION_IDS) -> ChoiceQuestion:
    return ChoiceQuestion(
        question_id=f"q-{topic}",
        topic=topic,
        mention="판단 대상",
        options=tuple(Option(option_id=i, label=i) for i in option_ids),
    )


def run(c: Checker) -> None:
    _calibration(c)
    _conformal(c)
    _risk(c)
    _request_gate(c)
    _correlated(c)
    _reason_gate(c)
    _readiness(c)
    _scorer(c)
    _router(c)


def _calibration(c: Checker) -> None:
    c.section("판단 계층: 온도 보정")
    probs = softmax([3.0, 1.0, -2.0])
    c.check("softmax 합은 1이고 점수 순서를 지킴", abs(sum(probs) - 1) < 1e-12 and probs[0] > probs[1] > probs[2])
    flat = softmax([3.0, 1.0, -2.0], temperature=1000)
    c.check("온도가 아주 높으면 거의 균등", max(flat) - min(flat) < 0.01)
    c.check("온도 0 이하는 거부", c.raises(lambda: softmax([1.0], temperature=0)))
    rng = random.Random(7)
    over = labeled(cases(rng, 3000, inflate=2.0))
    fitted = fit_temperature(over)
    c.check("과신한 점수기의 온도를 되찾음(참값 2)", 1.8 <= fitted <= 2.2, round(fitted, 3))
    c.check(
        "맞춘 온도가 온도 1보다 로그우도 손실이 작음",
        negative_log_likelihood(over, fitted) < negative_log_likelihood(over, 1.0),
    )
    fitted_under = fit_temperature(labeled(cases(rng, 3000, inflate=0.5)))
    c.check("자신 없는 점수기의 온도도 되찾음(참값 0.5)", 0.42 <= fitted_under <= 0.58, round(fitted_under, 3))
    good = [ranked(probabilities(case, 2.0))[0] + (case.label,) for case in cases(rng, 20000)]
    bad = [ranked(probabilities(case, 1.0))[0] + (case.label,) for case in cases(rng, 20000)]
    ece_good = expected_calibration_error([p for _, p, _ in good], [t == y for t, _, y in good])
    ece_bad = expected_calibration_error([p for _, p, _ in bad], [t == y for t, _, y in bad])
    c.check("보정된 확률의 ECE는 작음(< 0.02)", ece_good < 0.02, round(ece_good, 4))
    c.check("과신한 확률의 ECE는 큼(> 0.05)", ece_bad > 0.05, round(ece_bad, 4))


def _conformal(c: Checker) -> None:
    c.section("판단 계층: 되묻기 집합")
    c.check("보정 판단이 없으면 모든 선택지", conformal_qhat([], 0.05) == 1.0)
    c.check("보정 판단이 19개 미만이면 모든 선택지(α = 0.05)", conformal_qhat([0.9] * 18, 0.05) == 1.0)
    c.check("보정 판단이 19개면 계산함", conformal_qhat([0.9] * 19, 0.05) < 1.0)
    rng = random.Random(11)
    sample = dict(zip(OPTION_IDS, softmax([rng.gauss(0, 2) for _ in OPTION_IDS]), strict=True))
    sets = [prediction_set(sample, q) for q in (0.0, 0.3, 0.6, 0.9, 1.0)]
    c.check("집합은 언제나 최상위를 포함", all(s and s[0] == ranked(sample)[0][0] for s in sets))
    c.check("q̂가 커지면 집합이 넓어지기만 함", all(set(a) <= set(b) for a, b in pairwise(sets)))
    c.check("q̂ = 1이면 모든 선택지", set(sets[-1]) == set(OPTION_IDS))
    calibration = cases(rng, 1500)
    qhat = conformal_qhat([probabilities(case, 2.0)[case.label] for case in calibration], 0.05)
    test = cases(rng, 4000)
    rate = coverage([prediction_set(probabilities(case, 2.0), qhat) for case in test], [case.label for case in test])
    c.check("교환 가능한 자료에서 포함률이 목표 0.95 근처(0.935~0.97)", 0.935 <= rate <= 0.97, round(rate, 4))


def _risk(c: Checker) -> None:
    c.section("판단 계층: 자동 진행 문턱 검정")
    exact = [sum(comb(10, i) * 0.3**i * 0.7 ** (10 - i) for i in range(k + 1)) for k in range(11)]
    c.check("이항 누적확률이 직접 합과 같음", all(abs(binomial_cdf(k, 10, 0.3) - exact[k]) < 1e-12 for k in range(11)))
    c.check("모두 성공이면 하한 = (1 − 신뢰도)^(1/n)", abs(clopper_pearson_lower(100, 100) - 0.05 ** (1 / 100)) < 1e-9)
    lower = clopper_pearson_lower(95, 100)
    c.check("95/100의 단측 95% 하한은 약 0.898", 0.89 <= lower <= 0.905, round(lower, 4))
    c.check("성공이 늘면 하한이 높아짐", clopper_pearson_lower(90, 100) < lower < clopper_pearson_lower(99, 100))
    c.check(
        "자동 진행 단위가 76개 미만이면 오류 0건이어도 인증 못 함(ε 0.03, δ 0.1)",
        ltt_threshold([TopOutcome(0.999, True, True)] * 75, GRID, epsilon=0.03, delta=0.1) is None,
    )
    c.check(
        "자동 진행 단위가 76개면 인증함",
        ltt_threshold([TopOutcome(0.9995, True, True)] * 76, GRID, epsilon=0.03, delta=0.1) is not None,
    )
    grid = threshold_grid([0.99, 0.97, 0.95, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3], (0.2, 0.5, 0.9))
    c.check("문턱 목록은 신뢰도 상위 비율의 경계값(내림차순)", grid == (0.97, 0.8, 0.4), grid)
    c.check("같은 경계값이 겹치면 한 번만 검정", threshold_grid([0.9] * 10, (0.2, 0.5)) == (0.9,))
    wrong_top = [TopOutcome(0.995, False, True)] * 50 + [TopOutcome(0.95, True, True)] * 1000
    c.check(
        "가장 높은 문턱에서 기각 못 하면 거기서 멈춤(고정 순서)",
        ltt_threshold(wrong_top, (0.99, 0.9), epsilon=0.03, delta=0.1) is None,
    )
    none_top = [TopOutcome(0.999, False, False)] * 500 + [TopOutcome(0.999, True, True)] * 200
    c.check(
        "'해당 없음'이 최상위인 단위는 검정 집단에서 빠짐",
        ltt_threshold(none_top, (0.99,), epsilon=0.03, delta=0.1) == 0.99,
    )

    rng = random.Random(23)
    levels = (0.2, 0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95)
    expected_error = _true_error_curve([_case_outcome(case) for case in cases(rng, 60000, easy=0.6)])
    violations = certified = 0
    trials = 100
    for _ in range(trials):
        ordering = [o.top_prob for o in (_case_outcome(case) for case in cases(rng, 1000, easy=0.6)) if o.eligible]
        grid = threshold_grid(ordering, levels)
        tau = ltt_threshold([_case_outcome(case) for case in cases(rng, 2000, easy=0.6)], grid, 0.03, 0.1)
        if tau is not None:
            certified += 1
            violations += expected_error(tau) > 0.03
    c.check("문턱을 인증한 시행이 충분함", certified >= 75, f"{certified}/{trials}")
    c.check(
        "인증한 문턱의 실제 오류율이 ε를 넘는 시행 비율 ≤ δ(0.1)", violations / trials <= 0.1, f"{violations}/{trials}"
    )


def _request_gate(c: Checker) -> None:
    c.section("판단 계층: 요청 문 전체 흐름")
    targets = load_decision_config(Settings.from_env({}).decision_path).targets
    rng = random.Random(31)
    gate, calibrations = calibrate_gate(
        GateKind.REQUEST,
        DecisionBackend.LOCAL,
        targets,
        temperature_units=request_units(rng, 1500),
        tau_units=request_units(rng, 3000),
        set_units=request_units(rng, 3000),
        splits=Splits(temperature="t", tau="u", set="s"),
    )
    c.check(
        "주제마다 온도를 되찾음",
        all(1.8 <= cal.temperature <= 2.2 for cal in calibrations),
        [round(cal.temperature, 3) for cal in calibrations],
    )
    c.check("요청 문의 자동 진행 문턱을 인증함", gate.auto_threshold is not None, gate.auto_threshold)
    c.check(
        "주제마다 집합 보정 판단이 19개 이상",
        all(cal.n_set >= 19 for cal in calibrations),
        [cal.n_set for cal in calibrations],
    )

    by_topic = {cal.topic: cal for cal in calibrations}
    questions = {topic: question_for(topic) for topic in REQUEST_TOPICS}
    auto_units = auto_wrong = 0
    all_or_none = True
    shown: dict[DecisionTopic, list[bool]] = {topic: [] for topic in REQUEST_TOPICS}
    for unit in request_units(rng, 4000):
        items = [(questions[d.topic], dict(zip(d.case.option_ids, d.case.scores, strict=True))) for d in unit.decisions]
        answers = decide_unit(items, by_topic, gate, targets.max_choices, "test")
        autos = [a.route is Route.AUTO for a in answers]
        all_or_none = all_or_none and (all(autos) or not any(autos))
        if all(autos):
            auto_units += 1
            auto_wrong += any(a.top != d.case.label for a, d in zip(answers, unit.decisions, strict=True))
            continue
        for answer, decision in zip(answers, unit.decisions, strict=True):
            if shows_set(answer.top, answer.probabilities[answer.top], False, gate.auto_threshold):
                shown[decision.topic].append(decision.case.label in answer.prediction_set)
    c.check("요청 안 판단은 모두 자동 진행이거나 모두 아님", all_or_none)
    error = auto_wrong / max(auto_units, 1)
    c.check(
        "새 자료에서 자동 진행한 요청의 오류율(하나라도 오답) ≤ ε + 0.01",
        error <= targets.epsilon[GateKind.REQUEST] + 0.01,
        f"{auto_wrong}/{auto_units}",
    )
    for topic, hits in shown.items():
        rate = sum(hits) / max(len(hits), 1)
        c.check(f"새 자료에서 {topic} 되묻기 집합 포함률 ≥ 0.935", rate >= 0.935, f"{sum(hits)}/{len(hits)}")


def _reason_gate(c: Checker) -> None:
    c.section("판단 계층: 사유 문(변경 사유는 분석 뒤에)")
    targets = load_decision_config(Settings.from_env({}).decision_path).targets
    rng = random.Random(61)
    splits = Splits(temperature="t", tau="u", set="s")

    def reasons(n: int) -> list[Unit]:
        return [Unit((Decision(DecisionTopic.CHANGE_INTENT, scored(rng, 0.8)),)) for _ in range(n)]

    gate, calibrations = calibrate_gate(
        GateKind.INTENT, DecisionBackend.LOCAL, targets, reasons(1500), reasons(2000), reasons(1500), splits
    )
    c.check(
        "사유 문은 의도 판단 하나로 온도·자동 기록 문턱·집합을 정함",
        gate.kind is GateKind.INTENT
        and gate.auto_threshold is not None
        and [cal.topic for cal in calibrations] == [DecisionTopic.CHANGE_INTENT],
        (gate.auto_threshold, [cal.topic for cal in calibrations]),
    )
    with_reason = [
        Unit((Decision(DecisionTopic.CHANGE_OP, scored(rng, 0.9)), Decision(DecisionTopic.CHANGE_INTENT, scored(rng))))
        for _ in range(50)
    ]
    c.check(
        "요청 문 단위에 사유 판단을 넣으면 거부(요청 문은 대상·연산만)",
        c.raises(
            lambda: calibrate_gate(
                GateKind.REQUEST, DecisionBackend.LOCAL, targets, with_reason, with_reason, with_reason, splits
            )
        ),
    )


def _correlated(c: Checker) -> None:
    c.section("판단 계층: 단위 안 여러 판단")
    targets = load_decision_config(Settings.from_env({}).decision_path).targets
    rng = random.Random(53)
    splits = Splits(temperature="t", tau="u", set="s")
    temperature_units = request_units(rng, 1500)
    copied = scored(rng)
    one_unit = Unit(
        (
            *(Decision(DecisionTopic.TARGET_PART, copied) for _ in range(19)),
            Decision(DecisionTopic.CHANGE_OP, scored(rng)),
        )
    )
    _, calibrations = calibrate_gate(
        GateKind.REQUEST, DecisionBackend.LOCAL, targets, temperature_units, [], [one_unit], splits
    )
    target = next(cal for cal in calibrations if cal.topic is DecisionTopic.TARGET_PART)
    c.check(
        "한 단위의 상관된 판단 여러 개는 보정 표본 하나로 셈(소표본 보호 유지)",
        target.n_set == 1 and target.set_qhat == 1.0,
        (target.n_set, target.set_qhat),
    )

    def multi_target_units(n: int) -> list[Unit]:
        return [
            Unit(
                (
                    *(Decision(DecisionTopic.TARGET_PART, scored(rng, 0.7)) for _ in range(3)),
                    Decision(DecisionTopic.CHANGE_OP, scored(rng, 0.9)),
                )
            )
            for _ in range(n)
        ]

    gate, calibrations = calibrate_gate(
        GateKind.REQUEST,
        DecisionBackend.LOCAL,
        targets,
        temperature_units,
        multi_target_units(2000),
        multi_target_units(3000),
        splits,
    )
    by_topic = {cal.topic: cal for cal in calibrations}
    questions = {topic: question_for(topic) for topic in REQUEST_TOPICS}
    covered = total = 0
    for unit in multi_target_units(3000):
        items = [(questions[d.topic], dict(zip(d.case.option_ids, d.case.scores, strict=True))) for d in unit.decisions]
        answers = decide_unit(items, by_topic, gate, targets.max_choices, "test")
        shown = [
            d.case.label in a.prediction_set
            for a, d in zip(answers, unit.decisions, strict=True)
            if d.topic is DecisionTopic.TARGET_PART
            and a.route is not Route.AUTO
            and shows_set(a.top, a.probabilities[a.top], False, gate.auto_threshold)
        ]
        if shown:
            total += 1
            covered += all(shown)
    c.check(
        "대상 판단이 여럿인 요청에서 집합을 보인 대상 판단이 모두 정답을 포함할 비율 ≥ 0.935",
        covered / max(total, 1) >= 0.935,
        f"{covered}/{total}",
    )


def _router(c: Checker) -> None:
    c.section("판단 계층: 경로")
    gate = Gate(kind=GateKind.COLUMN, auto_threshold=0.95, n_units=500, split="u")
    calibration = TopicCalibration(
        topic=DecisionTopic.EXCEL_COLUMN,
        backend=DecisionBackend.LOCAL,
        temperature=1.0,
        set_qhat=0.8,
        n_temperature=500,
        n_set=300,
        temperature_split="t",
        set_split="s",
    )
    cals = {DecisionTopic.EXCEL_COLUMN: calibration}
    column = question_for(DecisionTopic.EXCEL_COLUMN, ("qty", "unit", "price", NONE_OPTION))

    def route(scores: dict[str, float], g: Gate = gate, cal: TopicCalibration = calibration, top_n: int = 7) -> Route:
        return decide_unit([(column, scores)], {cal.topic: cal}, g, top_n, "v")[0].route

    c.check(
        "확신이 문턱 이상이면 자동 진행", route({"qty": 9.0, "unit": 0.0, "price": 0.0, NONE_OPTION: 0.0}) is Route.AUTO
    )
    c.check(
        "'해당 없음'이 확실하면(진짜 후보 1% 미만) 다시 설명",
        route({"qty": 0.0, "unit": 0.0, "price": 0.0, NONE_OPTION: 9.0}) is Route.RESTATE,
    )
    # 고르기 우선: 집합에 '해당 없음'만 남아도 두드러진 진짜 후보가 3개 이하면 그 후보와 함께 고르기
    small = decide_unit([(column, {"qty": 0.0, "unit": 0.0, "price": -6.0, NONE_OPTION: 2.4})], cals, gate, 7, "v")[0]
    c.check(
        "'해당 없음'만 남아도 두드러진 후보(최상위 절반 이상)가 3개 이하면 고르기, 보이는 집합은 원래 집합을 포함",
        small.route is Route.CHOOSE
        and small.prediction_set == (NONE_OPTION, "qty", "unit")
        and set(prediction_set(small.probabilities, calibration.set_qhat)) <= set(small.prediction_set),
        (small.route, small.prediction_set),
    )
    four = question_for(DecisionTopic.EXCEL_COLUMN, ("a", "b", "c", "d", NONE_OPTION))
    spread = decide_unit([(four, {"a": 0.0, "b": 0.0, "c": 0.0, "d": 0.0, NONE_OPTION: 2.5})], cals, gate, 7, "v")[0]
    c.check(
        "두드러진 후보가 3개를 넘으면(고르게 많으면) 다시 설명", spread.route is Route.RESTATE, spread.prediction_set
    )
    c.check(
        "두 후보가 비슷하면 고르기", route({"qty": 2.0, "unit": 1.8, "price": -3.0, NONE_OPTION: -3.0}) is Route.CHOOSE
    )
    narrow = calibration.model_copy(update={"set_qhat": 0.1})
    c.check(
        "후보 하나지만 문턱 미달이면 확인",
        route({"qty": 3.0, "unit": 0.0, "price": 0.0, NONE_OPTION: 0.0}, cal=narrow) is Route.CONFIRM,
    )
    wide = calibration.model_copy(update={"set_qhat": 1.0})
    c.check(
        "후보가 최대 개수를 넘으면 다시 설명",
        route({"qty": 0.1, "unit": 0.0, "price": 0.0, NONE_OPTION: 0.0}, cal=wide, top_n=3) is Route.RESTATE,
    )
    off = gate.model_copy(update={"auto_threshold": None})
    rng = random.Random(41)
    routes = [route({k: rng.gauss(0, 6) for k in ("qty", "unit", "price", NONE_OPTION)}, g=off) for _ in range(500)]
    c.check("대체 관문: 자동 진행을 끈 문은 모든 판단이 확인을 거침", Route.AUTO not in routes)
    c.check(
        "선택지와 점수 키가 다르면 거부", c.raises(lambda: decide_unit([(column, {"qty": 1.0})], cals, gate, 7, "v"))
    )
    target = question_for(DecisionTopic.TARGET_PART)
    c.check(
        "문에 속하지 않는 주제는 거부",
        c.raises(lambda: decide_unit([(target, dict.fromkeys(OPTION_IDS, 0.0))], cals, gate, 7, "v")),
    )
    c.check("빈 단위는 거부", c.raises(lambda: decide_unit([], cals, gate, 7, "v")))
    c.check("'해당 없음' 없는 질문은 거부", c.raises(lambda: question_for(DecisionTopic.TARGET_PART, ("a", "b"))))

    request_gate = Gate(kind=GateKind.REQUEST, auto_threshold=0.95, n_units=500, split="u")
    req_cals = {topic: calibration.model_copy(update={"topic": topic}) for topic in REQUEST_TOPICS}
    sure = {k: (9.0 if k == "c0" else 0.0) for k in OPTION_IDS}
    unsure = {k: (1.0 if k in ("c0", "c1") else 0.0) for k in OPTION_IDS}
    mixed = decide_unit(
        [
            (question_for(DecisionTopic.TARGET_PART), unsure),
            (question_for(DecisionTopic.CHANGE_OP), sure),
        ],
        req_cals,
        request_gate,
        7,
        "v",
    )
    c.check("요청 안 판단 하나라도 불확실하면 요청은 자동 진행하지 않음", all(a.route is not Route.AUTO for a in mixed))
    c.check(
        "요청은 자동 진행이 아니어도 확신한 판단은 미리 채워 확인",
        mixed[1].route is Route.CONFIRM and mixed[1].prediction_set == ("c0",),
    )
    c.check("불확실한 판단에는 고르기 집합", mixed[0].route is Route.CHOOSE)


def _readiness(c: Checker) -> None:
    """판단 밖 자격(값 결정성·슬롯 완결성)을 보정·라우터가 같은 술어로 쓰는지.

    정답인 단위만 골라 자격을 빼는 필터(최악의 경우)로 두 가지를 본다.
    - 강한 필터: 보정이 같은 필터를 쓰면 실제 자동 진행 집단의 오류율 보장이 유지되고(인증 못 하면 끔),
      문턱은 필터 없이 보정한 것보다 낮아지지 않는다.
    - 약한 필터(문턱을 인증함): 라우터의 자동 진행이 보정 술어와 같고 자격 없는 단위는 자동 진행하지 않는다.
    """
    c.section("판단 계층: 판단 밖 자동 진행 자격(ready)")
    targets = load_decision_config(Settings.from_env({}).decision_path).targets
    splits = Splits(temperature="t", tau="u", set="s")
    raw = {topic: 1.0 for topic in REQUEST_TOPICS}
    questions = {topic: question_for(topic) for topic in REQUEST_TOPICS}

    def filtered(rng: random.Random, n: int, drop: float) -> list[Unit]:
        units = []
        for unit in request_units(rng, n):
            outcome = unit_outcome(unit, raw)
            ready = not (outcome.correct and rng.random() < drop)  # 정답만 빠지는 필터
            units.append(Unit(unit.decisions, ready=ready))
        return units

    def route(
        units: Sequence[Unit], gate: Gate, calibrations: Sequence[TopicCalibration]
    ) -> tuple[bool, int, int, int]:
        by_topic = {cal.topic: cal for cal in calibrations}
        temperatures = {cal.topic: cal.temperature for cal in calibrations}
        same, auto, wrong, blocked = True, 0, 0, 0
        for unit in units:
            items = [
                (questions[d.topic], dict(zip(d.case.option_ids, d.case.scores, strict=True))) for d in unit.decisions
            ]
            answers = decide_unit(items, by_topic, gate, targets.max_choices, "test", ready=unit.ready)
            routed = all(a.route is Route.AUTO for a in answers)
            outcome = unit_outcome(unit, temperatures)
            threshold = gate.auto_threshold
            same = same and routed == (outcome.eligible and threshold is not None and outcome.top_prob >= threshold)
            blocked += not unit.ready and routed
            auto += routed
            wrong += routed and not outcome.correct
        return same, auto, wrong, blocked

    rng = random.Random(77)
    temperature_units = request_units(rng, 1500)
    tau_units, set_units = filtered(rng, 3000, 0.4), filtered(rng, 3000, 0.4)
    strong, strong_cals = calibrate_gate(
        GateKind.REQUEST, DecisionBackend.LOCAL, targets, temperature_units, tau_units, set_units, splits
    )
    naive, _ = calibrate_gate(
        GateKind.REQUEST,
        DecisionBackend.LOCAL,
        targets,
        temperature_units,
        [Unit(u.decisions) for u in tau_units],
        [Unit(u.decisions) for u in set_units],
        splits,
    )
    c.check(
        "강한 필터: 보정 문턱이 필터 없이 보정한 것보다 낮아지지 않음(인증 못 하면 자동 진행 끔)",
        strong.auto_threshold is None
        or (naive.auto_threshold is not None and strong.auto_threshold >= naive.auto_threshold),
        (strong.auto_threshold, naive.auto_threshold),
    )
    _, auto, wrong, _ = route(filtered(rng, 4000, 0.4), strong, strong_cals)
    c.check(
        "강한 필터를 건 새 자료에서도 자동 진행 오류율 ≤ ε + 0.01",
        wrong / max(auto, 1) <= targets.epsilon[GateKind.REQUEST] + 0.01,
        f"{wrong}/{auto}",
    )

    mild, mild_cals = calibrate_gate(
        GateKind.REQUEST,
        DecisionBackend.LOCAL,
        targets,
        temperature_units,
        filtered(rng, 3000, 0.1),
        filtered(rng, 3000, 0.1),
        splits,
    )
    same, auto, wrong, blocked = route(filtered(rng, 4000, 0.1), mild, mild_cals)
    c.check(
        "약한 필터: 문턱을 인증하고 자동 진행이 있음(공허한 검사가 아님)",
        mild.auto_threshold is not None and auto > 0,
        auto,
    )
    c.check("라우터의 자동 진행 = 보정 술어(자격·해당 없음·문턱)", same)
    c.check("자격이 없는 단위는 자동 진행하지 않음", blocked == 0, blocked)
    c.check(
        "약한 필터를 건 새 자료에서 자동 진행 오류율 ≤ ε + 0.01",
        wrong / max(auto, 1) <= targets.epsilon[GateKind.REQUEST] + 0.01,
        f"{wrong}/{auto}",
    )


def _scorer(c: Checker) -> None:
    """조건부 로지스틱 점수기: 알려진 가중치로 만든 자료에서 가중치 부호·크기를 되찾고 손실을 줄인다."""
    c.section("판단 계층: 로컬 점수기")
    truth = {"match": 2.5, "near": 0.8, "none:bias": -0.5}
    rng = random.Random(11)

    def example() -> Example:
        options = ["a", "b", "c", "d", NONE_OPTION]
        features = [{"match": float(rng.random() < 0.3), "near": rng.random()} for _ in options[:-1]]
        features.append({"none:bias": 1.0})
        probs = softmax([sum(truth.get(k, 0.0) * v for k, v in f.items()) for f in features])
        label = rng.choices(options, weights=probs)[0]
        return Example(options=tuple(options), features=tuple(features), label=label)

    data = [example() for _ in range(1500)]
    weights = train(data, iterations=200)
    again = train(data, iterations=200)
    c.check("같은 자료면 같은 가중치(결정적)", weights == again)
    c.check(
        "알려진 가중치를 되찾음(±0.35)",
        all(abs(weights[k] - v) <= 0.35 for k, v in truth.items()),
        {k: weights.get(k) for k in truth},
    )
    held = [example() for _ in range(1000)]
    c.check(
        "학습한 가중치의 새 자료 손실 < 가중치 0의 손실",
        mean_log_loss(weights, held) < mean_log_loss({}, held),
        (round(mean_log_loss(weights, held), 4), round(mean_log_loss({}, held), 4)),
    )
    c.check("사례가 없으면 빈 가중치", train([]) == {})
    c.check(
        "정답이 선택지에 없으면 거부",
        c.raises(lambda: Example(options=("a", NONE_OPTION), features=({}, {}), label="z")),
    )
    c.check("점수는 선택지마다 하나", set(scores(weights, ("a", "b"), ({"match": 1.0}, {}))) == {"a", "b"})


def _case_outcome(case: ScoredCase) -> TopOutcome:
    return unit_outcome(Unit((Decision(DecisionTopic.EXCEL_COLUMN, case),)), {DecisionTopic.EXCEL_COLUMN: 2.0})


def _true_error_curve(population: Sequence[TopOutcome]) -> Callable[[float], float]:
    """보정이 맞을 때 문턱 τ 이상 자동 진행 집단의 실제 오류율 = 평균(1 − p). 큰 표본으로 미리 구한다."""
    ascending = sorted(o.top_prob for o in population if o.eligible)
    tail_error = [0.0] * (len(ascending) + 1)
    for i in range(len(ascending) - 1, -1, -1):
        tail_error[i] = tail_error[i + 1] + (1 - ascending[i])

    def error(threshold: float) -> float:
        start = bisect_left(ascending, threshold)
        count = len(ascending) - start
        return tail_error[start] / count if count else 0.0

    return error
