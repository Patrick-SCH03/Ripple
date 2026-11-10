"""외부 생성 모델 경로의 성질(가짜 모델·가짜 HTTP, 키·네트워크 없이): Claude 어댑터, 헤지 전환, 설정, real 모드 차단."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import date

import httpx
from harness import Checker

from ripple.agent.flow import Assistant
from ripple.agent.llm_tasks import EXPLAIN_SCHEMA, REWRITE_SCHEMA
from ripple.agent.resources import AssistantResources
from ripple.config.settings import PROJECT_ROOT, Settings, parse_llm
from ripple.contracts.assistant import AssistantTurnRequest, TurnContext
from ripple.contracts.domain import DataMode
from ripple.eval.llm_selection import Candidate, rank
from ripple.llm.base import Guarded, JsonModel, LlmBlocked, LlmUnavailable, Schema
from ripple.llm.claude import ClaudeModel, strict_schema
from ripple.llm.route import Route, Router, build_router, load_routes

CONTEXT = TurnContext(ship_ids=("S-001",), as_of=date(2026, 10, 20))
UNREAD = "pump room CS line valve No.1 ball type please (owner)"
GOOD = {"understood": True, "request": "P11C 화물 스트리핑 글로브 밸브 1번 볼 밸브로 사양 변경 (선주 요청)"}
FAKE_KEY = "test-key-not-real"


class Timed:
    """지연·답·예외를 정한 가짜 모델(헤지 검사용). 받은 제한 시간을 남긴다."""

    def __init__(self, name: str, delay: float, answer: object = None, error: Exception | None = None) -> None:
        self.name, self.delay, self.answer, self.error = name, delay, answer, error
        self.timeouts: list[float] = []

    def generate_json(self, prompt: str, schema: Schema, timeout_s: float) -> object:
        self.timeouts.append(timeout_s)
        time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.answer


def run(c: Checker, resources: Callable[[DataMode], AssistantResources]) -> None:
    _claude(c)
    _hedge(c)
    _settings(c)
    _selection(c)
    _flow(c, resources)


def _selection(c: Checker) -> None:
    c.section("외부 모델 경로: 측정 채택 순서(사전 등록 규칙)")
    near = [Candidate("A", 0.0742, 0.616, 5.1), Candidate("B", 0.0786, 0.638, 7.7)]
    c.check(
        "1차 지표 차이가 허용 폭(0.5%p) 안이면 2차 지표가 높은 쪽(반올림 구간으로 가르지 않음)",
        rank(near, 0.005, 0.01, 10.0)[0] == "B",
        rank(near, 0.005, 0.01, 10.0),
    )
    far = [Candidate("A", 0.061, 0.35, 4.7), Candidate("B", 0.074, 0.62, 5.1)]
    c.check("허용 폭 밖이면 1차 지표(틀림)가 낮은 쪽", rank(far, 0.005, 0.01, 10.0)[0] == "A")
    slow = [Candidate("A", 0.001, 1.0, 15.3), Candidate("B", 0.002, 1.0, 4.2)]
    c.check("p95 상한을 넘는 후보는 뒤로(제외)", rank(slow, 0.005, 0.01, 8.0) == ["B", "A"])
    tie = [Candidate("A", 0.0058, 1.0, 7.9), Candidate("B", 0.0097, 1.0, 4.6)]
    c.check("1·2차 지표가 허용 폭 안이면 p95가 짧은 쪽", rank(tie, 0.005, 0.01, 8.0)[0] == "B")
    stored = json.loads((PROJECT_ROOT / "eval" / "llm" / "llm_v1_selection.json").read_text("utf-8"))
    routes = load_routes(PROJECT_ROOT / "params" / "llm_v1.yaml").routes
    firsts = {
        task: f"{r.models[0].model}@{r.models[0].effort}" if r.models[0].effort else r.models[0].model
        for task, r in routes.items()
    }
    c.check(
        "경로 설정의 1순위 = 저장된 측정의 채택 1순위(설정과 측정이 어긋나지 않음)",
        all(firsts[task] == stored["order"][task][0] for task in ("rewrite", "explain")),
        (firsts, {task: stored["order"][task][0] for task in stored["order"]}),
    )


def _claude(c: Checker) -> None:
    c.section("외부 모델 경로: Claude 어댑터(가짜 HTTP)")
    strict = strict_schema(EXPLAIN_SCHEMA)
    item = strict["properties"]["blocks"]["items"]  # type: ignore[index]
    c.check(
        "구조화 출력 스키마: 모든 object에 additionalProperties false, 원본은 그대로",
        strict["additionalProperties"] is False
        and item["additionalProperties"] is False
        and "additionalProperties" not in EXPLAIN_SCHEMA,
    )
    seen: list[httpx.Request] = []

    def model(handler: Callable[[httpx.Request], httpx.Response]) -> ClaudeModel:
        return ClaudeModel(FAKE_KEY, "claude-haiku-5-5", client=httpx.Client(transport=httpx.MockTransport(handler)))

    def ok(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = {
            "content": [{"type": "text", "text": '{"understood": true, "request": "x"}'}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 120, "cache_read_input_tokens": 30, "output_tokens": 9},
        }
        return httpx.Response(200, json=body)

    good = model(ok)
    answer = good.generate_json("프롬프트", REWRITE_SCHEMA, 5.0)
    sent = json.loads(seen[-1].content)
    record = good.records[-1]
    c.check(
        "성공: JSON을 돌려주고, 요청에 구조화 출력 스키마·모델·키 헤더, 기록에 토큰(캐시 포함)",
        answer == {"understood": True, "request": "x"}
        and sent["output_config"]["format"]["schema"]["additionalProperties"] is False
        and sent["model"] == "claude-haiku-5-5"
        and seen[-1].headers["x-api-key"] == FAKE_KEY
        and record.ok
        and (record.input_tokens, record.output_tokens) == (150, 9)
        and "effort" not in sent["output_config"],
        (answer, record),
    )
    transport = httpx.Client(transport=httpx.MockTransport(ok))
    low = ClaudeModel(FAKE_KEY, "claude-sonnet-5-5", client=transport, effort="low")
    low.generate_json("프롬프트", REWRITE_SCHEMA, 5.0)
    sent = json.loads(seen[-1].content)
    c.check(
        "effort를 정하면 output_config.effort로 보내고(모델 ID는 그대로), 이름에 표시, 모르는 값은 거부",
        sent["output_config"]["effort"] == "low"
        and sent["model"] == "claude-sonnet-5-5"
        and low.name == "claude-sonnet-5-5@low"
        and sent["max_tokens"] >= 4096
        and Checker.raises(lambda: ClaudeModel(FAKE_KEY, "claude-haiku-5-5", effort="turbo")),
        sent.get("output_config"),
    )

    def failing(status: int, body: object) -> ClaudeModel:
        return model(lambda request: httpx.Response(status, json=body))

    secret = "비밀 프롬프트 원문"
    limited = failing(429, {"type": "error", "error": {"type": "rate_limit_error", "message": secret}})
    messages = []
    for broken in (
        limited,
        failing(200, {"content": [{"type": "text", "text": "{"}], "stop_reason": "max_tokens", "usage": {}}),
        failing(200, {"content": [{"type": "text", "text": "JSON 아님"}], "stop_reason": "end_turn", "usage": {}}),
        failing(200, ["형식이 다름"]),
    ):
        try:
            broken.generate_json(secret, REWRITE_SCHEMA, 5.0)
            messages.append("예외 없음")
        except LlmUnavailable as error:
            messages.append(str(error))
    c.check(
        "실패(429·끝나지 않음·JSON 아님·형식 다름)는 모두 LlmUnavailable, 메시지에 키·프롬프트·응답 원문 없음",
        "예외 없음" not in messages
        and "429" in messages[0]
        and "rate_limit_error" in messages[0]
        and not any(secret in m or FAKE_KEY in m for m in messages)
        and not limited.records[-1].ok,
        messages,
    )

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("연결 시간 초과", request=request)

    try:
        model(timeout).generate_json("x", REWRITE_SCHEMA, 1.0)
        message = "예외 없음"
    except LlmUnavailable as error:
        message = str(error)
    c.check("네트워크 시간 초과도 LlmUnavailable(예외 종류만)", "ConnectTimeout" in message, message)
    c.check("키가 없으면 어댑터를 만들지 않음", ClaudeModel.from_env(env={}, dotenv=PROJECT_ROOT / "없는.env") is None)


def _hedge(c: Checker) -> None:
    c.section("외부 모델 경로: 헤지 전환·시간 예산")

    def router(*models: JsonModel, hedge: float, budget: float) -> Router:
        return Router({"t": Route(models=models, hedge_after_s=hedge, budget_s=budget)})

    def timed_call(r: Router, accept: Callable[[object], bool] | None = None) -> tuple[object, float]:
        started = time.monotonic()
        try:
            answer = r.generate_routed("t", "p", {}, accept)
        except LlmUnavailable as error:
            answer = error
        return answer, time.monotonic() - started

    fast, spare = Timed("빠름", 0.01, {"n": 1}), Timed("예비", 0.01, {"n": 2})
    answer, _ = timed_call(router(fast, spare, hedge=0.5, budget=2.0))
    c.check("1순위가 빨리 답하면 그 답, 2순위는 부르지 않음", answer == {"n": 1} and spare.timeouts == [], answer)
    slow, quick = Timed("느림", 1.0, {"n": 1}), Timed("빠른 예비", 0.05, {"n": 2})
    answer, took = timed_call(router(slow, quick, hedge=0.1, budget=2.0))
    c.check(
        "1순위가 헤지 시간을 넘기면 2순위를 함께 시작해 먼저 온 답(1순위를 기다리지 않음)",
        answer == {"n": 2} and took < 0.7,
        (answer, round(took, 2)),
    )
    broken, backup = Timed("실패", 0.0, error=LlmUnavailable("x")), Timed("예비", 0.05, {"n": 2})
    answer, took = timed_call(router(broken, backup, hedge=1.0, budget=3.0))
    c.check(
        "1순위가 실패하면 헤지 시간을 기다리지 않고 바로 2순위",
        answer == {"n": 2} and took < 0.6,
        (answer, round(took, 2)),
    )
    empty, later = Timed("빈 답", 0.0, {"ok": False}), Timed("정상", 0.05, {"ok": True})
    answer, _ = timed_call(router(empty, later, hedge=1.0, budget=3.0), accept=lambda d: bool(d.get("ok")))  # type: ignore[attr-defined]
    c.check("작업 검사를 통과하지 못한 답은 버리고 다음 모델의 답", answer == {"ok": True}, answer)
    late_a, late_b = Timed("늦음1", 1.0, {"n": 1}), Timed("늦음2", 1.0, {"n": 2})
    answer, took = timed_call(router(late_a, late_b, hedge=0.05, budget=0.3))
    c.check(
        "전체 시간 예산이 지나면 더 기다리지 않고 LlmUnavailable",
        isinstance(answer, LlmUnavailable) and took < 0.8 and late_a.timeouts[0] <= 0.3,
        (type(answer).__name__, round(took, 2), late_a.timeouts),
    )
    blocker, queued = Timed("붙잡음", 0.6, {"n": 1}), Timed("대기열", 0.0, {"n": 2})
    tight = Router({"t": Route(models=(blocker, queued), hedge_after_s=0.05, budget_s=0.2)}, workers=1)
    answer, _ = timed_call(tight)
    time.sleep(0.8)  # 1순위가 끝나 일꾼이 비어도
    c.check(
        "풀이 꽉 차 대기열에 남은 호출은 요청이 끝난 뒤 시작하지 않음(끝난 요청의 외부 호출·과금 없음)",
        isinstance(answer, LlmUnavailable) and queued.timeouts == [],
        (type(answer).__name__, queued.timeouts),
    )
    dead_a, dead_b = Timed("실패1", 0.0, error=RuntimeError("x")), Timed("실패2", 0.0, error=LlmUnavailable("y"))
    answer, _ = timed_call(router(dead_a, dead_b, hedge=1.0, budget=2.0))
    c.check(
        "모두 실패하면 LlmUnavailable(실패 종류만, 어댑터가 아닌 예외도 그 모델의 실패로)",
        isinstance(answer, LlmUnavailable) and "RuntimeError" in str(answer),
        str(answer),
    )
    watched = Timed("감시", 0.0, {"n": 1})
    real = Guarded(router(watched, hedge=1.0, budget=1.0), DataMode.REAL)
    c.check(
        "real 모드: 경로가 있어도 어떤 모델도 부르지 않음",
        Checker.raises(lambda: real.generate_json("p", {}, task="t"), LlmBlocked) and watched.timeouts == [],
    )
    synthetic = Guarded(router(Timed("a", 0.0, {"ok": False}), hedge=1.0, budget=1.0), DataMode.SYNTHETIC)
    c.check(
        "Guarded가 작업 이름·작업 검사를 경로에 넘김(검사 불통과면 LlmUnavailable)",
        Checker.raises(
            lambda: synthetic.generate_json("p", {}, task="t", accept=lambda d: bool(d.get("ok"))),  # type: ignore[attr-defined]
            LlmUnavailable,
        ),
    )
    single = Guarded(Timed("단독", 0.0, {"ok": False}), DataMode.SYNTHETIC)
    c.check(
        "경로가 없는 단독 모델도 작업 검사를 적용",
        Checker.raises(
            lambda: single.generate_json("p", {}, accept=lambda d: bool(d.get("ok"))),  # type: ignore[attr-defined]
            LlmUnavailable,
        ),
    )


def _settings(c: Checker) -> None:
    c.section("외부 모델 경로: 설정")
    c.check(
        "RIPPLE_LLM: 기본 off, 쉼표 목록, 같은 이름 한 번, 뺀 제공자(gemini) 건너뜀, 모르는 이름 거부, 대소문자 무시",
        Settings.from_env({}).llm_providers == ()
        and parse_llm("off") == ()
        and parse_llm("OFF") == ()
        and parse_llm("Claude") == ("claude",)
        and parse_llm("claude") == ("claude",)
        and parse_llm("claude, claude") == ("claude",)
        and parse_llm("claude, gemini") == ("claude",)
        and parse_llm("gemini") == ()
        and Checker.raises(lambda: Settings.from_env({"RIPPLE_LLM": "gpt"})),
    )
    routes = load_routes(PROJECT_ROOT / "params" / "llm_v1.yaml")
    c.check(
        "경로 설정 파일: 해석 보조·설명 고르기 경로가 있고 시간 예산이 헤지 시간보다 김",
        {"rewrite", "explain"} <= set(routes.routes)
        and all(r.budget_s > r.hedge_after_s for r in routes.routes.values()),
    )
    path = PROJECT_ROOT / "params" / "llm_v1.yaml"
    made: list[tuple[str, str]] = []

    def make(provider: str, model: str, effort: str | None) -> JsonModel | None:
        made.append((provider, model))
        return Timed(f"{provider}:{model}", 0.0, {})

    on = build_router(("claude",), path, make)
    order = [m.name for m in on.routes["rewrite"].models] if on else []
    c.check(
        "경로의 모델 순서는 설정 파일 순서, 모두 Claude(Gemini는 llm-v2에서 뺌)",
        order == [f"{m.provider}:{m.model}" for m in routes.routes["rewrite"].models]
        and all(m.provider == "claude" for r in routes.routes.values() for m in r.models),
        order,
    )
    c.check(
        "꺼져 있거나 키가 없으면 경로 없음(규칙 기반·기본 설명만)",
        build_router((), path, make) is None and build_router(("claude",), path, lambda p, m, e: None) is None,
    )


def _flow(c: Checker, resources: Callable[[DataMode], AssistantResources]) -> None:
    c.section("외부 모델 경로: AI 비서 흐름")
    res = resources(DataMode.SYNTHETIC)
    empty = Timed("빈 다시 쓰기", 0.0, {"understood": True, "request": ""})
    echo = Timed("원문 반복", 0.0, {"understood": True, "request": UNREAD})
    good = Timed("정상", 0.05, GOOD)
    rewrite = Route(models=(empty, echo, good), hedge_after_s=2.0, budget_s=5.0)
    bot = Assistant(res, llm=Guarded(Router({"rewrite": rewrite}), DataMode.SYNTHETIC))
    started = time.monotonic()
    turn = bot.turn(AssistantTurnRequest(context=CONTEXT, message=UNREAD))
    took = time.monotonic() - started
    c.check(
        "빠른 빈 답·원문 반복은 버리고 늦게 온 정상 다시 쓰기를 채택(헤지 시간을 기다리지 않음)",
        turn.interpreter == "rule+llm" and good.timeouts != [] and took < 1.5,
        (turn.interpreter, round(took, 2)),
    )
    careful = Timed("거절", 0.0, {"understood": False, "request": ""})
    eager = Timed("추측", 0.0, GOOD)
    cautious = Route(models=(careful, eager), hedge_after_s=2.0, budget_s=5.0)
    bot = Assistant(res, llm=Guarded(Router({"rewrite": cautious}), DataMode.SYNTHETIC))
    turn = bot.turn(AssistantTurnRequest(context=CONTEXT, message=UNREAD))
    c.check(
        "1순위가 '이해 못 함'으로 답하면 최종(다음 모델의 추측으로 덮지 않고 규칙 기반 질문으로)",
        turn.interpreter == "rule" and eager.timeouts == [],
        (turn.interpreter, eager.timeouts),
    )
