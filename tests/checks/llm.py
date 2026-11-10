"""생성 모델 경계의 성질(가짜 모델, 키·네트워크 없이): real 모드 호출 0회, 고른 설명 검증, 다시 쓰기 숫자 검사."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from harness import Checker

from checks import llm_calls, llm_quota, llm_routes
from ripple.agent.flow import Assistant
from ripple.agent.llm_tasks import numbers_kept
from ripple.agent.resources import AssistantResources
from ripple.config.loaders import load_decision_config, load_lexicon, load_params, load_rulebook
from ripple.config.settings import Settings
from ripple.contracts.assistant import YES, Answer, AssistantTurnRequest, FillMethod, TurnContext, TurnState
from ripple.contracts.domain import DataMode
from ripple.engine.index import GraphIndex
from ripple.explain.audit import audit
from ripple.explain.render import name_of, result_entities
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.llm.base import Guarded, LlmBlocked, Schema

CONTEXT = TurnContext(ship_ids=("S-001",), as_of=date(2026, 10, 20))
DEMO1 = "선주 요청으로 펌프룸 스트리핑 글로브 밸브 1번을 볼 밸브로 바꿔 주세요"


class FakeModel:
    """요청 종류(설명 고르기·다시 쓰기)마다 미리 정한 JSON을 돌려준다. 받은 프롬프트를 남긴다."""

    name = "fake"

    def __init__(self, explain: object = None, rewrite: object = None) -> None:
        self.explain, self.rewrite = explain, rewrite
        self.prompts: list[str] = []

    def generate_json(self, prompt: str, schema: Schema, timeout_s: float) -> object:
        self.prompts.append(prompt)
        return self.rewrite if "다시 쓰세요" in prompt else self.explain


def run(c: Checker) -> None:
    settings = Settings.from_env({})
    snapshot = generate(load_config()).snapshot

    def resources(mode: DataMode) -> AssistantResources:
        return AssistantResources.build(
            snapshot,
            GraphIndex(snapshot),
            load_lexicon(settings.lexicon_path),
            load_decision_config(settings.decision_path),
            load_rulebook(settings.rules_path),
            load_params(settings.params_path),
            mode,
        )

    _boundary(c, resources)
    _explanations(c, resources)
    _rewrites(c, resources)
    llm_routes.run(c, resources)
    llm_quota.run(c, resources)
    llm_calls.run(c)


def _boundary(c: Checker, resources: Callable[[DataMode], AssistantResources]) -> None:
    c.section("생성 모델: real 모드 차단")
    fake = FakeModel(explain={"blocks": [{"kind": "template", "id": "verdict.approve"}]})
    guard = Guarded(fake, DataMode.REAL)
    c.check("real 모드에서 부르면 막음", Checker.raises(lambda: guard.generate_json("x", {}), LlmBlocked))
    bot = Assistant(resources(DataMode.REAL), llm=guard)
    turn = bot.turn(AssistantTurnRequest(context=CONTEXT, message=DEMO1))
    unread = bot.turn(AssistantTurnRequest(context=CONTEXT, message="pump room CS line valve No.1 ball type please"))
    c.check(
        "real 모드: 데모 문장·못 읽는 문장 모두 외부 호출 0회(규칙 기반·기본 설명으로 끝까지)",
        fake.prompts == []
        and guard.calls == 0
        and turn.state is TurnState.ANALYZED
        and unread.state is TurnState.ASKING,
        (len(fake.prompts), guard.calls),
    )
    c.check(
        "real 모드 설명은 기본 템플릿 순서",
        turn.explanation is not None and turn.explanation.source == "template" and turn.interpreter == "rule",
    )
    c.check("모델이 없으면 합성 모드도 호출하지 않음", not Guarded(None, DataMode.SYNTHETIC).usable)


def _explanations(c: Checker, resources: Callable[[DataMode], AssistantResources]) -> None:
    c.section("생성 모델: 설명 블록 고르기")
    picked = {
        "blocks": [
            {"kind": "template", "id": "verdict.approve"},
            {"kind": "template", "id": "verdict.reasons"},
            {"kind": "metric", "id": "cost.total"},
            {"kind": "metric", "id": "recommendation.total"},  # 대안을 만들지 않아 값이 없는 수치 → 버림
            {"kind": "template", "id": "hold.advice", "entities": ["PO-0130"]},
            {"kind": "template", "id": "impact.rework", "entities": ["S-001:T31C"]},  # 이 분석에 없는 블록 → 버림
            {"kind": "text", "id": "자유 글은 받지 않아요"},
            {"kind": "metric", "id": "hold.until", "entities": ["PO-0130"]},
        ]
    }
    res = resources(DataMode.SYNTHETIC)
    fake = FakeModel(explain=picked)
    bot = Assistant(res, llm=Guarded(fake, DataMode.SYNTHETIC))
    turn = bot.turn(AssistantTurnRequest(context=CONTEXT, message=DEMO1))
    explanation = turn.explanation
    assert explanation is not None and turn.result is not None
    kept = [b.template_id or b.metric for b in explanation.blocks]
    # 앞머리 판정 문장은 엔진 판정을 따른다(데모 1은 밸브 납기 위험으로 검토 필요)
    head = [f"verdict.{turn.result.verdict.level.value}", "verdict.reasons", "cost.total", "timing.deadline"]
    c.check(
        "합성 모드: 앞머리(엔진 판정·이유·총비용·마감일) 뒤에 검사를 통과한 블록만(값 없는 수치·없는 엔터티·자유 글)",
        explanation.source == "llm" and kept == [*head, "hold.advice", "hold.until"],
        kept,
    )
    names = {e: name_of(e, turn.result, res.directory) for ids in result_entities(turn.result).values() for e in ids}
    c.check("고른 설명도 E4 통과(숫자는 수치 블록이 결과 값으로)", audit(explanation, turn.result, names) == [])
    prompt = fake.prompts[-1] if fake.prompts else ""
    c.check(
        "프롬프트: 고를 수 있는 템플릿 ID·수치 키·엔터티만, 앞머리(판정 문장·총비용·마감일)는 목록에서 뺌",
        "hold.advice" in prompt and "- verdict.approve" not in prompt and "- cost.total:" not in prompt,
    )
    result = turn.result
    c.check(
        "프롬프트: 지연이 없는 사례(데모 1)에는 지연 수치(구역 출구)를 보이지 않음",
        result.schedule.max_exit_delay_days == 0 and "- schedule.max_exit_delay" not in prompt,
        result.schedule.max_exit_delay_days,
    )
    deadline = result.timing.deadline.kind.value
    wrong = {
        "blocks": [
            {"kind": "template", "id": "verdict.warn"},  # 엔진 판정(검토 필요)과 다름 → 버리고 엔진 판정으로
            {"kind": "metric", "id": "cost.total"},  # 앞머리와 중복 → 한 번만
            {"kind": "template", "id": "hold.advice", "entities": ["PO-0130"]},
            {"kind": "template", "id": "hold.advice", "entities": ["PO-0130"]},  # 중복
            {"kind": "template", "id": "timing.urgent"},  # 마감 종류가 confirm_now가 아니면 사실이 아님
            {"kind": "template", "id": "unresolved.note"},  # 판단 불가가 없으면 사실이 아님
            {"kind": "metric", "id": "schedule.max_exit_delay"},  # 지연 0일 → 쓸모없는 줄이라 버림
            {"kind": "template", "id": "next.review"},
        ]
    }
    fixed = Assistant(res, llm=Guarded(FakeModel(explain=wrong), DataMode.SYNTHETIC))
    shown = fixed.turn(AssistantTurnRequest(context=CONTEXT, message=DEMO1)).explanation
    ids = [b.template_id or b.metric for b in shown.blocks] if shown else []
    expected_tail = ["hold.advice", *(["timing.urgent"] if deadline == "confirm_now" else [])]
    expected_tail += [*(["unresolved.note"] if result.unresolved else []), "next.review"]
    c.check(
        "엔진과 반대인 판정·사실이 아닌 문장·지연 0 수치·중복을 골라도 설명은 엔진 결과와 일치"
        "(앞머리 고정, 사실 검사, 한 번만)",
        shown is not None and shown.source == "llm" and ids == [*head, *expected_tail],
        (deadline, ids),
    )
    thin = {"blocks": [{"kind": "template", "id": "verdict.approve"}, {"kind": "metric", "id": "cost.total"}]}
    sparse = Assistant(res, llm=Guarded(FakeModel(explain=thin), DataMode.SYNTHETIC))
    plain = sparse.turn(AssistantTurnRequest(context=CONTEXT, message=DEMO1)).explanation
    c.check(
        "앞머리 말고 고른 블록이 둘 미만이면 기본 템플릿 순서",
        plain is not None and plain.source == "template",
    )
    broken = Assistant(res, llm=Guarded(FakeModel(explain={"oops": True}), DataMode.SYNTHETIC))
    fallback = broken.turn(AssistantTurnRequest(context=CONTEXT, message=DEMO1))
    c.check(
        "응답이 형식에 맞지 않으면 기본 템플릿 순서",
        fallback.explanation is not None and fallback.explanation.source == "template",
    )


def _rewrites(c: Checker, resources: Callable[[DataMode], AssistantResources]) -> None:
    c.section("생성 모델: 해석 보조(다시 쓰기)")
    res = resources(DataMode.SYNTHETIC)
    c.check(
        "다시 쓴 문장의 숫자는 원문에 있어야 함(블록 코드·규격 ID 안 숫자는 지도와 대조)",
        numbers_kept("CS line valve No.1 ball", "P11C 화물 스트리핑 글로브 밸브 1번 볼 밸브로", res.vocab)
        and not numbers_kept("CS line valve ball", "P11C 화물 스트리핑 글로브 밸브 1번 볼 밸브로", res.vocab)
        and not numbers_kept("T31C plate 7 thicker", "T31C 판 7번 두께 15에서 17로", res.vocab),
    )
    text = "pump room CS line valve No.1 ball type please (owner)"
    good = {"understood": True, "request": "P11C 화물 스트리핑 글로브 밸브 1번 볼 밸브로 사양 변경 (선주 요청)"}
    fake = FakeModel(rewrite=good, explain=None)
    bot = Assistant(res, llm=Guarded(fake, DataMode.SYNTHETIC))
    first = bot.turn(AssistantTurnRequest(context=CONTEXT, message=text))
    draft = first.draft
    c.check(
        "규칙 기반이 못 읽은 문장: 다시 쓴 해석은 LLM 채움으로 표시하고 자동 진행 없이 확인받음",
        first.state is TurnState.ASKING
        and first.interpreter == "rule+llm"
        and draft is not None
        and draft.op is not None
        and draft.op.method is FillMethod.LLM
        and first.questions[-1].target == "summary",
        [(q.target, q.kind.value) for q in first.questions],
    )
    turn = first
    while turn.state is TurnState.ASKING:
        question = turn.questions[0]
        option = YES if question.target == "summary" else question.options[0].option_id
        answer = Answer(question_id=question.question_id, option_id=option)
        turn = bot.turn(AssistantTurnRequest(conversation_id=turn.conversation_id, context=CONTEXT, answer=answer))
    c.check(
        "확인하면 다시 쓴 해석으로 분석하고, 요청 원문은 사용자 문장 그대로",
        turn.request is not None
        and turn.request.change.raw_text == text
        and turn.request.change.ops[0].model_dump().get("to_spec_id") == "VL-BALL-DN100-16K",
    )
    invented = {"understood": True, "request": "P11C 화물 스트리핑 글로브 밸브 2번 볼 밸브로 사양 변경"}
    strict = Assistant(res, llm=Guarded(FakeModel(rewrite=invented), DataMode.SYNTHETIC))
    rejected = strict.turn(AssistantTurnRequest(context=CONTEXT, message=text))
    c.check(
        "원문에 없는 번호를 만든 다시 쓰기는 버리고 규칙 기반 질문으로",
        rejected.interpreter == "rule" and rejected.state is TurnState.ASKING,
    )
