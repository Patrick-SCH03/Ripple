"""값 표기(docs/data.md(생성기) 7-1 값 표기): 절대값·전후·증감·비율, 밸브 바뀌는 속성, 경로 변경 규격 목록."""

from __future__ import annotations

import random
import re

from ripple.contracts.change import (
    AddPart,
    AddPenetration,
    ChangeOp,
    DimensionChange,
    EquipmentSpecChange,
    GradeChange,
    RemovePart,
    ReroutePipe,
    ThicknessChange,
)
from ripple.contracts.dataset import ValueForm

from .lexicon import NlLexicon
from .pieces import Piece, number, pick


def value_form(rng: random.Random, op: ChangeOp) -> ValueForm:
    if isinstance(op, ThicknessChange | GradeChange | DimensionChange | EquipmentSpecChange) and rng.random() < 0.03:
        return "none"
    if isinstance(op, ThicknessChange | DimensionChange):
        forms = (
            ("absolute", "from_to", "delta", "ratio")
            if isinstance(op, ThicknessChange)
            else ("from_to", "delta", "ratio")
        )
        return pick(rng, forms)  # type: ignore[return-value]
    if isinstance(op, GradeChange | EquipmentSpecChange):
        return pick(rng, ("absolute", "from_to"))  # type: ignore[return-value]
    return "absolute"


_VALVE_SPEC = re.compile(r"^VL-([A-Z]+)-DN(\d+)-(\d+K)$")


def _valve_change(
    from_spec: str, to_spec: str, valve_specs: tuple[str, ...], lexicon: NlLexicon, rng: random.Random
) -> str | None:
    """바뀌는 속성만 적은 표현('볼 밸브로'·'DN200 10K 체크 밸브로'). 그 속성 조합이 지도의 규격 하나일 때만."""
    before, after = _VALVE_SPEC.fullmatch(from_spec), _VALVE_SPEC.fullmatch(to_spec)
    if before is None or after is None:
        return None
    changed = [i for i in range(3) if before.group(i + 1) != after.group(i + 1)]

    def fits(spec: str) -> bool:
        match = _VALVE_SPEC.fullmatch(spec)
        if match is None:
            return False
        return all(match.group(i + 1) == (after if i in changed else before).group(i + 1) for i in range(3))

    if not changed or [s for s in valve_specs if fits(s)] != [to_spec]:
        return None
    words = []
    if 1 in changed:
        words.append(f"DN{after.group(2)}")
    if 2 in changed:
        words.append(after.group(3))
    kind = after.group(1).lower()
    if 0 in changed and kind in lexicon.valves:
        words.append(pick(rng, lexicon.valves[kind]) + " 밸브로")
    elif words:
        words[-1] += "로"
    else:
        return None
    return " ".join(words)


def _thickness_pieces(rng: random.Random, op: ThicknessChange, form: ValueForm, stale: bool) -> list[Piece]:
    before = op.from_mm + (1 if stale else 0)
    after = op.to_mm
    if stale and before == after:
        before = op.from_mm + 0.5
    if form == "from_to":
        value = pick(rng, (f"{number(before)}→{number(after)}mm", f"{number(before)}T에서 {number(after)}T로"))
    elif form == "delta":
        delta = after - before
        value = f"{number(abs(delta))}mm {'증가' if delta > 0 else '감소'}"
    elif form == "ratio":
        ratio = (after / before - 1) * 100
        value = f"{number(before)}mm에서 약 {abs(ratio):.1f}% {'증가' if ratio > 0 else '감소'}, {number(after)}mm로"
    else:
        value = pick(rng, (f"{number(after)}mm로", f"{number(after)}T"))
    return [Piece(value, "to_mm", after)]


def _dimension_pieces(op: DimensionChange, form: ValueForm, stale: bool) -> list[Piece]:
    before = op.from_value + (100 if stale else 0)
    after = op.to_value
    if stale and before == after:
        before += 100
    delta = after - before
    if form == "delta":
        value = f"{number(before)}에서 {number(abs(delta))}mm {'늘려' if delta > 0 else '줄여'}"
    elif form == "ratio":
        ratio = delta / before * 100
        value = f"{number(before)}mm에서 약 {abs(ratio):.1f}% {'늘려' if ratio > 0 else '줄여'} {number(after)}mm로"
    else:
        value = f"{number(before)}→{number(after)}mm"
    return [Piece(value, "to_value", after)]


def _reroute_pieces(rng: random.Random, op: ReroutePipe) -> list[Piece]:
    result: list[Piece] = []
    specs = op.added_spool_spec_ids
    if specs and len(set(specs)) == 1:
        # 같은 규격 여러 개는 '규격 N개'로 한 번 적는다(조각 하나가 그 규격 N개를 가리킨다)
        count = pick(rng, (f" {len(specs)}개", f" x {len(specs)}", f" {len(specs)}EA"))
        return [Piece(specs[0] + count, "added_spool_spec_ids", specs[0])]
    for i, spec_id in enumerate(specs):
        if i:
            result.append(Piece(", "))
        result.append(Piece(spec_id, "added_spool_spec_ids", spec_id))
    return result


def value_pieces(
    rng: random.Random,
    op: ChangeOp,
    form: ValueForm,
    stale: bool,
    valve_specs: tuple[str, ...] = (),
    lexicon: NlLexicon | None = None,
) -> list[Piece]:
    if form == "none" or isinstance(op, RemovePart):
        return []
    if isinstance(op, ThicknessChange):
        return _thickness_pieces(rng, op, form, stale)
    if isinstance(op, GradeChange):
        grade_before = (
            next(grade for grade in ("A", "AH32", "AH36", "DH36", "EH36") if grade not in {op.from_grade, op.to_grade})
            if stale
            else op.from_grade
        )
        value = f"{grade_before}→{op.to_grade}" if form == "from_to" else f"{op.to_grade}으로"
        return [Piece(value, "to_grade", op.to_grade)]
    if isinstance(op, DimensionChange):
        return _dimension_pieces(op, form, stale)
    if isinstance(op, EquipmentSpecChange):
        described = _valve_change(op.from_spec_id, op.to_spec_id, valve_specs, lexicon, rng) if lexicon else None
        if form == "absolute" and described is not None and rng.random() < 0.5:
            return [Piece(described, "to_spec_id", op.to_spec_id)]
        spec_before = op.from_spec_id + "-OLD" if stale else op.from_spec_id
        value = f"{spec_before}→{op.to_spec_id}" if form == "from_to" else f"{op.to_spec_id}로"
        return [Piece(value, "to_spec_id", op.to_spec_id)]
    if isinstance(op, AddPart):
        qty = pick(rng, (number(op.qty) + "t", number(op.qty) + "톤", number(op.qty * 1000) + "kg"))
        return [Piece(op.spec_id, "spec_id", op.spec_id), Piece(" "), Piece(qty, "qty", op.qty)]
    if isinstance(op, ReroutePipe):
        return _reroute_pieces(rng, op)
    if isinstance(op, AddPenetration):
        return [
            Piece(
                pick(rng, (f"지름 {number(op.diameter_mm)}", f"Ø{number(op.diameter_mm)}")),
                "diameter_mm",
                op.diameter_mm,
            )
        ]
    return []
