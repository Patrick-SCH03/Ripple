"""생성기 조립: 설정·시드 → 지도(GraphSnapshot)와 설계변경 사례."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ripple.contracts.dataset import EcnSplit, GeneratedEcn
from ripple.contracts.domain import ActivityKind, DataMode, GraphSnapshot, PipeSystem, POStatus
from ripple.contracts.identity import snapshot_id

from . import ids
from .config import GeneratorConfig
from .ecn import make_ecns
from .imports import apply_imports
from .procurement import build_procurement
from .relations import RelationsError, relate
from .rng import sub_rng
from .schedule import make_activities, make_boundaries, plan_blocks
from .ship import make_blocks, make_crews, make_ship, make_zones
from .structure import build_structure


class GeneratorError(ValueError):
    """설정이나 데모 고정점이 맞지 않아 생성을 멈춘다."""


@dataclass(frozen=True, slots=True)
class Generated:
    config_version: str
    seed: int
    snapshot: GraphSnapshot
    ecns: tuple[GeneratedEcn, ...]
    actual_po_stages: dict[str, dict[POStatus, date]]
    actual_activity_start_floor: dict[str, date]


def generate(cfg: GeneratorConfig, seed: int | None = None) -> Generated:
    seed = cfg.seed if seed is None else seed
    plans = plan_blocks(cfg, seed)
    activities = make_activities(cfg, seed, plans)
    structure = build_structure(cfg, seed)
    apply_imports(cfg, structure)  # v4 외자재 규격(규격만 — 난수열·발주는 그대로)
    procurement = build_procurement(cfg, seed, structure, plans)
    draft = GraphSnapshot(
        snapshot_id="G-pending",
        origin="generator",
        data_mode=DataMode.SYNTHETIC,
        ships=(make_ship(cfg),),
        zones=make_zones(cfg),
        boundaries=make_boundaries(cfg, activities),
        blocks=make_blocks(cfg, seed),
        specs=tuple(sorted(structure.specs.values(), key=lambda s: s.spec_id)),
        parts=tuple(structure.parts),
        connections=tuple(structure.connections),
        suppliers=procurement.suppliers,
        purchase_orders=procurement.purchase_orders,
        po_lines=procurement.po_lines,
        stock=procurement.stock,
        activities=activities,
        drawings=tuple(sorted(structure.drawings.values(), key=lambda d: d.drawing_no)),
        pipe_systems=tuple(PipeSystem(system=s.name, name=s.label) for s in cfg.piping.systems),
        crews=make_crews(cfg),
    )
    snapshot = draft.model_copy(update={"snapshot_id": snapshot_id(draft)})
    problems = demo_problems(cfg, snapshot)
    if problems:
        raise GeneratorError("데모 고정점이 맞지 않아요: " + "; ".join(problems))
    ecns = make_ecns(cfg, snapshot, EcnSplit.DEV, cfg.ecn.dev, seed) + make_ecns(
        cfg, snapshot, EcnSplit.EVAL, cfg.ecn.eval, seed
    )
    if cfg.relations is not None:  # 시연 합성 지도: 설계변경은 기본 지도와 같게 두고 관계만 더한다
        try:
            related = relate(cfg.relations, snapshot, cfg.ship.ship_id)
        except RelationsError as error:
            raise GeneratorError(str(error)) from error
        snapshot = related.model_copy(update={"snapshot_id": snapshot_id(related)})
    floors = {
        a.activity_id: a.planned_start
        + timedelta(days=sub_rng(seed, "actuals", "activity", a.activity_id).randint(0, 3))
        for a in activities
        if a.kind is not ActivityKind.MILESTONE
    }
    return Generated(
        config_version=cfg.version,
        seed=seed,
        snapshot=snapshot,
        ecns=tuple(ecns),
        actual_po_stages=procurement.stage_days,
        actual_activity_start_floor=floors,
    )


def demo_problems(cfg: GeneratorConfig, snapshot: GraphSnapshot) -> list[str]:
    """데모 시나리오가 성립하는지 기준일 기준으로 확인한다(엔진을 쓰지 않고 날짜만 본다)."""
    ship = cfg.ship.ship_id
    as_of = cfg.scenario_date
    activities = {a.activity_id: a for a in snapshot.activities}
    orders = {p.po_id: p for p in snapshot.purchase_orders}
    problems: list[str] = []

    assembly = activities[ids.activity_id(ship, cfg.demo.assembly_block, ActivityKind.ASSEMBLY)]
    if not (assembly.actual_start is not None and assembly.actual_start <= as_of and assembly.actual_finish is None):
        problems.append(f"{cfg.demo.assembly_block}가 기준일에 조립 중이 아니에요")
    sub_id = ids.activity_id(ship, cfg.demo.assembly_block, ActivityKind.SUB_ASSEMBLY)
    if activities[sub_id].actual_start is None:
        problems.append(f"{cfg.demo.assembly_block} 소조립이 시작되지 않아 판이 가공 전이에요")
    steel_orders = {line.po_id for line in snapshot.po_lines if line.consumed_by_activity_id == sub_id}
    for po_id in sorted(steel_orders):
        received = orders[po_id].entered_on.get(POStatus.RECEIVED)
        if received is None or received > as_of:
            problems.append(f"{po_id}(판 발주)이 기준일까지 입고되지 않았어요")

    not_started = [a for a in snapshot.activities if a.block_id == ids.block_id(ship, cfg.demo.not_started_block)]
    if any(a.actual_start is not None for a in not_started):
        problems.append(f"{cfg.demo.not_started_block}가 이미 착수됐어요")
    outfitting_id = ids.activity_id(ship, cfg.demo.not_started_block, ActivityKind.PRE_OUTFITTING)
    valve_specs = {s.spec_id for s in snapshot.specs if s.category == "valve"}
    valve_orders = {
        line.po_id
        for line in snapshot.po_lines
        if line.consumed_by_activity_id == outfitting_id and line.spec_id in valve_specs
    }
    if not valve_orders:
        problems.append(f"{cfg.demo.not_started_block}에 밸브 발주가 없어요")
    for po_id in sorted(valve_orders):
        planned = orders[po_id].planned_order_date
        if planned is None or planned <= as_of:
            problems.append(f"{po_id}(밸브 발주)이 기준일에 이미 발주됐거나 계획일이 없어요")

    control_blocks = {b.block_id for b in snapshot.blocks if b.zone_id == ids.zone_id(ship, cfg.demo.control_zone)}
    if any(a.block_id in control_blocks and a.actual_start is not None for a in snapshot.activities):
        problems.append(f"대조 구역 {cfg.demo.control_zone}에 착수한 공정이 있어요")
    early = sorted(
        a.activity_id
        for a in snapshot.activities
        if a.kind in (ActivityKind.PRE_ERECTION, ActivityKind.ERECTION) and a.actual_start is not None
    )
    if early:
        problems.append(f"PE·탑재가 기준일에 이미 착수됐어요(v2와 같은 블록 단계가 아님): {early[:3]}")
    return problems
