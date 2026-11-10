"""단위(변경 요청·엑셀 열) 하나의 판단들에 보정된 답과 경로를 붙인다(docs/input.md(판단 계층) 3절의 경로 표)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ripple.contracts.decision import (
    GATE_TOPICS,
    NONE_OPTION,
    ChoiceQuestion,
    DecisionAnswer,
    DecisionTopic,
    Gate,
    Route,
    TopicCalibration,
)

from .calibration import softmax
from .conformal import prediction_set, ranked
from .policy import shows_set
from .risk import auto_predicate

Item = tuple[ChoiceQuestion, Mapping[str, float]]
"""질문 하나와 점수기가 낸 선택지별 점수."""

FALLBACK_CHOICES = 3
"""되묻기 집합에 '해당 없음'만 남았을 때 고르기로 보일 진짜 후보의 최대 수(현장에서는
다시 적기보다 고르기가 편하다). 최상위 진짜 후보의 확률이 FALLBACK_FLOOR 이상이고, 그 확률의 FALLBACK_RATIO 이상인
후보가 이 수 이하일 때만 그 후보들을 '해당 없음'과 함께 보인다. 모형이 '해당 없음'을 확신하거나 후보가 고르게 많으면
고를 근거가 약해 다시 설명을 묻는다. 보이는 집합은 conformal 집합을 포함하므로 포함률 보장은 그대로다.
세 값은 화면 정책이라 보정하지 않는다(docs/input.md(판단 계층) 3절)."""
FALLBACK_FLOOR = 0.01
FALLBACK_RATIO = 0.5


def decide_unit(
    items: Sequence[Item],
    calibrations: Mapping[DecisionTopic, TopicCalibration],
    gate: Gate,
    max_choices: int,
    policy_version: str,
    ready: bool = True,
) -> tuple[DecisionAnswer, ...]:
    """ready는 판단 밖 자동 진행 자격(값 결정성·슬롯 완결성)이다. 보정 단위(policy.Unit.ready)와 같은 정의를 쓴다."""
    if not items:
        raise ValueError("판단 없는 단위")
    probs_list = [_probabilities(question, scores, calibrations, gate) for question, scores in items]
    tops = [ranked(probs)[0] for probs in probs_list]
    unit_auto = auto_predicate(
        ready and all(top != NONE_OPTION for top, _ in tops),
        min(p for _, p in tops),
        gate.auto_threshold,
    )
    answers = []
    for (question, _), probs, (top, top_prob) in zip(items, probs_list, tops, strict=True):
        calibration = calibrations[question.topic]
        chosen: tuple[str, ...]
        if unit_auto:
            route, chosen = Route.AUTO, (top,)
        elif not shows_set(top, top_prob, unit_auto, gate.auto_threshold):
            route, chosen = Route.CONFIRM, (top,)  # 단위는 자동 진행이 아니지만 이 판단은 확신: 미리 채워 확인
        else:
            chosen, route = ask_route(probs, prediction_set(probs, calibration.set_qhat), max_choices)
        answers.append(
            DecisionAnswer(
                question_id=question.question_id,
                topic=question.topic,
                probabilities=probs,
                top=top,
                prediction_set=chosen,
                route=route,
                backend=calibration.backend,
                policy_version=policy_version,
            )
        )
    return tuple(answers)


def ask_route(
    probabilities: Mapping[str, float], chosen: tuple[str, ...], max_choices: int
) -> tuple[tuple[str, ...], Route]:
    """되묻기 경로와 보일 집합. '해당 없음'만 남으면 두드러진 진짜 후보를 더해 고르기로(FALLBACK_CHOICES)."""
    if chosen == (NONE_OPTION,):
        real = [(key, p) for key, p in ranked(probabilities) if key != NONE_OPTION]
        if not real or real[0][1] < FALLBACK_FLOOR:
            return chosen, Route.RESTATE
        near = tuple(key for key, p in real if p >= FALLBACK_RATIO * real[0][1])
        if len(near) > FALLBACK_CHOICES:
            return chosen, Route.RESTATE
        return (NONE_OPTION, *near), Route.CHOOSE
    if len(chosen) > max_choices:
        return chosen, Route.RESTATE
    return chosen, Route.CONFIRM if len(chosen) == 1 else Route.CHOOSE


def _probabilities(
    question: ChoiceQuestion,
    scores: Mapping[str, float],
    calibrations: Mapping[DecisionTopic, TopicCalibration],
    gate: Gate,
) -> dict[str, float]:
    if question.topic not in GATE_TOPICS[gate.kind]:
        raise ValueError(f"{gate.kind} 문에 {question.topic} 판단은 해당 없음")
    calibration = calibrations.get(question.topic)
    if calibration is None or calibration.topic is not question.topic:
        raise ValueError(f"{question.topic} 보정 산출물 없음")
    ids = question.option_ids
    if set(scores) != set(ids):
        raise ValueError("점수는 질문의 선택지마다 하나씩 필요")
    return dict(zip(ids, softmax([scores[i] for i in ids], calibration.temperature), strict=True))
