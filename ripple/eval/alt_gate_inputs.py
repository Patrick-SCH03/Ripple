"""3단계 관문 사례 입력 5건(대안 비교): 강도형 요청 세 종류((가) 판 두께·(나) 판 강종·(다) 보강재 추가)에서
템플릿·판정·최적 조합의 경로가 고루 걸리도록 대상과 확정일을 고른다(docs/engine.md(대안)).

- 데모 사례(ECN-D-0119 B31P 판 두께, ECN-D-0045 F11C 판 두께)의 블록은 쓰지 않고, 같은 조건의 다른 대상을 고른다.
- 대상이 의도한 조건(블록 단계, 발주 단계·계획 발주일, 강종과 상향 강종의 단가, 붙은 보강재, 두께 상한)을 갖췄는지는
  2단계 엔진과 같은 시계의 상태 함수와 지도·규칙 값으로 확인하고, 맞지 않으면 멈춘다.
- 기대 결과는 여기서 만들지 않는다(엔진 코드를 보지 않는 계산자가 명세로 계산).
"""

from __future__ import annotations

from datetime import date, timedelta

from ripple.config.loaders import load_params, load_strength
from ripple.config.settings import Settings
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.change import AddPart, ChangeIntent, ChangeOp, ChangeRequest, GradeChange, ThicknessChange
from ripple.contracts.domain import BlockStage, GraphSnapshot, Part, PartKind, POStatus, Relation
from ripple.contracts.evaluation import GateCaseInput, SnapshotRef
from ripple.contracts.params import ParamSet
from ripple.contracts.strength import StrengthRules
from ripple.engine.alternatives.strength import round_up_half_mm

from .gate_types import AddCase
from .picker import Picker

STAGE = 3
HOLD_CONFIRM_DAYS = 10  # 보류가 든 최적 조합을 보려고 확정 가능일을 기준일 10일 뒤로
DEMO_BLOCKS = frozenset({"B31P", "F11C"})  # 데모 사례의 블록(관문 사례에 쓰지 않음)
GRADE_RATIO = "steel.grade_price_ratio."


def _require(ok: bool, what: str) -> None:
    if not ok:
        raise LookupError(f"3단계 관문 사례의 전제가 맞지 않아요: {what}")


class _Rules:
    """전제 확인에 쓰는 규칙 값(강도 규칙·파라미터 키)."""

    def __init__(self, strength: StrengthRules, params: ParamSet) -> None:
        self.strength = strength
        self.params = params

    @property
    def tc(self) -> float:
        return self.strength.plate_corrosion_addition_mm.value

    @property
    def max_mm(self) -> float:
        return self.strength.max_plate_thickness_mm.value

    def upper_priced(self, grade: str | None) -> bool:
        """다음 강종이 있고 그 단가 비율이 파라미터에 있음(강종 상향 대안 T2를 만드는 조건)."""
        upper = self.strength.upgrade.values.get(grade or "")
        return upper is not None and f"{GRADE_RATIO}{upper}" in self.params.params

    def doubled_mm(self, t0: float) -> float:
        """보강재 대신 두께(T4)의 두께: t_c + 2(t₀ − t_c)를 0.5mm 단위로 올림."""
        return round_up_half_mm(self.tc + 2 * (t0 - self.tc))


class _Targets:
    """대상 후보: 기준일의 블록·발주 단계와 붙은 보강재로 거르고, 한 번 쓴 블록(데모 블록 포함)은 다시 쓰지 않는다."""

    def __init__(self, pick: Picker, rules: _Rules) -> None:
        self.pick = pick
        self.rules = rules
        self._used: set[str] = set(DEMO_BLOCKS)

    def stage_of(self, part: Part) -> BlockStage | None:
        return self.pick.state.block_stage_on(part.block_id, self.pick.as_of).likely

    def plates(self) -> list[Part]:
        """아직 쓰지 않은 블록의 판(ID 순)."""
        return [p for p in self.pick.parts if p.kind is PartKind.PLATE and self.pick.code(p) not in self._used]

    def attached(self, plate: Part) -> list[Part]:
        parts = self.pick.index.parts
        return sorted(
            (
                parts[n]
                for n, relation in self.pick.index.neighbours(plate.part_id)
                if relation is Relation.FILLET_WELD and n in parts and parts[n].kind is PartKind.STIFFENER
            ),
            key=lambda p: p.part_id,
        )

    def take(self, candidates: list[Part], what: str) -> Part:
        """첫 후보를 고르고 그 블록을 쓴 것으로 둔다(후보가 없으면 멈춘다)."""
        _require(bool(candidates), what)
        self.mark_used(candidates[0])
        return candidates[0]

    def mark_used(self, part: Part) -> None:
        """부재의 블록을 쓴 것으로 둔다(뒤 사례의 후보에서 빠진다)."""
        self._used.add(self.pick.code(part))

    def line_at_least(self, part: Part, status: POStatus) -> bool:
        line = self.pick.index.line_of_part.get(part.part_id)
        return line is not None and self.pick.state.line_stage_on(line, self.pick.as_of).at_least(status) is True

    def ordered_before(self, part: Part, confirm: date) -> bool:
        """기준일에 미발주이고 계획 발주일이 기준일 뒤 ~ confirm 안."""
        pick = self.pick
        planned = pick.planned_order(part) if part.part_id in pick.index.line_of_part else None
        return pick.line_stage(part) is POStatus.NOT_ORDERED and planned is not None and pick.as_of < planned <= confirm


def alt_gate_inputs(snapshot: GraphSnapshot, seed: int, as_of: date) -> list[GateCaseInput]:
    settings = Settings.from_env({})
    rules = _Rules(load_strength(settings.strength_path), load_params(settings.params_path))
    pick = Picker(snapshot, as_of, scheduled=True)
    ref = SnapshotRef(generator_seed=seed, snapshot_id=snapshot.snapshot_id)
    ship = snapshot.ships[0].ship_id
    cases: list[GateCaseInput] = []
    targets = _Targets(pick, rules)

    def add(title: str, focus: str, *ops: ChangeOp, confirm_on: date | None = None) -> None:
        number = len(cases) + 1
        change = ChangeRequest(
            ecn_id=f"GC3-{number:03d}", title=title, ship_ids=(ship,), intent=ChangeIntent.STRENGTH, ops=ops
        )
        request = AnalysisRequest(change=change, as_of=as_of, confirm_on=confirm_on, include_alternatives=True)
        cases.append(
            GateCaseInput(
                case_id=f"G3-{number:03d}", stage=STAGE, title=title, snapshot=ref, request=request, focus=focus
            )
        )

    _thicker_pre_outfitting(targets, add)  # 1
    _thicker_with_hold(targets, add)  # 2
    _upgrade_pair(targets, add)  # 3
    _stiffener_over_cap(targets, add)  # 4
    _thicker_trio(targets, add)  # 5
    return cases


def _thicker_pre_outfitting(targets: _Targets, add: AddCase) -> None:
    # 1. (가) 선행의장 블록의 판 두께 +1.5mm — 판 발주가 가공 이후라 두께안이 비싸고 보강재안(T1)이 맞섬,
    #    상향 강종 단가가 없어 강종 대안(T2)을 만들지 않음
    rules = targets.rules
    first = targets.take(
        [
            p
            for p in targets.plates()
            if targets.stage_of(p) is BlockStage.PRE_OUTFITTING
            and not rules.upper_priced(p.grade)
            and targets.line_at_least(p, POStatus.PROCESSED)
            and targets.attached(p)
            and p.thickness_mm is not None
            and (p.thickness_mm + 1.5 - rules.tc) / (p.thickness_mm - rules.tc) <= 2
        ],
        "선행의장 블록, 상향 강종 단가 없음, 가공까지 간 발주 품목, 보강재가 붙은 판",
    )
    t1 = first.thickness_mm or 0
    add(
        f"{targets.pick.code(first)} {first.name} 두께 {t1:g}→{t1 + 1.5:g}mm(선행의장)",
        "판 두께 증가(가): 보강재 추가안 T1의 보강재 수·중량과 판정 비율, "
        "상향 강종 단가가 없어 강종 대안을 만들지 않는 이유, 선행의장 블록의 재작업과 새 부재 제작 공수(C-02)",
        ThicknessChange(part_ids=(first.part_id,), from_mm=t1, to_mm=t1 + 1.5),
    )


def _thicker_with_hold(targets: _Targets, add: AddCase) -> None:
    # 2. (가) 미착수 블록의 판 두께 +2mm, 확정 가능일 = 기준일 + 10일 — 판 품목이 기준일에 미발주이고 계획 발주일이
    #    확정 가능일 전이라 발주 보류가 든 최적 조합이 될 수 있음
    confirm = targets.pick.as_of + timedelta(days=HOLD_CONFIRM_DAYS)
    second = targets.take(
        [
            p
            for p in targets.plates()
            if targets.stage_of(p) is BlockStage.NOT_STARTED
            and targets.rules.upper_priced(p.grade)
            and targets.ordered_before(p, confirm)
        ],
        f"미착수 블록, 상향 강종 단가 있음, 기준일 미발주이고 계획 발주일이 {confirm} 전인 판",
    )
    t2 = second.thickness_mm or 0
    add(
        f"{targets.pick.code(second)} {second.name} 두께 {t2:g}→{t2 + 2:g}mm({confirm.isoformat()}부터 확정 가능)",
        "확정 가능일이 기준일 뒤: 최적 조합의 확정일은 그날부터, 발주 보류 권고를 더한 보류 집합, 권고의 보류 행동, "
        "강종 상향안(T2)의 부족 판정",
        ThicknessChange(part_ids=(second.part_id,), from_mm=t2, to_mm=t2 + 2),
        confirm_on=confirm,
    )


def _upgrade_pair(targets: _Targets, add: AddCase) -> None:
    # 3. (나) 조립 중 블록의 판 두 장(두께가 다름) 강종 상향 — 강종 대신 두께안(T3)이 판 두께별 연산 둘
    pick, strength = targets.pick, targets.rules.strength
    assembly = [
        p
        for p in targets.plates()
        if targets.stage_of(p) is BlockStage.ASSEMBLY and targets.rules.upper_priced(p.grade)
    ]
    _require(bool(assembly), "조립 중 블록, 상향 강종 단가 있음")
    base = assembly[0]
    upper = strength.upgrade.values[base.grade or ""]
    pair = [
        q
        for q in assembly
        if q.block_id == base.block_id and q.grade == base.grade and q.thickness_mm != base.thickness_mm
    ]
    _require(bool(pair), f"{pick.code(base)}에 강종이 같고 두께가 다른 판")
    partner = pair[0]
    targets.mark_used(base)
    k0, k1 = strength.k(base.grade), strength.k(upper)
    _require(k0 is not None and k1 is not None and k1 < k0, f"{base.grade} → {upper}가 항복 강도를 올림")
    add(
        f"{pick.code(base)} {base.name}·{partner.name} 강종 {base.grade}→{upper}(조립 중)",
        "판 강종 상향(나): 강종 대신 두께안 T3의 두께(0.5mm 올림, 판 두께별 연산)와 판정 비율, 조립 중 블록의 재작업",
        GradeChange(part_ids=(base.part_id, partner.part_id), from_grade=base.grade or "", to_grade=upper),
    )


def _stiffener_over_cap(targets: _Targets, add: AddCase) -> None:
    # 4. (다) 조립 중 블록의 판에 보강재 하나 — 보강재 대신 두께안(T4)이 두께 상한을 넘어 설계자 확인,
    #    강종 상향안(T2)은 보강재만큼 강도를 못 올려 부족
    rules = targets.rules
    fourth = targets.take(
        [
            p
            for p in targets.plates()
            if targets.stage_of(p) is BlockStage.ASSEMBLY
            and rules.upper_priced(p.grade)
            and targets.attached(p)
            and p.thickness_mm is not None
            and rules.doubled_mm(p.thickness_mm) > rules.max_mm
        ],
        "조립 중 블록, 상향 강종 단가 있음, 보강재가 붙은 판, 보강재 대신 두께가 상한을 넘음",
    )
    reference = targets.attached(fourth)[0]
    add(
        f"{targets.pick.code(fourth)} {fourth.name}에 보강재 추가({reference.spec_id})",
        "판에 보강재 추가(다): 보강재를 붙인 패널 기준 비교, 보강재 대신 두께안 T4의 두께 상한(설계자 확인), "
        "강종 상향안 T2의 부족 판정, 새 부재 제작 공수(C-02)",
        AddPart(
            block_id=fourth.block_id,
            kind=PartKind.STIFFENER,
            spec_id=reference.spec_id,
            qty=reference.qty,
            attach_to_part_id=fourth.part_id,
        ),
    )


def _thicker_trio(targets: _Targets, add: AddCase) -> None:
    # 5. (가) 미착수 블록의 같은 두께 판 세 장 +2mm — 범위 축소안(T5)은 설계자 확인, 강종 상향안(T2)은 부족,
    #    날짜별 가장 싼 대안이 바뀔 수 있음
    groups: dict[tuple[str, float], list[Part]] = {}
    for p in targets.plates():
        if (
            targets.stage_of(p) is BlockStage.NOT_STARTED
            and targets.rules.upper_priced(p.grade)
            and p.thickness_mm is not None
            and p.head_m is not None
            and targets.pick.line_stage(p) is not None
        ):
            groups.setdefault((p.block_id, p.thickness_mm), []).append(p)
    trio_key = next((key for key, members in sorted(groups.items()) if len(members) >= 3), None)
    _require(trio_key is not None, "미착수 블록, 단계를 아는 발주 품목, 같은 두께 판 세 장")
    assert trio_key is not None
    trio = groups[trio_key][:3]
    t5 = trio_key[1]
    add(
        f"{targets.pick.code(trio[0])} 판 3장 두께 {t5:g}→{t5 + 2:g}mm(미착수)",
        "판 여러 장(가): 범위 축소안 T5(뺄 판 고르기, 설계자 확인), 보강재 추가안 T1의 판마다 연산, "
        "강종 상향안 T2 부족, 날짜별 가장 싼 대안 구간",
        ThicknessChange(part_ids=tuple(p.part_id for p in trio), from_mm=t5, to_mm=t5 + 2),
    )
