"""블록 공정·이정표·경계 조건.

블록마다 PE 착수일(설정 pe_offset)을 정하고 소조립~선행도장을 거꾸로, 탑재를 PE 뒤로 배치한다. 기준일 이전 공정에는
실제 착수·완료일을 넣되, 앞 공정이 끝나기 전에는 다음 공정이 시작하지 않게 한다.

v3(PE): v2의 탑재 착수일 자리에 PE를 두고 탑재를 그 뒤로 옮겼다. 소조립~선행도장의 날짜와 난수열(v2 뽑기 순서)은
그대로라 기준일의 블록 단계와 시연 고정점이 v2와 같다. PE 기간·PE 뒤 간격은 블록마다 따로 뽑는다.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from ripple.contracts.domain import (
    BLOCK_ACTIVITY_ORDER,
    DIRECT_PERFORMER,
    Activity,
    ActivityKind,
    Precedence,
    ZoneBoundary,
)

from . import ids
from .config import BlockConfig, DurationConfig, GeneratorConfig
from .rng import integer, sub_rng, uniform

BLOCK_SEQUENCE = BLOCK_ACTIVITY_ORDER
V2_SEQUENCE = (
    ActivityKind.SUB_ASSEMBLY,
    ActivityKind.PANEL,
    ActivityKind.ASSEMBLY,
    ActivityKind.PRE_OUTFITTING,
    ActivityKind.PRE_PAINTING,
    ActivityKind.ERECTION,
)
"""v2 공정 기간·간격 뽑기 순서(난수열을 지키려고 그대로 둔다). PE는 따로 뽑는다."""
LAUNCH_AFTER_EXIT_DAYS = 5


@dataclass(frozen=True, slots=True)
class BlockPlan:
    code: str
    starts: dict[ActivityKind, date]
    durations: dict[ActivityKind, int]

    def finish(self, kind: ActivityKind) -> date:
        return self.starts[kind] + timedelta(days=self.durations[kind])


def plan_blocks(cfg: GeneratorConfig, seed: int) -> dict[str, BlockPlan]:
    plans: dict[str, BlockPlan] = {}
    for block in cfg.blocks:
        rng = sub_rng(seed, "schedule", block.code)
        durations = {kind: _duration(rng, _duration_config(cfg, kind), block) for kind in V2_SEQUENCE}
        pe_rng = sub_rng(seed, "schedule", block.code, ActivityKind.PRE_ERECTION.value)
        durations[ActivityKind.PRE_ERECTION] = _duration(pe_rng, cfg.activities.pre_erection, block)
        pe_start = cfg.scenario_date + timedelta(days=block.pe_offset)
        starts = {ActivityKind.PRE_ERECTION: pe_start}
        cursor = pe_start
        for kind in reversed(V2_SEQUENCE[:-1]):
            gap = integer(rng, cfg.activities.gap_days)
            starts[kind] = cursor - timedelta(days=gap + durations[kind])
            cursor = starts[kind]
        pe_gap = integer(pe_rng, cfg.activities.gap_days)
        starts[ActivityKind.ERECTION] = pe_start + timedelta(days=durations[ActivityKind.PRE_ERECTION] + pe_gap)
        plans[block.code] = BlockPlan(code=block.code, starts=starts, durations=durations)
    return plans


def make_activities(cfg: GeneratorConfig, seed: int, plans: dict[str, BlockPlan]) -> tuple[Activity, ...]:
    ship = cfg.ship.ship_id
    as_of = cfg.scenario_date
    activities: list[Activity] = []
    for block in cfg.blocks:
        plan = plans[block.code]
        rng = sub_rng(seed, "actuals", block.code)
        previous_id: str | None = None
        previous_finish: date | None = None
        for kind in BLOCK_SEQUENCE:
            planned = plan.starts[kind]
            actual_start: date | None = None
            actual_finish: date | None = None
            ready = previous_id is None or previous_finish is not None
            if ready and planned <= as_of:
                candidate = planned + timedelta(days=integer(rng, cfg.activities.actual_delay_days))
                if previous_finish is not None:
                    candidate = max(candidate, previous_finish)
                if candidate <= as_of:
                    actual_start = candidate
                    finish = candidate + timedelta(days=plan.durations[kind])
                    actual_finish = finish if finish <= as_of else None
            activity_id = ids.activity_id(ship, block.code, kind)
            activity = Activity(
                activity_id=activity_id,
                ship_id=ship,
                block_id=ids.block_id(ship, block.code),
                kind=kind,
                duration_days=plan.durations[kind],
                planned_start=planned,
                predecessors=() if previous_id is None else (Precedence(activity_id=previous_id),),
                actual_start=actual_start,
                actual_finish=actual_finish,
                performer=performer(cfg, seed, activity_id, kind),
            )
            activities.append(activity)
            previous_id = activity.activity_id
            previous_finish = actual_finish
    activities.extend(_milestones(cfg, plans))
    return tuple(activities)


def performer(cfg: GeneratorConfig, seed: int, activity_id: str, kind: ActivityKind) -> str:
    """공정 수행 주체(v3): 탑재는 직영, 그 밖의 블록 공정은 확률 crews.share로 그 공정을 맡는 작업반 하나, 아니면 직영.
    공정마다 따로 뽑아(난수원 'crew'·공정 ID) 다른 생성 순서와 무관하다."""
    teams = [team for team in cfg.crews.teams if kind in team.processes]
    if kind is ActivityKind.ERECTION or not teams:
        return DIRECT_PERFORMER
    rng = sub_rng(seed, "crew", activity_id)
    if rng.random() >= cfg.crews.share:
        return DIRECT_PERFORMER
    return teams[rng.randrange(len(teams))].code


def make_boundaries(cfg: GeneratorConfig, activities: tuple[Activity, ...]) -> tuple[ZoneBoundary, ...]:
    ship = cfg.ship.ship_id
    by_id = {a.activity_id: a for a in activities}
    delivery = cfg.scenario_date + timedelta(days=cfg.ship.delivery_offset_days)
    boundaries = []
    for zone in cfg.zones:
        exit_activity = by_id[ids.zone_exit_id(ship, zone.code)]
        slack = (delivery - exit_activity.planned_start).days - zone.post_exit_days
        if slack < 0:
            raise ValueError(f"설정 오류: {zone.code} 구역 출구에서 인도까지 여유가 음수예요({slack}일)")
        boundaries.append(
            ZoneBoundary(
                zone_id=ids.zone_id(ship, zone.code),
                exit_activity_id=exit_activity.activity_id,
                float_to_delivery_days=slack,
                forecast_delivery_delay_days=zone.forecast_delay_days,
            )
        )
    return tuple(boundaries)


def _milestones(cfg: GeneratorConfig, plans: dict[str, BlockPlan]) -> list[Activity]:
    """구역 탑재 완료(구역마다) → 진수 → 시운전(v3) → 인도."""
    ship = cfg.ship.ship_id
    milestones: list[Activity] = []
    exits: list[Activity] = []
    for zone in cfg.zones:
        codes = [b.code for b in cfg.blocks if b.zone == zone.code]
        erection_ids = [ids.activity_id(ship, code, ActivityKind.ERECTION) for code in codes]
        exit_activity = _milestone(
            ids.zone_exit_id(ship, zone.code),
            ship,
            max(plans[code].finish(ActivityKind.ERECTION) for code in codes),
            tuple(Precedence(activity_id=a) for a in erection_ids),
        )
        exits.append(exit_activity)
    milestones.extend(exits)
    launch_day = max(e.planned_start for e in exits) + timedelta(days=LAUNCH_AFTER_EXIT_DAYS)
    launch = _milestone(
        ids.launch_id(ship), ship, launch_day, tuple(Precedence(activity_id=e.activity_id) for e in exits)
    )
    delivery_day = cfg.scenario_date + timedelta(days=cfg.ship.delivery_offset_days)
    trial_day = max(launch_day, delivery_day - timedelta(days=cfg.ship.sea_trial_before_delivery_days))
    trial = _milestone(
        ids.sea_trial_id(ship),
        ship,
        trial_day,
        (Precedence(activity_id=launch.activity_id, lag_days=(trial_day - launch_day).days),),
    )
    delivery = _milestone(
        ids.delivery_id(ship),
        ship,
        delivery_day,
        (Precedence(activity_id=trial.activity_id, lag_days=max(0, (delivery_day - trial_day).days)),),
    )
    milestones.extend([launch, trial, delivery])
    return milestones


def _milestone(activity_id: str, ship: str, day: date, predecessors: tuple[Precedence, ...]) -> Activity:
    return Activity(
        activity_id=activity_id,
        ship_id=ship,
        block_id=None,
        kind=ActivityKind.MILESTONE,
        duration_days=0,
        planned_start=day,
        predecessors=predecessors,
    )


def _duration_config(cfg: GeneratorConfig, kind: ActivityKind) -> DurationConfig:
    config: DurationConfig = getattr(cfg.activities, kind.value)
    return config


def _duration(rng: random.Random, config: DurationConfig, block: BlockConfig) -> int:
    return max(1, round(uniform(rng, config.base) + uniform(rng, config.per_100t) * block.weight_t / 100))
