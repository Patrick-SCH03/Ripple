"""v4 외자재 규격(현업 의견 '외자재는 운반 시간 추가 — 항공 1~2주, 선박 1달', docs/data.md(생성기) 11절).

설정 `imports.specs`의 (배관 계통, 부재 종류)마다 그 계통 주 블록 부재가 쓰는 규격을 외자재로 바꾼다: 원산지 외자재 ·
운송 방식 하나 · 생산 표준 리드타임(운송 제외, 설정 `imports.std_lead_days`). 규격만 바꾸고 부재·발주·난수열은 그대로다
(발주의 리드타임은 이미 운송을 포함한 값이라 손대지 않는다).
"""

from __future__ import annotations

from ripple.contracts.domain import MaterialSpec, PartKind

from . import ids
from .config import GeneratorConfig
from .structure import Structure

KINDS = {"valve": PartKind.VALVE, "equipment": PartKind.EQUIPMENT}
"""설정의 부재 종류 이름 → 부재 종류."""


def apply_imports(cfg: GeneratorConfig, structure: Structure) -> None:
    """설정의 외자재 규격을 structure.specs에 반영한다(없으면 그대로)."""
    if cfg.imports is None:
        return
    systems = {s.code: s for s in cfg.piping.systems}
    for item in cfg.imports.specs:
        system = systems[item.system]
        home = ids.block_id(cfg.ship.ship_id, system.block)
        spec_ids = sorted(
            {
                p.spec_id
                for p in structure.parts
                if p.kind is KINDS[item.kind] and p.system == system.name and p.block_id == home
            }
        )
        for spec_id in spec_ids:
            structure.specs[spec_id] = MaterialSpec.model_validate(
                {
                    **structure.specs[spec_id].model_dump(),
                    "origin": "import",
                    "transport": item.transport,
                    "std_lead_time_days": cfg.imports.std_lead_days[item.kind],
                }
            )
