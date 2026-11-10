"""대화 흐름(docs/input.md(판단 계층) 7절): 단순 상태 기계.

차례마다: 해석(규칙 기반 + 로컬 점수기) → 사용자가 정한 것 반영 → 판단 경로(보정 확률, 자격) → 질문이 남았으면
묻고, 없으면 조립 → 지도 검증(실패 이유는 다시 묻기) → 분석 → 설명·알림 초안.
자동 진행은 요청 문 술어(모든 판단 최상위 ≠ 해당 없음, 단위 신뢰도 ≥ τ, 판단 밖 자격)가 참일 때만이다.
그 밖에는 사용자가 마지막 질문에 답하거나 요약을 확인해야 분석한다(미리 채운 판단의 확인).
변경 사유(의도)는 분석 뒤에 정한다: 사유 문 보정으로 자동 기록이면 바로 기록하고, 아니면 분석한 차례의 분석 뒤
질문으로 묻는다. 사유 답은 마지막 분석에 묶어 사유만 바꾼다(다시 해석·조립·분석하지 않아 결과·분석 ID가 같다).

Assistant는 차례의 순서만 정하는 파사드다. 판단 경로는 routing, 사용자가 정한 것 반영은 overrides, 질문은
questions, 답 읽기·반영은 answers, 차례 응답(질문·초안·분석·사유 기록)은 replies, 대화 상태는 state에 있다.
"""

from __future__ import annotations

from ripple.contracts.assistant import YES, Answer, AssistantTurn, AssistantTurnRequest, Conversation
from ripple.llm.base import Guarded
from ripple.llm.quota import limited_now
from ripple.nl.pipeline import Fixed, Reading, read

from .answers import apply_choice, apply_slot, apply_target
from .errors import AssistantError
from .llm_tasks import rewrite_request, rewrite_wanted
from .overrides import as_llm, seeded_overrides, with_overrides
from .questions import REASON_KEY, build_questions, summary_question
from .replies import analyzed, asking, drafted, record_reason
from .resources import AssistantResources
from .routing import route_reason, route_request
from .state import Asked, ConversationState, ConversationStore

__all__ = ["Assistant", "AssistantError", "question_key"]


class Assistant:
    def __init__(
        self,
        resources: AssistantResources,
        store: ConversationStore | None = None,
        llm: Guarded | None = None,
    ) -> None:
        """llm: 데이터 모드 경계 뒤의 생성 모델(없거나 real 모드면 규칙 기반·기본 설명만)."""
        self.resources = resources
        self.store = store or ConversationStore()
        self.llm = llm

    # ---------- 진입점 ----------

    def turn(self, request: AssistantTurnRequest) -> AssistantTurn:
        """한 차례. 같은 대화의 차례는 잠금으로 하나씩 처리한다(답 확인과 반영 사이에 다른 요청이 끼지 않게)."""
        state = self.store.get(request.conversation_id) if request.conversation_id else None
        fresh = state is None
        if state is None:
            if request.message is None:
                raise AssistantError("대화 없음 · 처음부터 다시 입력")
            state = ConversationState(
                conversation_id=self.store.new_id(),
                context=request.context,
                text=request.message,
                draft_only=request.draft_only,
            )
            if request.seed is not None:  # 문서 접수 항목: 확인표에서 이미 정한 연산·슬롯 값(사용자가 정한 것)
                state.fixed_op = request.seed.fixed_op
                state.overrides = seeded_overrides(request, self.resources.vocab)
        with state.lock:
            saved = state.save()
            try:
                state.context = request.context
                asked = state.asked.get(request.answer.question_id) if request.answer is not None else None
                if (
                    request.answer is not None
                    and asked is not None
                    and question_key(asked.question.question_id) == REASON_KEY
                ):
                    turn = record_reason(state, asked, request.answer, self.resources)
                else:
                    if request.answer is not None:
                        self._apply(state, request.answer)
                    elif not fresh:
                        assert request.message is not None
                        state.restart(request.message)
                    turn = self._advance(state)
            except BaseException:  # 거절·오류로 끝난 차례는 상태에 흔적을 남기지 않는다(같은 질문에 다시 답할 수 있게)
                state.restore(saved)
                raise
            if limited_now():  # 이 차례에 한도로 못 부른 외부 호출이 있었다(화면 안내 한 줄)
                turn = turn.model_copy(update={"llm_limited": True})
            state.turns.append(turn)
            self.store.put(state)
        return turn

    def conversation(self, conversation_id: str) -> Conversation:
        state = self._existing(conversation_id)
        if not state.turns:
            raise AssistantError("답변 차례가 아직 없는 대화")
        return Conversation(conversation_id=state.conversation_id, turns=tuple(state.turns))

    def _existing(self, conversation_id: str) -> ConversationState:
        state = self.store.get(conversation_id)
        if state is None:
            raise AssistantError("대화 없음 · 처음부터 다시 입력")
        return state

    # ---------- 한 차례 ----------

    def _read(self, state: ConversationState) -> Reading:
        fixed = Fixed(op=state.fixed_op, intent=state.fixed_intent, targets=dict(state.fixed_targets))
        return read(
            state.llm_text or state.text,
            state.context.ship_ids,
            self.resources.vocab,
            self.resources.lexicon,
            self.resources.models,
            fixed,
        )

    def _advance(self, state: ConversationState) -> AssistantTurn:
        resources = self.resources
        reading = self._read(state)
        if self._needs_help(reading, state):
            state.rewrite_tried = True
            rewritten = rewrite_request(self.llm, state.text, resources.vocab) if self.llm else None
            if rewritten is not None:
                state.llm_text, state.llm_used = rewritten, True
                reading = self._read(state)
        read_proposal = as_llm(reading.proposal) if state.llm_text else reading.proposal
        proposal = with_overrides(read_proposal, state, resources.vocab)
        answers, unit_auto = route_request(resources.decision, reading, proposal)
        asked = build_questions(state, reading, answers, proposal, resources, unit_auto)
        if not asked and (unit_auto or state.confirmed or self._all_fixed(state, reading)):
            if state.draft_only:
                return drafted(state, proposal.draft, answers, resources)
            return analyzed(state, proposal, answers, route_reason(resources.decision, reading), resources, self.llm)
        if not asked:  # 안전장치: 진행 조건이 아닌데 물을 것도 없으면 요약 확인
            asked = [summary_question(proposal.draft, resources)]
        return asking(state, proposal.draft, answers, asked, resources)

    def _needs_help(self, reading: Reading, state: ConversationState) -> bool:
        """규칙 기반이 못 읽은 곳(연산·대상 '해당 없음', 다시 설명할 것, 빠진 값)이 있고 다시 쓰기를 안 했을 때."""
        if self.llm is None or not self.llm.usable or state.rewrite_tried or state.llm_text:
            return False
        return rewrite_wanted(reading)

    def _all_fixed(self, state: ConversationState, reading: Reading) -> bool:
        return state.fixed_op is not None and all(i in state.fixed_targets for i in range(len(reading.targets)))

    # ---------- 답 반영 ----------

    def _apply(self, state: ConversationState, answer: Answer) -> None:
        asked = state.asked.get(answer.question_id)
        if asked is None:
            raise AssistantError("현재 질문에 대한 답 아님 · 화면 새로 고침 필요")
        if answer.option_id is not None and answer.option_id not in {o.option_id for o in asked.question.options}:
            raise AssistantError("보여 준 선택지에서 선택 필요")
        last = len(state.asked) == 1
        key = question_key(asked.question.question_id)
        option = answer.option_id
        if key == "summary":
            if option == YES:
                state.confirmed = True
            else:
                state.detail = True
            return
        if key == "text":
            if answer.text is None:
                raise AssistantError("요청 글로 다시 입력")
            state.restart(answer.text)
            return
        if key in ("op", "intent"):
            apply_choice(state, key, answer)
        elif key.startswith("target#"):
            apply_target(state, int(key.split("#")[1]), answer, self.resources)
        elif key.startswith("slot:"):
            self._apply_slot(state, key.removeprefix("slot:"), asked, answer)
        if last:
            state.confirmed = True  # 화면에 보인 나머지 내용(미리 채운 판단)을 확인한 것으로 본다

    def _apply_slot(self, state: ConversationState, slot: str, asked: Asked, answer: Answer) -> None:
        draft = with_overrides(self._read(state).proposal, state, self.resources.vocab).draft
        apply_slot(state, slot, asked, answer, draft, self.resources)


def question_key(question_id: str) -> str:
    """차례가 붙은 질문 ID('slot:to_mm@3')의 질문 종류 키('slot:to_mm')."""
    return question_id.rsplit("@", 1)[0]
