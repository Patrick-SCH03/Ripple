"""사례 → 엔진이 계산할 수 있는 최소 지도와 설계변경 요청(docs/backtest.md 3절).

지도: 배 1척 · 구역 1개 · 대상 블록 1개와 공정 사슬(소조립 → … → 탑재 → 구역 출구 → 진수 → 인도) ·
블록 강재(바뀌지 않음) · 바뀐 부재 n개 · 재제작 스풀 s개(바뀌지 않는 양 끝 스풀 사이 사슬)와 그 발주 · 개정 도면 d장.
- 바뀐 부재 = 치수 변경(같은 자재 다시 가공: 블록 재작업·도면 개정, 발주는 그대로). 값은 자리표시(엔진은 대상만 표시).
- 재제작 스풀 = 사례의 재제작 방식: 사내 재제작·사외 재발주는 경로 변경(옛 스풀을 빼고 같은 규격 새 스풀, 새 스풀
  리드타임만 다름), 치수 변경은 같은 자재 다시 가공.
- 확정일 = 기준일 + 결정까지 걸린 일수(비면 기준일).
- 기준일까지의 공정·발주 실적은 계획 날짜 그대로 확인된 것으로 둔다(근거 있음 — 단계가 '판단 불가'가 되지 않게).
ID 형식은 생성기(ripple/generator/ids.py)를 그대로 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.change import ChangeOp, ChangeRequest, DimensionChange, ReroutePipe
from ripple.contracts.domain import ActivityKind, GraphSnapshot
from ripple.contracts.identity import snapshot_id
from ripple.generator import ids
from ripple.generator.config import GeneratorConfig

from .case import Case
from .defaults import BacktestDefaults
from .plan import as_of_for, make_plan
from .scope import Assumption, BuildError, Scope, resolve_scope
from .world import BLOCK, SHIP, SPOOL_SPEC, Layout, World, layout_for

PLACEHOLDER_MM = (1000.0, 1001.0)  # 치수 변경의 전·후 값 자리표시(엔진은 치수 변경 값을 계산에 쓰지 않는다)


@dataclass(frozen=True, slots=True)
class Built:
    snapshot: GraphSnapshot
    request: AnalysisRequest
    erection_id: str
    scope: Scope
    assumptions: tuple[Assumption, ...]


def build_case(case: Case, defaults: BacktestDefaults, gen: GeneratorConfig) -> Built:
    if case.problems:
        raise BuildError("; ".join(case.problems))
    if case.stage is None:
        raise BuildError("발견 단계가 비어 있어 계산 불가")
    scope, notes = resolve_scope(case, defaults)
    plan = make_plan(gen, defaults.schedule, scope.weight_t)
    as_of = as_of_for(plan, case.stage, defaults.schedule.stage_position)
    confirm_on = _confirm_on(case, as_of, notes)
    spool_order = plan.spool
    if scope.force_order and spool_order.ordered > as_of:
        spool_order = spool_order.ordered_on(as_of)
        reason = "발주 변경 있음 → 그때 이미 발주된 것으로 보고 스풀 발주일을 기준일로 조정"
        notes.append(Assumption("스풀 발주일", as_of.isoformat(), reason, False))
    layout = layout_for(scope)
    world = World(gen=gen, defaults=defaults, scope=scope, plan=plan, as_of=as_of, layout=layout)
    draft = world.snapshot(spool_order)
    snapshot = draft.model_copy(update={"snapshot_id": snapshot_id(draft)})
    request = AnalysisRequest(change=_change(case, scope, layout, as_of), as_of=as_of, confirm_on=confirm_on)
    return Built(
        snapshot=snapshot,
        request=request,
        erection_id=ids.activity_id(SHIP, BLOCK, ActivityKind.ERECTION),
        scope=scope,
        assumptions=tuple(notes),
    )


def _confirm_on(case: Case, as_of: date, notes: list[Assumption]) -> date:
    """확정일 = 기준일 + 결정까지 걸린 일수(비면 0일 — 기준일에 확정한 것으로 보고 '가정')."""
    if case.decision_days is None:
        notes.append(Assumption("결정까지 걸린 일수", "0", "비어 있어 확정일 = 기준일", True))
        return as_of
    return as_of + timedelta(days=case.decision_days)


def _change(case: Case, scope: Scope, layout: Layout, as_of: date) -> ChangeRequest:
    """사내 재제작·사외 재발주 = 경로 변경(빼는 스풀 + 같은 규격 새 스풀), 치수 변경 = 부재와 함께 치수 변경."""
    ops: list[ChangeOp] = []
    reroute = scope.spool_method != "dimension"
    if reroute and layout.spools:
        ops.append(ReroutePipe(removed_part_ids=layout.spools, added_spool_spec_ids=(SPOOL_SPEC,) * len(layout.spools)))
    reworked = layout.members + (() if reroute else layout.spools)
    if reworked:
        before, after = PLACEHOLDER_MM
        ops.append(DimensionChange(part_ids=reworked, field="length_mm", from_value=before, to_value=after))
    return ChangeRequest(
        ecn_id=f"BT-{case.row:04d}",
        title=f"백테스트 {case.number}",
        ship_ids=(SHIP,),
        ops=tuple(ops),
        requested_on=as_of,
        cause=scope.cause,
    )
