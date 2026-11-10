"""합성 과거 사례 묶음(합성 모드 전용, docs/records.md '합성 과거 사례').

- 재료: 대상 지도를 만든 생성기 세계를 다시 만들어(같은 설정 · 기준일 = 그 지도의 기준일) 지도 ID가 같은지 확인하고,
  개발 분할 설계변경 중 화면 샘플이 아닌 것에서 연산 비율대로 고른다(평가 분할은 최종 인증용이라 쓰지 않는다).
- 예측: 엔진이 그 사례를 분석한 값(결정한 날 확정할 때의 총변경비용·구역 출구 최대 지연, 추가손실 0 마감일).
- 실적: 같은 세계의 숨긴 실제 모델(ripple/generator/actuals)이 그 결정(확정일·발주 보류)으로 계산한 값.
  늦게 정한 효과도 이 모델이 계산한다. 반려·결정 보류는 실행하지 않아 실적이 없다.
- 시드 고정 난수는 결정 종류와 결정 시점(마감 며칠 전후)만 정한다(params/cases_v1.yaml, 가정).
"""

from __future__ import annotations

import random
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from ripple.contracts.analysis import AnalysisRequest, HoldAction
from ripple.contracts.brief import PastCase
from ripple.contracts.dataset import EcnSplit, GeneratedEcn
from ripple.contracts.domain import GraphSnapshot
from ripple.contracts.params import ParamSet
from ripple.contracts.records import EcnAction
from ripple.contracts.result import AnalysisResult, CurvePoint, DeadlineKind, TimingResult
from ripple.contracts.rulebook import RuleBook
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.generator.actuals import HiddenModel
from ripple.generator.build import Generated, generate
from ripple.generator.config import GeneratorConfig
from ripple.generator.rng import sub_rng
from ripple.records.metrics import curve_point

from .features import MapLookup, features_of
from .library import CaseLibrary, StoredCase
from .materials import contradiction, unique_titles
from .notes import CHOSEN, CaseFacts, note_of
from .settings import CaseSettings, Choice, Timing

Decision = Literal[EcnAction.APPROVE, EcnAction.REJECT, EcnAction.HOLD]
DECISION: dict[Choice, Decision] = {
    Choice.AS_REQUESTED: EcnAction.APPROVE,
    Choice.HOLD_PO: EcnAction.APPROVE,
    Choice.REJECT: EcnAction.REJECT,
    Choice.HOLD: EcnAction.HOLD,
}


@dataclass(frozen=True, slots=True)
class EngineKit:
    """엔진 입력(앱 컨텍스트의 규칙표·비용 파라미터)."""

    rulebook: RuleBook
    params: ParamSet


@dataclass(frozen=True, slots=True)
class World:
    """과거 사례의 세계: 다시 만든 생성 결과 · 그 지도 색인 · 숨긴 실제 모델 · 기준일."""

    generated: Generated
    index: GraphIndex
    hidden: HiddenModel
    as_of: date


def scenario_day(snapshot: GraphSnapshot, config: GeneratorConfig) -> date | None:
    """생성기 지도의 기준일: 계약 인도일 = 기준일 + 인도 오프셋(ripple/generator/ship.py). 그 호선이 없으면 None."""
    ship = next((s for s in snapshot.ships if s.ship_id == config.ship.ship_id), None)
    return None if ship is None else ship.delivery_date - timedelta(days=config.ship.delivery_offset_days)


def regenerate(
    snapshot: GraphSnapshot,
    root_id: str,
    config: GeneratorConfig,
    hidden_params: Path,
    generated: Generated | None = None,
) -> World | None:
    """그 지도의 기준일로 생성기 세계를 다시 만든다. 만든 지도 ID가 root_id(뿌리 기본 지도)와 다르면 None.

    generated를 받으면(그 기준일로 이미 만든 생성 결과) 다시 만들지 않고 그것을 대조한다."""
    day = scenario_day(snapshot, config)
    if day is None:
        return None
    if generated is None:
        generated = generate(config.model_copy(update={"scenario_date": day}))
    if generated.snapshot.snapshot_id != root_id:
        return None
    return World(generated, GraphIndex(generated.snapshot), HiddenModel(generated, hidden_params), day)


def build_library(world: World, kit: EngineKit, settings: CaseSettings, exclude: Iterable[str]) -> CaseLibrary:
    """개발 분할 중 exclude(화면 샘플)가 아닌 설계변경에서 settings.count건을 만든다(결정적: 같은 세계 → 같은 묶음).

    변경 방향과 목적이 모순되는 재료는 처음부터 빼고(ripple/cases/materials.py), 엔진이 거부하거나(지도와 안 맞음)
    예측·실적이 0원 이하(절감 변경 — 계약의 실적은 0 이상)인 재료는 건너뛰고 다음 재료를 쓴다.
    제목은 묶음 안에서 고유하게 한다."""
    started = time.perf_counter()
    skip = set(exclude)
    pool = [
        e
        for e in world.generated.ecns
        if e.split is EcnSplit.DEV and e.change.ecn_id not in skip and contradiction(e.change) is None
    ]
    lookup = MapLookup.of(world.generated.snapshot)
    cases: list[StoredCase] = []
    for ecn in candidates(pool, world.generated.seed, settings.count):
        if len(cases) >= settings.count:
            break
        stored = past_case(world, kit, settings, ecn, lookup)
        if stored is not None:
            cases.append(stored)
    cases.sort(key=lambda s: s.case.case_id)
    return CaseLibrary(
        snapshot_id=world.generated.snapshot.snapshot_id,
        status="ready",
        synthetic=True,
        similarity=settings.similarity,
        cases=unique_titles(cases),
        lookup=lookup,
        built_seconds=round(time.perf_counter() - started, 3),
    )


def candidates(pool: list[GeneratedEcn], seed: int, count: int) -> Iterator[GeneratedEcn]:
    """재료 순서: 연산마다 건수 비율로 몫을 나눠(큰 나머지 순) 몫만큼 먼저, 그 뒤 나머지 — 연산 안은 시드 고정 섞기.

    부족하면(건너뛴 재료) 다음 재료가 이어 채운다. 같은 재료 묶음·시드면 같은 순서."""
    groups: dict[str, list[GeneratedEcn]] = {}
    for ecn in sorted(pool, key=lambda e: e.change.ecn_id):
        groups.setdefault(ecn.change.ops[0].op, []).append(ecn)
    rng = sub_rng(seed, "cases", "order")
    for op in sorted(groups):
        rng.shuffle(groups[op])
    total = sum(len(g) for g in groups.values()) or 1
    exact = {op: count * len(g) / total for op, g in groups.items()}
    quota = {op: int(value) for op, value in exact.items()}
    for op in sorted(groups, key=lambda o: (-(exact[o] - quota[o]), o))[: count - sum(quota.values())]:
        quota[op] += 1
    first = [e for op in sorted(groups) for e in groups[op][: quota[op]]]
    yield from first
    yield from (e for op in sorted(groups) for e in groups[op][quota[op] :])


def past_case(
    world: World, kit: EngineKit, settings: CaseSettings, ecn: GeneratedEcn, lookup: MapLookup
) -> StoredCase | None:
    """재료 하나 → 과거 사례. 엔진이 거부하거나 예측·실적이 0원 이하면 None."""
    rng = sub_rng(world.generated.seed, "cases", "case", ecn.change.ecn_id)
    request = AnalysisRequest(change=ecn.change, as_of=world.as_of)
    try:
        base = analyze(world.index, request, kit.rulebook, kit.params)
    except RequestError:
        return None
    choice = _choice(rng, settings, base)
    holds = _advised(base) if choice is Choice.HOLD_PO else ()
    plan = (
        base
        if not holds
        else analyze(world.index, request.model_copy(update={"holds": holds}), kit.rulebook, kit.params)
    )
    decided = decision_day(rng, settings.timing, plan.timing)
    point = _point(plan.timing, decided)
    held = {h.po_id: h.hold_days for h in holds}
    approved = DECISION[choice] is EcnAction.APPROVE
    actual = world.hidden.outcome(ecn.change, world.as_of, decided, held) if approved else None
    if point.total.value <= 0 or (actual is not None and actual.total_krw < 0):
        return None
    deadline = plan.timing.deadline
    days_before = None if deadline.kind is DeadlineKind.NONE_IN_HORIZON else (deadline.last_day - decided).days
    late = days_before is not None and days_before < 0
    facts = CaseFacts(
        choice=choice,
        days_before=days_before,
        predicted=point.total,
        actual=None if actual is None else actual.total_krw,
        at_deadline=None if days_before is None else _point(plan.timing, deadline.last_day).total.value,
        actual_at_deadline=(
            world.hidden.outcome(ecn.change, world.as_of, deadline.last_day, held).total_krw
            if late and approved
            else None
        ),
        without_hold=_point(base.timing, decided).total.value if holds else None,
        no_deadline=deadline.kind is DeadlineKind.NONE_IN_HORIZON,
    )
    note_id, note = note_of(facts)
    case = PastCase(
        case_id="PAST-" + ecn.change.ecn_id.rsplit("-", 1)[-1],
        title=ecn.change.title,
        decision=DECISION[choice],
        chosen=CHOSEN[choice],
        predicted=point.total,
        actual_krw=facts.actual,
        predicted_delay_days=point.max_exit_delay_days,
        actual_delay_days=None if actual is None else actual.max_exit_delay_days,
        days_before_deadline=days_before,
        note=note,
        synthetic=True,
    )
    decision = request.model_copy(update={"confirm_on": decided, "holds": holds})
    return StoredCase(case, features_of(base, lookup), ecn.change.ecn_id, decision, facts, note_id)


def _choice(rng: random.Random, settings: CaseSettings, base: AnalysisResult) -> Choice:
    """할 수 있는 결정 중에서 비율대로(발주 보류는 보류 권고가 있을 때만). 난수 한 번."""
    feasible = {c: w for c, w in settings.decisions.items() if c is not Choice.HOLD_PO or _advised(base)}
    keys = sorted(feasible)
    return rng.choices(keys, weights=[feasible[k] for k in keys])[0]


def _advised(result: AnalysisResult) -> tuple[HoldAction, ...]:
    """엔진 보류 권고를 최대 보류 일수로(발주 ID 순, 1일 이상만)."""
    return tuple(
        HoldAction(po_id=a.po_id, hold_days=a.max_hold_days)
        for a in sorted(result.timing.holds, key=lambda a: a.po_id)
        if a.max_hold_days >= 1
    )


def decision_day(rng: random.Random, timing: Timing, result: TimingResult) -> date:
    """결정한 날: 마감 뒤(비율 late_share, 1~late_max일) 또는 마감 전(0~early_max일), 마감이 없으면 기준일 + 0~n일.
    곡선 안(기준일 ~ 탐색 기간 끝)으로 자른다. 난수는 늘 두 번(같은 시드면 같은 날)."""
    curve = result.curve
    first, last = curve[0].confirm_on, curve[-1].confirm_on
    deadline = result.deadline
    late = rng.random() < timing.late_share
    if deadline.kind is DeadlineKind.NONE_IN_HORIZON:
        day = first + timedelta(days=rng.randint(0, timing.no_deadline_max_days))
    elif late:
        day = deadline.last_day + timedelta(days=rng.randint(1, timing.late_max_days))
    else:
        day = deadline.last_day - timedelta(days=rng.randint(0, timing.early_max_days))
    return min(max(day, first), last)


def _point(timing: TimingResult, day: date) -> CurvePoint:
    """결정한 날은 곡선 안으로 자른 날이라 늘 있다(records.metrics.curve_point)."""
    point = curve_point(timing.curve, day)
    if point is None:
        raise ValueError(f"추가손실 곡선 밖의 날: {day}")
    return point
