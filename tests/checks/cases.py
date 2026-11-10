"""과거 사례 검사(docs/records.md '합성 과거 사례', ripple/cases): 합성 묶음·비슷한 사례 찾기·실데이터 모드.

- 합성: 결정성(같은 지도 → 같은 묶음·같은 답) · 모두 synthetic · 예측 = 엔진 재분석 ·
  실적 = 숨긴 모델 재계산(반려·보류는 실적 없음) · 개발 분할에서만, 화면 샘플과 겹치지 않음 ·
  마감 뒤 사례의 교훈 일관성 · 첫 요청은 기다리지 않음(만드는 중) · 만드는 시간 상한 ·
  상태 갱신 지도는 뿌리 지도 묶음 · 다른 세계면 만들 수 없음.
- 찾기: 같은 연산만 · 같은 블록이 앞 · 점수 순 · 문턱 · 자기 자신 제외 · 요약 숫자 = 사례 값(오차 통계 없음) ·
  샘플 두 건.
- 실데이터: 합성 사례 없음 — 종료 · 실적 있음 · 실데이터 본문인 기록만.
"""

from __future__ import annotations

import dataclasses
import logging
import math
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from harness import Checker, nominal

from checks.records import _actor, _body, _do, _do_line, _save, _who
from ripple.api.samples import pick_samples
from ripple.api.snapshot_info import default_info
from ripple.cases import (
    CaseLibrary,
    CaseShelf,
    EngineKit,
    MapLookup,
    StoredCase,
    build_library,
    contradiction,
    features_of,
    find_cases,
    load_settings,
    match,
    real_library,
    regenerate,
    unique_titles,
)
from ripple.cases.features import OP_NAMES
from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import Settings
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.brief import PastCase
from ripple.contracts.change import (
    ChangeIntent,
    ChangeRequest,
    DimensionChange,
    GradeChange,
    ThicknessChange,
)
from ripple.contracts.dataset import EcnSplit, GeneratedEcn
from ripple.contracts.domain import DataMode, GraphSnapshot
from ripple.contracts.outcomes import OutcomeEntry
from ripple.contracts.records import EcnAction
from ripple.contracts.result import AnalysisResult, DeadlineKind
from ripple.contracts.workspace import SnapshotInfo, UpdateStamp
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.generator.actuals import HiddenModel
from ripple.generator.build import Generated, generate
from ripple.generator.io import load_config, write_outputs
from ripple.graph.files import load_snapshot
from ripple.records.flow import Who
from ripple.store.outcomes import OutcomeLog
from ripple.store.records import RecordStore

A = EcnAction
BUILD_MAX_S = 20.0  # 합성 기본 지도 묶음(30건) 만드는 시간 상한 — 로컬 약 5초, 대안 계산을 켜면 두 배 넘게 늘어 걸린다
FIRST_CALL_MAX_S = 0.5  # 묶음이 없을 때 첫 요청은 기다리지 않는다
SAMPLES = ("ECN-D-0119", "ECN-D-0043")  # 합성 기본 지도 샘플(판 두께 B31P · 평형수 배관 경로)
LATE_NOTES = {"late_cost", "late_flat", "late"}
GRADES = ("A", "AH32", "AH36", "DH36", "EH36")  # 강종 높낮이(낮음 → 높음)


@dataclass(frozen=True, slots=True)
class _Ws:
    snapshot: GraphSnapshot
    info: SnapshotInfo
    data_mode: DataMode


@dataclass
class _Ctx:
    settings: Settings
    generated: Generated
    index: GraphIndex
    kit: EngineKit
    shelf: CaseShelf
    library: CaseLibrary
    samples: set[str]
    first: CaseLibrary
    first_s: float
    replays: dict[str, AnalysisResult]  # 사례 ID → 결정 요청을 엔진으로 다시 분석한 결과


def run(c: Checker) -> None:
    ctx = _context()
    _library(c, ctx)
    _materials(c, ctx)
    _engine(c, ctx)
    _late(c, ctx)
    _find(c, ctx)
    _samples(c, ctx)
    _maps(c, ctx)
    _retry(c, ctx)
    _real(c, ctx)


def _context() -> _Ctx:
    settings = Settings.from_env({})
    rulebook, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    generated = generate(load_config())
    index = GraphIndex(generated.snapshot)
    kit = EngineKit(rulebook, params)

    def picker(idx: GraphIndex, ecns: tuple[GeneratedEcn, ...]) -> list[str]:
        return [s.ecn_id for s in pick_samples(idx, ecns, rulebook)]

    dev = tuple(e for e in generated.ecns if e.split is EcnSplit.DEV)
    shelf = CaseShelf(kit, settings.params_path, picker)
    ws = _Ws(generated.snapshot, default_info(generated.snapshot), DataMode.SYNTHETIC)
    started = time.perf_counter()
    first = shelf.library_for(ws)
    first_s = time.perf_counter() - started
    shelf.wait()
    library = shelf.library_for(ws)
    replays = {
        s.case.case_id: analyze(index, s.request, rulebook, params) for s in library.cases if s.request is not None
    }
    return _Ctx(settings, generated, index, kit, shelf, library, set(picker(index, dev)), first, first_s, replays)


def _library(c: Checker, ctx: _Ctx) -> None:
    c.section("과거 사례: 합성 묶음(재료·표시·결정성)")
    lib, settings = ctx.library, ctx.shelf.settings
    cases = [s.case for s in lib.cases]
    dev = {e.change.ecn_id for e in ctx.generated.ecns if e.split is EcnSplit.DEV}
    c.check(
        f"합성 기본 지도 묶음이 준비되고 {settings.count}건(ready)",
        lib.ready and lib.size == settings.count and lib.snapshot_id == ctx.generated.snapshot.snapshot_id,
        (lib.status, lib.size, lib.problem),
    )
    c.check(
        "모든 사례가 합성 표시(synthetic=True)·'PAST-' 번호·겹치지 않는 번호",
        lib.synthetic
        and all(k.synthetic and k.case_id.startswith("PAST-") for k in cases)
        and len({k.case_id for k in cases}) == len(cases),
    )
    sources = {s.source_id for s in lib.cases}
    c.check(
        "재료는 개발 분할 설계변경만(평가 분할 없음)이고 화면 샘플과 겹치지 않음",
        sources <= dev and not sources & ctx.samples and len(ctx.samples) > 0,
        sorted(sources & ctx.samples),
    )
    world = regenerate(
        ctx.generated.snapshot, ctx.generated.snapshot.snapshot_id, load_config(), ctx.settings.params_path
    )
    again = build_library(world, ctx.kit, settings, ctx.samples) if world is not None else None
    c.check(
        "결정적: 세계를 다시 만들어 다시 만든 묶음이 같음(사례·결정 요청·교훈)",
        again is not None
        and [(s.case, s.request, s.note_id) for s in again.cases]
        == [(s.case, s.request, s.note_id) for s in lib.cases],
    )
    query = next(iter(ctx.replays.values()))
    c.check(
        "결정적: 같은 묶음·같은 분석이면 같은 답",
        again is not None and find_cases(lib, query) == find_cases(again, query),
    )
    c.check(
        "결정 종류는 계약 안(승인·반려·보류)이고 반려·보류는 실적이 없음",
        all(k.decision in (A.APPROVE, A.REJECT, A.HOLD) for k in cases)
        and all(k.actual_krw is None and k.actual_delay_days is None for k in cases if k.decision is not A.APPROVE)
        and all(k.actual_krw is not None and k.actual_delay_days is not None for k in cases if k.decision is A.APPROVE),
    )
    c.check(
        "승인 사례가 있음(묶음이 반려·보류로만 차지 않음)",
        sum(k.decision is A.APPROVE for k in cases) >= settings.count // 2,
    )
    c.check(
        f"첫 요청은 기다리지 않음(만드는 중, {ctx.first_s:.3f}초) · 빈 답",
        ctx.first.status == "building"
        and ctx.first_s < FIRST_CALL_MAX_S
        and find_cases(ctx.first, query).items == ()
        and find_cases(ctx.first, query).synthetic,
    )
    c.check(
        f"만드는 시간 {lib.built_seconds}초 ≤ {BUILD_MAX_S:.0f}초(백그라운드)",
        lib.built_seconds is not None and lib.built_seconds <= BUILD_MAX_S,
    )


def _direction_ok(change: ChangeRequest) -> bool:
    """검사 쪽에서 다시 적은 규칙: 줄이는 두께·낮추는 강종은 목적이 중량 조정(또는 미정),
    늘리는 치수는 목적이 중량 조정이 아님."""
    intent = change.intent
    for op in change.ops:
        down = (isinstance(op, ThicknessChange) and op.to_mm < op.from_mm) or (
            isinstance(op, GradeChange)
            and op.from_grade in GRADES
            and op.to_grade in GRADES
            and GRADES.index(op.to_grade) < GRADES.index(op.from_grade)
        )
        if down and intent not in (None, ChangeIntent.WEIGHT):
            return False
        if isinstance(op, DimensionChange) and op.to_value > op.from_value and intent is ChangeIntent.WEIGHT:
            return False
    return True


def _materials(c: Checker, ctx: _Ctx) -> None:
    c.section("과거 사례: 재료 방향·목적 일치 · 묶음 안 제목 고유")
    lib = ctx.library
    changes = [s.request.change for s in lib.cases if s.request is not None]
    dev = [e.change for e in ctx.generated.ecns if e.split is EcnSplit.DEV]
    contradicting = [ch.ecn_id for ch in dev if not _direction_ok(ch)]
    c.check(
        f"변경 방향과 목적이 맞는 재료만(개발 분할의 모순 {len(contradicting)}건은 재료에서 뺌)",
        len(changes) == lib.size
        and all(_direction_ok(ch) for ch in changes)
        and len(contradicting) > 0
        and all(contradiction(ch) is not None for ch in dev if ch.ecn_id in set(contradicting))
        and all(contradiction(ch) is None for ch in dev if ch.ecn_id not in set(contradicting)),
        [ch.ecn_id for ch in changes if not _direction_ok(ch)],
    )
    base = changes[0]

    def made(op: ThicknessChange | GradeChange | DimensionChange, intent: ChangeIntent | None) -> ChangeRequest:
        return base.model_copy(update={"ops": (op,), "intent": intent})

    parts = ("S-001:B31P-PL-002",)
    c.check(
        "반례: 두께 감소·강종 낮춤 + 강도·규칙 요구, 치수 증가 + 중량 조정은 모순 · 감소 + 중량 조정·미정은 아님",
        contradiction(made(ThicknessChange(part_ids=parts, from_mm=16, to_mm=15), ChangeIntent.STRENGTH)) is not None
        and contradiction(made(GradeChange(part_ids=parts, from_grade="AH36", to_grade="A"), ChangeIntent.RULE_CHANGE))
        is not None
        and contradiction(
            made(
                DimensionChange(part_ids=parts, field="length_mm", from_value=1000, to_value=1200), ChangeIntent.WEIGHT
            )
        )
        is not None
        and contradiction(made(ThicknessChange(part_ids=parts, from_mm=16, to_mm=15), ChangeIntent.WEIGHT)) is None
        and contradiction(made(ThicknessChange(part_ids=parts, from_mm=16, to_mm=15), None)) is None
        and contradiction(made(ThicknessChange(part_ids=parts, from_mm=15, to_mm=17), ChangeIntent.STRENGTH)) is None,
    )
    titles = [s.case.title for s in lib.cases]
    codes_ok = all(
        any(code.split(":")[-1] in s.case.title for code in s.features.blocks) for s in lib.cases if s.features.blocks
    )
    c.check(
        "묶음 안 사례 제목이 모두 다르고 바뀌는 블록 코드가 들어감",
        len(set(titles)) == len(titles) and codes_ok,
        [t for t in titles if titles.count(t) > 1],
    )
    first = lib.cases[0]
    twin = dataclasses.replace(first, case=first.case.model_copy(update={"case_id": "PAST-9999"}), request=None)
    fixed = [s.case.title for s in unique_titles([first, twin])]
    c.check("제목이 같고 구별할 부재 번호도 없으면 사례 번호를 붙여 고유하게", len(set(fixed)) == 2, fixed)
    for ecn_id in SAMPLES:
        found = find_cases(lib, _sample_result(ctx, ecn_id))
        shown = [k.title for k in found.items]
        c.check(f"{ecn_id}의 비슷한 사례 제목이 서로 다름", len(set(shown)) == len(shown), shown)


def _sample_result(ctx: _Ctx, ecn_id: str) -> AnalysisResult:
    ecn = next(e for e in ctx.generated.ecns if e.change.ecn_id == ecn_id)
    request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of)
    return analyze(ctx.index, request, ctx.kit.rulebook, ctx.kit.params)


def _engine(c: Checker, ctx: _Ctx) -> None:
    c.section("과거 사례: 예측 = 엔진 재분석, 실적 = 숨긴 모델 재계산")
    hidden = HiddenModel(ctx.generated, ctx.settings.params_path)
    bad_pred: list[str] = []
    bad_actual: list[str] = []
    for stored in ctx.library.cases:
        case, request = stored.case, stored.request
        replay = ctx.replays.get(case.case_id)
        if request is None or replay is None:
            bad_pred.append(case.case_id)
            continue
        deadline = replay.timing.deadline
        confirm_on = request.effective_confirm_on
        days = None if deadline.kind is DeadlineKind.NONE_IN_HORIZON else (deadline.last_day - confirm_on).days
        if (replay.total, replay.schedule.max_exit_delay_days, days) != (
            case.predicted,
            case.predicted_delay_days,
            case.days_before_deadline,
        ):
            bad_pred.append(case.case_id)
        if case.decision is A.APPROVE and request.confirm_on is not None:
            held = {h.po_id: h.hold_days for h in request.holds}
            outcome = hidden.outcome(request.change, request.as_of, request.confirm_on, held)
            if (outcome.total_krw, outcome.max_exit_delay_days) != (case.actual_krw, case.actual_delay_days):
                bad_actual.append(case.case_id)
    c.check(
        "예측(총변경비용·구역 출구 지연·마감 며칠 전) = 결정 요청을 엔진으로 다시 분석한 값", not bad_pred, bad_pred
    )
    c.check(
        "실적(비용·지연) = 같은 세계 숨긴 모델이 그 결정(확정일·보류)으로 다시 계산한 값", not bad_actual, bad_actual
    )
    holds = [s for s in ctx.library.cases if s.case.chosen == "발주 보류 뒤 승인"]
    c.check(
        "발주 보류 뒤 승인은 엔진 보류 권고의 발주로 분석한 사례",
        all(s.request is not None and s.request.holds for s in holds),
    )
    c.check(
        "예측·실적은 0원보다 큼(절감 변경은 재료에서 뺌 — 계약의 실적은 0 이상)",
        all(
            s.case.predicted.value > 0 and (s.case.actual_krw is None or s.case.actual_krw >= 0)
            for s in ctx.library.cases
        ),
    )


def _late(c: Checker, ctx: _Ctx) -> None:
    c.section("과거 사례: 결정 시점과 교훈(서버 템플릿)이 데이터와 맞음")
    hidden = HiddenModel(ctx.generated, ctx.settings.params_path)
    wrong: list[str] = []
    late_seen = 0
    for stored in ctx.library.cases:
        case, facts, request = stored.case, stored.facts, stored.request
        replay = ctx.replays.get(case.case_id)
        if facts is None or request is None or replay is None:
            wrong.append(case.case_id)
            continue
        late = case.days_before_deadline is not None and case.days_before_deadline < 0
        approved = case.decision is A.APPROVE
        if late and approved:
            late_seen += 1
            day = replay.timing.deadline.last_day
            at_deadline = next(p.total.value for p in replay.timing.curve if p.confirm_on == day)
            held = {h.po_id: h.hold_days for h in request.holds}
            actual_then = hidden.outcome(request.change, request.as_of, day, held).total_krw
            grew = case.predicted.value - at_deadline
            ok = stored.note_id in LATE_NOTES and (facts.at_deadline, facts.actual_at_deadline) == (
                at_deadline,
                actual_then,
            )
            if stored.note_id == "late_cost":
                ok = ok and grew > 0 and case.actual_krw is not None and case.actual_krw > actual_then
            if stored.note_id == "late_flat":
                ok = ok and grew == 0 and case.actual_krw is not None and case.actual_krw <= actual_then
            if not ok:
                wrong.append(case.case_id)
        elif stored.note_id in LATE_NOTES:
            wrong.append(case.case_id)
    c.check(
        "마감 뒤 승인 사례: 교훈은 '늦게' 계열, '증가'는 엔진 곡선과 숨긴 모델 실적이 모두 마감일보다 컸을 때만",
        not wrong and late_seen > 0,
        (wrong, late_seen),
    )
    others = [s.case.case_id for s in ctx.library.cases if not _template_ok(ctx, s)]
    c.check(
        "그 밖의 교훈도 데이터와 맞음(반려·보류 · 발주 보류로 줄인 금액 · 범위 초과 · 마감 안 결정)", not others, others
    )
    c.check(
        "교훈 문장은 명사형(해요체 끝맺음·마침표 없음)·300자 이내",
        all(nominal(s.case.note) and len(s.case.note) <= 300 for s in ctx.library.cases if s.case.note),
    )


def _template_ok(ctx: _Ctx, stored: StoredCase) -> bool:
    """마감 뒤 승인이 아닌 교훈: 결정 종류·발주 보류 절감(엔진 재분석)·범위 초과·마감 안 결정이 사례 값과 맞는지."""
    case, facts, request = stored.case, stored.facts, stored.request
    if facts is None or request is None:
        return False
    expected = {A.REJECT: "rejected", A.HOLD: "held"}.get(case.decision)
    if (expected is not None or stored.note_id in {"rejected", "held"}) and stored.note_id != expected:
        return False
    if stored.note_id == "hold_saved":
        plain = analyze(ctx.index, request.model_copy(update={"holds": ()}), ctx.kit.rulebook, ctx.kit.params)
        if not (request.holds and facts.without_hold == plain.total.value > case.predicted.value):
            return False
    if stored.note_id == "over_range" and not (case.actual_krw or 0) > case.predicted.high:
        return False
    days = case.days_before_deadline
    return not (stored.note_id in {"on_time", "on_deadline"} and (days is None or days < 0))


def _scores(ctx: _Ctx, query: AnalysisResult, items: tuple[str, ...]) -> list[float]:
    lib = ctx.library
    q = features_of(query, lib.lookup)
    by_id = {s.case.case_id: s for s in lib.cases}
    found = [match(q, by_id[i].features, lib.similarity, lib.lookup) for i in items]
    return [m.score if m is not None else -1.0 for m in found]


def _find(c: Checker, ctx: _Ctx) -> None:
    c.section("과거 사례: 비슷한 사례 찾기(같은 연산 · 같은 블록 먼저 · 점수 순 · 문턱 · 자기 자신 제외)")
    lib = ctx.library
    by_id = {s.case.case_id: s for s in lib.cases}
    problems: dict[str, list[str]] = {
        "op": [],
        "self": [],
        "order": [],
        "block": [],
        "threshold": [],
        "summary": [],
        "chips": [],
    }
    for case_id, query in ctx.replays.items():
        found = find_cases(lib, query)
        ids = tuple(k.case_id for k in found.items)
        q = features_of(query, lib.lookup)
        if any(by_id[k.case_id].features.op != q.op or k.same[0] != f"같은 {OP_NAMES[q.op]}" for k in found.items):
            problems["op"].append(case_id)
        if case_id in ids:
            problems["self"].append(case_id)
        scores = _scores(ctx, query, ids)
        keys = [_rank(k, score) for k, score in zip(found.items, scores, strict=True)]
        if keys != sorted(keys):
            problems["order"].append(case_id)
        blocks = [any(s.startswith("같은 블록") for s in k.same) for k in found.items]
        if blocks != sorted(blocks, reverse=True):
            problems["block"].append(case_id)
        _threshold(ctx, query, ids, keys, problems["threshold"], case_id)
        if not _summary_ok(found.items, found.summary):
            problems["summary"].append(case_id)
        problems["chips"] += [s for k in found.items for s in k.same if _awkward(s)]
    c.check(
        "찾은 사례는 모두 같은 변경 연산 종류이고 same 첫 줄이 '같은 두께 변경'처럼 그 연산",
        not problems["op"],
        problems["op"],
    )
    c.check("자기 자신(같은 변경)은 과거 사례로 나오지 않음", not problems["self"], problems["self"])
    c.check(
        "같은 블록 무리 → 무리 안에서는 실적 있는 사례(승인) 먼저 → 점수 순(반려·보류는 실적 있는 사례가 모자랄 때만)",
        not problems["order"],
        problems["order"],
    )
    c.check("같은 블록 사례가 다른 블록 사례보다 앞", not problems["block"], problems["block"])
    c.check(
        "문턱 미만은 빼고, 문턱 이상인데 빠진 것은 3건을 채워서일 때만",
        not problems["threshold"],
        problems["threshold"],
    )
    c.check(
        "요약의 숫자 = 사례 값으로 센 건수(예측보다 큰 실적·마감 뒤 결정), 오차율·중앙값·% 없음, 사례가 없으면 None",
        not problems["summary"],
        problems["summary"],
    )
    c.check(
        "같은 점 문구에 겹치는 말이 없음('같은 구역 화물탱크 구역'·'같은 계통 평형수'·'바뀔 강종' 같은 꼴 없음)",
        not problems["chips"],
        sorted(set(problems["chips"]))[:5],
    )
    one = next(iter(ctx.replays.values()))
    real = one.model_copy(update={"data_mode": DataMode.REAL})
    blocked = find_cases(lib, real)
    c.check(
        "실데이터 결과에는 합성 묶음이 빈 답(unavailable) — 묶음을 고른 쪽과 따로 막음",
        blocked.items == () and blocked.status == "unavailable" and not blocked.synthetic,
        blocked,
    )
    c.check(
        "limit 0 → 빈 답, limit 1 → 1건 이하, 묶음 크기 = 찾아본 과거 사례 수",
        find_cases(lib, one, limit=0).items == ()
        and len(find_cases(lib, one, limit=1).items) <= 1
        and find_cases(lib, one).library_size == lib.size,
    )


def _rank(case: PastCase, score: float) -> tuple[int, int, float]:
    """보이는 순서의 기준(독립 계산): 같은 블록 무리 먼저 → 실적 있는 사례 먼저 → 점수 큰 순."""
    same_block = any(s.startswith("같은 블록") for s in case.same)
    return (0 if same_block else 1, 0 if case.actual_krw is not None else 1, -score)


def _threshold(
    ctx: _Ctx,
    query: AnalysisResult,
    ids: tuple[str, ...],
    keys: list[tuple[int, int, float]],
    out: list[str],
    case_id: str,
) -> None:
    lib = ctx.library
    sim = lib.similarity
    if any(-k[2] < sim.threshold for k in keys):
        out.append(case_id)
        return
    q = features_of(query, lib.lookup)
    for stored in lib.cases:
        if stored.case.case_id in ids or stored.features.ops_key == q.ops_key:
            continue
        m = match(q, stored.features, sim, lib.lookup)
        if m is None or m.score < sim.threshold:
            continue
        key = _rank(stored.case.model_copy(update={"same": m.same}), m.score)
        if len(ids) < 3 or key < max(keys):
            out.append(case_id)
            return


_NUMBERS = re.compile(r"\d+")


def _shown_larger(actual: int, predicted: int) -> bool:
    """화면 차이 %(Math.round)가 0보다 큰가 — 요약의 '예측 초과'와 사례 줄의 %가 같은 기준인지 보려는 독립 계산."""
    if predicted <= 0:
        return actual > predicted
    return math.floor((actual - predicted) / predicted * 100 + 0.5) > 0  # JS Math.round와 같은 반올림


def _awkward(chip: str) -> bool:
    """같은 점 문구가 겹치는 말을 쓰는가."""
    words = chip.replace("(", " ").replace(")", " ").replace(",", " ").split()
    repeated = any(words.count(w) > 1 for w in ("구역", "계통"))
    return repeated or any(x in chip for x in ("같은 변경 종류", "같은 구역 ", "같은 계통 ", "바뀔", "변경 목적"))


def _summary_ok(items: tuple[PastCase, ...], summary: str | None) -> bool:
    """요약 문장의 숫자가 사례 값으로 센 건수와 같은지(오차율·중앙값·% 같은 통계는 없어야 함)."""
    if not items:
        return summary is None
    if summary is None or any(word in summary for word in ("%", "중앙값", "오차")):
        return False
    n = len(items)
    measured = sum(1 for k in items if k.actual_krw is not None)
    larger = sum(1 for k in items if k.actual_krw is not None and _shown_larger(k.actual_krw, k.predicted.value))
    late = sum(1 for k in items if k.days_before_deadline is not None and k.days_before_deadline < 0)
    on_time = sum(1 for k in items if k.days_before_deadline is not None and k.days_before_deadline >= 0)
    expected = [n]
    if larger:
        expected.append(larger)
    elif 0 < measured < n:
        expected.append(measured)
    if late:
        expected.append(late)
    numbers = [int(x) for x in _NUMBERS.findall(summary)]
    claims = (
        (larger == 0 or f"{larger}건은 실적이 예측 초과" in summary)
        and (late == 0) == ("결정 기한 뒤" not in summary)
        and (late > 0 or on_time != n or "모두 결정 기한 안에" in summary)
    )
    return numbers == expected and claims


def _samples(c: Checker, ctx: _Ctx) -> None:
    c.section("과거 사례: 합성 기본 지도 샘플마다 비슷한 사례")
    rulebook, params = ctx.kit.rulebook, ctx.kit.params
    dev = {e.change.ecn_id: e for e in ctx.generated.ecns if e.split is EcnSplit.DEV}
    for ecn_id in SAMPLES:
        ecn = dev[ecn_id]
        result = analyze(ctx.index, AnalysisRequest(change=ecn.change, as_of=ecn.as_of), rulebook, params)
        found = find_cases(ctx.library, result)
        c.check(
            f"{ecn_id}({ecn.change.title}): 비슷한 사례 {len(found.items)}건 · 요약 있음 · 합성 표시",
            1 <= len(found.items) <= 3 and found.summary is not None and found.synthetic,
            found.model_dump_json(),
        )


class _Flaky(CaseShelf):
    """처음 fails번은 묶음을 만들다 실패하는 선반(다시 시도 검사)."""

    def __init__(self, ctx: _Ctx, *, retry_s: float, fails: int = 1) -> None:
        super().__init__(ctx.kit, ctx.settings.params_path, lambda _i, _e: (), retry_s=retry_s)
        self.fails = fails
        self.made = 0

    def _make(self, snapshot: GraphSnapshot, root: str) -> CaseLibrary:
        self.made += 1
        if self.fails > 0:
            self.fails -= 1
            raise RuntimeError("일부러 실패")
        return CaseLibrary(snapshot_id=root, status="ready", synthetic=True, similarity=self.settings.similarity)


def _retry(c: Checker, ctx: _Ctx) -> None:
    c.section("과거 사례: 묶음을 만들다 실패하면 짧은 간격 뒤 다시 시도(영구 unavailable 아님)")
    snapshot = ctx.generated.snapshot
    ws = _Ws(snapshot, default_info(snapshot), DataMode.SYNTHETIC)
    quick, slow = _Flaky(ctx, retry_s=0.0), _Flaky(ctx, retry_s=3600.0)
    states = []
    quiet = logging.getLogger("ripple.cases.shelf")
    quiet.disabled = True  # 일부러 낸 실패의 로그는 검사 출력에 섞지 않는다
    try:
        for shelf in (quick, slow):
            shelf.prepare(snapshot, background=False)
            first = shelf.library_for(ws).status
            shelf.wait(30)
            states.append((first, shelf.library_for(ws).status, shelf.made))
    finally:
        quiet.disabled = False
    c.check(
        "간격이 지났으면 다음 요청이 다시 만들어 ready, 간격 안이면 실패 묶음(unavailable)을 그대로 — "
        "요청마다 만들지 않음",
        states == [("building", "ready", 2), ("unavailable", "unavailable", 1)],
        states,
    )


def _maps(c: Checker, ctx: _Ctx) -> None:
    c.section("과거 사례: 지도 ID 기억 · 상태 갱신 지도 · 지도 파일 · 다른 세계")
    snapshot = ctx.generated.snapshot
    root = snapshot.snapshot_id
    ws = _Ws(snapshot, default_info(snapshot), DataMode.SYNTHETIC)
    c.check("같은 지도면 다시 만들지 않음(기억한 묶음 그대로)", ctx.shelf.library_for(ws) is ctx.library)
    stamp = UpdateStamp(
        base_snapshot_id=root,
        lineage_root=root,
        event_id="U-1",
        at=datetime(2026, 10, 21, tzinfo=UTC),
        by="검사",
        origin="confirm",
        status_changed=1,
        plan_changed=0,
        activities=0,
        confirmed_only=0,
    )
    updated = snapshot.model_copy(update={"snapshot_id": "G-00000000000000aa"})
    info = default_info(updated).model_copy(update={"update": stamp, "default": False})
    c.check(
        "상태 갱신 지도는 계보 시작(뿌리 기본 지도)의 묶음을 씀",
        ctx.shelf.library_for(_Ws(updated, info, DataMode.SYNTHETIC)) is ctx.library,
    )
    with tempfile.TemporaryDirectory() as folder:
        write_outputs(ctx.generated, Path(folder))
        files = sorted(Path(folder).rglob("snapshot.json"))
        loaded = load_snapshot(files[0], DataMode.SYNTHETIC) if files else None
    c.check(
        "지도 파일로 읽은 기본 지도도 그 기준일로 다시 만든 세계와 지도 ID가 같음",
        loaded is not None
        and regenerate(loaded, loaded.snapshot_id, load_config(), ctx.settings.params_path) is not None,
    )
    other = snapshot.model_copy(update={"snapshot_id": "G-00000000000000bb"})
    ctx.shelf.prepare(other, background=False)
    lib = ctx.shelf.library_for(_Ws(other, default_info(other), DataMode.SYNTHETIC))
    query = next(iter(ctx.replays.values()))
    c.check(
        "다시 만든 세계와 지도 ID가 다르면 만들 수 없음(빈 답, 사유)",
        lib.status == "unavailable" and lib.problem is not None and find_cases(lib, query).items == (),
    )


def _real(c: Checker, ctx: _Ctx) -> None:
    c.section("과거 사례: 실데이터 모드 — 합성 사례 없이 실적 있는 종료 기록만")
    results = list(ctx.replays.values())[:4]
    member, lead = _who("kim"), _who("lead", record_=False, approve=True, admin=True)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        store = RecordStore(root / "records")
        store.start()
        outcomes = OutcomeLog(root / "records")
        plans = (
            ("ECN-R-0001", DataMode.REAL, A.CLOSE, True),  # 들어감
            ("ECN-R-0002", DataMode.SYNTHETIC, A.CLOSE, True),  # 합성 본문 → 뺌
            ("ECN-R-0003", DataMode.REAL, A.START, True),  # 실행 중 → 뺌
            ("ECN-R-0004", DataMode.REAL, A.CLOSE, False),  # 실적 없음 → 뺌
        )
        for (ecn, mode, last, with_outcome), result in zip(plans, results, strict=True):
            _flow(store, outcomes, ecn, mode, last, with_outcome, result, member, lead)
        lookup = MapLookup.of(ctx.generated.snapshot)
        lib = real_library(store, outcomes, load_settings().similarity, lookup)
        shelf = CaseShelf(ctx.kit, ctx.settings.params_path, lambda _i, _e: (), records=store, outcomes=outcomes)
        via = shelf.library_for(_Ws(ctx.generated.snapshot, default_info(ctx.generated.snapshot), DataMode.REAL))
        entry = outcomes.latest().get("ECN-R-0001")
    case = lib.cases[0].case if lib.cases else None
    c.check(
        "실데이터 묶음: 종료·실적 있음·실데이터 본문인 1건만, 합성 아님",
        lib.ready and not lib.synthetic and [s.case.case_id for s in lib.cases] == ["ECN-R-0001"],
        [s.case.case_id for s in lib.cases],
    )
    c.check(
        "실데이터 사례: 예측 = 승인한 본문 총액, 실적 = 넣은 실적, synthetic=False",
        case is not None
        and entry is not None
        and not case.synthetic
        and case.actual_krw == entry.cost_krw
        and case.predicted == results[0].total,
    )
    c.check(
        "작업 공간이 실데이터 모드면 합성 사례를 만들지 않고 기록에서 바로(지도 캐시 아님)",
        not via.synthetic and [s.case.case_id for s in via.cases] == ["ECN-R-0001"],
    )


def _flow(
    store: RecordStore,
    outcomes: OutcomeLog,
    ecn: str,
    mode: DataMode,
    last: EcnAction,
    with_outcome: bool,
    result: AnalysisResult,
    member: Who,
    lead: Who,
) -> None:
    body = _body(result, ecn=ecn, mode=mode)
    snapshot = body.snapshot_id
    _save(store, body, member, 0)
    _do(store, ecn, A.REQUEST_REVIEW, member, snapshot=snapshot)
    _do_line(store, ecn, lead, snapshot=snapshot)  # 결재선 끝까지(팀장 전결)
    _do(store, ecn, A.START, member, snapshot=snapshot)
    if last is A.CLOSE:
        _do(store, ecn, A.CLOSE, member, snapshot=snapshot)
    if with_outcome:
        status = next(i.status for i in store.listing(include_real=True).ecns if i.status.ecn_id == ecn)
        outcomes.append(
            OutcomeEntry(
                ecn_id=ecn,
                revision=status.approved_revision or 1,
                record_id=status.record_id,
                cost_krw=result.total.value + 123_000,
                exit_delay_days=1,
                entered_by=_actor(member),
                entered_at=datetime.now(UTC),
            )
        )
