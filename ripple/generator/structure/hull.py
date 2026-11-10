"""선체 블록: 판을 격자로 놓고 이웃 판끼리 맞대기 용접, 보강재·브라켓은 판에 필릿 용접한다."""

from __future__ import annotations

import random
from dataclasses import dataclass

from ripple.contracts.domain import Connection, ConnectionKind, Drawing, MaterialSpec, Part, PartKind

from .. import ids
from ..config import BlockConfig, GeneratorConfig, Span
from ..rng import integer, step, sub_rng, uniform, weighted
from .base import (
    STEEL_DENSITY_T_PER_M3,
    STIFFENER_HEIGHTS_MM,
    STIFFENER_WEBS_MM,
    THICKNESS_LIMITS_MM,
    Structure,
    ensure_plate_spec,
    spec_price,
)


@dataclass(frozen=True, slots=True)
class _Hull:
    """선체 블록 하나를 만드는 동안 같이 쓰는 값. 난수원은 블록마다 하나이고 부재를 만드는 순서대로 뽑는다."""

    cfg: GeneratorConfig
    seed: int
    structure: Structure
    block: BlockConfig
    rng: random.Random
    drawing_no: str
    grade: str

    @property
    def ship(self) -> str:
        return self.cfg.ship.ship_id

    @property
    def block_id(self) -> str:
        return ids.block_id(self.ship, self.block.code)


def hull_block(cfg: GeneratorConfig, seed: int, block: BlockConfig, structure: Structure) -> None:
    """블록 하나의 판(격자)·판 이음·보강재·브라켓. 블록 강종·기준 두께·판 수·격자 열 수를 먼저 뽑는다."""
    rng = sub_rng(seed, "parts", block.code)
    drawing_no = ids.hull_drawing(block.code)
    structure.drawings[drawing_no] = Drawing(
        drawing_no=drawing_no, revision="A", discipline="hull", title=f"{block.name} 구조도"
    )
    hull = _Hull(cfg, seed, structure, block, rng, drawing_no, weighted(rng, cfg.parts.grades))
    base_thickness = step(rng, cfg.parts.base_thickness_mm, 0.5)
    count = integer(rng, cfg.parts.plates_per_block)
    columns = integer(rng, cfg.parts.plate_grid_cols)

    plates = [_plate(hull, number, base_thickness) for number in range(1, count + 1)]
    structure.parts.extend(plates)
    structure.plates_by_block[block.code] = plates
    _plate_welds(hull, plates, columns)

    stiffeners = [
        _stiffener(hull, number, plates) for number in range(1, integer(rng, cfg.parts.stiffeners_per_block) + 1)
    ]
    structure.parts.extend(stiffeners)
    for number in range(1, integer(rng, cfg.parts.brackets_per_block) + 1):
        _bracket(hull, number, stiffeners)


def _plate(hull: _Hull, number: int, base_thickness: float) -> Part:
    """판 하나: 두께는 블록 기준 두께 ±1mm(0.5mm 단위, 한계 안), 무게는 면적 × 두께 × 강재 밀도."""
    cfg, rng = hull.cfg, hull.rng
    low, high = THICKNESS_LIMITS_MM
    thickness = min(max(base_thickness + step(rng, Span(lo=-1.0, hi=1.0), 0.5), low), high)
    area = uniform(rng, cfg.parts.plate_area_m2)
    weight_t = area * thickness / 1000 * STEEL_DENSITY_T_PER_M3
    return Part(
        part_id=ids.part_id(hull.ship, hull.block.code, "PL", number),
        ship_id=hull.ship,
        block_id=hull.block_id,
        kind=PartKind.PLATE,
        name=f"{hull.block.name} 판 {number}",
        spec_id=ensure_plate_spec(cfg, hull.seed, hull.structure, hull.grade, thickness),
        qty=round(weight_t, 3),
        drawing_no=hull.drawing_no,
        revision="A",
        thickness_mm=thickness,
        grade=hull.grade,
        stiffener_spacing_m=round(uniform(rng, cfg.parts.stiffener_spacing_m), 2),
        span_m=round(uniform(rng, cfg.parts.span_m), 2),
        head_m=round(uniform(rng, cfg.parts.head_m), 1),
        weight_kg=round(weight_t * 1000, 1),
    )


def _plate_welds(hull: _Hull, plates: list[Part], columns: int) -> None:
    """격자로 놓은 판마다 오른쪽·아래 이웃과 맞대기 용접."""
    for index, plate in enumerate(plates):
        column = index % columns
        right = index + 1 if column + 1 < columns and index + 1 < len(plates) else None
        below = index + columns if index + columns < len(plates) else None
        for neighbour in (right, below):
            if neighbour is not None:
                hull.structure.connections.append(
                    Connection(
                        a=plate.part_id,
                        b=plates[neighbour].part_id,
                        kind=ConnectionKind.BUTT_WELD,
                        length_m=round(hull.rng.uniform(2.0, 6.0), 1),
                    )
                )


def _stiffener(hull: _Hull, number: int, plates: list[Part]) -> Part:
    """보강재 하나(구평형강): 판 하나를 골라 필릿 용접하고 그 판의 간격·수두를 이어받는다."""
    rng = hull.rng
    plate = plates[rng.randrange(len(plates))]
    height = STIFFENER_HEIGHTS_MM[rng.randrange(len(STIFFENER_HEIGHTS_MM))]
    web = STIFFENER_WEBS_MM[rng.randrange(len(STIFFENER_WEBS_MM))]
    spec_id = _section_spec(hull, height, web)
    span = round(uniform(rng, hull.cfg.parts.span_m), 2)
    weight_t = round(height / 1000 * web / 1000 * 1.6 * span * STEEL_DENSITY_T_PER_M3, 3)
    stiffener = Part(
        part_id=ids.part_id(hull.ship, hull.block.code, "ST", number),
        ship_id=hull.ship,
        block_id=hull.block_id,
        kind=PartKind.STIFFENER,
        name=f"{hull.block.name} 보강재 {number}",
        spec_id=spec_id,
        qty=weight_t,
        drawing_no=hull.drawing_no,
        revision="A",
        thickness_mm=float(web),
        grade=hull.grade,
        stiffener_spacing_m=plate.stiffener_spacing_m,
        span_m=span,
        head_m=plate.head_m,
        weight_kg=round(weight_t * 1000, 1),
    )
    hull.structure.connections.append(
        Connection(a=stiffener.part_id, b=plate.part_id, kind=ConnectionKind.FILLET_WELD, length_m=span)
    )
    return stiffener


def _section_spec(hull: _Hull, height: int, web: int) -> str:
    spec_id = f"HP{height}x{web}-{hull.grade}"
    if spec_id not in hull.structure.specs:
        hull.structure.specs[spec_id] = MaterialSpec(
            spec_id=spec_id,
            category="section",
            description=f"{hull.grade} 구평형강 HP{height}×{web}",
            grade=hull.grade,
            thickness_mm=float(web),
            unit="t",
            unit_price_krw=spec_price(hull.seed, spec_id, hull.cfg.prices.section_per_t),
        )
    return spec_id


def _bracket(hull: _Hull, number: int, stiffeners: list[Part]) -> None:
    """브라켓 하나: 보강재 하나를 골라 그 보강재·보강재가 붙은 판과 필릿 용접한다(두께는 보강재 웨브)."""
    structure = hull.structure
    stiffener = stiffeners[hull.rng.randrange(len(stiffeners))]
    plate_id = next(c.b for c in structure.connections if c.a == stiffener.part_id)
    thickness = stiffener.thickness_mm or 10.0
    spec_id = _bracket_spec(hull, thickness)
    weight_t = round(hull.rng.uniform(0.02, 0.08), 3)
    bracket = Part(
        part_id=ids.part_id(hull.ship, hull.block.code, "BR", number),
        ship_id=hull.ship,
        block_id=hull.block_id,
        kind=PartKind.BRACKET,
        name=f"{hull.block.name} 브라켓 {number}",
        spec_id=spec_id,
        qty=weight_t,
        drawing_no=hull.drawing_no,
        revision="A",
        thickness_mm=thickness,
        grade=hull.grade,
        weight_kg=round(weight_t * 1000, 1),
    )
    structure.parts.append(bracket)
    structure.connections.append(Connection(a=bracket.part_id, b=plate_id, kind=ConnectionKind.FILLET_WELD))
    structure.connections.append(Connection(a=bracket.part_id, b=stiffener.part_id, kind=ConnectionKind.FILLET_WELD))


def _bracket_spec(hull: _Hull, thickness: float) -> str:
    spec_id = f"BR-{hull.grade}-{thickness:.1f}"
    if spec_id not in hull.structure.specs:
        hull.structure.specs[spec_id] = MaterialSpec(
            spec_id=spec_id,
            category="plate",
            description=f"{hull.grade} {thickness:.1f}mm 브라켓",
            grade=hull.grade,
            thickness_mm=thickness,
            unit="t",
            unit_price_krw=spec_price(hull.seed, spec_id, hull.cfg.prices.plate_per_t),
        )
    return spec_id
