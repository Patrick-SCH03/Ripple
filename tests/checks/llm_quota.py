"""외부 AI 사용량 한도의 성질(ripple/llm/quota.py — 가짜 모델·가짜 시계, 키·네트워크 없이).

장부(계정별·전체·KST 날짜 바뀜·재시작·깨진 파일·동시 예약) · 경로(한도면 모델을 부르지 않음, 헤지 다음 모델도) ·
설정(quota 없으면 시작 거부) · real 모드 · 비서(다시 쓰기 뒤 설명만 막힘) · API(계정별 몫, llm_limited).
"""

from __future__ import annotations

import json
import tempfile
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from harness import Checker

from ripple.agent.flow import Assistant
from ripple.agent.resources import AssistantResources
from ripple.api.app import create_app
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.assistant import YES, Answer, AssistantTurn, AssistantTurnRequest, TurnContext, TurnState
from ripple.contracts.domain import DataMode
from ripple.generator.build import generate
from ripple.generator.io import load_config, write_outputs
from ripple.llm.base import Guarded, LlmBlocked, LlmUnavailable
from ripple.llm.quota import KST, QuotaExceeded, QuotaLimits, UsageLedger, acting_as
from ripple.llm.route import Route, Router, build_router

from .llm_routes import GOOD, UNREAD, Timed
from .records import ADMIN_ENV, _client, _people, _settings_for

CONTEXT = TurnContext(ship_ids=("S-001",), as_of=date(2026, 10, 20))
DEMO1 = "선주 요청으로 펌프룸 스트리핑 글로브 밸브 1번을 볼 밸브로 바꿔 주세요"
EXPLAIN = {"blocks": [{"kind": "template", "id": "verdict.approve"}]}


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


def run(c: Checker, resources: Callable[[DataMode], AssistantResources]) -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        _ledger(c, root)
        _router(c, root)
        _settings(c, root)
        _assistant(c, root, resources)
        _api(c, root)


def _ledger(c: Checker, root: Path) -> None:
    c.section("외부 AI 사용량 한도: 장부(계정별·전체·날짜·재시작·깨진 파일·동시 예약)")
    clock = Clock(datetime(2026, 10, 10, 23, 59, tzinfo=KST))
    path = root / "a" / "llm_usage.json"
    ledger = UsageLedger(path, QuotaLimits(daily_total=5, daily_per_account=2), clock)
    kim = [ledger.reserve("kim") for _ in range(3)]
    lead = [ledger.reserve("lead") for _ in range(2)]
    park = [ledger.reserve("park") for _ in range(2)]
    c.check(
        "계정당 2회·전체 5회: kim 2회 뒤 막힘, lead 2회, park은 전체 한도로 1회만",
        kim == [True, True, False] and lead == [True, True] and park == [True, False],
        (kim, lead, park),
    )
    reopened = UsageLedger(path, QuotaLimits(daily_total=5, daily_per_account=2), clock)
    c.check(
        "다시 열어도(재시작) 그날 수가 남음",
        reopened.snapshot()[1:] == (5, {"kim": 2, "lead": 2, "park": 1}) and not reopened.reserve("new"),
        reopened.snapshot(),
    )
    clock.at = datetime(2026, 10, 11, 0, 0, tzinfo=KST)
    c.check(
        "KST 자정이 지나면 0부터(UTC 15:00 = KST 자정)",
        reopened.reserve("kim") and reopened.snapshot()[1] == 1 and reopened.snapshot()[0] == date(2026, 10, 11),
        reopened.snapshot(),
    )
    utc_clock = Clock(datetime(2026, 10, 10, 14, 59, tzinfo=KST) - timedelta(hours=9))  # UTC 05:59 = KST 14:59
    c.check(
        "날짜는 KST로 정함(UTC 시계를 줘도 KST 날짜)",
        UsageLedger(root / "tz.json", QuotaLimits(daily_total=1, daily_per_account=1), utc_clock).snapshot()[0]
        == date(2026, 10, 10),
    )
    broken = root / "b" / "llm_usage.json"
    broken.parent.mkdir()
    broken.write_text("{not json", encoding="utf-8")
    negative = root / "c" / "llm_usage.json"
    negative.parent.mkdir()
    negative.write_text(json.dumps({"date": "2026-10-11", "total": -3, "accounts": {}}), encoding="utf-8")
    c.check(
        "깨진 장부·음수 값은 오늘 한도를 다 쓴 것으로(넘치지 않는 쪽)",
        not UsageLedger(broken, QuotaLimits(daily_total=9, daily_per_account=9), clock).reserve("kim")
        and not UsageLedger(negative, QuotaLimits(daily_total=9, daily_per_account=9), clock).reserve("kim"),
    )
    c.check(
        "한도 0이면 아무 호출도 받지 않음",
        not UsageLedger(root / "zero.json", QuotaLimits(daily_total=0, daily_per_account=5), clock).reserve("kim"),
    )
    blocker = root / "blocked"
    blocker.write_text("폴더 자리에 파일", encoding="utf-8")  # 장부 폴더를 만들 수 없게(쓰기 실패)
    flaky = UsageLedger(blocker / "llm_usage.json", QuotaLimits(daily_total=2, daily_per_account=2), clock)
    errors = 0
    for _ in range(5):
        try:
            flaky.reserve("kim")
        except LlmUnavailable:
            errors += 1
    during = flaky.snapshot()[1]
    blocker.unlink()
    recovered = [flaky.reserve("kim") for _ in range(3)]
    c.check(
        "장부 쓰기 실패 중에는 부르지 않고(LlmUnavailable) 세지도 않음 — 저장소가 돌아오면 한도 2회를 그대로 씀",
        errors == 5 and during == 0 and recovered == [True, True, False],
        (errors, during, recovered),
    )
    stuck = UsageLedger(root / "stuck" / "llm_usage.json", QuotaLimits(daily_total=5, daily_per_account=5), clock)
    (root / "stuck").mkdir()
    (root / "stuck" / "llm_usage.json").mkdir()  # 바꿔 끼울 자리가 폴더라 쓰기 실패
    model = Timed("하나", 0.0, {"n": 1})
    stuck_router = Router({"t": Route(models=(model,), hedge_after_s=1.0, budget_s=2.0)}, ledger=stuck)
    with acting_as("kim") as usage:
        try:
            stuck_router.generate_routed("t", "p", {}, None)
            outcome = "답"
        except LlmUnavailable as error:
            outcome = str(error)
    c.check(
        "경로: 기록 실패면 모델을 부르지 않고 실패로 접음 — 한도 안내(llm_limited)는 켜지 않음",
        model.timeouts == [] and not usage.limited and "LlmUnavailable" in outcome,
        (outcome, model.timeouts, usage.limited),
    )
    shared = UsageLedger(root / "d" / "llm_usage.json", QuotaLimits(daily_total=20, daily_per_account=100), clock)
    granted: list[bool] = []
    lock = threading.Lock()
    gate = threading.Barrier(50)

    def worker(index: int) -> None:
        gate.wait()
        ok = shared.reserve(f"u{index % 7}")
        with lock:
            granted.append(ok)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    stored = json.loads((root / "d" / "llm_usage.json").read_text(encoding="utf-8"))
    c.check(
        "동시 예약 50개 · 전체 한도 20: 정확히 20개만 받고 파일 합계도 20",
        granted.count(True) == 20 and stored["total"] == 20 and sum(stored["accounts"].values()) == 20,
        (granted.count(True), stored["total"]),
    )


def _router(c: Checker, root: Path) -> None:
    c.section("외부 AI 사용량 한도: 경로(한도면 모델을 부르지 않음, 헤지 다음 모델도 예약)")
    ledger = UsageLedger(root / "r" / "llm_usage.json", QuotaLimits(daily_total=10, daily_per_account=1))
    model = Timed("하나", 0.0, {"n": 1})
    router = Router({"t": Route(models=(model,), hedge_after_s=1.0, budget_s=2.0)}, ledger=ledger)
    with acting_as("kim") as first:
        answer = router.generate_routed("t", "p", {}, None)
    with acting_as("kim") as second:
        try:
            router.generate_routed("t", "p", {}, None)
            blocked = "예외 없음"
        except QuotaExceeded:
            blocked = "QuotaExceeded"
        except LlmUnavailable as error:
            blocked = str(error)
    c.check(
        "kim 1회는 부르고 2회째는 모델을 부르지 않고 한도 표시(이 차례만)",
        answer == {"n": 1}
        and len(model.timeouts) == 1
        and not first.limited
        and second.limited
        and "QuotaExceeded" in blocked,
        (blocked, len(model.timeouts), first.limited, second.limited),
    )
    hedge_ledger = UsageLedger(root / "h" / "llm_usage.json", QuotaLimits(daily_total=10, daily_per_account=1))
    slow, spare = Timed("느림", 0.3, {"n": 1}), Timed("예비", 0.0, {"n": 2})
    hedged = Router({"t": Route(models=(slow, spare), hedge_after_s=0.05, budget_s=2.0)}, ledger=hedge_ledger)
    with acting_as("lead") as usage:
        answer = hedged.generate_routed("t", "p", {}, None)
    c.check(
        "헤지로 다음 모델을 시작할 때도 예약 — 계정 한도 1이면 예비 모델은 부르지 않고 1순위 답을 기다림",
        answer == {"n": 1} and spare.timeouts == [] and usage.limited and hedge_ledger.snapshot()[1] == 1,
        (answer, spare.timeouts, usage.limited),
    )


def _settings(c: Checker, root: Path) -> None:
    c.section("외부 AI 사용량 한도: 설정(기본 끔, quota 절을 넣으면 켜짐)")
    default = PROJECT_ROOT / "params" / "llm_v1.yaml"
    source = default.read_text(encoding="utf-8")
    enabled = root / "with_quota.yaml"
    enabled.write_text(
        source.replace("routes:\n", "quota:\n  daily_total: 3\n  daily_per_account: 1\nroutes:\n", 1), encoding="utf-8"
    )
    made: list[Timed] = []

    def make(provider: str, model: str, effort: str | None) -> Timed:
        made.append(Timed(f"{provider}:{model}", 0.0, {"blocks": []}))
        return made[-1]

    usage = root / "s" / "llm_usage.json"
    off = build_router(("claude",), default, make, usage)
    on = build_router(("claude",), enabled, make, root / "t" / "llm_usage.json")
    calls = 0
    if off is not None:
        for _ in range(5):  # 한도가 없으면 같은 계정이 몇 번이든 부른다
            with acting_as("kim"):
                off.generate_routed("explain", "p", {}, None)
        calls = sum(len(m.timeouts) for m in made)
    c.check(
        "기본 설정(quota 없음)은 한도 없이 부르고 장부 파일도 만들지 않음, quota 절을 넣으면 그 값으로 장부를 닮",
        off is not None
        and off.ledger is None
        and calls == 5
        and not usage.exists()
        and on is not None
        and on.ledger is not None
        and on.ledger.limits == QuotaLimits(daily_total=3, daily_per_account=1)
        and build_router((), default, make) is None,
        (calls, off is not None and off.ledger, usage.exists()),
    )


def _assistant(c: Checker, root: Path, resources: Callable[[DataMode], AssistantResources]) -> None:
    c.section("외부 AI 사용량 한도: 비서(다시 쓰기 뒤 설명만 막힘 · real 모드는 한도 전에 차단)")
    ledger = UsageLedger(root / "x" / "llm_usage.json", QuotaLimits(daily_total=10, daily_per_account=1))
    rewrite = Route(models=(Timed("다시 쓰기", 0.0, GOOD),), hedge_after_s=2.0, budget_s=5.0)
    explain = Route(models=(Timed("설명", 0.0, EXPLAIN),), hedge_after_s=2.0, budget_s=5.0)
    router = Router({"rewrite": rewrite, "explain": explain}, ledger=ledger)
    bot = Assistant(resources(DataMode.SYNTHETIC), llm=Guarded(router, DataMode.SYNTHETIC))
    turns: list[AssistantTurn] = []
    with acting_as("kim"):
        turn = bot.turn(AssistantTurnRequest(context=CONTEXT, message=UNREAD))
        turns.append(turn)
        for _ in range(6):
            if turn.state is TurnState.ANALYZED:
                break
            question = turn.questions[0]
            option = next((o.option_id for o in question.options if o.option_id == YES), None)
            option = option or (question.options[0].option_id if question.options else None)
            answer = Answer(question_id=question.question_id, option_id=option) if option else None
            if answer is None:
                break
            turn = bot.turn(AssistantTurnRequest(conversation_id=turn.conversation_id, context=CONTEXT, answer=answer))
            turns.append(turn)
    final = turns[-1]
    c.check(
        "다시 쓰기는 AI로(rule+llm), 같은 날 설명은 한도로 기본 설명 — 그 차례만 llm_limited(첫 차례는 아님)",
        final.state is TurnState.ANALYZED
        and final.interpreter == "rule+llm"
        and final.llm_limited
        and not turns[0].llm_limited
        and final.explanation is not None,
        [(t.state.value, t.interpreter, t.llm_limited) for t in turns],
    )
    real_ledger = UsageLedger(root / "y" / "llm_usage.json", QuotaLimits(daily_total=10, daily_per_account=10))
    real = Guarded(Router({"rewrite": rewrite}, ledger=real_ledger), DataMode.REAL)
    try:
        with acting_as("kim"):
            real.generate_json("p", {}, task="rewrite")
        stopped = False
    except LlmBlocked:
        stopped = True
    c.check(
        "real 모드는 한도보다 먼저 차단 — 장부 파일을 만들지 않음",
        stopped and not (root / "y" / "llm_usage.json").exists() and real_ledger.snapshot()[1] == 0,
    )


def _api(c: Checker, root: Path) -> None:
    c.section("외부 AI 사용량 한도: API(로그인 계정별 몫, 한도면 llm_limited와 기본 설명)")
    write_outputs(generate(load_config()), root / "synthetic")
    usage = root / "api" / "llm_usage.json"
    explain = Timed("설명", 0.0, EXPLAIN)
    router = Router(
        {"explain": Route(models=(explain,), hedge_after_s=2.0, budget_s=5.0)},
        ledger=UsageLedger(usage, QuotaLimits(daily_total=2, daily_per_account=1)),
    )
    settings = _settings_for(root, "api")
    app = create_app(settings, environ=ADMIN_ENV, llm_factory=lambda _s: router)

    def ask(client: Any) -> dict[str, Any]:
        body = {"context": {"ship_ids": ["S-001"], "as_of": "2026-10-20"}, "message": DEMO1}
        response = client.post("/api/assistant/turns", json=body)
        assert response.status_code == 200, response.text
        return dict(response.json())

    with _client(app):
        people = _people(app)
        kim1, kim2 = ask(people["kim"]), ask(people["kim"])
        lead1 = ask(people["lead"])
        park1 = ask(people["park"])
    stored = json.loads(usage.read_text(encoding="utf-8"))
    sources = [t.get("explanation", {}).get("source") for t in (kim1, kim2, lead1, park1)]
    c.check(
        "계정당 1·전체 2: kim 첫 차례만 AI 설명, kim 두 번째는 llm_limited, lead는 따로 1회, park은 전체 한도",
        [t.get("llm_limited") for t in (kim1, kim2, lead1, park1)] == [False, True, False, True]
        and stored["accounts"] == {"kim": 1, "lead": 1}
        and len(explain.timeouts) == 2,
        (sources, stored),
    )
