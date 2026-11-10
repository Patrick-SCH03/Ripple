"""판단 계층 보정(docs/input.md(판단 계층) 3·4절).

학습 분할로 주제별 로컬 점수기를 학습하고(정답 연산으로 질문), 온도 분할로 온도·검정할 문턱 목록,
τ 분할로 요청 문의 자동 진행 문턱, 집합 분할로 주제별 되묻기 집합 q̂를 정해 판단 계층 설정 새 판을 쓴다.
개발 중 점검은 선택 분할에서만 한다(E8 사전 점검 + E3 해석 정확도). 평가 분할 최종 인증은 --certify로
한 번만 한다.

실행: uv run python scripts/calibrate_decision.py [--out params/decision_v3.yaml]
      [--report eval/decision/v3_selection.md]
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import yaml

from ripple.config.loaders import load_decision_config, load_lexicon
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.dataset import EcnSplit, NlSample, NlSplit
from ripple.contracts.decision import (
    DecisionBackend,
    DecisionConfig,
    DecisionTopic,
    GateKind,
    ScorerModel,
)
from ripple.decide.policy import Splits, calibrate_gate
from ripple.decide.router import decide_unit
from ripple.decide.scorer import train
from ripple.eval.decision_metrics import (
    BASELINE_MODELS,
    E3Report,
    E8Report,
    IntentReport,
    e3_report,
    e8_report,
    intent_report,
    route_all,
    route_intent,
)
from ripple.eval.nl_labels import Labeled, read_and_label, training_examples
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.generator.nl import load_nl_lexicon, nl_samples, nl_samples_for_ecns
from ripple.nl.pipeline import Models, read
from ripple.nl.vocab import MapVocabulary

SIZES = {
    NlSplit.TRAIN: 2000,
    NlSplit.TEMPERATURE: 1500,
    NlSplit.SELECTION: 500,
    NlSplit.TAU: 2000,
    NlSplit.SET: 1500,
    NlSplit.EVAL: 1500,
}
MIN_SET_UNITS = 300  # 집합 분할: 필터 뒤 단위 300+ (모자라면 더 만든다)
MAX_SET_SIZE = 6000
ITERATIONS = 300


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="판단 계층 보정과 사전 점검")
    parser.add_argument("--targets", type=Path, default=PROJECT_ROOT / "params" / "decision_v0.yaml")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "params" / "decision_v3.yaml")
    parser.add_argument("--version", default="decision-v3")
    parser.add_argument("--report", type=Path, default=PROJECT_ROOT / "eval" / "decision" / "v3_selection.md")
    parser.add_argument("--certify", action="store_true", help="평가 분할 최종 인증(한 번만)")
    args = parser.parse_args(argv)
    if sys.stdout.encoding.lower() != "utf-8" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    settings = Settings.from_env({})
    base = load_decision_config(args.targets)  # 합격 기준을 보기 전에 고정한 목표값
    cfg = load_config()
    generated = generate(cfg)
    snapshot = generated.snapshot
    vocab = MapVocabulary(snapshot)
    lexicon = load_lexicon(settings.lexicon_path)
    surface = load_nl_lexicon()
    ships = (snapshot.ships[0].ship_id,)

    def samples(split: NlSplit, count: int) -> tuple[NlSample, ...]:
        return nl_samples(snapshot, split, count, cfg.seed, cfg.scenario_date, surface)

    started = time.perf_counter()
    train_samples = samples(NlSplit.TRAIN, SIZES[NlSplit.TRAIN])
    teacher = read_and_label(train_samples, vocab, lexicon, BASELINE_MODELS, teacher=True)
    examples = training_examples(teacher)
    train_hash = _digest(train_samples)
    scorers = tuple(
        ScorerModel(
            topic=topic,
            backend=DecisionBackend.LOCAL,
            weights=train(data, iterations=ITERATIONS),
            n_train=len(data),
            train_split=train_hash,
        )
        for topic, data in examples.items()
    )
    models = _models(scorers)
    print(f"점수기 학습: {', '.join(f'{s.topic.value} {s.n_train}건' for s in scorers)} ({_since(started)})")

    def units(split: NlSplit, count: int) -> tuple[list[Labeled], str]:
        chosen = samples(split, count)
        return read_and_label(chosen, vocab, lexicon, models), _digest(chosen)

    temperature, temperature_hash = units(NlSplit.TEMPERATURE, SIZES[NlSplit.TEMPERATURE])
    tau, tau_hash = units(NlSplit.TAU, SIZES[NlSplit.TAU])
    set_size = SIZES[NlSplit.SET]
    while True:
        set_labeled, set_hash = units(NlSplit.SET, set_size)
        splits = Splits(temperature=temperature_hash, tau=tau_hash, set=set_hash)
        gate, request_topics = calibrate_gate(
            GateKind.REQUEST,
            DecisionBackend.LOCAL,
            base.targets,
            [x.unit() for x in temperature],
            [x.unit() for x in tau],
            [x.unit() for x in set_labeled],
            splits,
        )
        # 변경 사유는 분석 뒤에 정한다: 사유 문(의도 판단 하나)을 따로 보정해 자동 기록 문턱·되묻기 집합을 정한다
        intent_gate, intent_topics = calibrate_gate(
            GateKind.INTENT,
            DecisionBackend.LOCAL,
            base.targets,
            [x.intent_unit() for x in temperature],
            [x.intent_unit() for x in tau],
            [x.intent_unit() for x in set_labeled],
            splits,
        )
        calibrations = (*request_topics, *intent_topics)
        # 집합을 보이는 판단이 아예 없는 주제(늘 확신하는 연산 등)는 q̂ = 1(보수값)로 두고 표본을 늘리지 않는다
        short = [c for c in calibrations if 0 < c.n_set < MIN_SET_UNITS]
        if not short or set_size >= MAX_SET_SIZE:
            break
        set_size = min(MAX_SET_SIZE, set_size * 2)
        print(f"집합 분할 필터 뒤 단위가 모자라 {set_size}건으로 늘려요: {[(c.topic.value, c.n_set) for c in short]}")
    config = DecisionConfig(
        version=args.version,
        updated=date.today(),
        targets=base.targets,
        scorers=scorers,
        topics=calibrations,
        gates=(gate, intent_gate),
    )
    _write_config(args.out, config, train_hash, temperature_hash, tau_hash, set_hash)
    sets = [(c.topic.value, c.n_set) for c in calibrations]
    taus = f"τ = {gate.auto_threshold}, 사유 τ = {intent_gate.auto_threshold}"
    print(f"보정 산출물: {taus}, 집합 단위 {sets} ({_since(started)})")
    print(f"썼어요: {args.out}")

    split = NlSplit.EVAL if args.certify else NlSplit.SELECTION
    checked = samples(split, SIZES[split])
    e8, latencies = _e8(checked, vocab, lexicon, models, config)
    intent = intent_report(route_intent(read_and_label(checked, vocab, lexicon, models), config))
    ecn_dev = [e for e in generated.ecns if e.split is EcnSplit.DEV]
    history = nl_samples_for_ecns(snapshot, ecn_dev, NlSplit.ECN_DEV, cfg.seed, surface)
    e3 = {
        "학습 점수기": e3_report(read_and_label(history, vocab, lexicon, models)),
        "규칙 기반 기준선": e3_report(read_and_label(history, vocab, lexicon, BASELINE_MODELS)),
    }
    e3_split = {
        "학습 점수기": e3_report(read_and_label(checked, vocab, lexicon, models)),
        "규칙 기반 기준선": e3_report(read_and_label(checked, vocab, lexicon, BASELINE_MODELS)),
    }
    del ships  # 호선은 문장 사례가 가진다
    report = _report(config, split, e8, intent, e3, e3_split, len(checked), len(history), latencies, surface.version)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8", newline="\n")
    print(report)
    print(f"썼어요: {args.report} ({_since(started)})")
    return 0


def _models(scorers: Sequence[ScorerModel]) -> Models:
    weights = {s.topic: s.weights for s in scorers}
    return Models(
        op=weights[DecisionTopic.CHANGE_OP],
        intent=weights[DecisionTopic.CHANGE_INTENT],
        target=weights[DecisionTopic.TARGET_PART],
    )


def _e8(
    samples: Sequence[NlSample], vocab: MapVocabulary, lexicon: object, models: Models, config: DecisionConfig
) -> tuple[E8Report, list[float]]:
    """읽기 + 경로 정하기 시간을 문장마다 재고 E8 지표를 낸다."""
    from ripple.contracts.lexicon import Lexicon

    assert isinstance(lexicon, Lexicon)
    gate = config.gate(GateKind.REQUEST)
    intent_gate = config.gate(GateKind.INTENT)
    assert gate is not None and intent_gate is not None
    calibrations = {t.topic: t for t in config.topics}
    latencies = []
    for sample in samples:
        started = time.perf_counter()
        reading = read(sample.text, (sample.ship_id,), vocab, lexicon, models)
        items = [(d.posed.question, d.scores) for d in reading.decisions()]
        decide_unit(items, calibrations, gate, config.targets.max_choices, config.version, ready=reading.proposal.ready)
        intent = [(reading.intent.posed.question, reading.intent.scores)]
        decide_unit(intent, calibrations, intent_gate, config.targets.max_choices, config.version)
        latencies.append((time.perf_counter() - started) * 1000)
    labeled = read_and_label(samples, vocab, lexicon, models)
    return e8_report(route_all(labeled, config), config, latencies), latencies


def _report(
    config: DecisionConfig,
    split: NlSplit,
    e8: E8Report,
    intent: IntentReport,
    e3: dict[str, E3Report],
    e3_split: dict[str, E3Report],
    n_split: int,
    n_history: int,
    latencies: Sequence[float],
    lexicon_version: str,
) -> str:
    gate = config.gate(GateKind.REQUEST)
    intent_gate = config.gate(GateKind.INTENT)
    lines = [
        f"# 판단 계층 {config.version} — {'평가 분할 최종 인증' if split is NlSplit.EVAL else '선택 분할 사전 점검'}",
        "",
        f"작성 {config.updated.isoformat()}. `scripts/calibrate_decision.py`가 만든다. "
        f"합성 문장(생성기 {lexicon_version}) 기준이며 실제 현장 문장과 분포가 다를 수 있다"
        "(사람이 쓴 문장 40건 점검은 아직).",
        "",
        "## 보정 산출물",
        "",
        f"- 요청 문(대상·연산) 자동 진행 문턱 τ = {gate.auto_threshold if gate else None} "
        f"(τ 분할 {gate.n_units if gate else 0}단위)",
        f"- 사유 문(변경 사유, 분석 뒤 기록) 자동 기록 문턱 τ = {intent_gate.auto_threshold if intent_gate else None}",
    ]
    for t in config.topics:
        lines.append(
            f"- {t.topic.value}: 온도 {t.temperature:.3f}, q̂ {t.set_qhat:.4f} "
            f"(온도 {t.n_temperature}건, 집합 {t.n_set}단위)"
        )
    for s in config.scorers:
        lines.append(f"- 점수기 {s.topic.value}: 특징 {len(s.weights)}개, 학습 {s.n_train}건")
    lines += [
        "",
        f"## E8 ({split.value} 분할 {n_split}문장)",
        "",
        "| 지표 | 값 | 기준 | 통과 |",
        "|---|---|---|---|",
    ]
    for name, value, threshold, passed in e8.criteria():
        mark = "—" if passed is None else ("통과" if passed else "미달")
        lines.append(f"| {name} | {value} | {threshold} | {mark} |")
    lines += [
        "",
        "변경 사유는 요청 문에 들지 않는다(분석 먼저, 사유는 뒤에). 사유 문은 분석 뒤 자동 기록"
        "하거나 묻는다(기준 없음, 기록용):",
        "",
        "| 지표 | 값 |",
        "|---|---|",
        *(f"| {name} | {value} |" for name, value in intent.rows()),
        "",
        f"지연: 읽기(해석·후보·점수) + 경로 정하기(요청 문·사유 문), 문장 {len(latencies)}개 중앙값 "
        f"{sorted(latencies)[len(latencies) // 2]:.1f}ms"
        if latencies
        else "",
        "",
        "## E3 자연어 해석 정확도(변경 사유 제외: 연산·대상·값)",
        "",
        "| 자료 | 해석기 | 연산 | 대상 | 값 | 전체 |",
        "|---|---|---|---|---|---|",
    ]
    for label, reports in (
        (f"설계변경 이력 개발 {n_history}건 문장", e3),
        (f"{split.value} 분할 {n_split}문장", e3_split),
    ):
        for name, r in reports.items():
            lines.append(f"| {label} | {name} | {r.op} | {r.targets} | {r.values} | {r.overall} |")
    lines += [
        "",
        "- 전체 = 연산·대상 부재·나머지 슬롯(값·규격·블록·역할 부재)을 모두 맞힌 문장. "
        "추정(확인 카드)으로 낸 값도 맞으면 셈.",
        "- 규칙 기반 기준선: 대상은 결정적 일치(코드·사전 유일 일치)만, 연산·의도는 사전 단서 수로 고른다.",
    ]
    return "\n".join(lines) + "\n"


def _write_config(path: Path, config: DecisionConfig, *hashes: str) -> None:
    body = config.model_dump(mode="json")
    header = (
        f"# 판단 계층 보정 산출물 {config.version} — 형식: ripple/contracts/decision.py, "
        "설계: docs/input.md(판단 계층)\n"
        "# scripts/calibrate_decision.py가 만든다(손으로 고치지 않는다). 목표값(targets)은 decision_v0.yaml과 같다.\n"
        f"# 자료 해시(학습·온도·τ·집합): {', '.join(hashes)}\n"
    )
    path.write_text(header + yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")


def _digest(samples: Sequence[NlSample]) -> str:
    data = b"".join(s.model_dump_json().encode("utf-8") + b"\n" for s in samples)
    return f"NL-{hashlib.sha256(data).hexdigest()[:16]}"


def _since(started: float) -> str:
    return f"{time.perf_counter() - started:.0f}초"


if __name__ == "__main__":
    sys.exit(main())
