"""강도형 요청의 템플릿 대안(docs/engine.md(대안) 1·3절).

요청 → 판마다의 요청안 이득과 대안 초안(연산·대안 이득). 지도 색인·강도 규칙·파라미터 키만 읽는 순수 계산이다.
비용은 모른다(대안 평가는 compare가 같은 평가기로 한다).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from ripple.contracts.change import AddPart, ChangeIntent, ChangeOp, ChangeRequest, GradeChange, ThicknessChange
from ripple.contracts.domain import Part, PartKind, Relation
from ripple.contracts.params import ParamSet
from ripple.contracts.strength import StrengthRules

from ..index import GraphIndex
from .strength import half_up, round3, round_up_half_mm

STEEL_DENSITY_T_PER_M3 = 7.85
GRADE_RATIO = "steel.grade_price_ratio."

PANEL_GAIN = 2.0
"""보강재를 패널 가운데에 더하면 간격이 절반이 되어 강도 여유 지표가 두 배가 된다."""

UNKNOWN_INTENT = "변경 사유를 강도 보강으로 정하면 요청안과 비교 가능"
SCOPE_NOTE = "적용 범위 축소 대안 — 설계자 확인 필요"
COUNT_NOTE = "보강재 수는 판 면적 ÷ (스팬 × 간격)으로 개략 산정"
LOCAL_NOTE = "보강재 붙인 패널 하나의 강도 여유 기준 비교"


@dataclass(frozen=True, slots=True)
class Draft:
    """템플릿 대안 하나: 연산과 판마다의 대안 이득(판정하지 않으면 None)."""

    alt_id: str
    label: str
    ops: tuple[ChangeOp, ...]
    gains: dict[str, float] | None
    scope_reduced: bool = False
    designer_note: str | None = None  # 판정하지 않고 설계자 확인으로 둘 이유
    notes: tuple[str, ...] = ()  # 이 대안이 있으면 결과에 붙일 문구


@dataclass(frozen=True, slots=True)
class Plan:
    """요청 하나의 템플릿 결과."""

    request_label: str
    required: dict[str, float] = field(default_factory=dict)  # 판 → 요청안 이득
    drafts: tuple[Draft, ...] = ()
    notes: tuple[str, ...] = ()  # 대안을 만들지 않은 이유·비교 기준 문구
    designer_note: str | None = None  # 모든 대안을 설계자 확인으로 둘 이유(사유 없음·구조 정보 없음)


def plan(index: GraphIndex, change: ChangeRequest, strength: StrengthRules, params: ParamSet) -> Plan:
    if len(change.ops) != 1:
        return Plan("요청안", notes=("여러 연산을 함께 바꾸는 요청 — 대안 없음",))
    op = change.ops[0]
    label = f"요청안: {_summary(index, op)}"
    if change.intent not in (ChangeIntent.STRENGTH, None):
        return Plan(label, notes=("변경 사유가 강도 보강일 때만 강도 대안 생성",))
    builder = _Builder(index, strength, params, label, None if change.intent else UNKNOWN_INTENT)
    if isinstance(op, ThicknessChange):
        return builder.thickness(op)
    if isinstance(op, GradeChange):
        return builder.grade(op)
    if isinstance(op, AddPart):
        return builder.stiffener(op)
    return Plan(label, notes=("판 두께·강종·보강재 추가 요청만 강도 대안 생성",))


@dataclass(frozen=True, slots=True)
class _Builder:
    index: GraphIndex
    strength: StrengthRules
    params: ParamSet
    label: str
    intent_note: str | None

    @property
    def tc(self) -> float:
        return self.strength.plate_corrosion_addition_mm.value

    @property
    def max_mm(self) -> float:
        return self.strength.max_plate_thickness_mm.value

    def none(self, why: str) -> Plan:
        return Plan(self.label, notes=(why,))

    def plates(self, part_ids: tuple[str, ...]) -> list[Part] | None:
        parts = [self.index.parts[p] for p in part_ids]
        return parts if all(p.kind is PartKind.PLATE for p in parts) else None

    def missing(self, plates: list[Part]) -> str | None:
        """판정에 필요한 구조 정보가 빠진 판이 있으면 그 이유(설계자 확인)."""
        lacking = sorted(
            {
                name
                for p in plates
                for name, absent in (
                    ("두께", p.thickness_mm is None),
                    ("보강재 간격", p.stiffener_spacing_m is None),
                    ("강종", self.strength.k(p.grade) is None),
                )
                if absent
            }
        )
        if lacking:
            return f"판의 {'·'.join(lacking)} 정보 없음 — 예비 비교 불가"
        if any((p.thickness_mm or 0.0) <= self.tc for p in plates):
            return "판 두께가 부식 여유 이하 — 예비 비교 불가"
        return None

    def finish(self, required: dict[str, float], drafts: list[Draft | str], notes: tuple[str, ...] = ()) -> Plan:
        built = tuple(d for d in drafts if isinstance(d, Draft))
        skipped = tuple(d for d in drafts if isinstance(d, str))
        return Plan(self.label, required, built, (*skipped, *notes), self.intent_note)

    # ---------- (가) 판 두께 증가 ----------

    def thickness(self, op: ThicknessChange) -> Plan:
        plates = self.plates(op.part_ids)
        if plates is None:
            return self.none("판이 아닌 부재의 두께 변경 — 강도 대안 없음")
        if op.to_mm <= op.from_mm:
            return self.none("두께를 줄이는 요청 — 강도 대안 없음")
        lacking = self.missing(plates)
        if lacking:
            return Plan(self.label, drafts=self.drafts_without_gains(op, plates), designer_note=lacking)
        need = (op.to_mm - self.tc) / (op.from_mm - self.tc)
        required = {p.part_id: need for p in plates}
        drafts: list[Draft | str] = [self.t1(plates), self.t2(plates)]
        if len(plates) >= 2:
            drafts.append(self.t5(op, plates))
        return self.finish(required, drafts)

    def drafts_without_gains(self, op: ThicknessChange, plates: list[Part]) -> tuple[Draft, ...]:
        """구조 정보가 없을 때: 만들 수 있는 대안만, 모두 설계자 확인."""
        made = [self.t1(plates), self.t2(plates)]
        return tuple(d for d in made if isinstance(d, Draft))

    def t1(self, plates: list[Part]) -> Draft | str:
        ops: list[ChangeOp] = []
        count = 0
        for p in plates:
            if p.weight_kg is None or p.span_m is None or p.stiffener_spacing_m is None or not p.thickness_mm:
                return "판의 중량·스팬·간격 정보 없음 — 보강재 대안 생략"
            area = p.weight_kg / (STEEL_DENSITY_T_PER_M3 * p.thickness_mm)
            n = max(1, half_up(area / (p.span_m * p.stiffener_spacing_m)))
            profile = self.profile(p)
            if profile is None:
                return "보강재 단면을 정할 기준 보강재 없음 — 보강재 대안 생략"
            spec_id, per_m = profile
            qty = round3(n * per_m * p.span_m)
            if qty <= 0:
                return "보강재 중량 산정 불가 — 보강재 대안 생략"
            ops.append(
                AddPart(
                    block_id=p.block_id,
                    kind=PartKind.STIFFENER,
                    spec_id=spec_id,
                    qty=qty,
                    attach_to_part_id=p.part_id,
                )
            )
            count += n
        return Draft(
            alt_id="ALT-T1",
            label=f"판 두께 대신 보강재 추가(판 {len(plates)}장에 보강재 {count}개)",
            ops=tuple(ops),
            gains={p.part_id: PANEL_GAIN for p in plates},
            notes=(COUNT_NOTE,),
        )

    def profile(self, plate: Part) -> tuple[str, float] | None:
        """새 보강재의 규격과 1m당 무게(t/m): 판에 붙은 보강재(없으면 같은 블록 보강재) 중 가장 많은 규격."""
        attached = sorted(
            n
            for n, relation in self.index.neighbours(plate.part_id)
            if relation is Relation.FILLET_WELD
            and n in self.index.parts
            and self.index.parts[n].kind is PartKind.STIFFENER
        )
        pool = attached or sorted(
            q.part_id
            for q in self.index.parts.values()
            if q.block_id == plate.block_id and q.kind is PartKind.STIFFENER
        )
        if not pool:
            return None
        counts = Counter(self.index.parts[s].spec_id for s in pool)
        spec_id = min(counts, key=lambda s: (-counts[s], s))
        reference = self.index.parts[min(s for s in pool if self.index.parts[s].spec_id == spec_id)]
        if not reference.span_m:
            return None
        return spec_id, reference.qty / reference.span_m

    def t2(self, plates: list[Part]) -> Draft | str:
        groups: dict[tuple[str, str], list[str]] = {}
        gains: dict[str, float] = {}
        for p in plates:
            grade = p.grade or ""
            upper = self.strength.upgrade.values.get(grade)
            k0 = self.strength.k(grade)
            k1 = self.strength.k(upper)
            if upper is None or k0 is None or k1 is None or f"{GRADE_RATIO}{upper}" not in self.params.params:
                return f"{grade or '강종 미상'}보다 항복 강도가 높은 강종의 단가 없음 — 강종 대안 생략"
            groups.setdefault((grade, upper), []).append(p.part_id)
            gains[p.part_id] = math.sqrt(k0 / k1)
        ops = tuple(
            GradeChange(part_ids=tuple(ids), from_grade=low, to_grade=high)
            for (low, high), ids in sorted(groups.items())
        )
        steps = ", ".join(f"{low} → {high}" for low, high in sorted(groups))
        return Draft(alt_id="ALT-T2", label=f"강종 상향({steps})", ops=ops, gains=gains)

    def t5(self, op: ThicknessChange, plates: list[Part]) -> Draft | str:
        if any(p.head_m is None for p in plates):
            return "판의 설계 수두 정보 없음 — 범위 축소 대안 생략"

        def load(p: Part) -> float:
            k = self.strength.k(p.grade) or 1.0
            return (
                (p.stiffener_spacing_m or 0.0) * math.sqrt((p.head_m or 0.0) * k) / ((p.thickness_mm or 0.0) - self.tc)
            )

        candidates = sorted(plates, key=lambda p: p.part_id, reverse=True)
        dropped = min(candidates, key=load)
        kept = tuple(p for p in op.part_ids if p != dropped.part_id)
        return Draft(
            alt_id="ALT-T5",
            label=f"적용 범위 축소(판 {len(plates)}장 중 {len(kept)}장)",
            ops=(ThicknessChange(part_ids=kept, from_mm=op.from_mm, to_mm=op.to_mm),),
            gains=None,
            scope_reduced=True,
            designer_note=SCOPE_NOTE,
        )

    # ---------- (나) 판 강종 상향 ----------

    def grade(self, op: GradeChange) -> Plan:
        plates = self.plates(op.part_ids)
        if plates is None:
            return self.none("판이 아닌 부재의 강종 변경 — 강도 대안 없음")
        k0, k1 = self.strength.k(op.from_grade), self.strength.k(op.to_grade)
        if k0 is not None and k1 is not None and k1 >= k0:
            return self.none("항복 강도를 올리지 않는 강종 변경 — 강도 대안 없음")
        lacking = self.missing(plates) or (None if k0 and k1 else "강종 재료 계수 없음 — 예비 비교 불가")
        if lacking or k0 is None or k1 is None:
            return Plan(self.label, designer_note=lacking)
        need = math.sqrt(k0 / k1)
        required = {p.part_id: need for p in plates}
        return self.finish(required, [self.t3(plates, need)])

    def t3(self, plates: list[Part], need: float) -> Draft:
        groups: dict[tuple[float, float], list[str]] = {}
        gains: dict[str, float] = {}
        for p in plates:
            t0 = p.thickness_mm or 0.0
            t1 = round_up_half_mm(self.tc + (t0 - self.tc) * need)
            groups.setdefault((t0, t1), []).append(p.part_id)
            gains[p.part_id] = (t1 - self.tc) / (t0 - self.tc)
        ops = tuple(
            ThicknessChange(part_ids=tuple(ids), from_mm=t0, to_mm=t1) for (t0, t1), ids in sorted(groups.items())
        )
        steps = ", ".join(f"{t0:g} → {t1:g}mm" for t0, t1 in sorted(groups))
        too_thick = any(t1 > self.max_mm for _, t1 in groups)
        return Draft(
            alt_id="ALT-T3",
            label=f"강종 대신 두께 증가({steps})",
            ops=ops,
            gains=gains,
            designer_note=f"두께 {self.max_mm:g}mm 초과 — 설계자 확인 필요" if too_thick else None,
        )

    # ---------- (다) 판에 보강재 추가 ----------

    def stiffener(self, op: AddPart) -> Plan:
        attach = self.index.parts.get(op.attach_to_part_id or "")
        if op.kind is not PartKind.STIFFENER or attach is None or attach.kind is not PartKind.PLATE:
            return self.none("판에 붙이는 보강재 추가만 강도 대안 생성")
        lacking = self.missing([attach])
        if lacking:
            return Plan(self.label, designer_note=lacking)
        required = {attach.part_id: PANEL_GAIN}
        return self.finish(required, [self.t4(attach), self.t2([attach])], notes=(LOCAL_NOTE,))

    def t4(self, plate: Part) -> Draft:
        t0 = plate.thickness_mm or 0.0
        t1 = round_up_half_mm(self.tc + PANEL_GAIN * (t0 - self.tc))
        return Draft(
            alt_id="ALT-T4",
            label=f"보강재 대신 판 두께 증가({t0:g} → {t1:g}mm)",
            ops=(ThicknessChange(part_ids=(plate.part_id,), from_mm=t0, to_mm=t1),),
            gains={plate.part_id: (t1 - self.tc) / (t0 - self.tc)},
            designer_note=f"두께 {self.max_mm:g}mm 초과 — 설계자 확인 필요" if t1 > self.max_mm else None,
        )


def _summary(index: GraphIndex, op: ChangeOp) -> str:
    if isinstance(op, ThicknessChange):
        return f"판 두께 {op.from_mm:g} → {op.to_mm:g}mm({len(op.part_ids)}장)"
    if isinstance(op, GradeChange):
        return f"강종 {op.from_grade} → {op.to_grade}({len(op.part_ids)}개)"
    if isinstance(op, AddPart):
        spec = index.specs.get(op.spec_id)
        return f"{spec.description if spec else op.spec_id} 추가"
    return op.op
