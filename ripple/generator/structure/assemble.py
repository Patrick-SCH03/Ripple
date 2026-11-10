"""전체 조립: 블록마다 선체·배관 계통을 만들고, 블록 이음의 가장자리 판 맞대기 용접과 관통 계통의 판 관통을 더한다.

v3: 관통마다 칼라 부재(판에 필릿 용접, 배관과 관통)를 두고, 관통 판·칼라에 계통 배관도를 다른 분야 도면으로 붙인다.
"""

from __future__ import annotations

from ripple.contracts.domain import Connection, ConnectionKind, MaterialSpec, Part, PartKind

from .. import ids
from ..config import GeneratorConfig, PipeSystemConfig
from ..rng import integer, sub_rng
from .base import Structure, spec_price
from .hull import hull_block
from .piping import pipe_system


def build_structure(cfg: GeneratorConfig, seed: int) -> Structure:
    structure = Structure()
    systems_by_block: dict[str, list[PipeSystemConfig]] = {}
    for system in cfg.piping.systems:
        systems_by_block.setdefault(system.block, []).append(system)
    for block in cfg.blocks:
        hull_block(cfg, seed, block, structure)
        for system in systems_by_block.get(block.code, []):
            pipe_system(cfg, seed, block, system, structure)
    _block_joints(cfg, seed, structure)
    _penetrations(cfg, seed, structure)
    return structure


def _block_joints(cfg: GeneratorConfig, seed: int, structure: Structure) -> None:
    for left_code, right_code in cfg.adjacency:
        rng = sub_rng(seed, "joint", left_code, right_code)
        left, right = structure.plates_by_block[left_code], structure.plates_by_block[right_code]
        pairs = min(integer(rng, cfg.parts.joint_plates), len(left), len(right))
        for a, b in zip(rng.sample(left, pairs), rng.sample(right, pairs), strict=True):
            structure.connections.append(
                Connection(
                    a=a.part_id, b=b.part_id, kind=ConnectionKind.BUTT_WELD, length_m=round(rng.uniform(3, 8), 1)
                )
            )


def _penetrations(cfg: GeneratorConfig, seed: int, structure: Structure) -> None:
    config = cfg.piping.penetrations
    rng = sub_rng(seed, "penetration", config.system, config.through_block)
    spools = structure.spools_by_system[config.system]
    plates = structure.plates_by_block[config.through_block]
    count = min(integer(rng, config.count), len(spools), len(plates))
    pairs = list(zip(rng.sample(spools, count), rng.sample(plates, count), strict=True))
    for spool, plate in pairs:
        structure.connections.append(Connection(a=plate.part_id, b=spool.part_id, kind=ConnectionKind.PENETRATION))
    _collars(cfg, seed, structure, pairs)


def _collars(cfg: GeneratorConfig, seed: int, structure: Structure, pairs: list[tuple[Part, Part]]) -> None:
    """v3: 관통마다 칼라 하나(관통 판의 블록, 판에 필릿 용접·배관과 관통, 사외 단품). 관통 판과 칼라의 다른 분야
    도면 = 그 배관의 계통 배관도. 난수원은 따로('collar')."""
    ship = cfg.ship.ship_id
    rng = sub_rng(seed, "collar", cfg.piping.penetrations.system)
    for number, (spool, plate) in enumerate(pairs, start=1):
        piping = ids.drawing_id(spool.drawing_no, spool.revision)
        structure.replace_part(plate.model_copy(update={"secondary_drawing_ids": (piping,)}))
        diameter = structure.specs[spool.spec_id].nominal_diameter_dn
        spec_id = f"CL-DN{diameter}"
        if spec_id not in structure.specs:
            structure.specs[spec_id] = MaterialSpec(
                spec_id=spec_id,
                category="fitting",
                description=f"관통 칼라 DN{diameter}",
                unit="ea",
                nominal_diameter_dn=diameter,
                unit_price_krw=spec_price(seed, spec_id, cfg.prices.collar_each),
            )
        code = plate.block_id.split(":")[-1]
        block_name = next(b.name for b in cfg.blocks if b.code == code)
        collar = Part(
            part_id=ids.part_id(ship, code, "CL", number),
            ship_id=ship,
            block_id=plate.block_id,
            kind=PartKind.COLLAR,
            name=f"{block_name} 관통 칼라 {number}",
            spec_id=spec_id,
            qty=1.0,
            drawing_no=plate.drawing_no,
            revision=plate.revision,
            weight_kg=round(rng.uniform(10.0, 30.0), 1),
            secondary_drawing_ids=(piping,),
        )
        structure.parts.append(collar)
        structure.connections.append(Connection(a=collar.part_id, b=plate.part_id, kind=ConnectionKind.FILLET_WELD))
        structure.connections.append(Connection(a=collar.part_id, b=spool.part_id, kind=ConnectionKind.PENETRATION))
