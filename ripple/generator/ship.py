"""선박·구역·블록·사내 협력사 작업반."""

from __future__ import annotations

from datetime import timedelta

from ripple.contracts.domain import Block, Crew, Ship, Zone

from . import ids
from .config import BlockConfig, GeneratorConfig
from .rng import sub_rng, uniform


def make_ship(cfg: GeneratorConfig) -> Ship:
    return Ship(
        ship_id=cfg.ship.ship_id,
        ship_type=cfg.ship.ship_type,
        dwt=cfg.ship.dwt,
        contract_price_krw=cfg.ship.contract_price_krw,
        delivery_date=cfg.scenario_date + timedelta(days=cfg.ship.delivery_offset_days),
    )


def make_zones(cfg: GeneratorConfig) -> tuple[Zone, ...]:
    ship = cfg.ship.ship_id
    return tuple(Zone(zone_id=ids.zone_id(ship, z.code), ship_id=ship, name=z.name) for z in cfg.zones)


def make_blocks(cfg: GeneratorConfig, seed: int) -> tuple[Block, ...]:
    """블록과 v3 난이도 입력(형상은 설정, 의장품·전장품 수는 밀도 수준의 t당 개수 범위에서 블록마다 뽑음)."""
    ship = cfg.ship.ship_id
    return tuple(
        Block(
            block_id=ids.block_id(ship, b.code),
            ship_id=ship,
            zone_id=ids.zone_id(ship, b.zone),
            name=b.name,
            steel_weight_t=b.weight_t,
            shape=b.shape,
            **_items(cfg, seed, b),
        )
        for b in cfg.blocks
    )


def _items(cfg: GeneratorConfig, seed: int, block: BlockConfig) -> dict[str, int]:
    rng = sub_rng(seed, "density", block.code)
    span = getattr(cfg.density, block.density)
    return {
        "outfit_items": round(block.weight_t * uniform(rng, span.outfit)),
        "electric_items": round(block.weight_t * uniform(rng, span.electric)),
    }


def make_crews(cfg: GeneratorConfig) -> tuple[Crew, ...]:
    """사내 협력사 작업반(가상 이름·가상 '.example' 연락처)."""
    return tuple(
        Crew(crew_id=team.code, name=team.name, processes=team.processes, contact=team.contact)
        for team in cfg.crews.teams
    )
