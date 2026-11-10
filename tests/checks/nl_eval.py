"""판단 계층 지표(E8)·해석 정확도(E3)와 보정 산출물 v3(요청 문 + 사유 문)의 성질."""

from __future__ import annotations

from harness import Checker

from ripple.config.loaders import load_decision_config, load_lexicon
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.dataset import NlSplit
from ripple.contracts.decision import GATE_TOPICS, NONE_OPTION, DecisionTopic, GateKind, Route
from ripple.eval.decision_metrics import BASELINE_MODELS, Ratio, _same, e3_report, e8_report, route_all, route_intent
from ripple.eval.nl_labels import read_and_label
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.generator.nl import load_nl_lexicon, nl_samples
from ripple.nl.pipeline import Models
from ripple.nl.vocab import MapVocabulary


def run(c: Checker) -> None:
    c.section("판단 계층 지표·보정 산출물")
    c.check("비율의 단측 95% 하한은 관측값 이하", Ratio(95, 100).lower() < 0.95 and Ratio(0, 0).lower() == 0.0)
    c.check("슬롯 비교: 목록은 순서 무관", _same(["b", "a"], ["a", "b"]) and not _same(["a"], ["a", "b"]))
    c.check("슬롯 비교: 정답의 빈 목록 = 채우지 않음", _same(None, []) and _same([], []) and not _same(["a"], []))
    c.check("슬롯 비교: 수치는 1e-6 안", _same(16.5, 16.5000001) and not _same(16.5, 17.0))

    config = load_decision_config(PROJECT_ROOT / "params" / "decision_v3.yaml")
    base = load_decision_config(PROJECT_ROOT / "params" / "decision_v0.yaml")
    c.check("v3의 목표값은 사전 등록한 v0와 같음", config.targets == base.targets)
    topics = set(GATE_TOPICS[GateKind.REQUEST]) | set(GATE_TOPICS[GateKind.INTENT])
    c.check(
        "v3에 요청 문(대상·연산)·사유 문 주제마다 점수기·보정 산출물과 두 문의 문턱이 있음",
        {s.topic for s in config.scorers} == topics
        and {t.topic for t in config.topics} == topics
        and config.gate(GateKind.REQUEST) is not None
        and config.gate(GateKind.INTENT) is not None,
    )
    c.check("앱 기본 판단 계층 설정은 v3", Settings.from_env({}).decision_path.name == "decision_v3.yaml")

    weights = {s.topic: s.weights for s in config.scorers}
    models = Models(
        op=weights[DecisionTopic.CHANGE_OP],
        intent=weights[DecisionTopic.CHANGE_INTENT],
        target=weights[DecisionTopic.TARGET_PART],
    )
    cfg = load_config()
    snapshot = generate(cfg).snapshot
    vocab = MapVocabulary(snapshot)
    lexicon = load_lexicon(Settings.from_env({}).lexicon_path)
    samples = nl_samples(snapshot, NlSplit.SELECTION, 60, cfg.seed, cfg.scenario_date, load_nl_lexicon())
    labeled = read_and_label(samples, vocab, lexicon, models)
    routed = route_all(labeled, config)
    c.check(
        "자동 진행은 자격 있는 단위만, 단위 안 판단은 모두 자동 진행이거나 모두 아님",
        all(r.labeled.reading.proposal.ready for r in routed if r.auto)
        and all(r.auto or not any(a.route is Route.AUTO for a in r.answers) for r in routed),
    )
    reasons = route_intent(labeled, config)
    c.check(
        "사유 문: 단위마다 의도 판단 하나, 자동 기록은 '해당 없음'이 아닌 사유만",
        all(len(r.answers) == 1 for r in reasons) and all(r.answers[0].top != NONE_OPTION for r in reasons if r.auto),
    )
    report = e8_report(routed, config, [1.0] * len(routed))
    c.check(
        "E8 보고: 단위 수·자동 진행 수가 경로와 같음",
        report.units == len(routed) and report.auto_rate.hits == sum(r.auto for r in routed),
    )
    learned, baseline = e3_report(labeled), e3_report(read_and_label(samples, vocab, lexicon, BASELINE_MODELS))
    c.check(
        "E3 보고: 전체 정확도 ≤ 연산 정확도, 학습 점수기 ≥ 규칙 기반 기준선(같은 문장)",
        learned.overall.hits <= learned.op.hits and learned.overall.value >= baseline.overall.value,
        (str(learned.overall), str(baseline.overall)),
    )
