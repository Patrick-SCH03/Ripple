"""2단계 관문 사례 입력 13건(비용·일정·확정 시점): 1단계 사례의 대상과 데모 고정점을 다시 쓰고,
비용 줄·일정·보류 권고·판정 규칙이 고루 걸리도록 연산과 확정일을 고른다.

대상이 의도한 조건(블록·발주 단계, 재고, 같은 규격의 다른 품목)을 갖췄는지는 2단계 엔진과 같은 시계의 상태
함수로 확인하고, 맞지 않으면 멈춘다. 기대 결과는 여기서 만들지 않는다(엔진 코드를 보지 않는 계산자가
docs/engine.md(비용·일정)로 계산).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.change import (
    ChangeCause,
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
from ripple.contracts.domain import ActivityKind, BlockStage, GraphSnapshot, Part, PartKind, POStatus
from ripple.contracts.evaluation import GateCaseInput, SnapshotRef
from ripple.engine.schedule import ShipSchedule

from .gate_types import AddCase
from .picker import Picker

STAGE = 2
HORIZON_DAYS = 60  # 기본 탐색 기간(AnalysisRequest 기본값과 같음)
LONG_HORIZON_DAYS = 90
LATE_DAYS = 60  # 기본 탐색 기간의 마지막 날 확정
ERECTED_LATE_DAYS = 74  # 90일 탐색 안, T31C 탑재 뒤이고 인도 지연이 지체상금 유예를 넘길 만큼 늦은 확정
NO_STOCK_MM = 17.0  # T31C 이음부 판의 재고 없는 새 두께
PIPE_LEAD_DAYS = 60  # 규격 표준 리드타임이 없는 배관의 lead_time_days.pipe 대표값(사례 전제 확인용)


@dataclass(frozen=True, slots=True)
class _Joint:
    """1·2번 사례의 T31C 이음부 판과 그 값(12번이 2번과 같은 변경을 선주 요청으로 다시 쓴다)."""

    part: Part
    thickness: float  # 지금 두께(mm)
    erected_late: date  # 탑재 뒤 늦은 확정일


def _require(ok: bool, what: str) -> None:
    if not ok:
        raise LookupError(f"2단계 관문 사례의 전제가 맞지 않아요: {what}")


def _part(pick: Picker, part_id: str) -> Part:
    _require(part_id in pick.index.parts, f"부재 {part_id}가 지도에 있음")
    return pick.index.parts[part_id]


def _block_stage(pick: Picker, block_id: str, day: date) -> BlockStage | None:
    return pick.state.block_stage_on(block_id, day).likely


def cost_gate_inputs(snapshot: GraphSnapshot, seed: int, as_of: date) -> list[GateCaseInput]:
    pick = Picker(snapshot, as_of, scheduled=True)
    ref = SnapshotRef(generator_seed=seed, snapshot_id=snapshot.snapshot_id)
    ship = snapshot.ships[0].ship_id
    assert pick.baseline is not None  # scheduled=True
    schedule = pick.baseline.ships[ship]
    late = as_of + timedelta(days=LATE_DAYS)
    cases: list[GateCaseInput] = []

    def add(
        title: str,
        focus: str,
        intent: ChangeIntent,
        *ops: ChangeOp,
        confirm_on: date | None = None,
        horizon_days: int = HORIZON_DAYS,
        cause: ChangeCause | None = None,
        outfit_on_board: bool = False,
    ) -> None:
        number = len(cases) + 1
        change = ChangeRequest(
            ecn_id=f"GC2-{number:03d}", title=title, ship_ids=(ship,), intent=intent, ops=ops, cause=cause
        )
        request = AnalysisRequest(
            change=change,
            as_of=as_of,
            confirm_on=confirm_on,
            horizon_days=horizon_days,
            outfit_on_board=outfit_on_board,
        )
        cases.append(
            GateCaseInput(
                case_id=f"G2-{number:03d}", stage=STAGE, title=title, snapshot=ref, request=request, focus=focus
            )
        )

    joint = _joint_thickness(pick, add, as_of)  # 1·2
    _valve_spec(pick, add, as_of)  # 3·4
    _shared_line(pick, add, ship, late)  # 5·6
    _reroute_and_unknown(pick, add)  # 7·8
    _late_and_erected(pick, add, schedule, as_of, late)  # 9·10
    _bow_plate(pick, add, as_of)  # 11
    _owner_request(add, joint)  # 12
    _outfit_on_board(pick, add, schedule, as_of)  # 13
    return cases


def _joint_thickness(pick: Picker, add: AddCase, as_of: date) -> _Joint:
    """1·2번 사례를 더하고 그 판과 값을 돌려준다(12번이 같은 변경을 다시 쓴다)."""
    # 1·2. 조립 중 T31C 이음부 판(G1-001과 같은 판) — 재고 규격 두께로 기준일 확정 / 재고 없는 두께로 탑재 뒤 확정
    joint, lot_thickness = pick.stock_joint()
    thickness = joint.thickness_mm or 0
    _require(_block_stage(pick, joint.block_id, as_of) is BlockStage.ASSEMBLY, "T31C가 기준일에 조립 중")
    add(
        f"T31C 이음부 판 두께 {thickness:g}→{lot_thickness:g}mm(재고 충당, 기준일 확정)",
        "같은 규격 재고 충당(4-7 가), 가공 끝난 발주의 변경·할증, 조립 중 재작업과 탑재 관문",
        ChangeIntent.STRENGTH,
        ThicknessChange(part_ids=(joint.part_id,), from_mm=thickness, to_mm=lot_thickness),
    )
    stocked = [
        lot.lot_id
        for lot in pick.snapshot.stock
        if lot.reserved_block_id is None
        and pick.index.specs[lot.spec_id].grade == joint.grade
        and pick.index.specs[lot.spec_id].thickness_mm == NO_STOCK_MM
    ]
    _require(not stocked, f"{NO_STOCK_MM:g}mm {joint.grade} 판 재고가 없음")
    erected_late = as_of + timedelta(days=ERECTED_LATE_DAYS)
    _require(_block_stage(pick, joint.block_id, erected_late) is BlockStage.ERECTED, "T31C가 늦은 확정일에 탑재 뒤")
    add(
        f"T31C 이음부 판 두께 {thickness:g}→{NO_STOCK_MM:g}mm(재고 없음, {erected_late.isoformat()} 확정)",
        "탑재 뒤 확정: 새 자재를 기다리는 선상 재작업, 구역 출구·인도 지연과 지체상금, 탐색 기간 90일",
        ChangeIntent.STRENGTH,
        ThicknessChange(part_ids=(joint.part_id,), from_mm=thickness, to_mm=NO_STOCK_MM),
        confirm_on=erected_late,
        horizon_days=LONG_HORIZON_DAYS,
    )
    return _Joint(joint, thickness, erected_late)


def _valve_spec(pick: Picker, add: AddCase, as_of: date) -> None:
    # 3·4. 미착수 P11C 밸브, 연결 규격이 같은 다른 사양(G1-002·003과 같은 연산) — 기준일 / 계획 발주일 5일 뒤 확정
    valve, twin = pick.valve_twin()
    _require(pick.line_stage(valve) is POStatus.NOT_ORDERED, "P11C 밸브 품목이 기준일에 미발주")
    valve_op = EquipmentSpecChange(part_ids=(valve.part_id,), from_spec_id=valve.spec_id, to_spec_id=twin)
    add(
        f"P11C {valve.name} 사양 변경(기준일 확정)",
        "미발주 품목의 사양 변경: 자재비 차이·도면, 발주 예정일 전 마감일, 발주 보류 권고(8-3)",
        ChangeIntent.EQUIPMENT,
        valve_op,
    )
    after_order = (pick.planned_order(valve) or as_of) + timedelta(days=5)
    add(
        f"P11C {valve.name} 사양 변경({after_order.isoformat()} 확정)",
        "계획 발주일 뒤 확정: 판정일 품목 단계 추정, 발주 변경·할증, 바로 승인 기준",
        ChangeIntent.EQUIPMENT,
        valve_op,
        confirm_on=after_order,
    )


def _regrade(part: Part) -> GradeChange:
    grade = part.grade or "AH36"
    return GradeChange(part_ids=(part.part_id,), from_grade=grade, to_grade="DH36" if grade != "DH36" else "AH36")


def _shared_line(pick: Picker, add: AddCase, ship: str, late: date) -> None:
    # 5·6. 같은 발주 품목을 쓰는 미착수 F11C 보강재 둘, 같은 규격 품목이 다른 블록에 있음(잉여 자재 전용 4-7 나)
    removed, regraded = _part(pick, f"{ship}:F11C-ST-003"), _part(pick, f"{ship}:F11C-ST-014")
    source = pick.index.line_of_part.get(removed.part_id)
    _require(
        source is not None and pick.index.line_of_part.get(regraded.part_id) == source,
        "두 보강재가 같은 발주 품목을 씀",
    )
    assert source is not None
    _require(
        pick.state.line_stage_on(source, late).at_least(POStatus.ORDERED) is True,
        f"{source}가 {late}에 발주 이후",
    )
    spec_id = pick.index.lines[source].spec_id
    _require(
        any(
            line.spec_id == spec_id and any(pick.index.parts[p].block_id != removed.block_id for p in line.part_ids)
            for line_id, line in pick.index.lines.items()
            if line_id != source
        ),
        f"{spec_id} 품목이 다른 블록에도 있음",
    )
    add(
        f"F11C {removed.name} 강종 변경({late.isoformat()} 확정)",
        "발주한 품목의 규격 변경과 남는 자재의 다른 블록 전용(취급비), 발주 보류 권고",
        ChangeIntent.RULE_CHANGE,
        _regrade(removed),
        confirm_on=late,
    )
    add(
        f"F11C {removed.name} 삭제 + {regraded.name} 강종 변경({late.isoformat()} 확정)",
        "같은 품목의 삭제(R-M02)와 규격 변경(R-T01), 같은 곳으로의 전용 취급비 줄 하나",
        ChangeIntent.WEIGHT,
        RemovePart(part_ids=(removed.part_id,)),
        _regrade(regraded),
        confirm_on=late,
    )


def _reroute_and_unknown(pick: Picker, add: AddCase) -> None:
    # 7. E21C 배관 경로 변경(G1-005와 같은 연산)
    spool, crossed = pick.supported_spool(), pick.started_plate_elsewhere()
    add(
        "E21C 배관 경로 변경(스풀 1개 → 2개, 판 관통)",
        "빼는 스풀의 발주 감축, 새 스풀(임시 ID)의 자재비·리드타임, 관통 판·서포트 수정과 칼라, 두 블록 재작업",
        ChangeIntent.INTERFERENCE,
        ReroutePipe(
            removed_part_ids=(spool.part_id,),
            added_spool_spec_ids=(spool.spec_id, spool.spec_id),
            crosses_part_ids=(crossed.part_id,),
        ),
    )

    # 8. 발주 단계를 알 수 없는 품목의 판 강종 변경(G1-009와 같은 대상)
    vague = pick.vague_plate()
    grade = vague.grade or "AH36"
    add(
        f"{pick.code(vague)} {vague.name} 강종 {grade}→EH36(발주 단계 판단 불가)",
        "판단 불가 단계의 금액 범위(2절)와 판단 불가 표시, 계산하지 못한 이유, 요약 판정",
        ChangeIntent.RULE_CHANGE,
        GradeChange(part_ids=(vague.part_id,), from_grade=grade, to_grade="EH36" if grade != "EH36" else "DH36"),
    )


def _late_and_erected(pick: Picker, add: AddCase, schedule: ShipSchedule, as_of: date, late: date) -> None:
    # 9. 미착수 P11C 첫 판 두께 +2.5mm, 기본 탐색 기간 마지막 날 확정 — 새 자재 대기와 탑재 관문
    plate = pick.first(lambda p: p.kind is PartKind.PLATE and pick.code(p) == "P11C", "P11C 판")
    plate_mm = plate.thickness_mm or 0
    stage_late = _block_stage(pick, plate.block_id, late)
    _require(stage_late is not None and stage_late is not BlockStage.ERECTED, f"P11C가 {late}에 탑재 전")
    add(
        f"P11C {plate.name} 두께 {plate_mm:g}→{plate_mm + 2.5:g}mm({late.isoformat()} 확정)",
        "늦은 확정의 새 자재 도착과 탑재 관문, 구역 출구·인도 지연, 발주 보류 권고",
        ChangeIntent.STRENGTH,
        ThicknessChange(part_ids=(plate.part_id,), from_mm=plate_mm, to_mm=plate_mm + 2.5),
        confirm_on=late,
    )

    # 10. 기준 일정에서 기준일 뒤 가장 먼저 탑재를 마치는 블록의 첫 판 길이 변경, 탑재가 끝난 날 확정 — 선상 재작업
    finished_on, erection = min(
        (schedule.base.ef[a], a)
        for a, node in schedule.network.nodes.items()
        if node.kind is ActivityKind.ERECTION and schedule.base.ef[a] > as_of
    )
    block_id = schedule.network.nodes[erection].block_id or ""
    _require(_block_stage(pick, block_id, finished_on) is BlockStage.ERECTED, f"{block_id}가 {finished_on}에 탑재 뒤")
    erected = pick.first(lambda p: p.kind is PartKind.PLATE and p.block_id == block_id, f"{block_id} 판")
    add(
        f"{pick.code(erected)} {erected.name} 길이 변경(탑재 뒤, {finished_on.isoformat()} 확정)",
        "탑재가 끝난 블록의 선상 재작업(새 자재 없음): 확정 다음 날부터, 구역 출구 관문",
        ChangeIntent.INTERFERENCE,
        DimensionChange(part_ids=(erected.part_id,), field="length_mm", from_value=1000.0, to_value=1100.0),
        confirm_on=finished_on,
    )


def _bow_plate(pick: Picker, add: AddCase, as_of: date) -> None:
    # 11. 미발주 품목을 쓰는 미착수 F11C 첫 판 두께 +2mm, 기준일 확정 — 발주 변경·재작업이 없는 바로 승인 경계(8-4)
    bow = pick.first(lambda p: p.kind is PartKind.PLATE and pick.code(p) == "F11C", "F11C 판")
    _require(pick.line_stage(bow) is POStatus.NOT_ORDERED, "F11C 판 품목이 기준일에 미발주")
    _require(_block_stage(pick, bow.block_id, as_of) is BlockStage.NOT_STARTED, "F11C가 기준일에 미착수")
    bow_mm = bow.thickness_mm or 0
    add(
        f"F11C {bow.name} 두께 {bow_mm:g}→{bow_mm + 2:g}mm(기준일 확정)",
        "미발주 품목·미착수 블록의 규격 변경: 자재비 차이와 도면만, 바로 승인 기준, 발주 예정일 전 마감일과 보류 권고",
        ChangeIntent.STRENGTH,
        ThicknessChange(part_ids=(bow.part_id,), from_mm=bow_mm, to_mm=bow_mm + 2),
    )


def _owner_request(add: AddCase, joint: _Joint) -> None:
    # 12. 2번과 같은 변경(탑재 뒤 확정·인도 지연·지체상금)을 선주 요청으로 — 허용 지연(4-6)
    add(
        f"T31C 이음부 판 두께 {joint.thickness:g}→{NO_STOCK_MM:g}mm(선주 요청, {joint.erected_late.isoformat()} 확정)",
        "선주 요청 변경의 허용 지연: 지체상금 줄 없이 인도일 조정과 노출 금액(4-6), 판정 이유(8-4)",
        ChangeIntent.STRENGTH,
        ThicknessChange(part_ids=(joint.part.part_id,), from_mm=joint.thickness, to_mm=NO_STOCK_MM),
        confirm_on=joint.erected_late,
        horizon_days=LONG_HORIZON_DAYS,
        cause=ChangeCause.OWNER_REQUEST,
    )


def _outfit_on_board(pick: Picker, add: AddCase, schedule: ShipSchedule, as_of: date) -> None:
    # 13. P11C 스풀 교체(같은 규격 새 스풀), 의장품 선상 설치(6-3·6-8)
    #     — 새 스풀이 탑재 기간 안에 와서 탑재는 계획대로, 구역 출구는 탑재가 끝난 뒤 배 위 설치를 기다림(재작업 포함).
    #     확정일은 탑재 시작에서 리드타임만큼 거꾸로 잡는다(새 스풀 도착 다음 날 = 탑재 시작 다음 날).
    #     생성기 v3에서 탑재가 PE 뒤로 밀려 고정 확정일(기본 탐색 기간 마지막 날)로는 도착이 탑재 전이 되므로,
    #     일정에서 날짜를 고르고 탐색 기간은 90일로 둔다.
    spool = pick.first(lambda p: p.kind is PartKind.PIPE_SPOOL and pick.code(p) == "P11C", "P11C 스풀")
    lead = pick.index.specs[spool.spec_id].std_lead_time_days or PIPE_LEAD_DAYS
    erect = f"{spool.block_id}:{ActivityKind.ERECTION.value}"
    _require(erect in schedule.base.es, f"{erect}가 기준 일정에 있음")
    confirm = schedule.base.es[erect] - timedelta(days=lead)
    _require(
        as_of < confirm <= as_of + timedelta(days=LONG_HORIZON_DAYS),
        f"확정일 {confirm}이 기준일 뒤 탐색 기간 {LONG_HORIZON_DAYS}일 안",
    )
    spool_stage = _block_stage(pick, spool.block_id, confirm)
    _require(
        spool_stage is not None and spool_stage not in (BlockStage.NOT_STARTED, BlockStage.ERECTED),
        f"P11C가 {confirm}에 작업 중(재작업 있음)이고 탑재 전",
    )
    ready = confirm + timedelta(days=lead + 1)
    _require(
        schedule.base.es[erect] < ready <= schedule.base.ef[erect],
        "새 스풀 도착 다음 날이 P11C 탑재 기간 안(탑재를 늦추되 탑재가 끝나기 전에 받음)",
    )
    add(
        f"P11C {spool.name} 교체(같은 규격 새 스풀, 선상 설치, {confirm.isoformat()} 확정)",
        "의장품 선상 설치: 선상 설치 수요·탑재 관문에서 빼기·출구 lag와 자재 제약(6-3), 할증 C-03(4-1-3), "
        "R-S01 (다), 판정 이유, 되돌리기 선택지(6-8)",
        ChangeIntent.INTERFERENCE,
        ReroutePipe(removed_part_ids=(spool.part_id,), added_spool_spec_ids=(spool.spec_id,)),
        confirm_on=confirm,
        horizon_days=LONG_HORIZON_DAYS,
        outfit_on_board=True,
    )
