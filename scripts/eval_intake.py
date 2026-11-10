"""E9 문서 접수 평가(docs/evaluation.md 3절, `ripple/eval/intake_docs.py`): 합성 설계변경 문서 → 확인표 채점.

  uv run python scripts/eval_intake.py                       개발 분할 120문서, 규칙 경로(외부 호출 없음)
  uv run python scripts/eval_intake.py --llm --count 30      개발 분할 30문서, 외부 AI 경로(합성 문서만 보냄, .env 키,
                                                             호출 비용이 든다)
  uv run python scripts/eval_intake.py --split eval --final  평가 분할 — 방법을 고정한 뒤 최종 인증 때 한 번만

기준(구현 전 고정, docs/evaluation.md): 사람에게 보이지 않은 정답 0건 · 문제 표시 재현율(지금 값 다름·개정 다름)
≥ 0.95 · 지원 안 함이 경고 없이 8종으로 들어간 경우 0건 · AI 경로 항목 재현율(연산·대상·값까지 정확) ≥ 0.9.
미달이면 종료 코드 1.
결과는 eval/reports/intake_e9_<분할>_<경로>.json.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ripple.agent.intake import IntakeService
from ripple.agent.resources import AssistantResources
from ripple.config.loaders import load_decision_config, load_lexicon, load_params, load_rulebook
from ripple.config.settings import Settings
from ripple.contracts.domain import DataMode
from ripple.contracts.intake import IntakeIssueCode
from ripple.engine.index import GraphIndex
from ripple.eval.intake_docs import DocScore, IntakeDoc, Summary, intake_docs, score, summarize
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.generator.nl import load_nl_lexicon
from ripple.llm.base import Guarded
from ripple.llm.providers import router_from_settings

REPORTS = Path(__file__).resolve().parents[1] / "eval" / "reports"
FLAG_RECALL_MIN = 0.95
LLM_RECALL_MIN = 0.9
FLAGGED = (IntakeIssueCode.FROM_MISMATCH.value, IntakeIssueCode.REVISION_MISMATCH.value)


def _service(llm: bool, data_dir: Path, routes: Path | None = None) -> tuple[IntakeService, AssistantResources]:
    env = {"RIPPLE_LLM": "claude" if llm else "off", "RIPPLE_DATA_DIR": str(data_dir)}
    if routes is not None:
        env["RIPPLE_LLM_ROUTES_PATH"] = str(routes)
    settings = Settings.from_env(env)
    snapshot = generate(load_config()).snapshot
    resources = AssistantResources.build(
        snapshot,
        GraphIndex(snapshot),
        load_lexicon(settings.lexicon_path),
        load_decision_config(settings.decision_path),
        load_rulebook(settings.rules_path),
        load_params(settings.params_path),
        DataMode.SYNTHETIC,
    )
    model = router_from_settings(settings) if llm else None
    guard = Guarded(model, DataMode.SYNTHETIC)
    if llm and not guard.usable:
        raise SystemExit("외부 AI를 쓸 수 없어요(.env의 ANTHROPIC_API_KEY 확인)")
    return IntakeService(resources, llm=guard), resources


def _run(service: IntakeService, doc: IntakeDoc, ship_id: str) -> tuple[DocScore, str, float]:
    started = time.perf_counter()
    proposal = service.propose(doc.text, (ship_id,), lambda _: None)
    return score(doc, proposal), proposal.extractor, time.perf_counter() - started


def _share(hit: int, total: int) -> str:
    return "-" if total == 0 else f"{hit}/{total} ({hit / total:.1%})"


def _report(summary: Summary, extractors: dict[str, int], seconds: list[float]) -> list[str]:
    lines = [f"문서 {summary.docs}개 · 경로 {extractors} · 문서당 평균 {sum(seconds) / max(1, len(seconds)):.2f}초"]
    for kind, counts in summary.outcomes.items():
        total = sum(counts.values())
        lines.append(f"  {kind:<15} {total:>4}건  " + " · ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    for code, (hit, total) in summary.expected.items():
        lines.append(f"  문제 표시 {code:<18} {_share(hit, total)}")
    lines.append(f"  항목 {summary.items}개 중 정답 밖 {summary.stray_items}개(그중 막힘 {summary.stray_blocking})")
    return lines


def _criteria(summary: Summary, llm: bool) -> list[tuple[str, bool, str]]:
    lost = sum(counts.get("lost", 0) for counts in summary.outcomes.values())
    flags = [summary.expected.get(code, (0, 0)) for code in FLAGGED]
    hit, total = sum(f[0] for f in flags), sum(f[1] for f in flags)
    silent = summary.outcomes.get("unsupported", {}).get("silent", 0)
    rows = [
        ("사람에게 보이지 않은 정답 0건", lost == 0, f"{lost}건"),
        (
            f"문제 표시 재현율(지금 값·개정) ≥ {FLAG_RECALL_MIN}",
            total == 0 or hit / total >= FLAG_RECALL_MIN,
            _share(hit, total),
        ),
        ("지원 안 함이 경고 없이 8종으로 0건", silent == 0, f"{silent}건"),
    ]
    if llm:
        recall = summary.rate("change", "exact_ready", "exact_flagged")
        rows.append(
            (
                f"AI 경로 항목 재현율 ≥ {LLM_RECALL_MIN}",
                recall is not None and recall >= LLM_RECALL_MIN,
                f"{recall:.1%}",
            )
        )
    return rows


def _failures(scores: list[DocScore]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for doc in scores:
        for s in doc.truths:
            missed = s.truth.expect - s.expected_hits
            if s.outcome in ("lost", "wrong_silent", "silent", "wrong_warned", "exact_flagged") or missed:
                out.append(
                    {
                        "doc": doc.doc.doc_id,
                        "style": doc.doc.style,
                        "kind": s.truth.kind,
                        "outcome": s.outcome,
                        "tags": list(s.truth.tags),
                        "missed_flags": sorted(c.value for c in missed),
                        "codes": sorted(s.codes),
                        "text": doc.doc.text[s.truth.start : s.truth.end],
                    }
                )
    return out


def main(argv: list[str] | None = None) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="E9 문서 접수 평가")
    parser.add_argument("--split", choices=("dev", "eval"), default="dev")
    parser.add_argument("--final", action="store_true", help="평가 분할을 연다(최종 인증 한 번)")
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--llm", action="store_true", help="외부 AI 경로(합성 문서만, 비용 발생)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--routes", type=Path, help="경로 설정 파일(기본 params/llm_v1.yaml) — 모델 비교용")
    parser.add_argument("--name", default="", help="결과 파일 이름 꼬리(예: haiku → intake_e9_dev_llm_haiku.json)")
    args = parser.parse_args(argv)
    if args.split == "eval" and not args.final:
        parser.error("평가 분할은 --final과 함께만 열어요")
    config = load_config()
    generated = generate(config)
    docs = intake_docs(
        generated.snapshot, args.count, generated.seed, config.scenario_date, load_nl_lexicon(), args.split
    )
    ship_id = generated.snapshot.ships[0].ship_id
    with tempfile.TemporaryDirectory() as tmp:
        service, _ = _service(args.llm, Path(tmp), args.routes)
        with ThreadPoolExecutor(max_workers=max(1, args.workers if args.llm else 1)) as pool:
            results = list(pool.map(lambda d: _run(service, d, ship_id), docs))
    scores = [r[0] for r in results]
    extractors: dict[str, int] = {}
    for _, extractor, _ in results:
        extractors[extractor] = extractors.get(extractor, 0) + 1
    summary = summarize(scores)
    path_name = "llm" if args.llm else "rule"
    print("\n".join(_report(summary, extractors, [r[2] for r in results])))
    criteria = _criteria(summary, args.llm)
    for name, ok, value in criteria:
        print(f"{'충족' if ok else '미달'}  {name}: {value}")
    REPORTS.mkdir(parents=True, exist_ok=True)
    suffix = f"_{args.name}" if args.name else ""
    out = REPORTS / f"intake_e9_{args.split}_{path_name}{suffix}.json"
    payload = {
        "split": args.split,
        "path": path_name,
        "routes": args.routes.name if args.routes else "llm_v1.yaml",
        "seed": generated.seed,
        "docs": summary.docs,
        "seconds_per_doc": round(sum(r[2] for r in results) / max(1, len(results)), 2),
        "extractors": extractors,
        "outcomes": summary.outcomes,
        "expected_flags": {k: list(v) for k, v in summary.expected.items()},
        "items": summary.items,
        "stray_items": summary.stray_items,
        "stray_blocking": summary.stray_blocking,
        "by_tag": summary.by_tag,
        "by_style": summary.by_style,
        "criteria": [{"name": n, "ok": ok, "value": v} for n, ok, v in criteria],
        "failures": _failures(scores),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"썼어요: {out}")
    return 0 if all(ok for _, ok, _ in criteria) else 1


if __name__ == "__main__":
    sys.exit(main())
