"""대상 블록 하나의 공정 계획과 발견 단계 → 기준일(docs/backtest.md 3절).

공정 기간·간격·발주 리드타임·자재 확보·제작 착수 비율은 생성기 설정(generator/config.yaml) 범위의 가운데 값을 쓴다
(난수 없음 — 같은 사례면 같은 지도). 기간 = 기본 + 100t당 × 블록 무게 / 100, 반올림(0.5는 올림), 최소 1일.
탑재 착수 계획일에서 공정을 거꾸로 배치한다(생성기 plan_blocks와 같은 방식).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from types import MappingProxyType

from ripple.contracts.domain import BLOCK_ACTIVITY_ORDER, STAGE_OF_ACTIVITY, ActivityKind, BlockStage, POStatus
from ripple.generator.config import DurationConfig, GeneratorConfig, Span

from .defaults import ScheduleDefaults

ACTIVITY_OF_STAGE: Mapping[BlockStage, ActivityKind] = MappingProxyType(
    {stage: kind for kind, stage in STAGE_OF_ACTIVITY.items()}
)


def middle(span: Span) -> float:
    return (span.lo + span.hi) / 2


def half_up(value: float) -> int:
    return math.floor(value + 0.5)


@dataclass(frozen=True, slots=True)
class OrderPlan:
    """발주 하나의 단계 날짜(계획 발주일 + 생성기 비율로 정한 간격)."""

    ordered: date
    secured_days: int
    fabrication_days: int
    lead_days: int

    def stages(self) -> dict[POStatus, date]:
        return {
            POStatus.ORDERED: self.ordered,
            POStatus.MATERIAL_SECURED: self.ordered + timedelta(days=self.secured_days),
            POStatus.IN_FABRICATION: self.ordered + timedelta(days=self.fabrication_days),
            POStatus.RECEIVED: self.ordered + timedelta(days=self.lead_days),
        }

    def ordered_on(self, day: date) -> OrderPlan:
        """발주일만 옮긴 계획(간격은 그대로)."""
        return replace(self, ordered=day)


@dataclass(frozen=True, slots=True)
class BlockPlan:
    starts: Mapping[ActivityKind, date]
    durations: Mapping[ActivityKind, int]
    exit_start: date  # 구역 출구 이정표 계획일
    steel: OrderPlan  # 강재 발주(소비 공정 = 소조립)
    spool: OrderPlan  # 스풀 발주(소비 공정 = 선행의장)

    def finish(self, kind: ActivityKind) -> date:
        return self.starts[kind] + timedelta(days=self.durations[kind])


def make_plan(gen: GeneratorConfig, schedule: ScheduleDefaults, weight_t: float) -> BlockPlan:
    durations = {kind: _duration(_config(gen, kind), weight_t) for kind in BLOCK_ACTIVITY_ORDER}
    gap = half_up(middle(gen.activities.gap_days))
    starts = {ActivityKind.ERECTION: schedule.erection_start}
    cursor = schedule.erection_start
    for kind in reversed(BLOCK_ACTIVITY_ORDER[:-1]):
        starts[kind] = cursor - timedelta(days=gap + durations[kind])
        cursor = starts[kind]
    erection_finish = starts[ActivityKind.ERECTION] + timedelta(days=durations[ActivityKind.ERECTION])
    procurement = gen.procurement
    return BlockPlan(
        starts=MappingProxyType(starts),
        durations=MappingProxyType(durations),
        exit_start=erection_finish + timedelta(days=schedule.exit_slack_days),
        steel=_order(gen, starts[ActivityKind.SUB_ASSEMBLY], procurement.plate_lead_days),
        spool=_order(gen, starts[ActivityKind.PRE_OUTFITTING], procurement.pipe_lead_days),
    )


def _config(gen: GeneratorConfig, kind: ActivityKind) -> DurationConfig:
    config: DurationConfig = getattr(gen.activities, kind.value)
    return config


def _duration(config: DurationConfig, weight_t: float) -> int:
    return max(1, half_up(middle(config.base) + middle(config.per_100t) * weight_t / 100))


def _order(gen: GeneratorConfig, consumer_start: date, lead_span: Span) -> OrderPlan:
    """생성기 _order의 가운데 값: 발주일 = 소비 공정 착수 − 리드타임 − 여유, 입고 = 발주 + 리드타임."""
    procurement = gen.procurement
    lead = half_up(middle(lead_span))
    secured = half_up(lead * middle(procurement.material_secured_ratio))
    fabrication = max(secured, half_up(lead * middle(procurement.fabrication_start_ratio)))
    slack = half_up(middle(procurement.order_slack_days))
    return OrderPlan(
        ordered=consumer_start - timedelta(days=lead + slack),
        secured_days=secured,
        fabrication_days=fabrication,
        lead_days=lead,
    )


def stage_window(plan: BlockPlan, stage: BlockStage) -> tuple[date, int]:
    """발견 단계가 '진행 중'인 날의 구간(첫날, 일수 ≥ 1).

    미착수 = 강재 발주 ~ 입고 전날, 강재 입고 = 입고 ~ 소조립 착수 전날, 공정 단계 = 그 공정 착수 ~ 완료 전날.
    """
    steel = plan.steel.stages()
    if stage is BlockStage.NOT_STARTED:
        first, end = steel[POStatus.ORDERED], steel[POStatus.RECEIVED]
    elif stage is BlockStage.STEEL_RECEIVED:
        first, end = steel[POStatus.RECEIVED], plan.starts[ActivityKind.SUB_ASSEMBLY]
    else:
        kind = ACTIVITY_OF_STAGE[stage]
        first, end = plan.starts[kind], plan.finish(kind)
    return first, max(1, (end - first).days)


def as_of_for(plan: BlockPlan, stage: BlockStage, position: float) -> date:
    """기준일 = 발견 단계 구간 안의 position 위치(0 = 첫날, 1 = 마지막 날, 내림)."""
    first, days = stage_window(plan, stage)
    return first + timedelta(days=math.floor((days - 1) * position))
