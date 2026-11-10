"""문장 하나 읽기: 해석 → 연산·의도·대상 질문과 점수 → 최상위로 채운 변경 초안.

판단 경로(자동 진행·확인·고르기·다시 설명)는 정하지 않는다. 보정 확률과 경로는 ripple.decide.router가,
대화는 ripple.agent가 정한다. 같은 함수를 보정 자료 만들기(scripts/calibrate_decision.py)와 실행이 함께
쓴다 — 자동 진행 자격(초안의 ready)이 보정 단위와 실행에서 같은 정의가 되도록.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ripple.contracts.assistant import FillMethod, SlotFill
from ripple.contracts.change import ChangeIntent
from ripple.contracts.decision import NONE_OPTION
from ripple.contracts.lexicon import Lexicon

from .draft import Proposal, build_draft
from .fill_types import TargetPick
from .interpret import Interpretation, interpret
from .questions import Posed, has_op_clue, intent_question, op_question, target_questions
from .vocab import MapVocabulary


@dataclass(frozen=True, slots=True)
class Models:
    """주제별 점수기 가중치(특징 이름 → 가중치)."""

    op: Mapping[str, float]
    intent: Mapping[str, float]
    target: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class Scored:
    posed: Posed
    scores: dict[str, float]  # 선택지 → 점수(보정 전)

    @property
    def top(self) -> str:
        """점수가 가장 큰 선택지(같으면 ID 순, 확률 순위와 같다)."""
        return min(self.scores.items(), key=lambda item: (-item[1], item[0]))[0]


@dataclass(frozen=True, slots=True)
class Fixed:
    """사용자가 정한 것: 연산·의도, 대상 질문 번호 → 부재."""

    op: str | None = None
    intent: str | None = None
    targets: Mapping[int, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Reading:
    interp: Interpretation
    op: Scored
    intent: Scored
    targets: tuple[Scored, ...]
    proposal: Proposal
    # 문장에 연산 단서가 있는가(nl.questions.has_op_clue). 없고 사용자가 정하지 않았으면 초안에 연산을 넣지 않는다
    op_clue: bool = True

    def decisions(self) -> tuple[Scored, ...]:
        """요청 문 단위의 판단들(연산·대상 부재). 변경 사유(의도)는 분석 뒤에 따로 정한다(intent)."""
        return (self.op, *self.targets)


def read(
    text: str,
    ship_ids: tuple[str, ...],
    vocab: MapVocabulary,
    lexicon: Lexicon,
    models: Models,
    fixed: Fixed | None = None,
) -> Reading:
    fixed = fixed or Fixed()
    interp = interpret(text, vocab, lexicon, ship_ids)
    op = _scored(op_question(interp, "op"), models.op)
    clue = has_op_clue(interp)
    op_top = fixed.op or (op.top if clue else NONE_OPTION)
    op_name = None if op_top == NONE_OPTION else op_top
    intent = _scored(intent_question(interp, op_name, "intent"), models.intent)
    targets = tuple(
        _scored(posed, models.target)
        for posed in (target_questions(interp, op_name, vocab, ship_ids, "target#") if op_name else ())
    )
    picks = []
    for index, scored in enumerate(targets):
        assert scored.posed.mention is not None
        chosen = fixed.targets.get(index)
        top = chosen or scored.top
        method = FillMethod.USER if chosen else FillMethod.DECISION
        picks.append(TargetPick(scored.posed.mention, None if top == NONE_OPTION else top, method))
    op_fill = _pick(op_top, FillMethod.USER if fixed.op else FillMethod.DECISION)
    # 사유는 후보(intent)와 기록을 나눈다: 초안에는 사용자가 정한 사유만 넣고, 판단으로 정하는 것은 대화 흐름이 사유 문
    # 보정으로 자동 기록일 때만 넣는다
    intent_fill = _pick(fixed.intent, FillMethod.USER) if fixed.intent else None
    if intent_fill is not None and intent_fill.value not in set(ChangeIntent):
        intent_fill = None
    proposal = build_draft(interp, text, ship_ids, op_fill, intent_fill, picks, vocab)
    return Reading(interp=interp, op=op, intent=intent, targets=targets, proposal=proposal, op_clue=clue)


def _scored(posed: Posed, weights: Mapping[str, float]) -> Scored:
    scores = {
        option: sum(weights.get(name, 0.0) * value for name, value in posed.features[option].items())
        for option in posed.question.option_ids
    }
    return Scored(posed=posed, scores=scores)


def _pick(value: str, method: FillMethod) -> SlotFill | None:
    return None if value == NONE_OPTION else SlotFill(value=value, method=method)
