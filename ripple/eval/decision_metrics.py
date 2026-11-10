"""판단 계층 지표(E8)와 자연어 해석 정확도(E3).

E8(docs/input.md(판단 계층) 5절): 후보 재현율, 대상 특정 최상위 정확도(전체 입력), 자동 진행 단위 정확도
(단측 95% Clopper–Pearson 하한), 자동 진행 비율, 되묻기 집합 포함률(주제마다, 하한), 고르기 집합 평균 크기,
ECE(15구간), 로컬 판단 지연 p95.
E3(docs/evaluation.md): 연산·대상·값을 모두 맞힌 문장 비율(의도 제외). 기준선은 규칙 기반 해석기 — 대상은 결정적
일치만, 연산·의도는 사전 단서 수로 고른다(BASELINE_MODELS).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ripple.contracts.assistant import OP_SLOTS
from ripple.contracts.decision import (
    GATE_TOPICS,
    DecisionAnswer,
    DecisionConfig,
    DecisionTopic,
    GateKind,
    Route,
)
from ripple.decide.metrics import expected_calibration_error
from ripple.decide.policy import shows_set
from ripple.decide.risk import clopper_pearson_lower
from ripple.decide.router import decide_unit
from ripple.nl.pipeline import Models

from .nl_labels import Labeled

BASELINE_MODELS = Models(
    op={"cue": 1.0, "none:bias": 0.5},
    intent={"cue": 1.0, "none:bias": 0.5},
    target={"det": 1.0, "none:bias": 0.5},
)
"""규칙 기반 해석기(E3 기준선): 대상은 결정적 일치(코드·사전 유일 일치)만, 연산·의도는 사전 단서 수."""


@dataclass(frozen=True, slots=True)
class Ratio:
    hits: int
    total: int

    @property
    def value(self) -> float:
        return self.hits / self.total if self.total else math.nan

    def lower(self, confidence: float = 0.95) -> float:
        return clopper_pearson_lower(self.hits, self.total, confidence) if self.total else 0.0

    def __str__(self) -> str:
        return f"{self.hits}/{self.total} = {self.value:.3f}" if self.total else "0/0"


@dataclass(frozen=True, slots=True)
class Routed:
    labeled: Labeled
    answers: tuple[DecisionAnswer, ...]

    @property
    def auto(self) -> bool:
        return all(a.route is Route.AUTO for a in self.answers)


def route_all(labeled: Sequence[Labeled], config: DecisionConfig, kind: GateKind = GateKind.REQUEST) -> list[Routed]:
    """보정 산출물로 단위마다 경로를 붙인다(실행 라우터와 같은 함수, 자격은 초안 자격)."""
    gate = config.gate(kind)
    if gate is None:
        raise ValueError(f"{kind} 문의 보정 산출물이 없어요")
    calibrations = {t.topic: t for t in config.topics if t.topic in GATE_TOPICS[kind]}
    routed = []
    for item in labeled:
        reading = item.reading
        items = [(d.posed.question, d.scores) for d in reading.decisions()]
        answers = decide_unit(
            items,
            calibrations,
            gate,
            config.targets.max_choices,
            config.version,
            ready=reading.proposal.ready,
        )
        routed.append(Routed(labeled=item, answers=answers))
    return routed


@dataclass(frozen=True, slots=True)
class E8Report:
    units: int
    candidate_recall: Ratio
    target_top1: Ratio
    auto_correct: Ratio  # 자동 진행 단위 중 정답
    auto_rate: Ratio  # 전체 단위 중 자동 진행
    set_coverage: Mapping[DecisionTopic, Ratio]
    choose_size: float | None
    ece: Mapping[str, float]
    latency_p95_ms: float | None

    def criteria(self) -> list[tuple[str, str, str, bool | None]]:
        """(지표, 값, 기준, 통과). 표본이 없어 판정할 수 없으면 통과는 None."""
        rows: list[tuple[str, str, str, bool | None]] = [
            ("후보 재현율", str(self.candidate_recall), "≥ 0.98", _at_least(self.candidate_recall.value, 0.98)),
            ("대상 특정 최상위 정확도", str(self.target_top1), "≥ 0.9", _at_least(self.target_top1.value, 0.9)),
            (
                "자동 진행 단위 정확도",
                f"{self.auto_correct} (하한 {self.auto_correct.lower():.3f})",
                "하한 ≥ 0.95",
                _at_least(self.auto_correct.lower(), 0.95) if self.auto_correct.total else None,
            ),
            ("자동 진행 비율", str(self.auto_rate), "≥ 0.7", _at_least(self.auto_rate.value, 0.7)),
        ]
        for topic, ratio in self.set_coverage.items():
            rows.append(
                (
                    f"되묻기 집합 포함률({topic.value})",
                    f"{ratio} (하한 {ratio.lower():.3f})",
                    "하한 ≥ 0.90",
                    _at_least(ratio.lower(), 0.90) if ratio.total else None,
                )
            )
        size = "—" if self.choose_size is None else f"{self.choose_size:.2f}"
        rows.append(("고르기 집합 평균 크기", size, "≤ 3", None if self.choose_size is None else self.choose_size <= 3))
        for name, value in self.ece.items():
            rows.append((f"ECE({name})", f"{value:.4f}", "≤ 0.05", value <= 0.05))
        latency = "—" if self.latency_p95_ms is None else f"{self.latency_p95_ms:.1f}ms"
        rows.append(
            (
                "로컬 판단 지연 p95",
                latency,
                "≤ 50ms",
                None if self.latency_p95_ms is None else self.latency_p95_ms <= 50,
            )
        )
        return rows


def _at_least(value: float, threshold: float) -> bool | None:
    return None if math.isnan(value) else value >= threshold


def e8_report(routed: Sequence[Routed], config: DecisionConfig, latencies_ms: Sequence[float] = ()) -> E8Report:
    gate = config.gate(GateKind.REQUEST)
    threshold = gate.auto_threshold if gate else None
    hits = sum(r.labeled.candidate_hits for r in routed)
    total = sum(r.labeled.candidate_total for r in routed)
    top1 = [
        (a.top == label) for r in routed for a, label in zip(_targets(r.answers), r.labeled.target_labels, strict=True)
    ]
    autos = [r for r in routed if r.auto]
    coverage: dict[DecisionTopic, list[bool]] = {topic: [] for topic in GATE_TOPICS[GateKind.REQUEST]}
    choose_sizes = []
    pooled_p: list[float] = []
    pooled_ok: list[bool] = []
    by_topic: dict[DecisionTopic, tuple[list[float], list[bool]]] = {t: ([], []) for t in coverage}
    for r in routed:
        labels = [r.labeled.op_label, *r.labeled.target_labels]
        worst: dict[DecisionTopic, bool] = {}
        for answer, label in zip(r.answers, labels, strict=True):
            p = answer.probabilities[answer.top]
            pooled_p.append(p)
            pooled_ok.append(answer.top == label)
            by_topic[answer.topic][0].append(p)
            by_topic[answer.topic][1].append(answer.top == label)
            if not r.auto and shows_set(answer.top, p, False, threshold):
                worst[answer.topic] = worst.get(answer.topic, True) and label in answer.prediction_set
            if answer.route is Route.CHOOSE:
                choose_sizes.append(len(answer.prediction_set))
        for topic, ok in worst.items():
            coverage[topic].append(ok)
    ece = {"전체": expected_calibration_error(pooled_p, pooled_ok)} if pooled_p else {}
    for topic, (ps, oks) in by_topic.items():
        if ps:
            ece[topic.value] = expected_calibration_error(ps, oks)
    ordered = sorted(latencies_ms)
    p95 = ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)] if ordered else None
    return E8Report(
        units=len(routed),
        candidate_recall=Ratio(hits, total),
        target_top1=Ratio(sum(top1), len(top1)),
        auto_correct=Ratio(sum(r.labeled.correct for r in autos), len(autos)),
        auto_rate=Ratio(len(autos), len(routed)),
        set_coverage={t: Ratio(sum(v), len(v)) for t, v in coverage.items()},
        choose_size=sum(choose_sizes) / len(choose_sizes) if choose_sizes else None,
        ece=ece,
        latency_p95_ms=p95,
    )


@dataclass(frozen=True, slots=True)
class IntentReport:
    """사유 문: 분석 뒤 바로 기록한 비율·정확도, 묻는 경우 예측 집합 포함률."""

    units: int
    auto_rate: Ratio
    auto_correct: Ratio
    set_coverage: Ratio

    def rows(self) -> list[tuple[str, str]]:
        return [
            ("사유 자동 기록 비율", str(self.auto_rate)),
            ("사유 자동 기록 정확도", f"{self.auto_correct} (하한 {self.auto_correct.lower():.3f})"),
            ("사유를 물을 때 선택지 포함률", f"{self.set_coverage} (하한 {self.set_coverage.lower():.3f})"),
        ]


def route_intent(labeled: Sequence[Labeled], config: DecisionConfig) -> list[Routed]:
    """사유 문 경로(실행 흐름과 같은 함수): 의도 판단 하나, 분석 뒤 기록이라 자격은 늘 참."""
    gate = config.gate(GateKind.INTENT)
    if gate is None:
        raise ValueError("사유 문의 보정 산출물이 없어요")
    calibrations = {t.topic: t for t in config.topics if t.topic in GATE_TOPICS[GateKind.INTENT]}
    return [
        Routed(
            labeled=item,
            answers=decide_unit(
                [(item.reading.intent.posed.question, item.reading.intent.scores)],
                calibrations,
                gate,
                config.targets.max_choices,
                config.version,
            ),
        )
        for item in labeled
    ]


def intent_report(routed: Sequence[Routed]) -> IntentReport:
    autos = [r for r in routed if r.auto]
    asked = [r for r in routed if not r.auto]
    return IntentReport(
        units=len(routed),
        auto_rate=Ratio(len(autos), len(routed)),
        auto_correct=Ratio(sum(r.answers[0].top == r.labeled.intent_label for r in autos), len(autos)),
        set_coverage=Ratio(sum(r.labeled.intent_label in r.answers[0].prediction_set for r in asked), len(asked)),
    )


def _targets(answers: Sequence[DecisionAnswer]) -> list[DecisionAnswer]:
    return [a for a in answers if a.topic is DecisionTopic.TARGET_PART]


@dataclass(frozen=True, slots=True)
class E3Report:
    sentences: int
    op: Ratio
    targets: Ratio  # 대상 부재 슬롯이 있는 연산의 문장
    values: Ratio  # 대상 부재 밖 슬롯(값·규격·블록·역할 부재)을 모두 맞힘
    overall: Ratio  # 연산·대상·값을 모두 맞힘(의도 제외)


def e3_report(labeled: Sequence[Labeled]) -> E3Report:
    op_ok = targets_ok = target_n = values_ok = overall_ok = 0
    for item in labeled:
        truth = item.sample.change.ops[0]
        draft = item.reading.proposal.draft
        truth_fields = {k: v for k, v in truth.model_dump(mode="json").items() if k != "op"}
        filled = {k: _jsonable(v.value) for k, v in draft.slots.items()}
        is_op = draft.op is not None and draft.op.value == truth.op
        names = {s.name for s in OP_SLOTS[truth.op]}
        target_fields = {"part_ids"} & names
        other = names - target_fields
        target_hit = all(_same(filled.get(k), truth_fields.get(k)) for k in target_fields)
        value_hit = all(_same(filled.get(k), truth_fields.get(k)) for k in other)
        op_ok += is_op
        if target_fields:
            target_n += 1
            targets_ok += is_op and target_hit
        values_ok += is_op and value_hit
        overall_ok += is_op and target_hit and value_hit
    n = len(labeled)
    return E3Report(
        sentences=n,
        op=Ratio(op_ok, n),
        targets=Ratio(targets_ok, target_n),
        values=Ratio(values_ok, n),
        overall=Ratio(overall_ok, n),
    )


def _jsonable(value: object) -> object:
    return list(value) if isinstance(value, tuple) else value


def _same(a: object, b: object) -> bool:
    """슬롯 값 비교: 목록은 순서 무관(더하는 스풀 규격은 같은 규격 반복이라 같다), 빈 목록 = 없음."""
    if isinstance(b, list) and not b:
        return a is None or a == []
    if isinstance(a, list) and isinstance(b, list):
        return sorted(map(str, a)) == sorted(map(str, b))
    if isinstance(a, float | int) and isinstance(b, float | int):
        return math.isclose(float(a), float(b), abs_tol=1e-6)
    return a == b
