"""부재 묶음(Structure)과 규격: 치수 상수, 판 규격, 규격 단가."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ripple.contracts.domain import Connection, Drawing, MaterialSpec, Part

from ..config import GeneratorConfig, Span
from ..rng import sub_rng, uniform

STEEL_DENSITY_T_PER_M3 = 7.85
THICKNESS_LIMITS_MM = (10.0, 20.0)
STIFFENER_HEIGHTS_MM = (200, 240, 280, 320)
STIFFENER_WEBS_MM = (10, 11, 12)
PIPE_DIAMETERS_DN = (100, 150, 200)
VALVE_TYPES = ("gate", "ball", "butterfly", "check", "globe")
# 밸브 종류의 현장 이름(이름·규격 설명에 쓴다). 종류 키는 pid_class·규격 ID에 그대로 남는다
VALVE_LABELS = {"gate": "게이트", "ball": "볼", "butterfly": "버터플라이", "check": "체크", "globe": "글로브"}
VALVE_CLASSES = ("10K", "16K")


@dataclass
class Structure:
    specs: dict[str, MaterialSpec] = field(default_factory=dict)
    parts: list[Part] = field(default_factory=list)
    connections: list[Connection] = field(default_factory=list)
    drawings: dict[str, Drawing] = field(default_factory=dict)
    plates_by_block: dict[str, list[Part]] = field(default_factory=dict)
    spools_by_system: dict[str, list[Part]] = field(default_factory=dict)  # 계통 주 블록의 스풀 사슬
    cross_spools_by_system: dict[str, list[Part]] = field(default_factory=dict)  # v3 이웃 블록으로 이어진 스풀

    def replace_part(self, part: Part) -> None:
        """같은 ID의 부재를 바꿔 넣는다(v3: 관통 판·서포트에 다른 분야 도면을 붙일 때)."""
        index = next(i for i, p in enumerate(self.parts) if p.part_id == part.part_id)
        self.parts[index] = part
        for group in (*self.plates_by_block.values(), *self.spools_by_system.values()):
            for i, p in enumerate(group):
                if p.part_id == part.part_id:
                    group[i] = part


def plate_spec_id(grade: str, thickness_mm: float) -> str:
    return f"PL-{grade}-{thickness_mm:.1f}"


def ensure_plate_spec(cfg: GeneratorConfig, seed: int, structure: Structure, grade: str, thickness_mm: float) -> str:
    spec_id = plate_spec_id(grade, thickness_mm)
    if spec_id not in structure.specs:
        structure.specs[spec_id] = MaterialSpec(
            spec_id=spec_id,
            category="plate",
            description=f"{grade} {thickness_mm:.1f}mm 후판",
            grade=grade,
            thickness_mm=thickness_mm,
            unit="t",
            unit_price_krw=spec_price(seed, spec_id, cfg.prices.plate_per_t),
        )
    return spec_id


def spec_price(seed: int, spec_id: str, span: Span) -> int:
    """규격 단가: 규격마다 시드로 범위 안 값 하나를 뽑아 천 원 단위로 내림."""
    rng: random.Random = sub_rng(seed, "price", spec_id)
    return int(math.floor(uniform(rng, span) / 1000) * 1000)
