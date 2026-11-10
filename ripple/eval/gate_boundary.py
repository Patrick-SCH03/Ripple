"""1단계 E1 의미 정확도 경계 사례 묶음(G1-011~030, docs/evaluation.md).

묶음마다 대상을 조건으로 고르고 사례를 더한다. 묶음은 문맥 `Boundary` 하나만 받고, `gate_inputs._boundary_cases`가
묶음 표의 순서(곧 사례 번호 순)로 부른다. 기대값은 만들지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from ripple.contracts.change import (
    AddPart,
    ChangeIntent,
    DimensionChange,
    EquipmentSpecChange,
    GradeChange,
    RemovePart,
    ReroutePipe,
    ThicknessChange,
)
from ripple.contracts.domain import Block, BlockStage, Part, PartKind, POLine, POStatus, Relation

from .gate_types import AddCase
from .picker import Picker

HORIZON_DAYS = 60  # 단계가 바뀌는 날·남는 자재 수요를 찾는 기간(사례 요청의 기본 탐색 기간과 같음)


class Boundary:
    """경계 사례 묶음이 함께 쓰는 문맥: 대상 고르기·사례 더하기·기준일·탐색 기간과, 맞대기 이웃 두께가 한 가지인 판
    (`take`로 한 번씩만 꺼낸다 — 앞 묶음이 꺼낸 판은 뒤 묶음이 다시 쓰지 않는다)."""

    def __init__(self, pick: Picker, add: AddCase) -> None:
        self.pick = pick
        self.add = add
        self.as_of = pick.as_of
        self.horizon = HORIZON_DAYS
        self._uniform = _uniform_plates(pick)
        self._used: set[str] = set()

    def take(self, test: Callable[[Part, float], bool], what: str) -> tuple[Part, float]:
        """이웃 두께가 한 가지인 판 중 아직 꺼내지 않았고 test에 맞는 첫 판(ID 순)과 그 이웃 두께."""
        for part, width in self._uniform:
            if part.part_id not in self._used and test(part, width):
                self._used.add(part.part_id)
                return part, width
        raise LookupError(f"관문 사례를 만들 부재가 없어요: {what}")

    def taken(self, part: Part) -> bool:
        """앞 묶음이 `take`로 이미 꺼낸 판."""
        return part.part_id in self._used

    def ordered_day(self, line_id: str) -> int | None:
        """품목이 탐색 기간 안에서 처음 '발주' 이상이 되는 날(기준일에서 며칠 뒤)."""
        return self._flip_day(lambda d: self.pick.state.line_stage_on(line_id, d).at_least(POStatus.ORDERED))

    def sub_assembly_day(self, block_id: str) -> int | None:
        """블록이 탐색 기간 안에서 처음 소조립 이상이 되는 날(기준일에서 며칠 뒤)."""
        return self._flip_day(lambda d: self.pick.state.block_stage_on(block_id, d).at_least(BlockStage.SUB_ASSEMBLY))

    def _flip_day(self, test: Callable[[date], bool | None]) -> int | None:
        """기준일 다음 날부터 탐색 기간 안에서 test가 처음 참인 날(기준일에서 며칠 뒤)."""
        return next((d for d in range(1, self.horizon + 1) if test(self.as_of + timedelta(days=d)) is True), None)


def _uniform_plates(pick: Picker) -> list[tuple[Part, float]]:
    """맞대기 이웃의 두께가 한 가지인 판(ID 순)과 그 두께."""
    found = []
    for part in pick.parts:
        if part.kind is not PartKind.PLATE or part.thickness_mm is None:
            continue
        widths = {n.thickness_mm for n in pick.neighbours(part, Relation.BUTT_WELD)}
        width = next(iter(widths)) if len(widths) == 1 else None
        if width is not None:
            found.append((part, float(width)))
    return found


def thickness_thresholds(boundary: Boundary) -> None:
    pick, add, take = boundary.pick, boundary.add, boundary.take
    # 11·12. 얇은 쪽 10mm 경계: 이웃 13mm, 10mm로 줄이면 차 3.0 = 문턱(테이퍼), 10.5mm면 얇은 쪽 > 10이라 문턱 4.0(없음)
    thin, near = take(lambda p, w: 10 < w <= 13, "이웃 두께가 한 가지(10~13mm)인 판")
    for to_mm, note in ((near - 3.0, "차 3.0 = 문턱"), (near - 2.5, "얇은 쪽 10mm 초과 → 문턱 4.0")):
        add(
            f"{pick.code(thin)} {thin.name} 두께 {thin.thickness_mm:g}→{to_mm:g}mm({note})",
            "R-T02 문턱 경계: 얇은 쪽 판 10mm 이하 여부와 '이상'",
            ChangeIntent.WEIGHT,
            ThicknessChange(part_ids=(thin.part_id,), from_mm=thin.thickness_mm or 0, to_mm=to_mm),
        )

    # 13·14. 얇은 쪽 10mm 초과: 차 4.0 = 문턱(테이퍼), 3.5(없음) — 착수한 블록
    thick, wide = take(lambda p, w: w > 10 and pick.started(p.block_id), "착수한 블록에서 이웃 두께가 한 가지인 판")
    for gap in (4.0, 3.5):
        add(
            f"{pick.code(thick)} {thick.name} 두께 {thick.thickness_mm:g}→{wide + gap:g}mm"
            f"(이웃 {wide:g}mm, 차 {gap:g})",
            "R-T02 문턱 경계(얇은 쪽 10mm 초과 → 4.0)",
            ChangeIntent.STRENGTH,
            ThicknessChange(part_ids=(thick.part_id,), from_mm=thick.thickness_mm or 0, to_mm=wide + gap),
        )

    # 15. 두께 차가 두꺼운 판의 50%를 넘음(테이퍼 + 설계자 확인 메모) — 판을 얇게
    halved, base = take(lambda p, w: w >= 12, "이웃 두께가 12mm 이상 한 가지인 판")
    to_half = float(int(base / 2) - 1)
    add(
        f"{pick.code(halved)} {halved.name} 두께 {halved.thickness_mm:g}→{to_half:g}mm(이웃 {base:g}mm의 절반 아래)",
        "R-T02 두께 차 > 두꺼운 판의 50%",
        ChangeIntent.WEIGHT,
        ThicknessChange(part_ids=(halved.part_id,), from_mm=halved.thickness_mm or 0, to_mm=to_half),
    )


def stage_flips(boundary: Boundary) -> None:
    pick, add, as_of = boundary.pick, boundary.add, boundary.as_of
    # 16·17. 발주 단계 경계: 기준일에 미발주이고 탐색 기간 안에 '발주'가 되는 첫 품목의 첫 부재 — 그 전날·당일 확정
    pending: tuple[POLine, int] | None = None
    for candidate in sorted(pick.snapshot.po_lines, key=lambda x: x.line_id):
        if pick.state.line_stage_on(candidate.line_id, as_of).at_least(POStatus.ORDERED) is not False:
            continue
        found = boundary.ordered_day(candidate.line_id)
        if found is not None and found >= 2:
            pending = (candidate, found)
            break
    if pending is None:
        raise LookupError("관문 사례를 만들 품목이 없어요: 탐색 기간 안에 발주되는 품목")
    line, day = pending
    ordered = pick.index.parts[line.part_ids[0]]
    old = ordered.grade or "AH36"
    new = "EH36" if old != "EH36" else "DH36"
    for shift, note in ((day - 1, "발주 전날"), (day, "발주 당일")):
        add(
            f"{pick.code(ordered)} {ordered.name} 강종 {old}→{new}"
            f"({note} {(as_of + timedelta(days=shift)).isoformat()} 확정)",
            "R-T01 판정일 발주 단계 경계",
            ChangeIntent.RULE_CHANGE,
            GradeChange(part_ids=(ordered.part_id,), from_grade=old, to_grade=new),
            confirm_on=as_of + timedelta(days=shift),
        )

    # 18·19. 블록 단계 경계: 기준일에 미착수이고 탐색 기간 안에 소조립이 되는 첫 블록의 첫 판 길이 변경 — 전날·당일
    flipping: tuple[Block, int] | None = None
    for candidate_block in sorted(pick.snapshot.blocks, key=lambda b: b.block_id):
        if pick.started(candidate_block.block_id):
            continue
        entered = boundary.sub_assembly_day(candidate_block.block_id)
        if entered is not None:
            flipping = (candidate_block, entered)
            break
    if flipping is None:
        raise LookupError("관문 사례를 만들 블록이 없어요: 탐색 기간 안에 소조립이 되는 블록")
    block, start = flipping
    plate = pick.first(lambda p: p.kind is PartKind.PLATE and p.block_id == block.block_id, "그 블록의 판")
    for shift, note in ((start - 1, "소조립 전날"), (start, "소조립 당일")):
        add(
            f"{pick.code(plate)} {plate.name} 길이 변경({note} {(as_of + timedelta(days=shift)).isoformat()} 확정)",
            "R-B01 판정일 블록 단계 경계, 치수 변경",
            ChangeIntent.INTERFERENCE,
            DimensionChange(part_ids=(plate.part_id,), field="length_mm", from_value=3000, to_value=3200),
            confirm_on=as_of + timedelta(days=shift),
        )


def material_reuse(boundary: Boundary) -> None:
    pick, add = boundary.pick, boundary.add
    # 20. 남는 자재 → 다른 수요(R-M01 나): 기준일에 '입고'(가공 전) 품목의 첫 부재 삭제
    received = pick.first(
        lambda p: p.part_id in pick.index.line_of_part and pick.line_stage(p) is POStatus.RECEIVED,
        "입고(가공 전) 품목의 부재",
    )
    add(
        f"{pick.code(received)} {received.name} 삭제(입고된 자재)",
        "R-M01 (나) 남는 자재의 다른 블록 수요, R-M02",
        ChangeIntent.WEIGHT,
        RemovePart(part_ids=(received.part_id,)),
    )

    # 21. 재고 → 변경 수요(R-M01 가): 예약 없는 가공 전 재고와 규격이 같은 첫 판의 폭 변경
    free = {
        lot.spec_id
        for lot in pick.snapshot.stock
        if lot.reserved_block_id is None and not lot.processed and lot.received_date <= boundary.as_of
    }
    stocked = pick.first(lambda p: p.kind is PartKind.PLATE and p.spec_id in free, "예약 없는 재고와 규격이 같은 판")
    add(
        f"{pick.code(stocked)} {stocked.name} 폭 변경(같은 규격 재고 있음)",
        "R-M01 (가) 치수 변경 = 같은 규격 판정",
        ChangeIntent.INTERFERENCE,
        DimensionChange(part_ids=(stocked.part_id,), field="width_mm", from_value=2000, to_value=2100),
    )


def valve_same_connection(boundary: Boundary) -> None:
    pick, add = boundary.pick, boundary.add
    # 22. 착수한 블록 밸브, 연결 규격이 같은 다른 사양(부재 수정 없음)
    valve = pick.first(lambda p: p.kind is PartKind.VALVE and pick.started(p.block_id), "착수한 블록 밸브")
    spec = pick.index.specs[valve.spec_id]
    same = next(
        s.spec_id
        for s in sorted(pick.snapshot.specs, key=lambda s: s.spec_id)
        if s.category == "valve"
        and s.spec_id != spec.spec_id
        and (s.nominal_diameter_dn, s.pressure_class) == (spec.nominal_diameter_dn, spec.pressure_class)
    )
    add(
        f"{pick.code(valve)} {valve.name} 사양 변경(연결 규격 같음, 착수한 블록)",
        "R-P01 연결 규격 같음 → 부재 수정 없음, 착수한 블록 재작업",
        ChangeIntent.EQUIPMENT,
        EquipmentSpecChange(part_ids=(valve.part_id,), from_spec_id=valve.spec_id, to_spec_id=same),
    )


def penetrations(boundary: Boundary) -> None:
    pick, add = boundary.pick, boundary.add
    # 23. 서포트 없는 스풀 경로 변경, 서로 다른 착수 블록의 판 두 장 관통
    loose = pick.first(
        lambda p: (
            p.kind is PartKind.PIPE_SPOOL and pick.started(p.block_id) and not pick.neighbours(p, Relation.SUPPORT)
        ),
        "서포트 없는 착수 블록 스풀",
    )
    crossed: list[Part] = []
    for part in pick.parts:
        if (
            part.kind is PartKind.PLATE
            and pick.started(part.block_id)
            and part.block_id != loose.block_id
            and all(c.block_id != part.block_id for c in crossed)
        ):
            crossed.append(part)
        if len(crossed) == 2:
            break
    add(
        f"{pick.code(loose)} 배관 경로 변경(서포트 없음, 다른 블록 판 두 장 관통)",
        "R-P02 판마다, R-P03 없음, 이어서 바뀌는 판의 블록·도면",
        ChangeIntent.INTERFERENCE,
        ReroutePipe(
            removed_part_ids=(loose.part_id,),
            added_spool_spec_ids=(loose.spec_id,),
            crosses_part_ids=tuple(p.part_id for p in crossed),
        ),
    )

    # 24. 배관이 지나는 판의 두께 변경(칼라 → 배관 블록·도면은 이어서 바뀌는 부재로)
    pierced = pick.first(
        lambda p: p.kind is PartKind.PLATE and bool(pick.neighbours(p, Relation.PENETRATION)), "관통이 있는 판"
    )
    add(
        f"{pick.code(pierced)} {pierced.name} 두께 {pierced.thickness_mm:g}→"
        f"{(pierced.thickness_mm or 0) + 1:g}mm(배관 관통)",
        "R-T04 칼라 → 배관의 블록·도면(두 단계 경로)",
        ChangeIntent.STRENGTH,
        ThicknessChange(
            part_ids=(pierced.part_id,), from_mm=pierced.thickness_mm or 0, to_mm=(pierced.thickness_mm or 0) + 1
        ),
    )


def merged_and_added_parts(boundary: Boundary) -> None:
    pick, add = boundary.pick, boundary.add
    # 25. 한 판에 두께·강종 두 연산(같은 키는 한 번)
    double = pick.first(lambda p: p.kind is PartKind.PLATE and pick.code(p) == "S31P", "S31P 판")
    grade = double.grade or "AH36"
    add(
        f"S31P {double.name} 두께 +2mm와 강종 {grade}→EH36",
        "같은 부재 두 연산의 병합(같은 키 하나)",
        ChangeIntent.STRENGTH,
        ThicknessChange(
            part_ids=(double.part_id,), from_mm=double.thickness_mm or 0, to_mm=(double.thickness_mm or 0) + 2
        ),
        GradeChange(part_ids=(double.part_id,), from_grade=grade, to_grade="EH36" if grade != "EH36" else "DH36"),
    )

    # 26. 부재 추가: 착수한 블록 판에 맞대는 새 판 + 미착수 블록 판에 붙는 새 보강재
    started_plate = pick.first(lambda p: p.kind is PartKind.PLATE and pick.code(p) == "S31S", "S31S 판")
    idle_plate = pick.first(lambda p: p.kind is PartKind.PLATE and not pick.started(p.block_id), "미착수 블록 판")
    plate_spec = started_plate.spec_id
    section = next(s.spec_id for s in sorted(pick.snapshot.specs, key=lambda s: s.spec_id) if s.category == "section")
    add(
        f"S31S {started_plate.name}에 새 판, {pick.code(idle_plate)} {idle_plate.name}에 새 보강재",
        "새 부재 연결 종류(맞대기·필릿), 착수/미착수 블록, 도면 이어받기",
        ChangeIntent.STRENGTH,
        AddPart(
            block_id=started_plate.block_id,
            kind=PartKind.PLATE,
            spec_id=plate_spec,
            qty=0.3,
            attach_to_part_id=started_plate.part_id,
        ),
        AddPart(
            block_id=idle_plate.block_id,
            kind=PartKind.STIFFENER,
            spec_id=section,
            qty=0.1,
            attach_to_part_id=idle_plate.part_id,
        ),
    )


def unknown_and_processed(boundary: Boundary) -> None:
    pick, add = boundary.pick, boundary.add
    # 27. 발주 단계를 알 수 없는 품목의 브라켓 삭제
    vague = pick.first(
        lambda p: p.kind is PartKind.BRACKET and p.part_id in pick.index.line_of_part and pick.line_stage(p) is None,
        "단계를 알 수 없는 품목의 브라켓",
    )
    add(
        f"{pick.code(vague)} {vague.name} 삭제(발주 단계 모름)",
        "R-M02 단계 모름(영향 + 이유), R-M01 (나) 찾지 않음",
        ChangeIntent.WEIGHT,
        RemovePart(part_ids=(vague.part_id,)),
    )

    # 28. 가공이 끝난 품목의 판 강종 변경(R-M01 나는 입고·가공 전만)
    processed = pick.first(
        lambda p: (
            p.kind is PartKind.PLATE
            and pick.started(p.block_id)
            and not boundary.taken(p)
            and pick.line_stage(p) is POStatus.PROCESSED
        ),
        "가공 끝난 품목의 착수 블록 판",
    )
    pgrade = processed.grade or "AH36"
    add(
        f"{pick.code(processed)} {processed.name} 강종 {pgrade}→{'EH36' if pgrade != 'EH36' else 'DH36'}(가공 끝)",
        "R-T01 가공 단계, R-M01 (나) 해당 없음",
        ChangeIntent.RULE_CHANGE,
        GradeChange(part_ids=(processed.part_id,), from_grade=pgrade, to_grade="EH36" if pgrade != "EH36" else "DH36"),
    )


def thinner_plate(boundary: Boundary) -> None:
    pick = boundary.pick
    # 29. 판을 얇게: 이웃이 더 두꺼운 쪽, 얇은 쪽(바꾼 판) 10mm 이하로 문턱 3.0, 차 4
    thinner, thick_side = boundary.take(lambda p, w: w >= 13, "이웃 두께가 13mm 이상 한 가지인 판(남은 것)")
    boundary.add(
        f"{pick.code(thinner)} {thinner.name} 두께 {thinner.thickness_mm:g}→{thick_side - 4:g}mm(얇게)",
        "R-T02 바꾼 판이 얇은 쪽이 되는 방향",
        ChangeIntent.WEIGHT,
        ThicknessChange(part_ids=(thinner.part_id,), from_mm=thinner.thickness_mm or 0, to_mm=thick_side - 4),
    )


def surplus_demand(boundary: Boundary) -> None:
    pick, as_of, horizon = boundary.pick, boundary.as_of, boundary.horizon
    snapshot = pick.snapshot
    # 30. 남는 자재를 쓸 다른 블록 수요가 실제로 있는 날(R-M01 나 양성): 판정일에 대표 단계 '입고'인 품목과
    #     같은 규격 ID의 다른 블록 품목(그날 입고 미만, 소비 공정 착수 예정일이 판정일 + 3 ~ + 57일 — 탐색 기간
    #     끝과 겹치지 않게)이 있는 첫 날·첫 품목의 첫 부재를 뺀다
    activity_start = {a.activity_id: a.planned_start for a in snapshot.activities}
    by_spec: dict[str, list[POLine]] = {}
    for item in sorted(snapshot.po_lines, key=lambda x: x.line_id):
        by_spec.setdefault(item.spec_id, []).append(item)

    def blocks_of(item: POLine) -> set[str]:
        return {pick.index.parts[p].block_id for p in item.part_ids if p in pick.index.parts}

    def demand(source: POLine, on: date) -> bool:
        for other in by_spec[source.spec_id]:
            begins = activity_start.get(other.consumed_by_activity_id or "")
            if (
                other.line_id != source.line_id
                and blocks_of(other) - blocks_of(source)
                and begins is not None
                and on + timedelta(days=3) <= begins <= on + timedelta(days=horizon - 3)
                and pick.state.line_stage_on(other.line_id, on).at_least(POStatus.RECEIVED) is False
            ):
                return True
        return False

    surplus: tuple[POLine, int] | None = None
    for offset in range(horizon + 1):
        on = as_of + timedelta(days=offset)
        for source in sorted(snapshot.po_lines, key=lambda x: x.line_id):
            if pick.state.line_stage_on(source.line_id, on).likely is POStatus.RECEIVED and demand(source, on):
                surplus = (source, offset)
                break
        if surplus is not None:
            break
    if surplus is None:
        raise LookupError("관문 사례를 만들 품목이 없어요: 남는 자재를 쓸 다른 블록 수요")
    source, offset = surplus
    spare = pick.index.parts[source.part_ids[0]]
    boundary.add(
        f"{pick.code(spare)} {spare.name} 삭제"
        f"({(as_of + timedelta(days=offset)).isoformat()} 확정, 입고된 자재 → 다른 블록 수요)",
        "R-M01 (나) 양성: 남는 자재를 쓸 다른 블록 수요가 탐색 기간 안에 있음",
        ChangeIntent.WEIGHT,
        RemovePart(part_ids=(spare.part_id,)),
        confirm_on=as_of + timedelta(days=offset),
    )
