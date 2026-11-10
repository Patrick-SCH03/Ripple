"""최소 지도 조립(docs/backtest.md 3절): 범위(Scope)·공정 계획·기준일 → GraphSnapshot.

단가·선가·배 종류는 생성기 설정 범위의 가운데 값, 부재·스풀 무게와 일정 여유는 백테스트 기본값이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise

from ripple.contracts.domain import (
    BLOCK_ACTIVITY_ORDER,
    PO_STATUS_ORDER,
    Activity,
    ActivityKind,
    Block,
    BlockShape,
    Connection,
    ConnectionKind,
    DataMode,
    Drawing,
    GraphSnapshot,
    MaterialSpec,
    Part,
    PartKind,
    PipeSystem,
    POLine,
    POStatus,
    Precedence,
    PurchaseOrder,
    Ship,
    StatusObservation,
    Supplier,
    SupplierKind,
    Zone,
    ZoneBoundary,
)
from ripple.generator import ids
from ripple.generator.config import GeneratorConfig
from ripple.generator.schedule import LAUNCH_AFTER_EXIT_DAYS

from .crew import crews_for, performer_of
from .defaults import BacktestDefaults
from .plan import BlockPlan, OrderPlan, half_up, middle
from .scope import Scope

SHIP = "BT-001"
BLOCK = "B01"
ZONE = "ZBT"
SYSTEM = "backtest_piping"
STEEL_SUPPLIER, PIPE_SUPPLIER = "SUP-BT-ST", "SUP-BT-PP"
PLATE_SPEC, MEMBER_SPEC, SPOOL_SPEC = "PL-AH36-BT", "SC-BT", "SP-DN150-BT"
HULL_BASE, PIPE_BASE = f"DWG-{BLOCK}-H00", f"DWG-{BLOCK}-P00"
BLOCK_ID = ids.block_id(SHIP, BLOCK)
BASE_PART = ids.part_id(SHIP, BLOCK, "ST", 1)
STEEL_PO = "PO-0001"


@dataclass(frozen=True, slots=True)
class Layout:
    """부재 ID와 도면 배치. 바뀌는 부재·스풀을 차례로 d장에 나눠 그린다(도면마다 하나 이상)."""

    members: tuple[str, ...]
    spools: tuple[str, ...]  # 재제작 스풀(사슬 순서)
    ends: tuple[str, ...]  # 바뀌지 않는 양 끝 스풀(스풀이 있을 때만 2개)
    drawing_of: dict[str, str]
    drawings: tuple[Drawing, ...]


def layout_for(scope: Scope) -> Layout:
    members = tuple(ids.part_id(SHIP, BLOCK, "MB", n) for n in range(1, scope.members + 1))
    spools = tuple(ids.part_id(SHIP, BLOCK, "SP", n) for n in range(1, scope.spools + 1))
    ends = tuple(ids.part_id(SHIP, BLOCK, "SE", n) for n in (1, 2)) if spools else ()
    numbers = [f"DWG-{BLOCK}-{n:02d}" for n in range(1, scope.drawings + 1)]
    targets = members + spools
    drawing_of = {part_id: numbers[i % len(numbers)] for i, part_id in enumerate(targets)}
    drawings = [
        Drawing(
            drawing_no=number,
            revision="A",
            discipline="hull" if targets[i] in members else "piping",
            title=f"대상 블록 도면 {i + 1}",
        )
        for i, number in enumerate(numbers)
    ]
    drawings.append(Drawing(drawing_no=HULL_BASE, revision="A", discipline="hull", title="블록 구조도(바뀌지 않음)"))
    if ends:
        drawings.append(Drawing(drawing_no=PIPE_BASE, revision="A", discipline="piping", title="배관도(바뀌지 않음)"))
    return Layout(members, spools, ends, drawing_of, tuple(sorted(drawings, key=lambda d: d.drawing_no)))


@dataclass(frozen=True, slots=True)
class World:
    gen: GeneratorConfig
    defaults: BacktestDefaults
    scope: Scope
    plan: BlockPlan
    as_of: date
    layout: Layout

    def snapshot(self, spool_order: OrderPlan) -> GraphSnapshot:
        specs = _specs(self.gen, self.scope)
        prices = {spec.spec_id: spec.unit_price_krw for spec in specs}
        steel_lines, spool_lines = _steel_lines(self, prices), _spool_lines(self, prices)
        orders = (
            _order(STEEL_PO, STEEL_SUPPLIER, self.plan.steel, self.as_of),
            *(_order(line.po_id, PIPE_SUPPLIER, spool_order, self.as_of) for line in spool_lines),
        )
        return GraphSnapshot(
            snapshot_id="G-pending",
            origin="excel_import",
            data_mode=DataMode.REAL,
            ships=(self._ship(),),
            zones=(Zone(zone_id=ids.zone_id(SHIP, ZONE), ship_id=SHIP, name="대상 구역"),),
            boundaries=(
                ZoneBoundary(
                    zone_id=ids.zone_id(SHIP, ZONE),
                    exit_activity_id=ids.zone_exit_id(SHIP, ZONE),
                    float_to_delivery_days=self.defaults.schedule.float_to_delivery_days,
                ),
            ),
            blocks=(self._block(),),
            specs=specs,
            parts=_parts(self),
            connections=_connections(self.layout),
            suppliers=(
                Supplier(supplier_id=STEEL_SUPPLIER, name="강재 공급사", kind=SupplierKind.STEEL),
                Supplier(supplier_id=PIPE_SUPPLIER, name="배관재 협력사", kind=SupplierKind.PIPE),
            ),
            purchase_orders=orders,
            po_lines=steel_lines + spool_lines,
            stock=(),
            activities=_block_activities(self.plan, self.as_of, self.scope) + _milestones(self.plan, self.delivery()),
            drawings=self.layout.drawings,
            pipe_systems=(PipeSystem(system=SYSTEM, name="재제작 배관"),) if self.layout.spools else (),
            crews=crews_for(self.scope.performer),
        )

    def delivery(self) -> date:
        schedule = self.defaults.schedule
        return self.plan.exit_start + timedelta(days=schedule.post_exit_days + schedule.float_to_delivery_days)

    def _ship(self) -> Ship:
        ship = self.gen.ship
        return Ship(
            ship_id=SHIP,
            ship_type=ship.ship_type,
            dwt=ship.dwt,
            contract_price_krw=ship.contract_price_krw,
            delivery_date=self.delivery(),
        )

    def _block(self) -> Block:
        """블록 형상 = 사례의 블록 종류(재작업 난이도 계수). 사외 제작 협력사는 두지 않는다(수행 주체는 공정에,
        crew.py). 의장품·전장품 수는 양식에 없어 비워 둔다(밀도 계수 1)."""
        block_type = self.scope.block_type
        return Block(
            block_id=BLOCK_ID,
            ship_id=SHIP,
            zone_id=ids.zone_id(SHIP, ZONE),
            name="대상 블록",
            steel_weight_t=self.scope.weight_t,
            shape=None if block_type is None else BlockShape(block_type),
        )


def _specs(gen: GeneratorConfig, scope: Scope) -> tuple[MaterialSpec, ...]:
    """판·형강·스풀 규격. 스풀의 표준 리드타임 = 재제작 방식의 새 스풀 리드타임(사외 재발주면 비워 엔진 파라미터)."""
    prices = gen.prices
    plate = MaterialSpec(
        spec_id=PLATE_SPEC,
        category="plate",
        description="AH36 후판",
        grade="AH36",
        unit="t",
        unit_price_krw=half_up(middle(prices.plate_per_t)),
    )
    member = MaterialSpec(
        spec_id=MEMBER_SPEC,
        category="section",
        description="형강(바뀐 부재)",
        unit="t",
        unit_price_krw=half_up(middle(prices.section_per_t)),
    )
    spool = MaterialSpec(
        spec_id=SPOOL_SPEC,
        category="pipe",
        description="배관 스풀 DN150",
        unit="m",
        unit_price_krw=half_up(middle(prices.pipe_per_m)),
        std_lead_time_days=scope.spool_lead_days,
        nominal_diameter_dn=150,
        pressure_class="10K",
    )
    return plate, spool, member


def _part(part_id: str, kind: PartKind, name: str, spec_id: str, qty: float, drawing: str, kg: float | None) -> Part:
    piping = kind is PartKind.PIPE_SPOOL
    return Part(
        part_id=part_id,
        ship_id=SHIP,
        block_id=BLOCK_ID,
        kind=kind,
        name=name,
        spec_id=spec_id,
        qty=qty,
        drawing_no=drawing,
        revision="A",
        system=SYSTEM if piping else None,
        pid_class="pipe" if piping else None,
        weight_kg=kg,
    )


def _parts(world: World) -> tuple[Part, ...]:
    """블록 강재(무게 = 블록 무게) · 바뀐 부재(보강재) · 재제작 스풀 · 양 끝 스풀(무게 없음).

    블록 강재와 양 끝 스풀은 바뀌지 않는다."""
    layout, member, spool = world.layout, world.defaults.member, world.defaults.spool
    weight = world.scope.weight_t
    parts = [_part(BASE_PART, PartKind.PLATE, "블록 강재", PLATE_SPEC, weight, HULL_BASE, weight * 1000)]
    for n, part_id in enumerate(layout.members, start=1):
        drawing = layout.drawing_of[part_id]
        kg = member.weight_t * 1000
        parts.append(_part(part_id, PartKind.STIFFENER, f"바뀐 부재 {n}", MEMBER_SPEC, member.weight_t, drawing, kg))
    for n, part_id in enumerate(layout.spools, start=1):
        drawing = layout.drawing_of[part_id]
        kg = spool.weight_t * 1000
        parts.append(_part(part_id, PartKind.PIPE_SPOOL, f"재제작 스풀 {n}", SPOOL_SPEC, spool.length_m, drawing, kg))
    for n, part_id in enumerate(layout.ends, start=1):
        parts.append(
            _part(part_id, PartKind.PIPE_SPOOL, f"양 끝 스풀 {n}", SPOOL_SPEC, spool.length_m, PIPE_BASE, None)
        )
    return tuple(parts)


def _connections(layout: Layout) -> tuple[Connection, ...]:
    """양 끝 스풀 – 재제작 스풀 사슬 – 양 끝 스풀(배관 연결). 새 스풀이 양 끝에 이어져 '붙는 위치'를 안다."""
    if not layout.spools:
        return ()
    chain = (layout.ends[0], *layout.spools, layout.ends[1])
    return tuple(Connection(a=a, b=b, kind=ConnectionKind.PIPE_JOINT) for a, b in pairwise(chain))


def _steel_lines(world: World, prices: dict[str, int]) -> tuple[POLine, ...]:
    """강재 발주 1건: 블록 강재 품목 + 바뀐 부재 품목(소비 공정 = 소조립 — 블록의 '강재 입고'를 정한다)."""
    sub = ids.activity_id(SHIP, BLOCK, ActivityKind.SUB_ASSEMBLY)
    lines = [
        POLine(
            po_id=STEEL_PO,
            line_no=1,
            spec_id=PLATE_SPEC,
            qty=world.scope.weight_t,
            unit_price_krw=prices[PLATE_SPEC],
            part_ids=(BASE_PART,),
            consumed_by_activity_id=sub,
        )
    ]
    members = world.layout.members
    if members:
        qty = round(world.defaults.member.weight_t * len(members), 6)
        lines.append(
            POLine(
                po_id=STEEL_PO,
                line_no=2,
                spec_id=MEMBER_SPEC,
                qty=qty,
                unit_price_krw=prices[MEMBER_SPEC],
                part_ids=members,
                consumed_by_activity_id=sub,
            )
        )
    return tuple(lines)


def _spool_lines(world: World, prices: dict[str, int]) -> tuple[POLine, ...]:
    """재제작 스풀을 품목 k개에 차례로 나눔(품목마다 발주 하나, 소비 공정 = 선행의장)."""
    spools, count = world.layout.spools, world.scope.spool_lines
    outfit = ids.activity_id(SHIP, BLOCK, ActivityKind.PRE_OUTFITTING)
    lines = []
    for n in range(count):
        chunk = spools[n * len(spools) // count : (n + 1) * len(spools) // count]
        lines.append(
            POLine(
                po_id=f"PO-{n + 2:04d}",
                line_no=1,
                spec_id=SPOOL_SPEC,
                qty=round(world.defaults.spool.length_m * len(chunk), 6),
                unit_price_krw=prices[SPOOL_SPEC],
                part_ids=chunk,
                consumed_by_activity_id=outfit,
            )
        )
    return tuple(lines)


def _order(po_id: str, supplier_id: str, plan: OrderPlan, as_of: date) -> PurchaseOrder:
    """기준일까지 들어간 단계는 확인된 진입일로, 기준일 현재 상태는 발주대장 관측 하나로 남긴다."""
    reached = {stage: day for stage, day in plan.stages().items() if day <= as_of}
    status = max(reached, key=PO_STATUS_ORDER.index, default=POStatus.NOT_ORDERED)
    return PurchaseOrder(
        po_id=po_id,
        ship_id=SHIP,
        supplier_id=supplier_id,
        planned_order_date=plan.ordered,
        material_secured_days=plan.secured_days,
        fabrication_start_days=plan.fabrication_days,
        lead_time_days=plan.lead_days,
        entered_on=reached,
        observations=(StatusObservation(status=status, observed_on=as_of),),
    )


def _block_activities(plan: BlockPlan, as_of: date, scope: Scope) -> tuple[Activity, ...]:
    """블록 공정 사슬. 기준일까지 시작·끝난 공정은 계획 날짜 그대로 실적으로 둔다. 수행 주체는 crew.py."""
    activities: list[Activity] = []
    previous: str | None = None
    for kind in BLOCK_ACTIVITY_ORDER:
        start, finish = plan.starts[kind], plan.finish(kind)
        activity_id = ids.activity_id(SHIP, BLOCK, kind)
        activities.append(
            Activity(
                activity_id=activity_id,
                ship_id=SHIP,
                block_id=BLOCK_ID,
                kind=kind,
                duration_days=plan.durations[kind],
                planned_start=start,
                predecessors=() if previous is None else (Precedence(activity_id=previous),),
                actual_start=start if start <= as_of else None,
                actual_finish=finish if finish <= as_of else None,
                performer=performer_of(scope.performer, kind),
            )
        )
        previous = activity_id
    return tuple(activities)


def _milestones(plan: BlockPlan, delivery: date) -> tuple[Activity, ...]:
    """구역 출구(탑재 완료 + 여유) → 진수(생성기와 같은 간격) → 인도."""
    exit_id, launch_id = ids.zone_exit_id(SHIP, ZONE), ids.launch_id(SHIP)
    launch_day = plan.exit_start + timedelta(days=LAUNCH_AFTER_EXIT_DAYS)
    erection = ids.activity_id(SHIP, BLOCK, ActivityKind.ERECTION)
    lag = max(0, (delivery - launch_day).days)
    rows = (
        (exit_id, plan.exit_start, Precedence(activity_id=erection)),
        (launch_id, launch_day, Precedence(activity_id=exit_id)),
        (ids.delivery_id(SHIP), delivery, Precedence(activity_id=launch_id, lag_days=lag)),
    )
    return tuple(
        Activity(
            activity_id=activity_id,
            ship_id=SHIP,
            block_id=None,
            kind=ActivityKind.MILESTONE,
            duration_days=0,
            planned_start=day,
            predecessors=(predecessor,),
        )
        for activity_id, day, predecessor in rows
    )
