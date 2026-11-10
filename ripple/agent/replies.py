"""차례 응답 만들기: 질문하기 · 초안만 돌려주기 · 분석하기 · 변경 사유 기록하기(docs/input.md(판단 계층) 7절).

질문 ID에는 차례 번호를 붙인다('summary@3'): 지난 차례 화면의 늦은 답이 새 질문에 붙지 않는다.
분석한 차례와 사유를 기록한 차례에는 분석 뒤 변경 사유 질문을 함께 둔다.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.assistant import (
    Answer,
    AssistantTurn,
    ChangeDraft,
    FillMethod,
    Question,
    QuestionKind,
    SlotFill,
    TurnState,
)
from ripple.contracts.change import ChangeIntent
from ripple.contracts.decision import DecisionAnswer, Route
from ripple.contracts.result import VERDICT_NAMES, AnalysisResult
from ripple.engine.analyze import analyze
from ripple.engine.validate import RequestError
from ripple.explain.compose import default_explanation, notifications
from ripple.explain.render import render
from ripple.llm.base import Guarded
from ripple.nl.draft import Proposal

from .errors import AssistantError
from .llm_tasks import pick_explanation
from .questions import reason_question, summarize
from .resources import AssistantResources
from .state import Analysis, Asked, ConversationState

TITLE_MAX = 200  # 비서가 만든 설계변경 제목 길이 상한(문서 접수 제목과 같음)


def asking(
    state: ConversationState,
    draft: ChangeDraft,
    answers: tuple[DecisionAnswer, ...],
    asked: list[Asked],
    resources: AssistantResources,
) -> AssistantTurn:
    number = len(state.turns) + 1
    # 질문 ID는 차례마다 새로('summary@3'): 지난 차례 화면의 늦은 답이 새 질문에 붙지 않는다
    scoped = [
        replace(a, question=a.question.model_copy(update={"question_id": f"{a.question.question_id}@{number}"}))
        for a in asked
    ]
    state.asked = {a.question.question_id: a for a in scoped}
    message = f"확인할 항목 {len(asked)}개" if len(asked) > 1 else "확인할 항목 하나 · 답하면 이 내용대로 분석"
    return AssistantTurn(
        conversation_id=state.conversation_id,
        turn=number,
        state=TurnState.ASKING,
        message=message,
        interpreter=_interpreter(state),
        draft=draft,
        summary=_summary(draft, resources),
        questions=tuple(a.question for a in scoped),
        decisions=answers,
    )


def drafted(
    state: ConversationState, draft: ChangeDraft, answers: tuple[DecisionAnswer, ...], resources: AssistantResources
) -> AssistantTurn:
    """초안만(문서 접수 항목 고치기): 분석하지 않고 다 채운 초안을 돌려준다. 확정·분석은 확인표가 한다."""
    number = len(state.turns) + 1
    return AssistantTurn(
        conversation_id=state.conversation_id,
        turn=number,
        state=TurnState.DRAFTED,
        message="고친 내용 확인표로 반환",
        interpreter=_interpreter(state),
        draft=draft,
        summary=_summary(draft, resources),
        decisions=answers,
    )


def analyzed(
    state: ConversationState,
    proposal: Proposal,
    answers: tuple[DecisionAnswer, ...],
    reason: DecisionAnswer,
    resources: AssistantResources,
    llm: Guarded | None,
) -> AssistantTurn:
    """조립해 분석하고 설명·알림 초안을 붙인다. 지도와 맞지 않는 요청이면 다시 적어 달라고 묻는다."""
    draft = proposal.draft
    if draft.intent is None and reason.route is Route.AUTO and reason.top in {i.value for i in ChangeIntent}:
        # 사유 문이 자동 진행이면 판단한 사유를 바로 기록한다(아니면 사유 미정으로 분석하고 분석 뒤에 묻는다)
        draft = draft.model_copy(update={"intent": SlotFill(value=reason.top, method=FillMethod.DECISION)})
    number = len(state.turns) + 1
    change = draft.to_change(ecn_id=f"ECN-AI-{state.conversation_id[-6:]}-{number}", title=_title(draft, resources))
    change = change.model_copy(update={"raw_text": state.text})  # 다시 쓴 문장이 아니라 사용자 원문
    context = state.context
    request = AnalysisRequest(
        change=change, as_of=context.as_of, confirm_on=context.confirm_on, horizon_days=context.horizon_days
    )
    try:
        result = analyze(resources.index, request, resources.rulebook, resources.params)
    except RequestError as error:
        question = Question(
            question_id="text",
            kind=QuestionKind.RESTATE,
            target="text",
            prompt="요청이 연결 지도와 불일치 · 고쳐서 다시 입력",
            reason=" ".join(error.problems),
        )
        return asking(state, draft, answers, [Asked(question=question)], resources)
    directory = resources.directory
    picked = pick_explanation(llm, result, directory) if llm else None
    explanation = render(picked, result, directory) if picked else None
    if explanation is None:
        explanation = render(default_explanation(result), result, directory)
    notices = notifications(result, directory)
    state.analysis = Analysis(draft, request, result, explanation, notices, reason)
    verdict = VERDICT_NAMES[result.verdict.level]
    return AssistantTurn(
        conversation_id=state.conversation_id,
        turn=number,
        state=TurnState.ANALYZED,
        message=f"분석 완료 · 판정 '{verdict}'",
        interpreter=_interpreter(state),
        draft=draft,
        summary=_summary(draft, resources, analyzed=True),
        decisions=answers,
        request=request,
        result=result,
        explanation=explanation,
        notifications=notices,
        follow_ups=(_ask_reason(state, number, reason, change.intent),),
    )


def record_reason(
    state: ConversationState, asked: Asked, answer: Answer, resources: AssistantResources
) -> AssistantTurn:
    """변경 사유 답: 마지막 분석의 요청과 결과 안 요청에 사유만 넣는다.

    다시 해석·조립·분석하지 않으므로 결과·분석 ID·확정일·보류가 그대로다(답을 보낼 때의 화면 맥락은 쓰지 않는다).
    """
    analysis = state.analysis
    if analysis is None:
        raise AssistantError("사유를 기록할 분석 없음 · 처음부터 다시 입력")
    labels = {o.option_id: o.label for o in asked.question.options}
    value = answer.option_id
    if value is None and answer.text is not None:
        matched = [v for v, label in labels.items() if label in answer.text or v in answer.text]
        value = matched[0] if len(matched) == 1 else None
    if value is None or value not in labels:
        raise AssistantError("보여 준 사유에서 선택 필요")
    intent = ChangeIntent(value)
    change = analysis.request.change.model_copy(update={"intent": intent})
    request = AnalysisRequest.model_validate({**analysis.request.model_dump(), "change": change.model_dump()})
    result = AnalysisResult.model_validate({**analysis.result.model_dump(), "request": request.model_dump()})
    draft = analysis.draft.model_copy(update={"intent": SlotFill(value=intent.value, method=FillMethod.USER)})
    state.fixed_intent = intent.value
    state.analysis = replace(analysis, draft=draft, request=request, result=result)
    number = len(state.turns) + 1
    return AssistantTurn(
        conversation_id=state.conversation_id,
        turn=number,
        state=TurnState.ANALYZED,
        message=f"변경 사유 기록됨 · {labels[value]}",
        interpreter=_interpreter(state),
        draft=draft,
        summary=_summary(draft, resources, analyzed=True),
        request=request,
        result=result,
        explanation=analysis.explanation,
        notifications=analysis.notifications,
        follow_ups=(_ask_reason(state, number, analysis.intent, intent),),
        reason_recorded=True,
    )


def _ask_reason(
    state: ConversationState, number: int, reason: DecisionAnswer, recorded: ChangeIntent | None
) -> Question:
    """분석 뒤 변경 사유 질문을 이 차례에 묶어 둔다(지난 차례의 늦은 답은 받지 않는다)."""
    question = reason_question(reason, recorded)
    question = question.model_copy(update={"question_id": f"{question.question_id}@{number}"})
    state.asked = {question.question_id: Asked(question=question)}
    return question


def _title(draft: ChangeDraft, resources: AssistantResources) -> str:
    """ECN 제목: 요약에서 사유만 뺀 것('두께 변경 · No.3 COT 횡격벽 판 7 · 15mm → 17mm') — 목록·결재함·리포트에서
    제목만 보고도 무엇을 얼마로 바꾸는지 알게(앞 두 조각만이면 값이 빠진다). 부재가 많으면 문서 접수와 같은
    200자에서 자른다."""
    title = summarize(draft, resources, reason=False)
    return title if len(title) <= TITLE_MAX else title[: TITLE_MAX - 1] + "…"


def _summary(draft: ChangeDraft, resources: AssistantResources, analyzed: bool = False) -> str | None:
    """이해한 변경 한 줄. 연산을 아직 못 정했으면 없다. 분석했는데 사유가 없으면 '사유 미정'까지."""
    return summarize(draft, resources, unrecorded=analyzed) or None if draft.op is not None else None


def _interpreter(state: ConversationState) -> Literal["rule", "rule+llm"]:
    return "rule+llm" if state.llm_used else "rule"
