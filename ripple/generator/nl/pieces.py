"""문장 조각과 작은 도우미: 조각은 표면형과 (있으면) 정답 칸·값·지도 존재 여부를 함께 든다."""

from __future__ import annotations

import random
from dataclasses import dataclass

ABBREVIATIONS = frozenset(
    {"PL", "STF", "BKT", "V/V", "T.BHD", "L.BHD", "D/B", "DK", "P/R", "E/R", "C/S", "B/W", "GV", "BV", "BFV", "NRV"}
)


@dataclass(frozen=True)
class Piece:
    text: str
    slot: str | None = None
    value: str | float = ""
    exists: bool = True


def number(value: float) -> str:
    return f"{value:g}"


def pick(rng: random.Random, variants: tuple[str, ...]) -> str:
    return variants[rng.randrange(len(variants))]
