"""배관 계통: 스풀을 사슬로 잇고 밸브를 사이에 끼우며, 서포트가 스풀을 받친다."""

from __future__ import annotations

import random
from dataclasses import dataclass
from itertools import pairwise

from ripple.contracts.domain import Connection, ConnectionKind, Drawing, MaterialSpec, Part, PartKind

from .. import ids
from ..config import BlockConfig, GeneratorConfig, PipeSystemConfig
from ..rng import integer, sub_rng
from .base import PIPE_DIAMETERS_DN, VALVE_CLASSES, VALVE_LABELS, VALVE_TYPES, Structure, spec_price

CROSS_START = 101
"""이웃 블록으로 이어지는 스풀의 첫 번호(v3)."""


@dataclass(frozen=True, slots=True)
class _Piping:
    """배관 계통 하나를 만드는 동안 같이 쓰는 값. 난수원은 계통마다 하나이고 부재를 만드는 순서대로 뽑는다."""

    cfg: GeneratorConfig
    seed: int
    structure: Structure
    system: PipeSystemConfig
    rng: random.Random
    diameter: int
    pressure_class: str
    common: dict[str, str]


def pipe_system(
    cfg: GeneratorConfig, seed: int, block: BlockConfig, system: PipeSystemConfig, structure: Structure
) -> None:
    """배관 계통 하나의 스풀 사슬·밸브·서포트. 계통 지름·압력 등급을 먼저 뽑는다."""
    ship = cfg.ship.ship_id
    rng = sub_rng(seed, "piping", system.code)
    drawing_no = ids.piping_drawing(block.code, system.code)
    structure.drawings[drawing_no] = Drawing(
        drawing_no=drawing_no, revision="A", discipline="piping", title=f"{system.label} 배관도"
    )
    diameter = PIPE_DIAMETERS_DN[rng.randrange(len(PIPE_DIAMETERS_DN))]
    pressure_class = VALVE_CLASSES[rng.randrange(len(VALVE_CLASSES))]
    common = {
        "ship_id": ship,
        "block_id": ids.block_id(ship, block.code),
        "drawing_no": drawing_no,
        "revision": "A",
        "system": system.name,
    }
    piping = _Piping(cfg, seed, structure, system, rng, diameter, pressure_class, common)
    spools = _spools(piping, block)
    structure.parts.extend(spools)
    structure.spools_by_system[system.code] = spools
    _valves(piping, block, spools)
    _supports(piping, block, spools)
    # v3: 난수원을 따로 써서(위 부재의 난수열은 v2 그대로) 이웃 블록으로 이어지는 스풀과 계통 장비를 더한다
    if system.extends_to is not None:
        _cross_block(piping, spools, next(b for b in cfg.blocks if b.code == system.extends_to))
    if system.equipment is not None:
        _equipment(piping, block, spools[0])


def _spools(piping: _Piping, block: BlockConfig) -> list[Part]:
    """스풀 사슬(길이 2~6m)."""
    system, rng = piping.system, piping.rng
    spool_spec = f"SP-DN{piping.diameter}-S40"
    if spool_spec not in piping.structure.specs:
        piping.structure.specs[spool_spec] = MaterialSpec(
            spec_id=spool_spec,
            category="pipe",
            description=f"배관 스풀 DN{piping.diameter} SCH40",
            unit="m",
            nominal_diameter_dn=piping.diameter,
            pressure_class=piping.pressure_class,
            unit_price_krw=spec_price(piping.seed, spool_spec, piping.cfg.prices.pipe_per_m),
        )
    return [
        Part(
            part_id=ids.part_id(piping.cfg.ship.ship_id, block.code, f"SP{system.code}", number),
            kind=PartKind.PIPE_SPOOL,
            name=f"{system.label} 스풀 {number}",
            spec_id=spool_spec,
            qty=round(rng.uniform(2.0, 6.0), 1),
            pid_class="pipe",
            **piping.common,
        )
        for number in range(1, integer(rng, piping.cfg.piping.spools_per_system) + 1)
    ]


def _valves(piping: _Piping, block: BlockConfig, spools: list[Part]) -> None:
    """스풀 사이 이음마다 배관 연결. 고른 이음 자리에는 밸브를 끼워 양쪽 스풀과 잇는다."""
    structure, rng = piping.structure, piping.rng
    valve_count = min(integer(rng, piping.cfg.piping.valves_per_system), len(spools) - 1)
    positions = set(rng.sample(range(len(spools) - 1), valve_count))
    valve_number = 0
    for index in range(len(spools) - 1):
        left, right = spools[index], spools[index + 1]
        if index not in positions:
            structure.connections.append(Connection(a=left.part_id, b=right.part_id, kind=ConnectionKind.PIPE_JOINT))
            continue
        valve_number += 1
        valve = _valve(piping, block, valve_number)
        structure.parts.append(valve)
        structure.connections.append(Connection(a=left.part_id, b=valve.part_id, kind=ConnectionKind.PIPE_JOINT))
        structure.connections.append(Connection(a=valve.part_id, b=right.part_id, kind=ConnectionKind.PIPE_JOINT))


def _valve(piping: _Piping, block: BlockConfig, number: int) -> Part:
    """밸브 하나(종류는 무작위, 지름·압력 등급은 계통 것)."""
    system = piping.system
    valve_type = VALVE_TYPES[piping.rng.randrange(len(VALVE_TYPES))]
    valve_class = piping.pressure_class
    valve_spec = f"VL-{valve_type.upper()}-DN{piping.diameter}-{valve_class}"
    if valve_spec not in piping.structure.specs:
        piping.structure.specs[valve_spec] = MaterialSpec(
            spec_id=valve_spec,
            category="valve",
            description=f"{VALVE_LABELS[valve_type]} 밸브 DN{piping.diameter} {valve_class}",
            unit="ea",
            nominal_diameter_dn=piping.diameter,
            pressure_class=valve_class,
            unit_price_krw=spec_price(piping.seed, valve_spec, piping.cfg.prices.valve_each),
        )
    return Part(
        part_id=ids.part_id(piping.cfg.ship.ship_id, block.code, f"VL{system.code}", number),
        kind=PartKind.VALVE,
        name=f"{system.label} {VALVE_LABELS[valve_type]} 밸브 {number}",
        spec_id=valve_spec,
        qty=1.0,
        pid_class=f"{valve_type}_valve",
        **piping.common,
    )


def _supports(piping: _Piping, block: BlockConfig, spools: list[Part]) -> None:
    """서포트마다 스풀 하나를 골라 받친다."""
    structure, system, rng = piping.structure, piping.system, piping.rng
    support_spec = f"PS-DN{piping.diameter}"
    if support_spec not in structure.specs:
        structure.specs[support_spec] = MaterialSpec(
            spec_id=support_spec,
            category="fitting",
            description=f"배관 서포트 DN{piping.diameter}",
            unit="ea",
            nominal_diameter_dn=piping.diameter,
            unit_price_krw=spec_price(piping.seed, support_spec, piping.cfg.prices.support_each),
        )
    hull = ids.drawing_id(ids.hull_drawing(block.code))  # v3: 서포트는 선체에 붙어 선체도에도 그려진다
    for number in range(1, integer(rng, piping.cfg.piping.supports_per_system) + 1):
        support = Part(
            part_id=ids.part_id(piping.cfg.ship.ship_id, block.code, f"PS{system.code}", number),
            kind=PartKind.PIPE_SUPPORT,
            name=f"{system.label} 서포트 {number}",
            spec_id=support_spec,
            qty=1.0,
            pid_class="pipe_support",
            secondary_drawing_ids=(hull,),
            **piping.common,
        )
        structure.parts.append(support)
        held = spools[rng.randrange(len(spools))]
        structure.connections.append(Connection(a=support.part_id, b=held.part_id, kind=ConnectionKind.SUPPORT))


def _cross_block(piping: _Piping, spools: list[Part], other: BlockConfig) -> None:
    """v3: 계통 사슬 끝 스풀에서 이웃 블록으로 이어지는 스풀(블록 경계 배관 연결). 번호는 101부터(CROSS_START)라 주 블록
    스풀 이름·번호, 문장 사례의 지도에 없는 번호(가장 큰 번호 바로 위)와 겹치지 않는다. 도면은 계통 배관도, 다른 분야
    도면은 그 블록의 선체도."""
    cfg, system = piping.cfg, piping.system
    rng = sub_rng(piping.seed, "piping", system.code, "cross", other.code)
    ship = cfg.ship.ship_id
    hull = ids.drawing_id(ids.hull_drawing(other.code))
    common = {**piping.common, "block_id": ids.block_id(ship, other.code)}
    start = CROSS_START
    crossing = [
        Part(
            part_id=ids.part_id(ship, other.code, f"SP{system.code}", number),
            kind=PartKind.PIPE_SPOOL,
            name=f"{system.label} 스풀 {number}",
            spec_id=spools[-1].spec_id,
            qty=round(rng.uniform(2.0, 6.0), 1),
            pid_class="pipe",
            secondary_drawing_ids=(hull,),
            **common,
        )
        for number in range(start, start + integer(rng, cfg.piping.cross_block_spools))
    ]
    piping.structure.parts.extend(crossing)
    piping.structure.cross_spools_by_system[system.code] = crossing
    chain = [spools[-1], *crossing]
    for left, right in pairwise(chain):
        piping.structure.connections.append(Connection(a=left.part_id, b=right.part_id, kind=ConnectionKind.PIPE_JOINT))


def _equipment(piping: _Piping, block: BlockConfig, first: Part) -> None:
    """v3: 계통 장비(펌프) 하나 — 계통 첫 스풀과 배관 연결. 도면은 블록 기계 배치도, 다른 분야 도면은 계통 배관도."""
    cfg, system, structure = piping.cfg, piping.system, piping.structure
    spec_id = f"EQ-PUMP-{system.code}-DN{piping.diameter}"
    structure.specs[spec_id] = MaterialSpec(
        spec_id=spec_id,
        category="equipment",
        description=f"{system.equipment} DN{piping.diameter} {piping.pressure_class}",
        unit="ea",
        nominal_diameter_dn=piping.diameter,
        pressure_class=piping.pressure_class,
        unit_price_krw=spec_price(piping.seed, spec_id, cfg.prices.equipment_each),
    )
    drawing_no = ids.machinery_drawing(block.code)
    structure.drawings[drawing_no] = Drawing(
        drawing_no=drawing_no, revision="A", discipline="machinery", title=f"{block.name} 기계 배치도"
    )
    pump = Part(
        part_id=ids.part_id(cfg.ship.ship_id, block.code, f"EQ{system.code}", 1),
        ship_id=cfg.ship.ship_id,
        block_id=ids.block_id(cfg.ship.ship_id, block.code),
        kind=PartKind.EQUIPMENT,
        name=f"{system.equipment} 1",
        spec_id=spec_id,
        qty=1.0,
        drawing_no=drawing_no,
        revision="A",
        system=system.name,
        pid_class="pump",
        secondary_drawing_ids=(ids.drawing_id(str(piping.common["drawing_no"])),),
    )
    structure.parts.append(pump)
    structure.connections.append(Connection(a=pump.part_id, b=first.part_id, kind=ConnectionKind.PIPE_JOINT))
