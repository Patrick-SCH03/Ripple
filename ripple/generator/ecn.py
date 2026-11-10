"""설계변경 이력(구조화된 변경 연산). 연산 분포대로 연산을 뽑고 연산에 맞는 대상·의도를 고른다."""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import timedelta

from ripple.contracts.change import (
    AddPart,
    AddPenetration,
    ChangeIntent,
    ChangeOp,
    ChangeRequest,
    DimensionChange,
    EquipmentSpecChange,
    GradeChange,
    RemovePart,
    ReroutePipe,
    ThicknessChange,
)
from ripple.contracts.dataset import EcnSplit, GeneratedEcn
from ripple.contracts.domain import GraphSnapshot, Part, PartKind

from .config import GeneratorConfig
from .rng import integer, sub_rng, weighted

INTENTS: dict[str, dict[str, float]] = {
    "thickness": {ChangeIntent.STRENGTH: 0.7, ChangeIntent.RULE_CHANGE: 0.3},
    "grade": {ChangeIntent.RULE_CHANGE: 0.6, ChangeIntent.STRENGTH: 0.4},
    "dimension": {ChangeIntent.INTERFERENCE: 0.6, ChangeIntent.WEIGHT: 0.4},
    "add_part": {ChangeIntent.STRENGTH: 1.0},
    "remove_part": {ChangeIntent.WEIGHT: 1.0},
    "reroute_pipe": {ChangeIntent.INTERFERENCE: 1.0},
    "equipment_spec": {ChangeIntent.EQUIPMENT: 0.6, ChangeIntent.OWNER_REQUEST: 0.4},
    "add_penetration": {ChangeIntent.INTERFERENCE: 0.5, ChangeIntent.EQUIPMENT: 0.5},
}
THICKNESS_DELTAS_MM = (1.0, 1.5, 2.0, 3.0, 4.0, -1.0)
GRADES = ("A", "AH32", "AH36", "DH36", "EH36")


class Catalog:
    """지도에서 연산 대상을 고르기 쉽게 모은 색인. 계통 이름은 지도의 이름표(설계변경 제목에 쓴다).

    배관 부재는 계통의 주 블록(설정 piping.systems[].block) 것만 대상 후보다(v3): 생성기 v3가 더한 이웃 블록 스풀은
    후보에 넣지 않아 v2 설계변경 이력·문장 사례(번호·연산·대상)와 시연 고정점이 그대로다.
    칼라·장비는 원래 후보가 아니다.
    """

    def __init__(self, snapshot: GraphSnapshot, home_blocks: Mapping[str, str] | None = None) -> None:
        self.system_names = {s.system: s.name for s in snapshot.pipe_systems}
        self.hull: dict[str, list[Part]] = defaultdict(list)
        self.by_kind: dict[PartKind, list[Part]] = defaultdict(list)
        self.spools: dict[str, list[Part]] = defaultdict(list)
        home = home_blocks or {}
        for part in snapshot.parts:
            if part.system is not None and part.system in home and part.block_id != home[part.system]:
                continue
            self.by_kind[part.kind].append(part)
            if part.kind is PartKind.PLATE:
                self.hull[part.block_id].append(part)
            if part.kind is PartKind.PIPE_SPOOL and part.system:
                self.spools[part.system].append(part)
        self.valve_specs = sorted(s.spec_id for s in snapshot.specs if s.category == "valve")
        self.section_specs = {s.spec_id: s.grade for s in snapshot.specs if s.category == "section"}
        self.blocks = sorted(self.hull)

    def system_name(self, system: str) -> str:
        """계통의 현장 이름. 지도에 이름표가 없으면 키 그대로(지도 계약과 같은 규칙)."""
        return self.system_names.get(system, system)


Builder = Callable[[random.Random, Catalog], tuple[ChangeOp, str]]


def home_blocks(cfg: GeneratorConfig) -> dict[str, str]:
    """계통 키 → 주 블록 ID(설계변경·문장 사례의 배관 대상 블록)."""
    return {s.name: f"{cfg.ship.ship_id}:{s.block}" for s in cfg.piping.systems}


def make_ecns(
    cfg: GeneratorConfig, snapshot: GraphSnapshot, split: EcnSplit, count: int, seed: int
) -> list[GeneratedEcn]:
    rng = sub_rng(seed, "ecn", split.value)
    catalog = Catalog(snapshot, home_blocks(cfg))
    prefix = "D" if split is EcnSplit.DEV else "E"
    ecns = []
    for number in range(1, count + 1):
        op_name = weighted(rng, cfg.ecn.op_mix)
        op, title = BUILDERS[op_name](rng, catalog)
        intent = ChangeIntent(weighted(rng, INTENTS[op_name]))
        change = ChangeRequest(
            ecn_id=f"ECN-{prefix}-{number:04d}",
            title=title,
            ship_ids=(cfg.ship.ship_id,),
            intent=intent,
            ops=(op,),
            requested_on=cfg.scenario_date + timedelta(days=integer(rng, cfg.ecn.request_window_days)),
        )
        ecns.append(GeneratedEcn(split=split, as_of=cfg.scenario_date, change=change))
    return ecns


def _code(part: Part) -> str:
    return part.block_id.split(":")[-1]


def _thickness(rng: random.Random, catalog: Catalog) -> tuple[ChangeOp, str]:
    block = catalog.blocks[rng.randrange(len(catalog.blocks))]
    plates = catalog.hull[block]
    anchor = plates[rng.randrange(len(plates))]
    same = sorted(
        (p for p in plates if p.thickness_mm == anchor.thickness_mm and p.grade == anchor.grade),
        key=lambda p: p.part_id,
    )
    chosen = rng.sample(same, min(len(same), rng.randint(1, 3)))
    before = anchor.thickness_mm or 12.0
    after = before + THICKNESS_DELTAS_MM[rng.randrange(len(THICKNESS_DELTAS_MM))]
    op = ThicknessChange(part_ids=tuple(sorted(p.part_id for p in chosen)), from_mm=before, to_mm=after)
    return op, f"{_code(anchor)} 판 두께 {before:.1f}→{after:.1f}mm ({len(chosen)}장)"


def _grade(rng: random.Random, catalog: Catalog) -> tuple[ChangeOp, str]:
    candidates = catalog.by_kind[PartKind.PLATE] + catalog.by_kind[PartKind.STIFFENER]
    anchor = candidates[rng.randrange(len(candidates))]
    same = sorted(
        (p for p in candidates if p.block_id == anchor.block_id and p.kind is anchor.kind and p.grade == anchor.grade),
        key=lambda p: p.part_id,
    )
    chosen = rng.sample(same, min(len(same), rng.randint(1, 3)))
    before = anchor.grade or "AH36"
    after = rng.choice([g for g in GRADES if g != before])
    op = GradeChange(part_ids=tuple(sorted(p.part_id for p in chosen)), from_grade=before, to_grade=after)
    return op, f"{_code(anchor)} {before}→{after} 강종 변경 ({len(chosen)}개)"


def _dimension(rng: random.Random, catalog: Catalog) -> tuple[ChangeOp, str]:
    candidates = (
        catalog.by_kind[PartKind.PLATE] + catalog.by_kind[PartKind.STIFFENER] + catalog.by_kind[PartKind.PIPE_SPOOL]
    )
    part = candidates[rng.randrange(len(candidates))]
    before = float(rng.randrange(1000, 6001, 100))
    after = round(before * (1 + rng.choice((-1, 1)) * rng.uniform(0.1, 0.2)), -1)
    op = DimensionChange(part_ids=(part.part_id,), field="length_mm", from_value=before, to_value=after)
    return op, f"{_code(part)} {part.name} 길이 {before:.0f}→{after:.0f}mm"


def _add_part(rng: random.Random, catalog: Catalog) -> tuple[ChangeOp, str]:
    block = catalog.blocks[rng.randrange(len(catalog.blocks))]
    plates = catalog.hull[block]
    plate = plates[rng.randrange(len(plates))]
    specs = sorted(s for s, grade in catalog.section_specs.items() if grade == plate.grade) or sorted(
        catalog.section_specs
    )
    op = AddPart(
        block_id=block,
        kind=PartKind.STIFFENER,
        spec_id=specs[rng.randrange(len(specs))],
        qty=round(rng.uniform(0.1, 0.3), 3),
        attach_to_part_id=plate.part_id,
    )
    return op, f"{_code(plate)} {plate.name}에 보강재 추가"


def _remove_part(rng: random.Random, catalog: Catalog) -> tuple[ChangeOp, str]:
    candidates = catalog.by_kind[PartKind.BRACKET] + catalog.by_kind[PartKind.STIFFENER]
    anchor = candidates[rng.randrange(len(candidates))]
    same = sorted(
        (p for p in candidates if p.block_id == anchor.block_id and p.kind is anchor.kind), key=lambda p: p.part_id
    )
    chosen = rng.sample(same, min(len(same), rng.randint(1, 2)))
    op = RemovePart(part_ids=tuple(sorted(p.part_id for p in chosen)))
    return op, f"{_code(anchor)} {anchor.name} 등 {len(chosen)}개 삭제"


def _reroute(rng: random.Random, catalog: Catalog) -> tuple[ChangeOp, str]:
    system = sorted(catalog.spools)[rng.randrange(len(catalog.spools))]
    spools = sorted(catalog.spools[system], key=lambda p: p.part_id)
    start = rng.randrange(len(spools) - 1)
    removed = spools[start : start + rng.randint(1, 2)]
    added = tuple(removed[0].spec_id for _ in range(len(removed) + rng.randint(0, 1)))
    crosses: tuple[str, ...] = ()
    plates = catalog.by_kind[PartKind.PLATE]
    if rng.random() < 0.4:
        crosses = (plates[rng.randrange(len(plates))].part_id,)
    op = ReroutePipe(
        removed_part_ids=tuple(p.part_id for p in removed), added_spool_spec_ids=added, crosses_part_ids=crosses
    )
    # 개수가 같으면 '2개 → 2개'처럼 바뀐 게 없어 보이므로 새 경로로 바꾼다고 적는다
    same = len(removed) == len(added)
    count = f"스풀 {len(removed)}개 새 경로로" if same else f"스풀 {len(removed)}개 → {len(added)}개"
    through = ", 판 관통" if crosses else ""
    return op, f"{catalog.system_name(system)} 배관 경로 변경({count}{through})"


def _equipment(rng: random.Random, catalog: Catalog) -> tuple[ChangeOp, str]:
    valves = catalog.by_kind[PartKind.VALVE]
    valve = valves[rng.randrange(len(valves))]
    others = [s for s in catalog.valve_specs if s != valve.spec_id] or [f"{valve.spec_id}-R1"]
    target = others[rng.randrange(len(others))]
    op = EquipmentSpecChange(part_ids=(valve.part_id,), from_spec_id=valve.spec_id, to_spec_id=target)
    return op, f"{valve.name} 사양 변경 {valve.spec_id}→{target}"


def _penetration(rng: random.Random, catalog: Catalog) -> tuple[ChangeOp, str]:
    system = sorted(catalog.spools)[rng.randrange(len(catalog.spools))]
    spools = catalog.spools[system]
    spool = spools[rng.randrange(len(spools))]
    plates = catalog.by_kind[PartKind.PLATE]
    plate = plates[rng.randrange(len(plates))]
    diameter = int(spool.spec_id.split("DN")[1].split("-")[0]) + 50
    op = AddPenetration(plate_part_id=plate.part_id, pipe_part_id=spool.part_id, diameter_mm=float(diameter))
    return op, f"{_code(plate)} {plate.name}에 관통부 추가(지름 {diameter}mm)"


BUILDERS: dict[str, Builder] = {
    "thickness": _thickness,
    "grade": _grade,
    "dimension": _dimension,
    "add_part": _add_part,
    "remove_part": _remove_part,
    "reroute_pipe": _reroute,
    "equipment_spec": _equipment,
    "add_penetration": _penetration,
}
