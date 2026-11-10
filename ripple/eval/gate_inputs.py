"""1단계 사례 입력 30건: 관문 10건(G1-001~010) + E1 의미 정확도 경계 사례 20건(G1-011~030, docs/evaluation.md).
합성 지도에서 규칙·조건을 고루 건드리도록 대상을 결정적으로 고른다.

기대 결과는 여기서 만들지 않는다(엔진 코드를 보지 않는 계산자가 docs/engine.md(전파)로 계산).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from ripple.contracts.analysis import AnalysisRequest
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
from ripple.contracts.domain import GraphSnapshot, PartKind, POStatus, Relation
from ripple.contracts.evaluation import GateCaseInput, SnapshotRef

from .gate_boundary import (
    Boundary,
    material_reuse,
    merged_and_added_parts,
    penetrations,
    stage_flips,
    surplus_demand,
    thickness_thresholds,
    thinner_plate,
    unknown_and_processed,
    valve_same_connection,
)
from .gate_types import AddCase
from .picker import Picker

__all__ = ["gate_inputs"]


def gate_inputs(snapshot: GraphSnapshot, seed: int, as_of: date) -> list[GateCaseInput]:
    pick = Picker(snapshot, as_of)
    ref = SnapshotRef(generator_seed=seed, snapshot_id=snapshot.snapshot_id)
    ship = snapshot.ships[0].ship_id
    cases: list[GateCaseInput] = []

    def add(title: str, focus: str, intent: ChangeIntent, *ops: ChangeOp, confirm_on: date | None = None) -> None:
        number = len(cases) + 1
        change = ChangeRequest(ecn_id=f"GC-{number:03d}", title=title, ship_ids=(ship,), intent=intent, ops=ops)
        request = AnalysisRequest(change=change, as_of=as_of, confirm_on=confirm_on)
        cases.append(
            GateCaseInput(case_id=f"G1-{number:03d}", stage=1, title=title, snapshot=ref, request=request, focus=focus)
        )

    _joint_and_valve(pick, add)  # 1~3
    _equipment_and_reroute(pick, add)  # 4·5
    _part_changes(pick, add)  # 6~8
    _unknown_and_paired(pick, add)  # 9·10
    _boundary_cases(pick, add, lambda: len(cases))  # 11~30
    return cases


def _joint_and_valve(pick: Picker, add: AddCase) -> None:
    # 1. 조립 중 T31C, 블록 이음에 놓인 가장 얇은 AH36 판을 재고 규격 두께로
    joint, lot_thickness = pick.stock_joint()
    add(
        f"T31C 이음부 판 두께 {joint.thickness_mm:g}→{lot_thickness:g}mm(조립 중)",
        "조립 중 블록의 판, 블록 이음 너머 이웃, 가공 끝난 발주, 같은 규격 재고",
        ChangeIntent.STRENGTH,
        ThicknessChange(part_ids=(joint.part_id,), from_mm=joint.thickness_mm or 0, to_mm=lot_thickness),
    )

    # 2·3. 미착수 P11C 밸브, 연결 규격이 같은 다른 사양 — 기준일 확정 / 계획 발주일 뒤 확정
    valve, twin = pick.valve_twin()
    valve_op = EquipmentSpecChange(part_ids=(valve.part_id,), from_spec_id=valve.spec_id, to_spec_id=twin)
    planned = pick.planned_order(valve)
    add(
        f"P11C {valve.name} 사양 변경(기준일 확정)",
        "미착수 블록, 발주 전 품목, 연결 규격 같음",
        ChangeIntent.EQUIPMENT,
        valve_op,
    )
    later = (planned or pick.as_of) + timedelta(days=5)
    add(
        f"P11C {valve.name} 사양 변경({later.isoformat()} 확정)",
        "같은 변경을 계획 발주일 뒤에 확정(판정일 단계 추정)",
        ChangeIntent.EQUIPMENT,
        valve_op,
        confirm_on=later,
    )


def _equipment_and_reroute(pick: Picker, add: AddCase) -> None:
    # 4. 착수한 E21C 밸브, 연결 규격이 다른 사양
    e21c = pick.first(lambda p: p.kind is PartKind.VALVE and pick.code(p) == "E21C", "E21C 밸브")
    e21c_spec = pick.index.specs[e21c.spec_id]
    other = next(
        s.spec_id
        for s in sorted(pick.snapshot.specs, key=lambda s: s.spec_id)
        if s.category == "valve"
        and (s.nominal_diameter_dn, s.pressure_class) != (e21c_spec.nominal_diameter_dn, e21c_spec.pressure_class)
    )
    add(
        f"E21C {e21c.name} 사양 변경(연결 규격 다름)",
        "착수한 블록의 장비, 연결 규격이 다른 새 사양",
        ChangeIntent.EQUIPMENT,
        EquipmentSpecChange(part_ids=(e21c.part_id,), from_spec_id=e21c.spec_id, to_spec_id=other),
    )

    # 5. 서포트가 받치는 E21C 스풀을 스풀 2개로 교체, 새 경로가 착수한 다른 블록 판을 관통
    spool, crossed = pick.supported_spool(), pick.started_plate_elsewhere()
    add(
        "E21C 배관 경로 변경(스풀 1개 → 2개, 판 관통)",
        "빼는 스풀의 발주·서포트, 새 스풀, 새 관통",
        ChangeIntent.INTERFERENCE,
        ReroutePipe(
            removed_part_ids=(spool.part_id,),
            added_spool_spec_ids=(spool.spec_id, spool.spec_id),
            crosses_part_ids=(crossed.part_id,),
        ),
    )


def _part_changes(pick: Picker, add: AddCase) -> None:
    # 6. 판계 단계 S31P, 발주된 보강재 삭제
    stiffener = pick.first(
        lambda p: (
            p.kind is PartKind.STIFFENER
            and pick.code(p) == "S31P"
            and (pick.line_stage(p) or POStatus.NOT_ORDERED) is not POStatus.NOT_ORDERED
        ),
        "발주된 S31P 보강재",
    )
    add(
        f"S31P {stiffener.name} 삭제",
        "빼는 부재의 발주 품목·블록·도면",
        ChangeIntent.WEIGHT,
        RemovePart(part_ids=(stiffener.part_id,)),
    )

    # 7. T31C 판에 보강재 추가 + 선수부(대조 구역)에 붙는 위치 없는 브라켓 추가
    base = pick.first(lambda p: p.kind is PartKind.PLATE and pick.code(p) == "T31C", "T31C 판")
    section = next(s.spec_id for s in sorted(pick.snapshot.specs, key=lambda s: s.spec_id) if s.category == "section")
    bow = next(
        b.block_id for b in sorted(pick.snapshot.blocks, key=lambda b: b.block_id) if b.block_id.endswith(":F11C")
    )
    add(
        f"T31C {base.name}에 보강재 추가, F11C에 브라켓 추가(위치 미정)",
        "새 부재(붙는 위치 있음·없음), 연산 두 개",
        ChangeIntent.STRENGTH,
        AddPart(
            block_id=base.block_id, kind=PartKind.STIFFENER, spec_id=section, qty=0.2, attach_to_part_id=base.part_id
        ),
        AddPart(block_id=bow, kind=PartKind.BRACKET, spec_id=section, qty=0.05),
    )

    # 8. 착수한 L31C 판에 미착수 P11C 스풀 관통부 추가
    pierced = pick.first(lambda p: p.kind is PartKind.PLATE and pick.code(p) == "L31C", "L31C 판")
    pipe = pick.first(lambda p: p.kind is PartKind.PIPE_SPOOL and pick.code(p) == "P11C", "P11C 스풀")
    add(
        f"L31C {pierced.name}에 관통부 추가(P11C 스풀)",
        "새 관통 연결, 칼라를 받는 배관과 그 블록·도면",
        ChangeIntent.INTERFERENCE,
        AddPenetration(plate_part_id=pierced.part_id, pipe_part_id=pipe.part_id, diameter_mm=200),
    )


def _unknown_and_paired(pick: Picker, add: AddCase) -> None:
    # 9. 발주 단계를 알 수 없는 품목의 판 강종 변경
    vague = pick.vague_plate()
    grade = vague.grade or "AH36"
    add(
        f"{pick.code(vague)} {vague.name} 강종 {grade}→EH36",
        "발주 단계 판단 불가 품목",
        ChangeIntent.RULE_CHANGE,
        GradeChange(part_ids=(vague.part_id,), from_grade=grade, to_grade="EH36" if grade != "EH36" else "DH36"),
    )

    # 10. 판계 단계 S31S, 맞댄 같은 두께 두 판을 함께 두껍게 + 한 판 길이 변경
    first = pick.first(
        lambda p: (
            p.kind is PartKind.PLATE
            and pick.code(p) == "S31S"
            and any(
                n.thickness_mm == p.thickness_mm and n.block_id == p.block_id
                for n in pick.neighbours(p, Relation.BUTT_WELD)
            )
        ),
        "맞댄 같은 두께 S31S 판",
    )
    second = next(
        n
        for n in pick.neighbours(first, Relation.BUTT_WELD)
        if n.thickness_mm == first.thickness_mm and n.block_id == first.block_id
    )
    t = first.thickness_mm or 0
    add(
        f"S31S {first.name}·{second.name} 두께 {t:g}→{t + 4:g}mm, {first.name} 길이 변경",
        "맞댄 두 판 동시 변경(최종 두께), 연산 여러 개",
        ChangeIntent.STRENGTH,
        ThicknessChange(part_ids=(first.part_id, second.part_id), from_mm=t, to_mm=t + 4),
        DimensionChange(part_ids=(first.part_id,), field="length_mm", from_value=4000, to_value=4400),
    )


_BOUNDARY_GROUPS: tuple[tuple[Callable[[Boundary], None], range], ...] = (
    (thickness_thresholds, range(11, 16)),
    (stage_flips, range(16, 20)),
    (material_reuse, range(20, 22)),
    (valve_same_connection, range(22, 23)),
    (penetrations, range(23, 25)),
    (merged_and_added_parts, range(25, 27)),
    (unknown_and_processed, range(27, 29)),
    (thinner_plate, range(29, 30)),
    (surplus_demand, range(30, 31)),
)
"""경계 사례 묶음과 그 묶음이 더하는 사례 번호(표 순서대로 부른다)."""


def _boundary_cases(pick: Picker, add: AddCase, count: Callable[[], int]) -> None:
    """E1 의미 정확도 경계 사례 11~30(docs/evaluation.md '손 계산 경계 사례 30건' 중 관문 10건 다음).

    문턱 바로 위·아래(R-T02 두께 차, '10mm 이하' 얇은 쪽), 판정일 단계가 바뀌는 날 전·당일(R-T01 발주, R-B01 소조립),
    잉여 자재 전용 두 방향(R-M01 가·나), 연결 규격 같음/다름(R-P01), 관통·지지(R-P02·R-P03·R-T04 이어서 바뀌는 부재),
    단계를 모름, 새 부재 연결 유무(R-X01)를 하나씩 건드린다. 대상은 조건으로 고르고 기대값은 만들지 않는다.
    묶음은 `gate_boundary`에 있고 `_BOUNDARY_GROUPS` 순서로 부른다. count는 지금까지 더한 사례 수 — 묶음이 더한 사례
    번호가 표와 다르면 멈춘다(뒤 사례 번호가 조용히 밀리지 않게).
    """
    boundary = Boundary(pick, add)
    for group, numbers in _BOUNDARY_GROUPS:
        start = count() + 1
        group(boundary)
        added = range(start, count() + 1)
        assert added == numbers, f"경계 사례 묶음 {group.__name__}의 사례 번호가 {numbers}가 아니라 {added}"
