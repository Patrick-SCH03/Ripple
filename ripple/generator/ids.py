"""생성기가 만드는 ID의 형식을 한곳에 모은다."""

from __future__ import annotations

from ripple.contracts.domain import ActivityKind


def zone_id(ship_id: str, code: str) -> str:
    return f"{ship_id}:{code}"


def block_id(ship_id: str, code: str) -> str:
    return f"{ship_id}:{code}"


def activity_id(ship_id: str, block_code: str, kind: ActivityKind) -> str:
    return f"{ship_id}:{block_code}:{kind.value}"


def zone_exit_id(ship_id: str, zone_code: str) -> str:
    return f"{ship_id}:{zone_code}:exit"


def launch_id(ship_id: str) -> str:
    return f"{ship_id}:launch"


def sea_trial_id(ship_id: str) -> str:
    return f"{ship_id}:sea_trial"


def delivery_id(ship_id: str) -> str:
    return f"{ship_id}:delivery"


def drawing_id(drawing_no: str, revision: str = "A") -> str:
    """도면 ID(도면번호@개정) — 다른 분야 도면(Part.secondary_drawing_ids)에 쓴다."""
    return f"{drawing_no}@{revision}"


def machinery_drawing(block_code: str) -> str:
    return f"DWG-{block_code}-M01"


def part_id(ship_id: str, block_code: str, prefix: str, number: int) -> str:
    return f"{ship_id}:{block_code}-{prefix}-{number:03d}"


def hull_drawing(block_code: str) -> str:
    return f"DWG-{block_code}-H01"


def piping_drawing(block_code: str, system_code: str) -> str:
    return f"DWG-{block_code}-{system_code}-P01"
