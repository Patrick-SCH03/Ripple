"""엑셀 열 매핑 보정(판단 계층 열 문 — docs/input.md(엑셀 양식) 4절, docs/input.md(판단 계층) 3·4절).

합성 변형 엑셀(ripple/ingest/variants.py 개발 변형: 요소를 파일마다 섞고 시트마다 앞 40행)로
학습 분할 → 점수기 가중치, 온도 분할 → 온도·검정 문턱 목록, τ 분할 → 열 문 자동 진행 문턱,
집합 분할 → 되묻기 집합 q̂를 정해 params/column_v1.yaml을 쓴다. 정확 일치 열은 판단 밖이라 보정에 넣지 않는다.

τ·집합·선택·평가 분할은 파일마다 판단 열 하나만 쓴다(한 파일의 열끼리는 상관되므로 독립 단위를 파일로).
개발 중 점검은 선택 분할(600파일)에서만 한다: E6 열 매핑 정확도(개입 전, 시트·머리글·항목이 모두 맞음), 기준선
'필드 사전만', 처음 보는 머리글, 자동 진행 비율·오류, 되묻기 집합 포함률, 단위 해석. 평가 분할 최종 인증은 --certify로
한 번만 한다.

실행: uv run python scripts/calibrate_columns.py [--workers 8] [--out params/column_v1.yaml]
      [--report eval/columns/v2_selection.md] [--certify]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import random
import sys
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import yaml

from ripple.config.loaders import load_decision_config
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.decision import (
    NONE_OPTION,
    ChoiceQuestion,
    DecisionBackend,
    DecisionConfig,
    DecisionTopic,
    GateKind,
    Option,
    Route,
    ScorerModel,
)
from ripple.contracts.domain import GraphSnapshot
from ripple.contracts.ingest import ColumnMethod, SheetMapping, UnitState
from ripple.decide.conformal import prediction_set, ranked
from ripple.decide.policy import Decision, ScoredCase, Splits, Unit, calibrate_gate, probabilities, shows_set
from ripple.decide.risk import clopper_pearson_lower
from ripple.decide.router import decide_unit
from ripple.decide.scorer import Example, Features, train
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.ingest.columns import (
    ColumnJudgment,
    Featurizer,
    References,
    exact_key,
    judge_sheet,
    read_columns,
    reference_sets,
    unit_state,
)
from ripple.ingest.fields import default_fields
from ripple.ingest.normalize import unit_factor
from ripple.ingest.tables import HeaderIndex, SheetGuess, guess_sheets
from ripple.ingest.template import SHEET_BY_KEY, Sheet
from ripple.ingest.variants import default_vocabulary, dev_style, make_variant
from ripple.ingest.workbook import RawSheet, read_workbook

SEEDS = {"train": 100_000, "temperature": 200_000, "selection": 300_000, "tau": 400_000, "set": 500_000}
SEEDS |= {"eval": 600_000, "described": 700_000}
SIZES = {"train": 20, "temperature": 12, "selection": 600, "described": 10, "tau": 2000, "set": 1500, "eval": 1500}
MIN_SET_UNITS = 300  # 집합 분할: 필터 뒤 단위 300+(모자라면 파일을 늘린다)
MAX_SET_FILES = 6000
ITERATIONS = 300
E6_TARGET = 0.95


@dataclass(frozen=True, slots=True)
class Row:
    """파일 열 하나의 제안과 정답."""

    seed: int
    file_sheet: str
    position: int
    method: str  # exact · decided · unread(그 시트를 양식 시트로 읽지 않음)
    truth_key: str | None
    proposal: str | None  # 시트 안 배정 뒤 제안
    baseline: str | None  # 필드 사전만(정확·동의어 일치, 앞 열 먼저)
    sheet_ok: bool
    header_ok: bool
    unit_ok: bool
    unit_resolved: bool | None  # 정답 항목에 단위가 있을 때: 단위가 정해졌는가
    ready: bool
    unseen: bool  # 정답 항목의 머리글이 필드 사전에 없음
    option_ids: tuple[str, ...] = ()
    scores: tuple[float, ...] = ()
    features: tuple[Features, ...] = ()
    label: str | None = None

    @property
    def sound(self) -> bool:
        return self.sheet_ok and self.header_ok and self.unit_ok

    @property
    def correct(self) -> bool:
        """개입 전 제안이 맞음: 시트·머리글 행·항목이 모두 정답."""
        return self.sheet_ok and self.header_ok and self.proposal == self.truth_key

    def unit(self) -> Unit:
        case = ScoredCase(self.option_ids, self.scores, self.label or NONE_OPTION)
        return Unit((Decision(DecisionTopic.EXCEL_COLUMN, case),), ready=self.ready, sound=self.sound)


Truth = dict[str, SheetMapping]


@dataclass(frozen=True, slots=True)
class _Worker:
    snapshot: GraphSnapshot
    featurizer: Featurizer
    index: HeaderIndex


_WORKER: list[_Worker] = []


def _init() -> None:
    fields = default_fields()
    _WORKER[:] = [_Worker(generate(load_config()).snapshot, Featurizer(fields), HeaderIndex(fields))]


def _task(args: tuple[int, str, dict[str, float], float]) -> list[Row]:
    """파일 하나(시드). mode: all(모든 열, 특징 포함) · one(판단 열 하나) · e6(양식 열 하나 + 판단 열 하나)."""
    seed, mode, weights, temperature = args
    if not _WORKER:
        _init()
    worker = _WORKER[0]
    featurizer, index = worker.featurizer, worker.index
    variant = make_variant(worker.snapshot, f"F{seed}", dev_style(random.Random(seed)), seed)
    raw = read_workbook(variant.data)
    truth = {s.file_sheet: s for s in variant.truth.sheets}
    guesses = {g.file_sheet: g for g in guess_sheets(raw, index)}
    refs = reference_sets(raw, list(guesses.values()), index)
    rng = random.Random(seed * 7 + 1)
    if mode == "all":
        rows = []
        for guess in guesses.values():
            rows += _judge(seed, raw, guess, truth, featurizer, index, weights, temperature, refs, features=True)
        rows += _unread(seed, guesses, truth)
        return rows
    decided = _decided_candidates(raw, guesses)
    picked: list[Row] = []
    if decided:
        name, position = rng.choice(decided)
        rows = _judge(seed, raw, guesses[name], truth, featurizer, index, weights, temperature, refs)
        picked += [r for r in rows if r.position == position and r.method == "decided"]
    if mode == "e6":
        population = [(s.file_sheet, c.position) for s in truth.values() if s.template for c in s.columns]
        name, position = rng.choice(population)
        guess = guesses[name]
        rows = (
            _judge(seed, raw, guess, truth, featurizer, index, weights, temperature, refs)
            if guess.template
            else _unread(seed, {name: guess}, truth)
        )
        found = [replace(r, method=f"e6:{r.method}") for r in rows if r.position == position]
        picked += found or [_missing(seed, name, position, truth)]
    return picked


def _missing(seed: int, name: str, position: int, truth: Truth) -> Row:
    """정답 열인데 제안에 없는 열(머리글 행을 잘못 잡아 그 위치가 열로 안 잡힘 등)."""
    key = next((c.key for c in truth[name].columns if c.position == position), None)
    return Row(seed, name, position, "e6:missing", key, None, None, False, False, True, None, False, False)


def _decided_candidates(raw: dict[str, RawSheet], guesses: dict[str, SheetGuess]) -> list[tuple[str, int]]:
    found = []
    for name, guess in guesses.items():
        if guess.template is None or guess.header is None:
            continue
        sheet = SHEET_BY_KEY[guess.template]
        found += [
            (name, fc.position) for fc in read_columns(raw[name], guess.header.rows) if exact_key(sheet, fc) is None
        ]
    return found


def _judge(
    seed: int,
    raw: dict[str, RawSheet],
    guess: SheetGuess,
    truth: Truth,
    featurizer: Featurizer,
    index: HeaderIndex,
    weights: dict[str, float],
    temperature: float,
    refs: References,
    features: bool = False,
) -> list[Row]:
    if guess.template is None or guess.header is None:
        return []
    sheet = SHEET_BY_KEY[guess.template]
    entry = truth[guess.file_sheet]
    truth_keys = {c.position: c for c in entry.columns}
    sheet_ok = entry.template == guess.template
    header_ok = tuple(guess.header.rows) == tuple(entry.header_rows)
    judged = judge_sheet(
        sheet,
        raw[guess.file_sheet],
        guess.header.rows,
        guess.certain,
        featurizer,
        weights,
        temperature,
        references=refs,
    )
    baseline = _baseline(judged.columns, sheet, index)
    rows = []
    for j in judged.columns:
        fc = j.file_column
        mapped = truth_keys.get(fc.position)
        truth_key = mapped.key if mapped is not None else None
        unit_ok, resolved = True, None
        if sheet_ok and truth_key is not None and (column := sheet.column(truth_key)).unit:
            state, _, factor, _ = unit_state(column, fc, exact_key(sheet, fc) == truth_key)
            resolved = state is UnitState.CONFIRMED
            wanted = unit_factor(mapped.unit, column.unit) if mapped is not None and mapped.unit else None
            unit_ok = not resolved or (factor is not None and wanted is not None and factor == wanted)
        seen = truth_key is not None and sheet_ok and any(index.key(sheet, n) == truth_key for n in fc.names)
        case = j.case
        label = None
        if case is not None:
            ids = case.question.option_ids
            label = truth_key if sheet_ok and truth_key in ids else NONE_OPTION
        rows.append(
            Row(
                seed=seed,
                file_sheet=guess.file_sheet,
                position=fc.position,
                method="decided" if j.method is ColumnMethod.DECIDED and case is not None else "exact",
                truth_key=truth_key,
                proposal=j.key,
                baseline=baseline.get(fc.position),
                sheet_ok=sheet_ok,
                header_ok=header_ok,
                unit_ok=unit_ok,
                unit_resolved=resolved,
                ready=j.ready,
                unseen=truth_key is not None and not seen,
                option_ids=case.question.option_ids if case else (),
                scores=tuple(j.score_map[i] for i in case.question.option_ids) if case and j.score_map else (),
                features=case.features if case and features else (),
                label=label,
            )
        )
    return rows


def _unread(seed: int, guesses: dict[str, SheetGuess], truth: Truth) -> list[Row]:
    """정답은 양식 시트인데 읽지 않음으로 제안한 시트의 열(E6에서 틀림으로 센다)."""
    rows = []
    for name, guess in guesses.items():
        entry = truth[name]
        if guess.template is not None or entry.template is None:
            continue
        for column in entry.columns:
            rows.append(
                Row(
                    seed,
                    name,
                    column.position,
                    "unread",
                    column.key,
                    None,
                    None,
                    False,
                    False,
                    True,
                    None,
                    False,
                    False,
                )
            )
    return rows


def _baseline(judgments: Sequence[ColumnJudgment], sheet: Sheet, index: HeaderIndex) -> dict[int, str | None]:
    """기준선 '필드 사전만': 머리글이 양식 머리글·사전 동의어와 같으면 그 항목(앞 열 먼저), 아니면 해당 없음."""
    used: set[str] = set()
    found: dict[int, str | None] = {}
    for j in sorted(judgments, key=lambda x: x.file_column.position):
        key = next((k for n in j.file_column.names if (k := index.key(sheet, n))), None)
        found[j.file_column.position] = key if key and key not in used else None
        if key:
            used.add(key)
    return found


def _run(
    pool: ProcessPoolExecutor, split: str, count: int, mode: str, weights: dict[str, float], temperature: float
) -> list[Row]:
    start = SEEDS[split]
    tasks = [(start + i, mode, weights, temperature) for i in range(count)]
    rows: list[Row] = []
    for chunk in pool.map(_task, tasks, chunksize=8):
        rows += chunk
    return rows


def _digest(split: str, count: int) -> str:
    vocab = default_vocabulary()
    text = f"{split}:{SEEDS[split]}:{count}:{vocab.version}:{default_fields().version}"
    return f"COL-{hashlib.sha256(text.encode()).hexdigest()[:16]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="엑셀 열 매핑(열 문) 보정과 사전 점검")
    parser.add_argument("--targets", type=Path, default=PROJECT_ROOT / "params" / "decision_v0.yaml")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "params" / "column_v1.yaml")
    parser.add_argument("--version", default="column-v2")
    parser.add_argument("--report", type=Path, default=PROJECT_ROOT / "eval" / "columns" / "v2_selection.md")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument(
        "--scale", type=float, default=1.0, help="분할 크기 배율(개발 중 빠른 확인용, 산출물은 1.0으로)"
    )
    parser.add_argument("--certify", action="store_true", help="평가 분할 최종 인증(한 번만)")
    args = parser.parse_args(argv)
    if sys.stdout.encoding.lower() != "utf-8" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sizes = {k: max(1, round(v * args.scale)) for k, v in SIZES.items()}
    base = load_decision_config(args.targets)  # 합격 기준을 보기 전에 고정한 목표값
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init) as pool:
        train_rows = _run(pool, "train", sizes["train"], "all", {}, 1.0)
        examples = [
            Example(r.option_ids, r.features, r.label or NONE_OPTION)
            for r in train_rows
            if r.method == "decided" and r.sheet_ok and r.header_ok
        ]
        weights = train(examples, iterations=ITERATIONS)
        scorer = ScorerModel(
            topic=DecisionTopic.EXCEL_COLUMN,
            backend=DecisionBackend.LOCAL,
            weights=weights,
            n_train=len(examples),
            train_split=_digest("train", sizes["train"]),
        )
        print(f"점수기 학습: 판단 열 {len(examples)}개, 특징 {len(weights)}개 ({_since(started)})")
        temperature_rows = [
            r for r in _run(pool, "temperature", sizes["temperature"], "all", weights, 1.0) if r.method == "decided"
        ]
        tau_rows = _run(pool, "tau", sizes["tau"], "one", weights, 1.0)
        set_files = sizes["set"]
        while True:
            set_rows = _run(pool, "set", set_files, "one", weights, 1.0)
            splits = Splits(
                temperature=_digest("temperature", sizes["temperature"]),
                tau=_digest("tau", sizes["tau"]),
                set=_digest("set", set_files),
            )
            gate, topics = calibrate_gate(
                GateKind.COLUMN,
                DecisionBackend.LOCAL,
                base.targets,
                [r.unit() for r in temperature_rows],
                [r.unit() for r in tau_rows],
                [r.unit() for r in set_rows],
                splits,
            )
            short = [t for t in topics if 0 < t.n_set < MIN_SET_UNITS]
            if not short or set_files >= MAX_SET_FILES or args.scale < 1:
                break
            set_files = min(MAX_SET_FILES, set_files * 2)
            print(
                f"집합 분할 필터 뒤 단위가 모자라 {set_files}파일로 늘려요: {[(t.topic.value, t.n_set) for t in short]}"
            )
        config = DecisionConfig(
            version=args.version,
            updated=date.today(),
            targets=base.targets,
            scorers=(scorer,),
            topics=topics,
            gates=(gate,),
        )
        _write_config(args.out, config, scorer.train_split, splits)
        temperature = topics[0].temperature
        print(
            f"보정 산출물: τ = {gate.auto_threshold}, 온도 {temperature:.3f}, "
            f"q̂ {topics[0].set_qhat:.4f} ({_since(started)})"
        )
        print(f"썼어요: {args.out}")
        split = "eval" if args.certify else "selection"
        checked = _run(pool, split, sizes[split], "e6", weights, temperature)
        described = _run(pool, "described", sizes["described"], "all", weights, temperature)
    report = _report(config, split, checked, described, len(tau_rows), len(set_rows), sizes)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8", newline="\n")
    print(report)
    print(f"썼어요: {args.report} ({_since(started)})")
    return 0


def _routes(rows: Iterable[Row], config: DecisionConfig) -> list[tuple[Row, Route, tuple[str, ...], str]]:
    gate = config.gate(GateKind.COLUMN)
    assert gate is not None
    calibrations = {t.topic: t for t in config.topics}
    out = []
    for r in rows:
        question = ChoiceQuestion(
            question_id=f"{r.seed}:{r.position}",
            topic=DecisionTopic.EXCEL_COLUMN,
            mention=str(r.position),
            options=tuple(Option(option_id=i, label=i) for i in r.option_ids),
        )
        (answer,) = decide_unit(
            [(question, dict(zip(r.option_ids, r.scores, strict=True)))],
            calibrations,
            gate,
            config.targets.max_choices,
            config.version,
            ready=r.ready,
        )
        out.append((r, answer.route, answer.prediction_set, answer.top))
    return out


def _shown_sets(
    rows: Sequence[Row], routed: Sequence[tuple[Row, Route, tuple[str, ...], str]], config: DecisionConfig
) -> list[tuple[Row, tuple[str, ...]]]:
    """집합을 보이는 판단(정책 shows_set과 같은 정의)과 그 conformal 집합(보일 수 없어 다시 묻는 큰 집합 포함)."""
    gate = config.gate(GateKind.COLUMN)
    assert gate is not None
    calibration = config.topics[0]
    shown = []
    for r, (_, route, _, _) in zip(rows, routed, strict=True):
        probs = probabilities(ScoredCase(r.option_ids, r.scores, r.label or NONE_OPTION), calibration.temperature)
        top, top_prob = ranked(probs)[0]
        if shows_set(top, top_prob, route is Route.AUTO, gate.auto_threshold):
            shown.append((r, prediction_set(probs, calibration.set_qhat)))
    return shown


def _pct(n: int, d: int) -> str:
    return f"{n / d:.1%} ({n}/{d})" if d else "—"


def _report(
    config: DecisionConfig,
    split: str,
    checked: list[Row],
    described: list[Row],
    n_tau: int,
    n_set: int,
    sizes: dict[str, int],
) -> str:
    gate = config.gate(GateKind.COLUMN)
    topic = config.topics[0]
    e6 = [r for r in checked if r.method.startswith("e6:")]
    decided = [r for r in checked if r.method == "decided"]
    correct = sum(r.correct for r in e6)
    lower = clopper_pearson_lower(correct, len(e6)) if e6 else 0.0
    baseline = sum(r.sheet_ok and r.header_ok and r.baseline == r.truth_key for r in e6)
    by_method = Counter(r.method for r in e6)
    unseen = [r for r in e6 if r.unseen]
    routed = _routes(decided, config)
    autos = [(r, s) for r, route, s, _ in routed if route is Route.AUTO]
    auto_errors = sum(not (r.sound and r.label == s[0]) for r, s in autos)
    shown = _shown_sets(decided, routed, config)
    covered = sum((r.label or NONE_OPTION) in s for r, s in shown)
    routes = Counter(route.value for _, route, _, _ in routed)
    units = [r for r in e6 if r.unit_resolved is not None]
    resolved = [r for r in units if r.unit_resolved]
    lines = [
        f"# 엑셀 열 매핑 {config.version} — {'평가 분할 최종 인증' if split == 'eval' else '선택 분할 사전 점검'}",
        "",
        f"작성 {config.updated.isoformat()}. `scripts/calibrate_columns.py`가 만든다. 합성 변형 엑셀(생성기 "
        f"{default_vocabulary().version}, 필드 사전 {default_fields().version}) 기준 보정이며 "
        "실제 회사 엑셀과 분포가 다를 수 있다"
        "(현업 머리글은 현장 의견으로 받는다).",
        "",
        "## 보정 산출물",
        "",
        f"- 열 문 자동 진행 문턱 τ = {gate.auto_threshold if gate else None} "
        f"(τ 분할 {n_tau}단위 = 판단 열이 있는 파일마다 열 하나)",
        f"- excel_column: 온도 {topic.temperature:.3f}, q̂ {topic.set_qhat:.4f} (온도 {topic.n_temperature}열, "
        f"집합 {topic.n_set}단위 = 집합 분할에서 판단 열이 있는 {n_set}파일 중 집합을 보인 판단)",
        f"- 점수기: 특징 {len(config.scorers[0].weights)}개, 학습 판단 열 {config.scorers[0].n_train}개"
        f"({sizes['train']}파일의 모든 판단 열)",
        "",
        f"## E6 열 매핑 정확도({split} 분할 {len(e6)}파일 × 양식 열 하나, 개입 전)",
        "",
        "| 지표 | 값 | 기준 | 통과 |",
        "|---|---|---|---|",
        f"| 정확도(시트·머리글 행·항목 모두 맞음) | {_pct(correct, len(e6))} | ≥ {E6_TARGET:.2f} | "
        f"{'통과' if e6 and correct / len(e6) >= E6_TARGET else '미달'} |",
        f"| 정확도 95% 하한(Clopper–Pearson) | {lower:.3f} | — | — |",
        f"| 기준선 '필드 사전만' | {_pct(baseline, len(e6))} | — | — |",
        f"| 처음 보는 머리글(사전에 없음)에서 정확도 | {_pct(sum(r.correct for r in unseen), len(unseen))} | — | — |",
    ]
    for method in sorted(by_method):
        part = [r for r in e6 if r.method == method]
        lines.append(f"| └ {method.removeprefix('e6:')} 열 | {_pct(sum(r.correct for r in part), len(part))} | — | — |")
    lines += [
        f"| 단위가 필요한 열: 단위 정해짐 | {_pct(sum(bool(r.unit_resolved) for r in units), len(units))} | — | — |",
        f"| 단위가 정해진 열: 단위 맞음 | {_pct(sum(r.unit_ok for r in resolved), len(resolved))} | — | — |",
        "",
        f"## 판단 열 경로({split} 분할 {len(decided)}파일 × 판단 열 하나)",
        "",
        "| 지표 | 값 |",
        "|---|---|",
        f"| 자동 진행 비율 | {_pct(len(autos), len(decided))} |",
        f"| 자동 진행 오류(정답 또는 시트·머리글·단위가 틀림) | {_pct(auto_errors, len(autos))} |",
        f"| 되묻기 집합(집합을 보이는 판단)의 정답 포함률 | {_pct(covered, len(shown))} "
        f"(목표 ≥ {1 - config.targets.alpha:.2f}) |",
        f"| 되묻기 집합 평균 크기 | {sum(len(s) for _, s in shown) / len(shown):.2f} |"
        if shown
        else "| 되묻기 집합 평균 크기 | — |",
        f"| 경로 | {', '.join(f'{k} {v}' for k, v in sorted(routes.items()))} |",
        "",
        f"## 기술 통계({len({r.seed for r in described})}파일의 모든 열)",
        "",
    ]
    d_all = [r for r in described if r.method != "unread"]
    d_decided = [r for r in d_all if r.method == "decided"]
    routed_all = _routes(d_decided, config)
    lines += [
        "| 지표 | 값 |",
        "|---|---|",
        f"| 열 | {len(d_all)} (정확 일치 {sum(r.method == 'exact' for r in d_all)}, 판단 {len(d_decided)}) |",
        f"| 제안 정확도 | {_pct(sum(r.correct for r in d_all), len(d_all))} |",
        f"| 판단 열 자동 진행 | {_pct(sum(route is Route.AUTO for _, route, _, _ in routed_all), len(d_decided))} |",
        "",
        "- 정확도는 사람이 고치기 전 제안(시트 안 배타 배정 뒤)을 정답 매핑과 비교한다. "
        "시트·머리글 행을 잘못 잡은 열은 틀림.",
        "- 판단 열 = 머리글이 양식 머리글과 정확히 같지 않은 열(정확 일치 열은 판단 밖).",
        "- 기준선은 같은 표 찾기 위에서 필드 사전 일치만 쓴다(정확 일치 포함, 사전에 없으면 해당 없음).",
    ]
    return "\n".join(lines) + "\n"


def _write_config(path: Path, config: DecisionConfig, train_hash: str, splits: Splits) -> None:
    body = config.model_dump(mode="json")
    header = (
        f"# 엑셀 열 매핑 보정 산출물 {config.version} — 형식: ripple/contracts/decision.py, "
        "설계: docs/input.md(엑셀 양식) 4절\n"
        "# scripts/calibrate_columns.py가 만든다(손으로 고치지 않는다). 목표값(targets)은 decision_v0.yaml과 같다.\n"
        "# 합성 변형 엑셀 기준 보정. 자료 해시(학습·온도·τ·집합): "
        f"{train_hash}, {splits.temperature}, {splits.tau}, {splits.set}\n"
    )
    path.write_text(header + yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")


def _since(started: float) -> str:
    return f"{time.perf_counter() - started:.0f}초"


if __name__ == "__main__":
    sys.exit(main())
