"""협력사·발주·발주 품목·재고.

강재는 블록 × 자재군(판·형강·브라켓)마다 규격 1~3개씩 묶어 발주하고, 품목의 소비 공정은 그 블록의
소조립이다. 배관은 계통마다 스풀·서포트·밸브 발주를 따로 내고, 소비 공정은 선행의장이다.
기준일 이전 단계는 발주마다 '확인된 진입일 + 기준일 상태(발주대장 내보내기) / 관측만 / 정보 없음' 중
하나의 형태로 남긴다.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from ripple.contracts.domain import (
    PO_STATUS_ORDER,
    ActivityKind,
    Part,
    PartKind,
    POLine,
    POStatus,
    PurchaseOrder,
    StatusObservation,
    StockLot,
    Supplier,
    SupplierKind,
)

from . import ids
from .config import GeneratorConfig, Span
from .rng import integer, sub_rng, uniform, weighted
from .schedule import BlockPlan
from .structure import Structure, ensure_plate_spec

SUPPLIERS: tuple[Supplier, ...] = (
    Supplier(supplier_id="SUP-ST1", name="제강사 A", kind=SupplierKind.STEEL),
    Supplier(supplier_id="SUP-ST2", name="제강사 B", kind=SupplierKind.STEEL),
    Supplier(supplier_id="SUP-PP1", name="배관재 공급사", kind=SupplierKind.PIPE),
    Supplier(supplier_id="SUP-VL1", name="밸브 제조사", kind=SupplierKind.EQUIPMENT),
    Supplier(supplier_id="SUP-EQ1", name="펌프 제조사", kind=SupplierKind.EQUIPMENT),  # v3 기자재 공급사(장비)
    Supplier(supplier_id="SUP-OS1", name="사외 협력사(단품 제작)", kind=SupplierKind.PARTS),  # v3 브라켓·서포트·칼라
)
PARTS_SUPPLIER = "SUP-OS1"
STEEL_GROUPS: tuple[tuple[PartKind, str], ...] = (
    (PartKind.PLATE, "SUP-ST1"),
    (PartKind.STIFFENER, "SUP-ST2"),
    (PartKind.BRACKET, PARTS_SUPPLIER),  # v3: 브라켓 단품은 사외 협력사(v2는 제강사 A)
)


@dataclass(frozen=True, slots=True)
class Procurement:
    suppliers: tuple[Supplier, ...]
    purchase_orders: tuple[PurchaseOrder, ...]
    po_lines: tuple[POLine, ...]
    stock: tuple[StockLot, ...]
    stage_days: dict[str, dict[POStatus, date]]


@dataclass(frozen=True, slots=True)
class Purchase:
    """발주 하나로 묶을 부재: 협력사, 소비 블록·공정, 리드타임 범위."""

    supplier_id: str
    block: str  # 소비 블록 코드
    consumer: ActivityKind
    lead: Span
    part_ids: tuple[str, ...]


class _Book:
    """발주 번호를 차례로 매기며 발주·품목·참 단계 날짜를 모은다(부재가 없으면 번호를 쓰지 않는다)."""

    def __init__(self, cfg: GeneratorConfig, seed: int, structure: Structure, plans: dict[str, BlockPlan]) -> None:
        self.cfg, self.seed, self.structure, self.plans = cfg, seed, structure, plans
        self.numbers = itertools.count(1)
        self.parts = {p.part_id: p for p in structure.parts}
        self.orders: list[PurchaseOrder] = []
        self.lines: list[POLine] = []
        self.stages: dict[str, dict[POStatus, date]] = {}

    def add(self, purchase: Purchase) -> None:
        if not purchase.part_ids:
            return
        cfg = self.cfg
        po_id = f"PO-{next(self.numbers):04d}"
        start = self.plans[purchase.block].starts[purchase.consumer]
        force = purchase.block in {cfg.demo.assembly_block, cfg.demo.not_started_block}
        order, stages = _order(cfg, self.seed, po_id, purchase.supplier_id, start, purchase.lead, force)
        self.orders.append(order)
        self.stages[po_id] = stages
        consumer = ids.activity_id(cfg.ship.ship_id, purchase.block, purchase.consumer)
        self.lines.extend(
            _lines(po_id, itertools.count(1), list(purchase.part_ids), self.parts, self.structure, consumer)
        )


def build_procurement(
    cfg: GeneratorConfig, seed: int, structure: Structure, plans: dict[str, BlockPlan]
) -> Procurement:
    ship = cfg.ship.ship_id
    book = _Book(cfg, seed, structure, plans)
    for block in cfg.blocks:
        rng = sub_rng(seed, "procurement", "steel", block.code)
        for kind, supplier_id in STEEL_GROUPS:
            by_spec: dict[str, list[str]] = defaultdict(list)
            for part in structure.parts:
                if part.block_id == ids.block_id(ship, block.code) and part.kind is kind:
                    by_spec[part.spec_id].append(part.part_id)
            specs = sorted(by_spec)
            while specs:
                size = integer(rng, cfg.procurement.specs_per_steel_po)
                chunk, specs = specs[:size], specs[size:]
                part_ids = tuple(part_id for spec_id in chunk for part_id in by_spec[spec_id])
                lead = cfg.procurement.plate_lead_days
                book.add(Purchase(supplier_id, block.code, ActivityKind.SUB_ASSEMBLY, lead, part_ids))

    for system in cfg.piping.systems:
        home = ids.block_id(ship, system.block)
        system_parts = [p for p in structure.parts if p.system == system.name and p.block_id == home]
        for kind, supplier_id, lead in (
            (PartKind.PIPE_SPOOL, "SUP-PP1", cfg.procurement.pipe_lead_days),
            (PartKind.PIPE_SUPPORT, PARTS_SUPPLIER, cfg.procurement.pipe_lead_days),  # v3: 서포트 단품은 사외 협력사
            (PartKind.VALVE, "SUP-VL1", cfg.procurement.valve_lead_days),
        ):
            part_ids = tuple(p.part_id for p in system_parts if p.kind is kind)
            book.add(Purchase(supplier_id, system.block, ActivityKind.PRE_OUTFITTING, lead, part_ids))

    # v3 발주(번호는 v2 발주 뒤로 이어 붙여 v2 발주 번호·품목은 그대로): 이웃 블록 스풀 · 계통 장비 · 관통 칼라
    for purchase in _v3_purchases(cfg, structure):
        book.add(purchase)

    return Procurement(
        suppliers=SUPPLIERS,
        purchase_orders=tuple(book.orders),
        po_lines=tuple(book.lines),
        stock=_stock(cfg, seed, structure, plans),
        stage_days=book.stages,
    )


def _v3_purchases(cfg: GeneratorConfig, structure: Structure) -> list[Purchase]:
    """v3 부재의 발주: 계통마다 이웃 블록 스풀(그 블록 선행의장) · 장비(주 블록 선행의장),
    관통 칼라(관통 블록 선행의장)."""
    ship = cfg.ship.ship_id
    work = ActivityKind.PRE_OUTFITTING
    found: list[Purchase] = []
    for system in cfg.piping.systems:
        crossing = tuple(p.part_id for p in structure.cross_spools_by_system.get(system.code, ()))
        if system.extends_to is not None:
            found.append(Purchase("SUP-PP1", system.extends_to, work, cfg.procurement.pipe_lead_days, crossing))
        home = ids.block_id(ship, system.block)
        pumps = tuple(
            p.part_id
            for p in structure.parts
            if p.kind is PartKind.EQUIPMENT and p.system == system.name and p.block_id == home
        )
        found.append(Purchase("SUP-EQ1", system.block, work, cfg.procurement.equipment_lead_days, pumps))
    through = cfg.piping.penetrations.through_block
    collars = tuple(
        p.part_id for p in structure.parts if p.kind is PartKind.COLLAR and p.block_id == ids.block_id(ship, through)
    )
    found.append(Purchase(PARTS_SUPPLIER, through, work, cfg.procurement.parts_lead_days, collars))
    return found


def _order(
    cfg: GeneratorConfig,
    seed: int,
    po_id: str,
    supplier_id: str,
    consumer_start: date,
    lead_span: Span,
    force_known: bool,
) -> tuple[PurchaseOrder, dict[POStatus, date]]:
    rng = sub_rng(seed, "order", po_id)
    config = cfg.procurement
    lead = integer(rng, lead_span)
    secured = round(lead * uniform(rng, config.material_secured_ratio))
    fabrication = max(secured, round(lead * uniform(rng, config.fabrication_start_ratio)))
    planned = consumer_start - timedelta(days=lead + integer(rng, config.order_slack_days))
    ordered = planned + timedelta(days=rng.randint(0, 3))
    stage_days = {
        POStatus.ORDERED: ordered,
        POStatus.MATERIAL_SECURED: ordered + timedelta(days=secured),
        POStatus.IN_FABRICATION: ordered + timedelta(days=fabrication),
        POStatus.RECEIVED: ordered + timedelta(days=lead + rng.randint(0, 5)),
    }
    reached = {stage: day for stage, day in stage_days.items() if day <= cfg.scenario_date}
    mix = {
        "entered_on": config.evidence.entered_on,
        "observations_only": config.evidence.observations_only,
        "unknown": config.evidence.unknown,
    }
    mode = "entered_on" if force_known else weighted(rng, mix)
    common = {
        "po_id": po_id,
        "ship_id": cfg.ship.ship_id,
        "supplier_id": supplier_id,
        "material_secured_days": secured,
        "fabrication_start_days": fabrication,
        "lead_time_days": lead,
    }
    if mode == "entered_on":
        # 발주대장 내보내기: 확인된 진입일과 함께 기준일 현재 상태가 남는다(빈 칸 = 아직 그 단계 전)
        export = StatusObservation(status=_status_on(reached, cfg.scenario_date), observed_on=cfg.scenario_date)
        return (
            PurchaseOrder(planned_order_date=planned, entered_on=reached, observations=(export,), **common),
            stage_days,
        )
    if mode == "observations_only":
        days = sorted({cfg.scenario_date - timedelta(days=rng.randint(0, 30)) for _ in range(2)})
        observations = tuple(StatusObservation(status=_status_on(reached, day), observed_on=day) for day in days)
        return PurchaseOrder(planned_order_date=planned, observations=observations, **common), stage_days
    return PurchaseOrder(planned_order_date=None, **common), stage_days


def _status_on(reached: dict[POStatus, date], day: date) -> POStatus:
    status = POStatus.NOT_ORDERED
    for stage in PO_STATUS_ORDER:
        entered = reached.get(stage)
        if entered is not None and entered <= day:
            status = stage
    return status


def _lines(
    po_id: str,
    numbers: itertools.count[int],
    part_ids: list[str],
    parts_by_id: dict[str, Part],
    structure: Structure,
    consumer: str,
) -> list[POLine]:
    grouped: dict[str, list[str]] = defaultdict(list)
    quantities: dict[str, float] = defaultdict(float)
    for part_id in part_ids:
        part = parts_by_id[part_id]
        grouped[part.spec_id].append(part_id)
        quantities[part.spec_id] += part.qty
    return [
        POLine(
            po_id=po_id,
            line_no=next(numbers),
            spec_id=spec_id,
            qty=round(quantities[spec_id], 3),
            unit_price_krw=structure.specs[spec_id].unit_price_krw,
            part_ids=tuple(sorted(grouped[spec_id])),
            consumed_by_activity_id=consumer,
        )
        for spec_id in sorted(grouped)
    ]


def _stock(cfg: GeneratorConfig, seed: int, structure: Structure, plans: dict[str, BlockPlan]) -> tuple[StockLot, ...]:
    """조립 중 데모 블록의 판보다 1~2mm 두꺼운 규격의 잉여 재고(잉여 자재 전용 시연용)."""
    ship = cfg.ship.ship_id
    rng = sub_rng(seed, "stock")
    plates = structure.plates_by_block[cfg.demo.assembly_block]
    later = sorted(
        (b.code for b in cfg.blocks if plans[b.code].starts[ActivityKind.SUB_ASSEMBLY] > cfg.scenario_date),
    )
    lots = []
    for number in range(1, integer(rng, cfg.procurement.stock_lots) + 1):
        base = plates[rng.randrange(len(plates))]
        thickness = min((base.thickness_mm or 12.0) + (1.0, 1.5, 2.0)[rng.randrange(3)], 20.0)
        spec_id = ensure_plate_spec(cfg, seed, structure, base.grade or "AH36", thickness)
        reserved = later[rng.randrange(len(later))] if later and rng.random() < 0.5 else None
        lots.append(
            StockLot(
                lot_id=f"LOT-{number:02d}",
                spec_id=spec_id,
                qty=round(rng.uniform(2.0, 8.0), 2),
                received_date=cfg.scenario_date - timedelta(days=rng.randint(10, 60)),
                reserved_block_id=ids.block_id(ship, reserved) if reserved else None,
            )
        )
    return tuple(lots)
