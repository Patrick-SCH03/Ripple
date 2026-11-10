"""AI 비서 대화 흐름의 성질: 자동 진행은 보정 술어일 때만, 되묻기·다시 설명·값 확인 뒤 분석, 설명·알림 E4."""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from unittest import mock

from harness import Checker

from ripple.agent.flow import Assistant, AssistantError
from ripple.agent.resources import AssistantResources
from ripple.agent.state import ConversationState, ConversationStore
from ripple.config.loaders import load_decision_config, load_lexicon, load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.assistant import (
    OP_LABELS,
    OP_SLOTS,
    YES,
    Answer,
    AssistantTurn,
    AssistantTurnRequest,
    QuestionKind,
    SlotKind,
    TurnContext,
    TurnState,
)
from ripple.contracts.change import ChangeIntent
from ripple.contracts.dataset import NlSample, NlSplit
from ripple.contracts.decision import NONE_OPTION, Route
from ripple.contracts.domain import DataMode
from ripple.engine.index import GraphIndex
from ripple.eval.nl_labels import same_change
from ripple.explain.audit import audit
from ripple.explain.render import name_of, result_entities
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.generator.nl import load_nl_lexicon, nl_samples

AS_OF = date(2026, 10, 20)
CONTEXT = TurnContext(ship_ids=("S-001",), as_of=AS_OF)
DEMO2 = "3번 탱크 횡격벽 7번 판 두께 15에서 17로 올려 주세요 (강도 보강)"
DEMO1 = "선주 요청으로 펌프룸 스트리핑 글로브 밸브 1번을 볼 밸브로 바꿔 주세요"


def run(c: Checker) -> None:
    settings = Settings.from_env({})
    config = load_config()
    snapshot = generate(config).snapshot
    resources = AssistantResources.build(
        snapshot,
        GraphIndex(snapshot),
        load_lexicon(settings.lexicon_path),
        load_decision_config(settings.decision_path),
        load_rulebook(settings.rules_path),
        load_params(settings.params_path),
        DataMode.SYNTHETIC,
    )
    _demos(c, resources)
    _asking(c, resources)
    _reasons(c, resources)
    _errors(c, resources)
    _answers(c, resources)
    _predicate(c, resources, config.seed, config.scenario_date)
    _all_ops(c, resources, config.seed, config.scenario_date)
    _uncalibrated(c, resources)


def _say(bot: Assistant, text: str, context: TurnContext = CONTEXT) -> AssistantTurn:
    return bot.turn(AssistantTurnRequest(context=context, message=text))


def _reply(bot: Assistant, turn: AssistantTurn, option: str | None = None, text: str | None = None) -> AssistantTurn:
    answer = Answer(question_id=turn.questions[0].question_id, option_id=option, text=text)
    return bot.turn(AssistantTurnRequest(conversation_id=turn.conversation_id, context=CONTEXT, answer=answer))


def _e4(turn: AssistantTurn, resources: AssistantResources) -> bool:
    result = turn.result
    assert result is not None and turn.explanation is not None
    names = {e: name_of(e, result, resources.directory) for ids in result_entities(result).values() for e in ids}
    bodies = [turn.explanation, *(n.body for n in turn.notifications)]
    return all(audit(body, result, names) == [] for body in bodies)


def _demos(c: Checker, resources: AssistantResources) -> None:
    c.section("비서: 데모 문장 → 분석 → 설명·알림")
    bot = Assistant(resources)
    late = TurnContext(ship_ids=("S-001",), as_of=AS_OF, confirm_on=date(2027, 1, 2), horizon_days=90)
    demo2 = _say(bot, DEMO2, late)
    c.check(
        "데모 2(탑재 뒤 두께 변경): 첫 차례에 자동 진행해 분석까지",
        demo2.state is TurnState.ANALYZED and all(d.route is Route.AUTO for d in demo2.decisions),
        [(d.topic.value, d.route.value) for d in demo2.decisions],
    )
    c.check(
        "데모 2: 경고 판정, 협력사·재작업 블록 담당·도면 담당 알림(사전 점검 P-06 작업반은 더해질 수 있음)",
        demo2.result is not None
        and demo2.result.verdict.level.value == "warn"
        and {n.target.value for n in demo2.notifications} - {"crew"} == {"supplier", "fabricator", "drawing"},
    )
    c.check("데모 2: 설명·알림의 숫자는 모두 수치 블록(E4)", _e4(demo2, resources))
    demo1 = _say(bot, DEMO1)
    c.check(
        "데모 1(펌프룸 밸브 사양): 바꿀 규격을 지금 규격 + '볼 밸브'로 정해 분석까지"
        "(판정은 밸브 납기 위험으로 검토 필요)",
        demo1.state is TurnState.ANALYZED
        and demo1.request is not None
        and demo1.request.change.ops[0].model_dump().get("to_spec_id") == "VL-BALL-DN100-16K"
        and demo1.result is not None
        and demo1.result.verdict.level.value == "review",
    )
    c.check("데모 1: 설명·알림 E4", _e4(demo1, resources))
    c.check("데모 문장의 원문이 요청에 남음", demo1.request is not None and demo1.request.change.raw_text == DEMO1)
    asking = _say(Assistant(resources), "3번 탱크 횡격벽 7번 판 두께 바꿔 주세요 (강도 보강)")
    c.check(
        "차례마다 이해한 변경 한 줄(묻는 차례·분석한 차례)",
        (demo2.summary or "").startswith("두께 변경")
        and "15mm → 17mm" in (demo2.summary or "")
        and (demo1.summary or "").startswith("장비 사양 변경")
        and asking.state is TurnState.ASKING
        and (asking.summary or "").startswith("두께 변경"),
        (demo2.summary, demo1.summary, asking.summary),
    )
    title2 = demo2.request.change.title if demo2.request else ""
    c.check(
        "비서가 만든 설계변경 제목 = 요약에서 사유만 뺀 것(무엇을 얼마로 — 목록·결재함에서 값이 보이게)",
        demo2.request is not None
        and title2.startswith("두께 변경")
        and "15mm → 17mm" in title2
        and "강도 보강" not in title2
        and (demo2.summary or "").startswith(title2),
        (title2, demo2.summary),
    )
    c.check(
        "사유를 적은 문장은 판단한 사유를 바로 기록하고, 분석 뒤 질문은 '바꾸기'로 남김",
        demo2.request is not None
        and demo2.request.change.intent is ChangeIntent.STRENGTH
        and len(demo2.follow_ups) == 1
        and demo2.follow_ups[0].proposal == "강도 보강",
        [(q.target, q.proposal) for q in demo2.follow_ups],
    )


def _reasons(c: Checker, resources: AssistantResources) -> None:
    c.section("비서: 변경 사유는 분석 뒤에(기록·바꾸기, 원래 분석에 묶음)")
    bot = Assistant(resources)
    first = _say(bot, "T31C 판 7번 두께 15에서 17로")
    reason = first.follow_ups[0] if first.follow_ups else None
    c.check(
        "사유 없는 문장: 바로 분석하고(사유 미정) 분석 뒤에 기록할 사유를 물음(사유 여섯 가지, 판단 확률 높은 순)",
        first.state is TurnState.ANALYZED
        and first.request is not None
        and first.request.change.intent is None
        and "사유 미정" in (first.summary or "")
        and reason is not None
        and reason.target == "reason"
        and len(reason.options) == 6,
        (first.state.value, first.summary, None if reason is None else [o.option_id for o in reason.options]),
    )
    if reason is None or first.result is None or first.request is None:
        return
    later = TurnContext(ship_ids=("S-001",), as_of=AS_OF, confirm_on=date(2026, 11, 30))
    pick = Answer(question_id=reason.question_id, option_id="strength")
    recorded = bot.turn(AssistantTurnRequest(conversation_id=first.conversation_id, context=later, answer=pick))
    c.check(
        "사유는 그 분석에만 기록: 다른 확정일 맥락으로 답해도 결과·분석 ID·확정일 그대로, 결과 안 요청도 같은 사유",
        recorded.state is TurnState.ANALYZED
        and recorded.request is not None
        and recorded.result is not None
        and recorded.request.change.intent is ChangeIntent.STRENGTH
        and recorded.result.request.change.intent is ChangeIntent.STRENGTH
        and recorded.result.analysis_id == first.result.analysis_id
        and recorded.request.confirm_on == first.request.confirm_on
        and recorded.result.total == first.result.total
        and recorded.reason_recorded
        and not first.reason_recorded,
    )
    again = recorded.follow_ups[0] if recorded.follow_ups else None
    changed = (
        bot.turn(
            AssistantTurnRequest(
                conversation_id=first.conversation_id,
                context=CONTEXT,
                answer=Answer(question_id=again.question_id, option_id="owner_request"),
            )
        )
        if again is not None
        else None
    )
    c.check(
        "기록한 사유도 '바꾸기'로 다시 고를 수 있고 분석 ID는 그대로",
        again is not None
        and again.proposal == "강도 보강"
        and changed is not None
        and changed.request is not None
        and changed.result is not None
        and changed.request.change.intent is ChangeIntent.OWNER_REQUEST
        and changed.result.analysis_id == first.result.analysis_id,
    )
    stale = Answer(question_id=reason.question_id, option_id="weight")
    c.check(
        "지난 차례의 사유 질문 답과 보여 준 사유 밖의 답은 거부",
        Checker.raises(
            lambda: bot.turn(
                AssistantTurnRequest(conversation_id=first.conversation_id, context=CONTEXT, answer=stale)
            ),
            AssistantError,
        )
        and changed is not None
        and Checker.raises(
            lambda: bot.turn(
                AssistantTurnRequest(
                    conversation_id=first.conversation_id,
                    context=CONTEXT,
                    answer=Answer(question_id=changed.follow_ups[0].question_id, option_id="__yes__"),
                )
            ),
            AssistantError,
        ),
    )


def _asking(c: Checker, resources: AssistantResources) -> None:
    c.section("비서: 되묻기·다시 설명·값 확인")
    bot = Assistant(resources)
    vague = _say(bot, "이중저 판 4번 두께 2mm 올려 (강도 보강)")
    choose = vague.questions[0] if vague.questions else None
    c.check(
        "블록이 여럿('이중저')이면 번호·종류로 좁힌 후보에서 고르기(+ 해당 없음)",
        choose is not None
        and choose.target == "target#0"
        and choose.kind is QuestionKind.CHOOSE
        and len(choose.options) == 4
        and choose.options[-1].option_id == NONE_OPTION,
        [(q.target, q.kind.value, len(q.options)) for q in vague.questions],
    )
    picked = _reply(bot, vague, option="S-001:B31P-PL-004")
    summary = picked.questions[0] if picked.questions else None
    c.check(
        "대상을 고르면 증감('2mm 올려')이 그 부재의 지금 두께로 정해지고, 처음 보는 값이라 요약 확인",
        summary is not None and summary.target == "summary" and "→" in (summary.proposal or ""),
        [(q.target, q.proposal) for q in picked.questions],
    )
    analyzed = _reply(bot, picked, option=YES)
    c.check(
        "요약을 확인하면 고른 부재로 분석",
        analyzed.state is TurnState.ANALYZED
        and analyzed.request is not None
        and analyzed.request.change.ops[0].model_dump()["part_ids"] == ("S-001:B31P-PL-004",),
    )
    stale = _say(bot, "T31C PL-007 두께 14에서 17로 (선급 지적)")
    value = next((q for q in stale.questions if q.target == "to_mm"), None)
    c.check(
        "지도와 다른 변경 전 값: 바꿀 두께 확인(제안 17mm, 이유에 지도 값)",
        value is not None
        and value.kind is QuestionKind.VALUE
        and value.proposal == "17mm"
        and "지도" in (value.reason or ""),
        [(q.target, q.proposal, q.reason) for q in stale.questions],
    )
    while stale.state is TurnState.ASKING and stale.questions[0].target != "to_mm":
        stale = _reply(bot, stale, option=stale.questions[0].options[0].option_id)
    confirmed = _reply(bot, stale, option=YES)
    c.check(
        "확인하면 변경 전은 지도 값(15mm), 바꿀 값은 확인한 17mm로 분석",
        confirmed.state is TurnState.ANALYZED
        and confirmed.request is not None
        and (
            confirmed.request.change.ops[0].model_dump()["from_mm"],
            confirmed.request.change.ops[0].model_dump()["to_mm"],
        )
        == (15.0, 17.0),
    )
    missing = _say(bot, "T31C 판 7번 두께 변경해 주세요 (강도 보강)")
    asked = next((q for q in missing.questions if q.target == "to_mm"), None)
    c.check("바꿀 값이 없으면 값을 물음", asked is not None and asked.kind is QuestionKind.VALUE)
    while missing.state is TurnState.ASKING and missing.questions[0].target != "to_mm":
        missing = _reply(bot, missing, option=missing.questions[0].options[0].option_id)
    typed = _reply(bot, missing, text="17mm로 해 주세요")
    c.check(
        "직접 입력한 값으로 분석",
        typed.state is TurnState.ANALYZED
        and typed.request is not None
        and typed.request.change.ops[0].model_dump()["to_mm"] == 17.0,
    )
    restate = _say(bot, "판 7번 두께 15에서 17로 (강도 보강)")
    target_q = next((q for q in restate.questions if q.target == "target#0"), None)
    if target_q is not None and target_q.kind is not QuestionKind.RESTATE:
        restate = _reply(bot, restate, option=NONE_OPTION)
        target_q = next((q for q in restate.questions if q.target == "target#0"), None)
    c.check(
        "'해당 없음'이나 모호한 대상은 다시 설명을 받음",
        target_q is not None and target_q.kind is QuestionKind.RESTATE,
        [(q.target, q.kind.value) for q in restate.questions],
    )
    fixed = _reply(bot, restate, text="T31C 판 7번")
    while fixed.state is TurnState.ASKING:
        fixed = _reply(bot, fixed, option=fixed.questions[0].options[0].option_id)
    c.check(
        "다시 설명한 대상(코드·사전 유일 일치)으로 분석",
        fixed.request is not None and fixed.request.change.ops[0].model_dump()["part_ids"] == ("S-001:T31C-PL-007",),
    )
    _no_clue(c, bot)


def _no_clue(c: Checker, bot: Assistant) -> None:
    """점검 D-3: 연산 단서가 없는 문장은 연산·슬롯을 정하지 않고 '어떤 변경인가요?' 하나만, 단서가 있으면 그대로."""
    chat = _say(bot, "안녕하세요 오늘 날씨 어때요")
    only = chat.questions[0] if len(chat.questions) == 1 else None
    c.check(
        "변경 요청이 아닌 문장: 요약에 연산 없음, 질문은 '어떤 변경인가요?' 하나(연산 전체 + 해당 없음, 이유 한 줄)",
        chat.state is TurnState.ASKING
        and not chat.summary
        and only is not None
        and only.target == "op"
        and only.kind is QuestionKind.CHOOSE
        and len(only.options) == len(OP_LABELS) + 1
        and bool(only.reason),
        (chat.summary, [(q.target, q.prompt, len(q.options)) for q in chat.questions]),
    )
    picked = _reply(bot, chat, option="thickness")
    c.check(
        "연산을 고르면 그 연산의 슬롯을 물음(연산 질문은 다시 나오지 않음)",
        picked.state is TurnState.ASKING
        and bool(picked.questions)
        and all(q.target != "op" for q in picked.questions)
        and "두께" in (picked.summary or ""),
        (picked.summary, [q.target for q in picked.questions]),
    )
    valve = _say(bot, "평형수 밸브 바꿔 주세요")
    c.check(
        "단서가 있는 문장('평형수 밸브 바꿔 주세요')은 그대로 연산을 짐작해 요약에 적음",
        bool(valve.summary) and any(q.target != "op" for q in valve.questions),
        (valve.summary, [q.target for q in valve.questions]),
    )


def _errors(c: Checker, resources: AssistantResources) -> None:
    c.section("비서: 대화 오류와 보관")
    bot = Assistant(resources)
    first = _say(bot, "T31C 판 7번 두께 15에서 17로")
    stale = Answer(question_id="op", option_id="thickness")
    c.check(
        "지금 묻지 않은 질문의 답은 거부",
        Checker.raises(
            lambda: bot.turn(
                AssistantTurnRequest(conversation_id=first.conversation_id, context=CONTEXT, answer=stale)
            ),
            AssistantError,
        ),
    )
    ghost = Answer(question_id="intent", option_id="strength")
    c.check(
        "없는 대화의 답은 거부",
        Checker.raises(
            lambda: bot.turn(AssistantTurnRequest(conversation_id="C-none", context=CONTEXT, answer=ghost)),
            AssistantError,
        ),
    )
    c.check(
        "대화 기록에 차례가 쌓임",
        len(bot.conversation(first.conversation_id).turns) == 1,
    )
    clock = [datetime(2026, 10, 20, 9)]
    store = ConversationStore(limit=2, ttl=timedelta(minutes=30), now=lambda: clock[0])
    timed = Assistant(resources, store=store)
    kept = _say(timed, DEMO1)
    clock[0] += timedelta(hours=1)
    c.check(
        "보관 시간이 지난 대화는 지움",
        Checker.raises(lambda: timed.conversation(kept.conversation_id), AssistantError),
    )
    ids = [_say(timed, DEMO1).conversation_id for _ in range(3)]
    c.check(
        "보관 개수를 넘으면 오래 쓰지 않은 대화부터 지움",
        Checker.raises(lambda: timed.conversation(ids[0]), AssistantError) and timed.conversation(ids[2]) is not None,
    )


def _answers(c: Checker, resources: AssistantResources) -> None:
    c.section("비서: 직접 적은 수치, 지난 차례의 답, 선택지 밖 답, 동시에 온 답")
    ask = "3번 탱크 횡격벽 7번 판 두께 바꿔 주세요 (강도 보강)"

    def typed(text: str) -> tuple[Assistant, AssistantTurn]:
        bot = Assistant(resources)
        turn = _say(bot, ask)
        question = next(q for q in turn.questions if q.target == "to_mm")
        answer = Answer(question_id=question.question_id, text=text)
        return bot, bot.turn(AssistantTurnRequest(conversation_id=turn.conversation_id, context=CONTEXT, answer=answer))

    def to_mm(turn: AssistantTurn) -> object:
        return None if turn.request is None else turn.request.change.ops[0].model_dump().get("to_mm")

    deltas = {text: to_mm(typed(text)[1]) for text in ("+2mm", "2mm 올려", "1.5mm 얇게", "17")}
    c.check(
        "바꿀 두께 답의 증감은 지금 값(지도 15mm)에 더해 분석('+2mm' → 17mm, 2mm가 아님)",
        deltas == {"+2mm": 17.0, "2mm 올려": 17.0, "1.5mm 얇게": 13.5, "17": 17.0},
        deltas,
    )

    def refused(text: str) -> bool:
        return Checker.raises(lambda: typed(text), AssistantError)

    c.check(
        "단위가 다르거나('17kg') 지금 값과 같거나('15') 0 이하가 되는 답('-20mm')은 받지 않음",
        refused("17kg") and refused("15") and refused("-20mm"),
    )
    ratios = typed("10% 올려 또는 20% 올려")[1]
    c.check(
        "서로 다른 비율 답은 하나를 고르지 않고 한 번 더 확인",
        ratios.state is TurnState.ASKING and ratios.questions[0].kind is QuestionKind.VALUE,
        [(q.question_id, q.proposal, q.reason) for q in ratios.questions],
    )

    def again(make_bad: bool) -> tuple[bool, object]:
        """거절·오류로 끝난 차례 뒤에 같은 질문에 다시 답한다. make_bad면 처리 도중 상태를 망가뜨리고 오류를 낸다."""
        bot = Assistant(resources)
        start = _say(bot, ask)
        question = next(q for q in start.questions if q.target == "to_mm")

        def send(text: str) -> AssistantTurn:
            answer = Answer(question_id=question.question_id, text=text)
            return bot.turn(AssistantTurnRequest(conversation_id=start.conversation_id, context=CONTEXT, answer=answer))

        if not make_bad:
            return Checker.raises(lambda: send("-20mm"), AssistantError), to_mm(send("17mm"))

        def poisoned(state: ConversationState, slot: str, asked: object, answer: Answer) -> None:
            state.value_checks[slot] = (-5.0, "남으면 안 되는 값")
            raise RuntimeError("차례 처리 중 오류")

        with mock.patch.object(bot, "_apply_slot", poisoned):
            broke = Checker.raises(lambda: send("17mm"), RuntimeError)
        return broke, to_mm(send("17mm"))

    retried = again(False)
    c.check("거절된 답('-20mm') 뒤에도 같은 질문에 다시 답하면 분석", retried == (True, 17.0), retried)
    restored = again(True)
    c.check("차례 처리가 도중에 실패하면 대화 상태를 되돌려 다음 답이 그대로 됨", restored == (True, 17.0), restored)
    bot, vague = typed("2")
    check = vague.questions[0] if vague.questions else None
    c.check(
        "모호한 답('2': 2mm로? 2mm만큼?)은 추정 값으로 한 번 더 확인",
        vague.state is TurnState.ASKING
        and check is not None
        and check.kind is QuestionKind.VALUE
        and check.proposal == "17mm"
        and check.reason is not None,
        None if check is None else (check.proposal, check.reason),
    )
    if check is not None:
        confirmed = _reply(bot, vague, option=YES)
        c.check("확인하면 그 값으로 분석", to_mm(confirmed) == 17.0)

    bot = Assistant(resources)
    first = _say(bot, "3번 탱크 횡격벽 7번 판 두께 바꿔 주세요 (강도 보강)")
    second = bot.turn(
        AssistantTurnRequest(
            conversation_id=first.conversation_id,
            context=CONTEXT,
            message="3번 탱크 횡격벽 7번 판 두께 바꿔 줘 (강도 보강)",
        )
    )
    late = Answer(question_id=first.questions[0].question_id, text="17mm")
    c.check(
        "질문 ID는 차례마다 새것이고, 지난 차례 질문의 늦은 답은 새 질문에 붙지 않음",
        first.questions[0].question_id != second.questions[0].question_id
        and Checker.raises(
            lambda: bot.turn(AssistantTurnRequest(conversation_id=first.conversation_id, context=CONTEXT, answer=late)),
            AssistantError,
        ),
    )
    outside = Answer(question_id=second.questions[0].question_id, option_id="S-001:T31C-PL-001")
    c.check(
        "보여 준 선택지 밖의 답은 거부",
        Checker.raises(
            lambda: bot.turn(
                AssistantTurnRequest(conversation_id=first.conversation_id, context=CONTEXT, answer=outside)
            ),
            AssistantError,
        ),
    )
    finished = _reply(bot, second, text="19mm")
    c.check("지금 질문의 답은 지금 차례 질문으로 분석(19mm)", to_mm(finished) == 19.0)

    bot = Assistant(resources)
    asked = _say(bot, "3번 탱크 횡격벽 7번 판 두께 바꿔 주세요 (강도 보강)")
    question = asked.questions[0]
    gate = threading.Barrier(2)
    outcomes: list[str] = []

    def answer() -> None:
        gate.wait()
        reply = Answer(question_id=question.question_id, text="17mm")
        try:
            bot.turn(AssistantTurnRequest(conversation_id=asked.conversation_id, context=CONTEXT, answer=reply))
            outcomes.append("ok")
        except AssistantError:
            outcomes.append("rejected")

    threads = [threading.Thread(target=answer) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    c.check(
        "같은 질문의 답이 동시에 두 번 와도 하나만 반영(대화 차례 2개)",
        sorted(outcomes) == ["ok", "rejected"] and len(bot.conversation(asked.conversation_id).turns) == 2,
        outcomes,
    )


def _predicate(c: Checker, resources: AssistantResources, seed: int, as_of: date) -> None:
    c.section("비서: 자동 진행 = 보정 술어")
    bot = Assistant(resources)
    samples = nl_samples(resources.snapshot, NlSplit.SELECTION, 60, seed, as_of, load_nl_lexicon())
    consistent = True
    analyzed = 0
    for sample in samples:
        turn = _say(bot, sample.text)
        auto = all(d.route is Route.AUTO for d in turn.decisions)
        consistent = consistent and ((turn.state is TurnState.ANALYZED) == auto or not auto)
        if turn.state is TurnState.ANALYZED:
            analyzed += 1
            consistent = consistent and auto
    c.check("첫 차례에 분석한 요청은 모두 판단이 자동 진행 경로", consistent)
    c.check("선택 분할 문장 일부는 첫 차례에 분석(자동 진행이 동작함)", analyzed > 0, analyzed)


def _uncalibrated(c: Checker, resources: AssistantResources) -> None:
    c.section("비서: 보정 산출물이 없을 때")
    targets_only = load_decision_config(PROJECT_ROOT / "params" / "decision_v0.yaml")
    plain = AssistantResources.build(
        resources.snapshot,
        resources.index,
        resources.lexicon,
        targets_only,
        resources.rulebook,
        resources.params,
        resources.data_mode,
    )
    bot = Assistant(plain)
    turn = _say(bot, DEMO2)
    c.check(
        "보정 산출물이 없으면 자동 진행 없이 요약 확인을 받고 분석",
        turn.state is TurnState.ASKING and turn.questions[-1].target == "summary",
        [(q.target, q.kind.value) for q in turn.questions],
    )
    while turn.state is TurnState.ASKING:
        q = turn.questions[0]
        turn = _reply(bot, turn, option=YES if q.target == "summary" else q.options[0].option_id)
    c.check("확인하면 분석", turn.state is TurnState.ANALYZED)


def _all_ops(c: Checker, resources: AssistantResources, seed: int, as_of: date) -> None:
    c.section("비서: 여덟 연산 완주(문장 → 슬롯 → 조립 → 분석)")
    samples = nl_samples(resources.snapshot, NlSplit.SELECTION, 400, seed, as_of, load_nl_lexicon())
    finished: dict[str, bool] = {}
    for op in OP_LABELS:
        chosen = [s for s in samples if s.change.ops[0].op == op and all(m.exists for m in s.mentions)][:3]
        finished[op] = any(_complete(resources, sample) for sample in chosen)
    c.check(
        "연산 8종 모두 생성 문장 하나 이상이 정답으로 답하면 분석까지 가고 조립한 요청 = 정답",
        all(finished.values()),
        {op: ok for op, ok in finished.items() if not ok},
    )


def _complete(resources: AssistantResources, sample: NlSample) -> bool:
    """질문마다 정답으로 답한다(고르기는 정답 선택지, 값은 정답 값을 글로). 6차례 안에 분석하고 요청이 정답이면 참."""
    bot = Assistant(resources)
    truth = sample.change
    op = truth.ops[0]
    body = op.model_dump(mode="json")
    turn = _say(bot, sample.text)
    for _ in range(6):
        if turn.state is TurnState.ANALYZED:
            # 변경 사유는 분석 뒤에 따로 정하므로 연산·호선만 정답과 맞춘다
            return turn.request is not None and same_change(turn.request.change, truth, intent=False)
        question = turn.questions[0]
        option, text = _oracle(question.target, [o.option_id for o in question.options], body, op.op)
        answer = Answer(question_id=question.question_id, option_id=option, text=text)
        turn = bot.turn(AssistantTurnRequest(conversation_id=turn.conversation_id, context=CONTEXT, answer=answer))
    return False


def _oracle(target: str, options: list[str], body: dict[str, object], op: str) -> tuple[str | None, str | None]:
    if target == "summary":
        return YES, None
    if target == "op":
        return op, None
    if target.startswith("target#"):
        listed = body.get("part_ids")
        wanted = [p for p in listed if isinstance(p, str)] if isinstance(listed, list) else []
        hit = next((o for o in options if o in wanted), None)
        return (hit, None) if hit else (None, wanted[0].split(":")[-1] if wanted else "모름")
    spec = next((s for s in OP_SLOTS[op] if s.name == target), None)
    value = body.get(target)
    if spec is None or value is None:
        return (options[0], None) if options else (None, "모름")
    if spec.kind in (SlotKind.PARTS, SlotKind.SPECS) and isinstance(value, list):
        shown = " ".join(str(v).split(":")[-1] for v in value)
    else:
        shown = str(value).split(":")[-1] if spec.kind in (SlotKind.PART, SlotKind.BLOCK) else str(value)
    if str(value) in options:
        return str(value), None
    unit = "mm" if spec.kind is SlotKind.MILLIMETER else ("t" if spec.kind is SlotKind.QUANTITY else "")
    return None, f"{shown}{unit}"
