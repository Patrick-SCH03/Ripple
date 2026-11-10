"""관리자 'AI 호출 기록'의 성질(ripple/llm/route.py recent_calls · GET /api/llm/calls — 가짜 모델, 키·네트워크 없이).

경로: 실제로 부른 호출만(성공·실패·헤지 둘 다, 한도로 막힌 호출은 없음), 최근 것부터, 최대 CALL_LOG개, 문장·응답 없음.
API: 관리자만(담당자 403·로그인 전 401), 비서 차례 뒤 그 호출이 보임, 외부 모델이 없으면 빈 목록.
"""

from __future__ import annotations

import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from harness import Checker

from ripple.api.app import create_app
from ripple.generator.build import generate
from ripple.generator.io import load_config, write_outputs
from ripple.llm.base import LlmUnavailable
from ripple.llm.quota import QuotaLimits, UsageLedger, acting_as
from ripple.llm.route import CALL_LOG, Route, Router

from .llm_routes import Timed
from .records import ADMIN_ENV, _client, _people, _settings_for

PROMPT = "비밀 문장 S-001 판 7번"
EXPLAIN = {"blocks": [{"kind": "template", "id": "verdict.approve"}]}
DEMO1 = "선주 요청으로 펌프룸 스트리핑 글로브 밸브 1번을 볼 밸브로 바꿔 주세요"


def run(c: Checker) -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        _router(c, root)
        _api(c, root)


def _router(c: Checker, root: Path) -> None:
    c.section("AI 호출 기록: 경로(실제로 부른 호출만, 최근 것부터, 문장 없음)")
    good = Timed("좋음", 0.0, {"n": 1})
    bad = Timed("실패", 0.0, error=LlmUnavailable("http 500"))
    router = Router(
        {
            "explain": Route(models=(good,), hedge_after_s=1.0, budget_s=2.0),
            "rewrite": Route(models=(bad, good), hedge_after_s=1.0, budget_s=2.0),
        }
    )
    router.generate_routed("explain", PROMPT, {}, None)
    router.generate_routed("rewrite", PROMPT, {}, None)  # 1순위 실패 → 바로 2순위
    calls = router.recent_calls()
    shape = [(call.task, call.model, call.ok, call.error) for call in calls]
    c.check(
        "세 호출을 최근 것부터: 다시 쓰기 2순위 성공 · 1순위 실패(예외 이름만) · 설명 성공",
        shape
        == [("rewrite", "좋음", True, ""), ("rewrite", "실패", False, "LlmUnavailable"), ("explain", "좋음", True, "")]
        and calls[0].at >= calls[-1].at
        and all(call.latency_ms >= 0 for call in calls),
        shape,
    )
    dumped = "".join(call.model_dump_json() for call in calls)
    c.check("기록에 문장·응답·오류 메시지 원문이 없음", PROMPT not in dumped and "http 500" not in dumped)
    for _ in range(CALL_LOG + 5):
        router.generate_routed("explain", PROMPT, {}, None)
    c.check(f"최근 {CALL_LOG}개만 남김", len(router.recent_calls()) == CALL_LOG, len(router.recent_calls()))
    limited = Router(
        {"explain": Route(models=(Timed("하나", 0.0, {"n": 1}),), hedge_after_s=1.0, budget_s=2.0)},
        ledger=UsageLedger(root / "q" / "llm_usage.json", QuotaLimits(daily_total=5, daily_per_account=1)),
    )
    for _ in range(3):
        with acting_as("kim"), suppress(LlmUnavailable):
            limited.generate_routed("explain", PROMPT, {}, None)
    c.check("한도로 부르지 않은 호출은 기록하지 않음(실제로 부른 1회만)", len(limited.recent_calls()) == 1)


def _api(c: Checker, root: Path) -> None:
    c.section("AI 호출 기록: API(관리자만, 비서 차례 뒤 그 호출이 보임)")
    write_outputs(generate(load_config()), root / "synthetic")
    explain = Timed("설명 모델", 0.0, EXPLAIN)
    router = Router({"explain": Route(models=(explain,), hedge_after_s=2.0, budget_s=5.0)})
    app = create_app(_settings_for(root, "api"), environ=ADMIN_ENV, llm_factory=lambda _s: router)
    plain = create_app(_settings_for(root, "api-plain"), environ=ADMIN_ENV, llm_factory=lambda _s: None)
    with _client(app) as anonymous:
        people = _people(app)
        before: dict[str, Any] = people["lead"].get("/api/llm/calls").json()
        body = {"context": {"ship_ids": ["S-001"], "as_of": "2026-10-20"}, "message": DEMO1}
        turn = people["kim"].post("/api/assistant/turns", json=body)
        after: dict[str, Any] = people["lead"].get("/api/llm/calls").json()
        member = people["kim"].get("/api/llm/calls").status_code
        outside = anonymous.get("/api/llm/calls").status_code
    with _client(plain):
        none: dict[str, Any] = _people(plain)["lead"].get("/api/llm/calls").json()
    c.check(
        "관리자: 차례 전 빈 목록 → 비서 차례 뒤 설명 호출 1건(작업·모델·성공), 문장 없음",
        before == {"external": True, "calls": []}
        and turn.status_code == 200
        and [(x["task"], x["model"], x["ok"]) for x in after["calls"]] == [("explain", "설명 모델", True)]
        and DEMO1 not in str(after),
        (before, after),
    )
    c.check("담당자 403 · 로그인 전 401", (member, outside) == (403, 401), (member, outside))
    c.check("외부 모델이 없으면 external false·빈 목록", none == {"external": False, "calls": []}, none)
