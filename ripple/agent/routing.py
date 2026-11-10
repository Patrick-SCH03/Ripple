"""판단 경로(docs/input.md(판단 계층) 3절): 해석한 판단들을 보정 확률·자격으로 자동 진행·확인·고르기·다시 설명에 보낸다.

요청 문(연산·대상)과 사유 문(의도)을 따로 판단한다. 보정 산출물이 없으면 자동 진행 없이 최상위를 확인받는다.
"""

from __future__ import annotations

from ripple.contracts.decision import (
    GATE_TOPICS,
    NONE_OPTION,
    ChoiceQuestion,
    DecisionAnswer,
    DecisionBackend,
    DecisionConfig,
    Gate,
    GateKind,
    Route,
)
from ripple.decide.calibration import softmax
from ripple.decide.conformal import ranked
from ripple.decide.router import decide_unit
from ripple.nl.draft import Proposal
from ripple.nl.pipeline import Reading


def route_request(
    decision: DecisionConfig, reading: Reading, proposal: Proposal
) -> tuple[tuple[DecisionAnswer, ...], bool]:
    """요청 문 경로: 판단마다의 답과, 모두 자동 진행인지(초안 자격까지 본 단위 판단)."""
    gate = decision.gate(GateKind.REQUEST) or Gate(kind=GateKind.REQUEST, auto_threshold=None, n_units=0, split="-")
    calibrations = {t.topic: t for t in decision.topics if t.topic in GATE_TOPICS[GateKind.REQUEST]}
    items = [(d.posed.question, d.scores) for d in reading.decisions()]
    if len(calibrations) < len(GATE_TOPICS[GateKind.REQUEST]):
        return uncalibrated(items), False
    answers = decide_unit(
        items, calibrations, gate, decision.targets.max_choices, decision.version, ready=proposal.ready
    )
    return answers, all(a.route is Route.AUTO for a in answers)


def route_reason(decision: DecisionConfig, reading: Reading) -> DecisionAnswer:
    """사유 문 경로: 의도 판단 하나(분석 뒤 기록이라 초안 자격과 무관). 보정이 없으면 묻는다."""
    gate = decision.gate(GateKind.INTENT)
    calibrations = {t.topic: t for t in decision.topics if t.topic in GATE_TOPICS[GateKind.INTENT]}
    item = (reading.intent.posed.question, reading.intent.scores)
    if gate is None or len(calibrations) < len(GATE_TOPICS[GateKind.INTENT]):
        return uncalibrated([item])[0]
    return decide_unit([item], calibrations, gate, decision.targets.max_choices, decision.version)[0]


def uncalibrated(items: list[tuple[ChoiceQuestion, dict[str, float]]]) -> tuple[DecisionAnswer, ...]:
    """보정 산출물이 없으면(판단 계층 v0) 자동 진행 없이 최상위를 확인받는다(온도 1, 집합 = 최상위)."""
    answers = []
    for question, scores in items:
        ids = question.option_ids
        probs = dict(zip(ids, softmax([scores[i] for i in ids]), strict=True))
        top = ranked(probs)[0][0]
        answers.append(
            DecisionAnswer(
                question_id=question.question_id,
                topic=question.topic,
                probabilities=probs,
                top=top,
                prediction_set=(top,),
                route=Route.RESTATE if top == NONE_OPTION else Route.CONFIRM,
                backend=DecisionBackend.LOCAL,
                policy_version="uncalibrated",
            )
        )
    return tuple(answers)
