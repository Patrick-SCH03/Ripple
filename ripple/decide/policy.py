"""보정 산출물 만들기: 주제별 온도 → 문의 자동 진행 문턱 τ → 주제별 되묻기 집합 q̂(docs/input.md(판단 계층) 3·4절).

세 단계는 서로 다른 분할을 쓴다. 온도 분할은 온도와 검정할 문턱 목록을 정하고, τ 분할은 단위
(요청·열) 술어 그대로 검정하며, 집합 분할은 τ를 고정한 뒤 실제로 집합을 보여 줄 판단만으로 q̂를 구한다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ripple.contracts.decision import (
    GATE_TOPICS,
    NONE_OPTION,
    DecisionBackend,
    DecisionTargets,
    DecisionTopic,
    Gate,
    GateKind,
    TopicCalibration,
)

from .calibration import fit_temperature, softmax
from .conformal import conformal_qhat, ranked
from .risk import TopOutcome, auto_predicate, ltt_threshold, threshold_grid


@dataclass(frozen=True, slots=True)
class ScoredCase:
    """점수기가 낸 선택지별 점수와 정답. option_ids와 scores는 같은 순서다."""

    option_ids: tuple[str, ...]
    scores: tuple[float, ...]
    label: str

    def __post_init__(self) -> None:
        if len(self.option_ids) != len(self.scores):
            raise ValueError("선택지와 점수의 개수가 다름")
        if NONE_OPTION not in self.option_ids or self.label not in self.option_ids:
            raise ValueError("선택지에 '해당 없음'과 정답 필요")


@dataclass(frozen=True, slots=True)
class Decision:
    """단위 안의 판단 하나."""

    topic: DecisionTopic
    case: ScoredCase


@dataclass(frozen=True, slots=True)
class Unit:
    """자동 진행 단위: 요청 문이면 변경 요청 하나의 판단들, 열 문이면 엑셀 열 판단 하나.

    ready: 판단 밖 자동 진행 자격(값이 결정적이고 모든 슬롯이 채워짐, ChangeDraft.ready). 정답을 보지
           않고 정하므로 선택 규칙으로 쓸 수 있다. 보정·라우터·평가가 같은 값을 쓴다.
    sound: 판단 밖 부분이 정답과 같음(조립한 요청의 나머지 슬롯, 빠진 표현 없음). 보정 자료에서만 안다.
    """

    decisions: tuple[Decision, ...]
    ready: bool = True
    sound: bool = True

    def __post_init__(self) -> None:
        if not self.decisions:
            raise ValueError("판단 없는 단위")


@dataclass(frozen=True, slots=True)
class Splits:
    """보정에 쓴 분할 자료의 해시."""

    temperature: str
    tau: str
    set: str


def probabilities(case: ScoredCase, temperature: float) -> dict[str, float]:
    return dict(zip(case.option_ids, softmax(case.scores, temperature), strict=True))


def unit_outcome(unit: Unit, temperatures: Mapping[DecisionTopic, float]) -> TopOutcome:
    """단위 신뢰도 = 판단 최상위 확률의 최솟값, 정답 = 모든 판단이 정답이고 판단 밖도 정답,
    후보 = 판단 밖 자격이 있고 '해당 없음' 최상위가 없음."""
    tops = [ranked(probabilities(d.case, temperatures[d.topic]))[0] for d in unit.decisions]
    return TopOutcome(
        top_prob=min(p for _, p in tops),
        correct=unit.sound and all(top == d.case.label for (top, _), d in zip(tops, unit.decisions, strict=True)),
        eligible=unit.ready and all(top != NONE_OPTION for top, _ in tops),
    )


def shows_set(top: str, top_prob: float, unit_auto: bool, threshold: float | None) -> bool:
    """집합을 보여 줄 판단: 단위가 자동 진행이 아니고, 자신이 '해당 없음'이 최상위이거나 확신이 문턱 미만.

    보정(calibrate_gate)과 라우터(router.decide_unit)가 같은 정의를 쓴다.
    """
    return not unit_auto and not auto_predicate(top != NONE_OPTION, top_prob, threshold)


def calibrate_gate(
    kind: GateKind,
    backend: DecisionBackend,
    targets: DecisionTargets,
    temperature_units: Sequence[Unit],
    tau_units: Sequence[Unit],
    set_units: Sequence[Unit],
    splits: Splits,
) -> tuple[Gate, tuple[TopicCalibration, ...]]:
    topics = GATE_TOPICS[kind]
    by_topic = {topic: [d.case for u in temperature_units for d in u.decisions if d.topic is topic] for topic in topics}
    if not all(by_topic.values()) or any(d.topic not in topics for u in temperature_units for d in u.decisions):
        raise ValueError(f"{kind} 문의 온도 분할에는 이 문의 주제만, 주제마다 하나 이상 필요")
    temperatures = {
        topic: fit_temperature([(c.scores, c.option_ids.index(c.label)) for c in cases])
        for topic, cases in by_topic.items()
    }
    grid = threshold_grid(
        [o.top_prob for o in (unit_outcome(u, temperatures) for u in temperature_units) if o.eligible],
        targets.coverage_levels,
    )
    threshold = ltt_threshold(
        [unit_outcome(u, temperatures) for u in tau_units],
        grid,
        targets.epsilon[kind],
        targets.delta,
    )
    gate = Gate(kind=kind, auto_threshold=threshold, n_units=len(tau_units), split=splits.tau)

    # 단위 안의 같은 주제 판단은 서로 상관될 수 있으므로 단위마다 점수 하나(정답 확률의 최솟값)만 쓴다.
    # 그러면 '단위 안에서 집합을 보여 준 그 주제 판단이 모두 정답을 포함할 확률 ≥ 1 − α'가 성립한다.
    shown: dict[DecisionTopic, list[float]] = {topic: [] for topic in topics}
    for unit in set_units:
        outcome = unit_outcome(unit, temperatures)
        unit_auto = auto_predicate(outcome.eligible, outcome.top_prob, threshold)
        worst: dict[DecisionTopic, float] = {}
        for decision in unit.decisions:
            probs = probabilities(decision.case, temperatures[decision.topic])
            top, top_prob = ranked(probs)[0]
            if shows_set(top, top_prob, unit_auto, threshold):
                label_prob = probs[decision.case.label]
                worst[decision.topic] = min(label_prob, worst.get(decision.topic, label_prob))
        for topic, label_prob in worst.items():
            shown[topic].append(label_prob)
    calibrations = tuple(
        TopicCalibration(
            topic=topic,
            backend=backend,
            temperature=temperatures[topic],
            set_qhat=conformal_qhat(shown[topic], targets.alpha),
            n_temperature=len(by_topic[topic]),
            n_set=len(shown[topic]),
            temperature_split=splits.temperature,
            set_split=splits.set,
        )
        for topic in topics
    )
    return gate, calibrations
