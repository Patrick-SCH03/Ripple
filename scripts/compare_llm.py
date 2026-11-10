"""외부 생성 모델 비교 측정(docs/input.md(외부 AI) 3절): 해석 보조(rewrite)·설명 고르기(explain)를 모델마다 단독으로
잰다.

합성 데이터만 쓴다 — 해석 보조는 문장 선택 분할(평가 분할은 최종 인증용이라 쓰지 않음), 설명 고르기는 개발 분할
설계변경. 키는 어댑터가 .env에서 읽고 출력하지 않는다. 호출마다 비용이 들어 --yes 없이는 예상 호출 수만 출력한다.

정확도 지표(해석 보조, 다시 쓴 문장을 결정적 해석기로 다시 읽어 정답 요청과 비교):
- exact: 초안이 완성되고 정답과 같음
- wrong: 초안이 완성됐는데 정답과 다름(금전 위험, numeric = 연산·대상은 같고 수치만 다름)
- incomplete: 초안에 빠진 곳(앱이 되물음) / unaccepted: 이해 못 함·원문 반복·없는 숫자(앱이 규칙 질문으로)
- error: 호출 실패
설명 고르기: 사실 검사 위반(판정 반대 포함) 블록 비율, 앱이 실제로 쓰는 설명이 되는 비율(앞머리 뒤 2블록 이상).

채택 규칙(사전 등록, 정확도 최우선): p95가 상한(rewrite 10초, explain 8초)을 넘는 모델 제외 →
rewrite는 wrong 비율 최저(0.5%p 안은 같음) → exact 비율 최고(1%p 안은 같음) → p95 최소,
explain은 사실 검사 위반 비율 최저(0.5%p 안은 같음) → 쓰는 설명 비율 최고(1%p 안은 같음) → p95 최소.
경로 2순위는 llm-v2부터 Claude Haiku 5.5(Gemini 제외, docs/input.md(외부 AI) 4절).

실행: uv run python scripts/compare_llm.py --yes [--models a,b] [--forced 200] [--explain 100] [--workers 8]
결과: eval/llm/llm_v1_selection.json(모델·작업별 집계와 채택 순서).
--route: 단독 측정 뒤, params/llm_v1.yaml 경로(헤지)로 앱과 같이(작업 이름·수락 검사) 같은 문장·분석을 잰다
(eval/llm/llm_v1_route.json). 헤지가 덜 정확한 2순위 답을 고르는 회귀가 없는지 단독 1순위와 비교한다.
"""

from __future__ import annotations

import argparse
import io
import json
import random
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Any

from ripple.agent.llm_tasks import (
    EXPLAIN_SCHEMA,
    REWRITE_SCHEMA,
    _explain_prompt,
    _parse_blocks,
    _rewrite_prompt,
    accepted_rewrite,
    pick_explanation,
    refused,
    rewrite_wanted,
)
from ripple.agent.resources import directory_of, models_of
from ripple.config.loaders import load_decision_config, load_lexicon, load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.dataset import EcnSplit, NlSample
from ripple.contracts.domain import DataMode
from ripple.contracts.explain import TemplateBlock
from ripple.contracts.identity import normalized_op
from ripple.contracts.lexicon import Lexicon
from ripple.contracts.result import AnalysisResult
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.validate import RequestError
from ripple.eval.llm_selection import Candidate, rank
from ripple.eval.nl_labels import same_change
from ripple.explain.render import Directory, fact_problem
from ripple.explain.templates import TEMPLATES, VERDICT_TEMPLATES, Use
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.llm.base import CallRecord, Guarded, JsonModel, LlmUnavailable, Schema
from ripple.llm.providers import make_model, router_from_settings
from ripple.llm.route import PROVIDERS, Router
from ripple.nl.pipeline import Models, read
from ripple.nl.vocab import MapVocabulary

# 제공자:모델[@effort]. effort가 없으면 모델 기본(Haiku·Opus 5.5 medium, Sonnet 5.5 high)
CANDIDATES = (
    "claude:claude-haiku-5-5",
    "claude:claude-haiku-5-5@low",
    "claude:claude-sonnet-5-5",
    "claude:claude-sonnet-5-5@low",
    "claude:claude-opus-5-5",
    "claude:claude-opus-5-5@low",
)
# 100만 토큰당 USD(입력, 출력). Claude: platform.claude.com/docs/en/about-claude/pricing(10-08 확인, Haiku는 프롬프트
# 10만 토큰 이하). 저장된 옛 측정의 Gemini 행은 기록으로만 남긴다
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
}
P95_LIMIT = {"rewrite": 10.0, "explain": 8.0}
CALL_TIMEOUT_S = 30.0
SELECTION = PROJECT_ROOT / "data" / "synthetic" / "20261020" / "nl" / "selection.jsonl"
OUT = PROJECT_ROOT / "eval" / "llm"

Outcome = tuple[str, str, Counter[str]]


@dataclass
class Tally:
    task: str
    model: str
    outcomes: Counter[str] = field(default_factory=Counter)
    latencies: list[float] = field(default_factory=list)
    detail: Counter[str] = field(default_factory=Counter)

    def rate(self, key: str) -> float:
        return self.outcomes[key] / max(sum(self.outcomes.values()), 1)

    def p(self, q: float) -> float:
        if not self.latencies:
            return float("inf")
        ordered = sorted(self.latencies)
        return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


class Replay:
    """이미 받은 응답을 돌려주는 모델(앱의 설명 고르기 함수를 그대로 쓰려고)."""

    name = "replay"

    def __init__(self, data: object) -> None:
        self.data = data

    def generate_json(self, prompt: str, schema: Schema, timeout_s: float) -> object:
        return self.data


def needs_help(sample: NlSample, vocab: MapVocabulary, lexicon: Lexicon, models: Models) -> bool:
    """앱이 다시 쓰기를 부르는 조건(ripple.agent.flow.Assistant._needs_help와 같은 rewrite_wanted)."""
    return rewrite_wanted(read(sample.text, (sample.ship_id,), vocab, lexicon, models))


def judge_rewrite(
    sample: NlSample, data: object, vocab: MapVocabulary, lexicon: Lexicon, models: Models
) -> tuple[str, str]:
    """(결과, 세부): exact / wrong(numeric·other) / incomplete / unaccepted(understood=false·검사 불통과)."""
    rewritten = accepted_rewrite(data, sample.text, vocab)
    if rewritten is None:
        understood = isinstance(data, dict) and bool(data.get("understood"))
        return "unaccepted", "understood=false" if not understood else "검사 불통과"
    reading = read(rewritten, (sample.ship_id,), vocab, lexicon, models)
    draft = reading.proposal.draft
    try:
        change = draft.to_change(ecn_id="X", title="x")
    except ValueError:
        return "incomplete", ",".join(draft.missing()) or "op"
    if same_change(change, sample.change, intent=False):
        return "exact", "intent ok" if change.intent is sample.change.intent else "intent 다름"
    got = [normalized_op(op) for op in change.ops]
    want = [normalized_op(op) for op in sample.change.ops]
    if len(got) == len(want) and all(_same_except_numbers(a, b) for a, b in zip(got, want, strict=True)):
        return "wrong", "numeric"
    return "wrong", "other"


def _same_except_numbers(a: dict[str, object], b: dict[str, object]) -> bool:
    numeric = {k for k, v in {**a, **b}.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return {k: v for k, v in a.items() if k not in numeric} == {k: v for k, v in b.items() if k not in numeric}


def judge_explanation(data: object, result: AnalysisResult, directory: Directory) -> tuple[str, Counter[str]]:
    """(결과, 블록 집계): used(앱이 씀)/fallback(기본 설명) + 블록별 verdict_wrong·verdict_ok·fact."""
    counts: Counter[str] = Counter()
    expected = VERDICT_TEMPLATES[result.verdict.level]
    for block in _parse_blocks(data):
        counts["blocks"] += 1
        if not isinstance(block, TemplateBlock):
            continue
        if block.template_id.startswith("verdict.") and block.template_id in TEMPLATES:
            counts["verdict_wrong" if block.template_id != expected else "verdict_ok"] += 1
            continue
        template = TEMPLATES.get(block.template_id)
        checkable = template is not None and template.use is Use.EXPLANATION
        if checkable and template is not None and len(block.entities) == len(template.slots):
            counts["fact"] += bool(fact_problem(block.template_id, block.entities, result))
    picked = pick_explanation(Guarded(Replay(data), DataMode.SYNTHETIC), result, directory)
    if picked is not None:
        counts["kept_rest"] += len(picked.blocks) - 4
    return ("used" if picked is not None else "fallback"), counts


def model_of(spec: str) -> JsonModel:
    provider, rest = spec.split(":", 1)
    name, _, effort = rest.partition("@")
    model = make_model(provider, name, effort or None)
    if model is None:
        raise SystemExit(f"{provider} 키가 없어요(.env)")
    return model


def run_model(
    model: JsonModel, jobs: list[tuple[str, object]], call: Callable[[JsonModel, str, object], Outcome], workers: int
) -> tuple[list[tuple[str, str, Counter[str], float]], list[CallRecord]]:

    def one(job: tuple[str, object]) -> tuple[str, str, Counter[str], float]:
        started = time.perf_counter()
        try:
            outcome, detail, counts = call(model, job[0], job[1])
        except LlmUnavailable as error:
            outcome, detail, counts = "error", str(error)[:60], Counter()
        return outcome, detail, counts, time.perf_counter() - started

    with ThreadPoolExecutor(max_workers=workers) as pool:
        done = list(pool.map(one, jobs))
    return done, list(getattr(model, "records", []))


def guard_router(guard: Guarded) -> Router:
    inner = getattr(guard, "_inner", None)
    if not isinstance(inner, Router):
        raise SystemExit("경로가 없어요(키·params/llm_v1.yaml 확인)")
    return inner


def cost(model: str, records: list[CallRecord]) -> float:
    price_in, price_out = PRICES.get(model.split("@", 1)[0], (0.0, 0.0))
    tokens_in = sum(r.input_tokens or 0 for r in records)
    tokens_out = sum(r.output_tokens or 0 for r in records)
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


def violations(t: Tally) -> float:
    return (t.detail["fact"] + t.detail["verdict_wrong"]) / max(t.detail["blocks"], 1)


TOLERANCE = {"rewrite": (0.005, 0.01), "explain": (0.005, 0.01)}  # (1차 지표 허용 폭, 2차 지표 허용 폭)


def order_of(rows: list[dict[str, Any]], task: str) -> list[str]:
    """채택 순서(사전 등록 규칙, ripple.eval.llm_selection.rank). rows는 결과 JSON의 작업별 줄."""
    candidates = []
    for row in rows:
        n = max(int(row["n"]), 1)
        outcomes = row["outcomes"]
        if task == "rewrite":
            primary, secondary = outcomes.get("wrong", 0) / n, outcomes.get("exact", 0) / n
        else:
            primary, secondary = float(row["violation_rate"]), outcomes.get("used", 0) / n
        candidates.append(Candidate(name=row["model"], primary=primary, secondary=secondary, p95_s=float(row["p95_s"])))
    primary_tol, secondary_tol = TOLERANCE[task]
    return rank(candidates, primary_tol, secondary_tol, P95_LIMIT[task])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="외부 생성 모델 비교 측정")
    parser.add_argument("--models", default=",".join(CANDIDATES))
    parser.add_argument("--forced", type=int, default=200, help="규칙이 읽는 문장 중 강제로 다시 쓰게 할 수")
    parser.add_argument("--explain", type=int, default=100, help="설명 고르기에 쓸 개발 분할 분석 수")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--yes", action="store_true", help="실제로 호출(비용 발생)")
    parser.add_argument("--route", action="store_true", help="params/llm_v1.yaml 경로(헤지)로 앱과 같이 잼")
    parser.add_argument("--recompute", action="store_true", help="저장된 결과로 채택 순서만 다시(호출 없음)")
    args = parser.parse_args(argv)
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.recompute:
        stored = json.loads((OUT / "llm_v1_selection.json").read_text("utf-8"))
        stored["order"] = {task: order_of(rows, task) for task, rows in stored["report"].items()}
        (OUT / "llm_v1_selection.json").write_text(
            json.dumps(stored, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print("채택 순서(다시 계산):", json.dumps(stored["order"], ensure_ascii=False))
        return 0
    settings = Settings.from_env({})
    config = load_config()
    generated = generate(config)
    snapshot = generated.snapshot
    index = GraphIndex(snapshot)
    vocab = MapVocabulary(snapshot)
    lexicon = load_lexicon(settings.lexicon_path)
    models = models_of(load_decision_config(settings.decision_path))
    rulebook, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    directory = directory_of(snapshot)

    samples = [NlSample.model_validate_json(line) for line in SELECTION.read_text("utf-8").splitlines() if line.strip()]
    hard = [s for s in samples if needs_help(s, vocab, lexicon, models)]
    easy = [s for s in samples if s not in hard]
    forced = random.Random(20261008).sample(easy, min(args.forced, len(easy)))
    rewrite_jobs: list[tuple[str, object]] = [("rule_fail", s) for s in hard]
    rewrite_jobs += [("forced", s) for s in forced]
    results: list[AnalysisResult] = []
    for ecn in [e for e in generated.ecns if e.split is EcnSplit.DEV]:
        if len(results) >= args.explain:
            break
        request = AnalysisRequest(change=ecn.change, as_of=config.scenario_date)
        try:
            results.append(analyze(index, request, rulebook, params))
        except RequestError:
            continue
    explain_jobs: list[tuple[str, object]] = [("dev", r) for r in results]
    specs = ["route"] if args.route else [m.strip() for m in args.models.split(",") if m.strip()]
    calls = len(specs) * (len(rewrite_jobs) + len(explain_jobs))
    print(f"선택 분할 {len(samples)}문장: 규칙이 못 읽는 문장 {len(hard)}, 강제 다시 쓰기 {len(forced)}")
    print(f"설명 {len(results)}건, 모델 {len(specs)}개 → 호출 {calls}회")
    if not args.yes:
        print("--yes를 주면 실제로 호출해요(비용 발생)")
        return 0

    guard = Guarded(router_from_settings(replace(settings, llm_providers=PROVIDERS)), DataMode.SYNTHETIC)

    def rewrite_call(model: JsonModel, group: str, sample: object) -> Outcome:
        assert isinstance(sample, NlSample)
        prompt = _rewrite_prompt(sample.text, vocab)
        if args.route:  # 앱과 같이: 작업 이름·수락 검사를 경로에 넘김
            data = guard.generate_json(
                prompt,
                REWRITE_SCHEMA,
                task="rewrite",
                accept=lambda answer: refused(answer) or accepted_rewrite(answer, sample.text, vocab) is not None,
            )
        else:
            data = model.generate_json(prompt, REWRITE_SCHEMA, CALL_TIMEOUT_S)
        outcome, detail = judge_rewrite(sample, data, vocab, lexicon, models)
        return outcome, f"{group}:{detail}", Counter({group: 1})

    def explain_call(model: JsonModel, group: str, result: object) -> Outcome:
        assert isinstance(result, AnalysisResult)
        prompt = _explain_prompt(result, directory)
        if args.route:
            data = guard.generate_json(
                prompt, EXPLAIN_SCHEMA, task="explain", accept=lambda answer: bool(_parse_blocks(answer))
            )
        else:
            data = model.generate_json(prompt, EXPLAIN_SCHEMA, CALL_TIMEOUT_S)
        outcome, counts = judge_explanation(data, result, directory)
        return outcome, group, counts

    report: dict[str, list[dict[str, object]]] = {"rewrite": [], "explain": []}
    tasks: tuple[tuple[str, list[tuple[str, object]], Callable[[JsonModel, str, object], Outcome]], ...] = (
        ("rewrite", rewrite_jobs, rewrite_call),
        ("explain", explain_jobs, explain_call),
    )
    for spec in specs:
        model_name = "route" if args.route else spec.split(":", 1)[1]
        for task, jobs, call in tasks:
            started = time.perf_counter()
            model = Replay(None) if args.route else model_of(spec)  # 경로 모드는 guard가 부름
            done, records = run_model(model, jobs, call, args.workers)
            tally = Tally(task=task, model=model_name)
            by_group: Counter[str] = Counter()
            for (group, _), (outcome, detail, counts, latency) in zip(jobs, done, strict=True):
                tally.outcomes[outcome] += 1
                tally.latencies.append(latency)
                tally.detail.update(counts)
                tally.detail[f"{outcome}:{detail}"] += 1
                by_group[f"{group}:{outcome}"] += 1
            row = {
                "model": model_name,
                "n": len(jobs),
                "outcomes": dict(tally.outcomes),
                "by_group": dict(by_group),
                "detail": dict(tally.detail),
                "violation_rate": round(violations(tally), 4) if task == "explain" else None,
                "p50_s": round(tally.p(0.5), 2),
                "p95_s": round(tally.p(0.95), 2),
                "mean_s": round(statistics.mean(tally.latencies), 2) if tally.latencies else None,
                "cost_usd": round(cost(model_name, records), 4),
                "tokens_in": sum(r.input_tokens or 0 for r in records),
                "tokens_out": sum(r.output_tokens or 0 for r in records),
                "wall_s": round(time.perf_counter() - started, 1),
            }
            report[task].append(row)
            print(json.dumps({"task": task, **row}, ensure_ascii=False)[:700], flush=True)
    order = {task: order_of(report[task], task) for task in report}
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "candidates": specs,
        "samples": {"rule_fail": len(hard), "forced": len(forced), "explain": len(results)},
        "order": order,
        "report": report,
    }
    name = "llm_v1_route.json" if args.route else "llm_v1_selection.json"
    if args.route:  # 경로 모드의 비용·토큰은 경로 안 모델들의 기록 합
        router = guard_router(guard)
        payload["route_records"] = {
            m.name: {
                "calls": len(getattr(m, "records", [])),
                "ok": sum(r.ok for r in getattr(m, "records", [])),
                "cost_usd": round(cost(m.name, list(getattr(m, "records", []))), 4),
            }
            for m in {id(m): m for r in router.routes.values() for m in r.models}.values()
        }
    (OUT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("채택 순서:", json.dumps(order, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
