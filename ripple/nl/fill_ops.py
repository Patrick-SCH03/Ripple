"""연산 8종의 슬롯 채우기(docs/input.md(판단 계층) 7절). 연산 이름 → 채우기 함수 표(FILLERS)로 고른다.

대상 부재는 판단 최상위로, 지금 값은 지도로, 바꿀 값은 값 정규화로, 블록·규격·역할 부재는 결정적 일치로만 채운다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ripple.contracts.assistant import FillMethod
from ripple.contracts.domain import PartKind

from .fill_types import TargetPick
from .filler import Filler
from .specs import resolve_section, resolve_spools, resolve_valve_target
from .values import Measure, normalize_grade


def fill(filler: Filler, op: str, targets: Sequence[TargetPick]) -> None:
    """연산 op의 슬롯을 채우고, 어느 슬롯에도 쓰지 않은 표현을 확인할 것으로 남긴다."""
    filler.used.update(t.mention.span for t in targets)
    FILLERS[op](filler, targets)
    filler.leftovers(op)


def _thickness(f: Filler, targets: Sequence[TargetPick]) -> None:
    ids = f.targets(targets, "두께를 바꿀 부재")
    current = f.current(ids, "thickness_mm", "두께", "from_mm") if ids else None
    f.measure("to_mm", "thickness", current if isinstance(current, float) else None, None)


def _grade(f: Filler, targets: Sequence[TargetPick]) -> None:
    ids = f.targets(targets, "강종을 바꿀 부재")
    current = f.current(ids, "grade", "강종", "from_grade") if ids else None
    f.used_grades.update((g.start, g.end) for g in f.interp.grades)
    result = normalize_grade(f.interp.text, f.interp.grades, current if isinstance(current, str) else None)
    f.text_value("to_grade", result)


def _dimension(f: Filler, targets: Sequence[TargetPick]) -> None:
    f.targets(targets, "치수를 바꿀 부재")
    fields = sorted({h.value for h in f.interp.dimension_cues})
    if len(fields) == 1:
        hit = next(h for h in f.interp.dimension_cues if h.value == fields[0])
        f.put("field", fields[0], FillMethod.RULE, (hit.start, hit.end))
    elif fields:
        f.put("field", fields[0], FillMethod.GUESS)
        f.issue("field", "치수 종류 여럿", proposal=fields[0], options=tuple(fields))
    else:
        f.issue("field", "치수 종류 없음", options=("length_mm", "width_mm", "height_mm", "diameter_mm"))
    measure: Measure = "diameter" if fields == ["diameter_mm"] else "length"
    f.measure("to_value", measure, None, "from_value")
    if "from_value" not in f.slots:
        f.issue("from_value", "문장에 지금 치수 없음(지도에도 없는 값)")


def _equipment_spec(f: Filler, targets: Sequence[TargetPick]) -> None:
    ids = f.targets(targets, "사양을 바꿀 장비")
    current = f.current(ids, "spec_id", "규격", "from_spec_id") if ids else None
    described = [t.valve_type for t in f.interp.refs.targets if t.valve_type]
    current_id = current if isinstance(current, str) else None
    f.used_specs.update(
        t.span
        for t in f.interp.refs.specs
        if (t.spec_id and f.vocab.specs[t.spec_id].category == "valve") or t.attrs.keys() & {"dn", "pclass"}
    )
    part_phrases = [t.mention.phrase for t in targets]
    choice = resolve_valve_target(
        f.vocab, f.interp.refs.specs, current_id, described[0] if described else None, part_phrases
    )
    if choice.spec_id is not None and choice.spec_id == current_id:
        f.issue("to_spec_id", "바꿀 규격이 지금 규격과 같음", options=choice.candidates, span=choice.span)
        return
    f.spec_value("to_spec_id", choice)


def _remove_part(f: Filler, targets: Sequence[TargetPick]) -> None:
    f.targets(targets, "뺄 부재")


def _add_part(f: Filler, targets: Sequence[TargetPick]) -> None:
    mentions = f.interp.refs.mentions
    attach = next((m for m in mentions if m.role in ("at", "attach") and m.number is not None), None)
    # 붙일 부재는 선택 슬롯이라 문장에 없으면 묻지 않는다
    attach_id = f.role_part("attach_to_part_id", attach, "붙일 부재", ()) if attach else None
    block_id = f.vocab.parts[attach_id].part.block_id if attach_id else None
    cue_blocks = {c.value for c in f.interp.refs.cues if c.kind == "block"}
    if block_id is not None:
        f.put("block_id", block_id, FillMethod.RULE, attach.phrase if attach else None)
    elif len(cue_blocks) == 1:
        cue = next(c for c in f.interp.refs.cues if c.kind == "block")
        f.put("block_id", cue.value, FillMethod.RULE, (cue.start, cue.end))
    else:
        blocks = sorted({b for m in mentions for b in m.block_ids})
        f.issue("block_id", "부재를 더할 블록 하나로 특정 불가", options=tuple(blocks))
    new_kinds = [m for m in mentions if m.number is None and m.code is None and m.kind is not None]
    f.used.update(m.span for m in new_kinds)
    kinds = sorted({str(m.kind) for m in new_kinds})
    if len(kinds) == 1:
        f.put("kind", kinds[0], FillMethod.RULE, new_kinds[0].span)
    else:
        f.issue("kind", "더할 부재 종류 미정", options=tuple(k.value for k in PartKind))
    stated = f.interp.grades[0].grade if f.interp.grades else None
    if f.interp.grades:
        f.used_grades.add((f.interp.grades[0].start, f.interp.grades[0].end))
    f.used_specs.update(
        t.span
        for t in f.interp.refs.specs
        if (t.spec_id and f.vocab.specs[t.spec_id].category == "section") or "profile" in t.attrs
    )
    plate_grade = f.vocab.parts[attach_id].part.grade if attach_id else None
    choice = resolve_section(f.vocab, f.interp.refs.specs, stated or plate_grade)
    f.spec_value("spec_id", choice, guessed=stated is None and plate_grade is not None and len(choice.candidates) > 1)
    f.measure("qty", "mass", None)


def _reroute_pipe(f: Filler, targets: Sequence[TargetPick]) -> None:
    mentions = f.interp.refs.mentions
    # 번호 없는 종류 단어('새 스풀'·'관통 판')는 설명이다
    f.used.update(m.span for m in mentions if m.number is None and m.code is None)
    spools = [m for m in mentions if m.kind is PartKind.PIPE_SPOOL and m.number is not None and m.role != "add"]
    removed = f.role_parts("removed_part_ids", spools, "빼는 스풀", (PartKind.PIPE_SPOOL,)) or []
    if removed:
        span = (min(m.start for m in spools), max(m.end for m in spools))
        f.put("removed_part_ids", tuple(removed), FillMethod.RULE, span)
    f.used_specs.update(
        t.span
        for t in f.interp.refs.specs
        if (t.spec_id and f.vocab.specs[t.spec_id].category == "pipe") or (t.spec_id is None and "dn" in t.attrs)
    )
    added, added_span, reason = resolve_spools(f.vocab, f.interp.refs.specs)
    if reason:
        f.issue("added_spool_spec_ids", reason, span=added_span)
    elif added:
        f.put("added_spool_spec_ids", added, FillMethod.RULE, added_span)
    crossing = [
        m
        for m in mentions
        if m.role == "crosses" and m.kind in (PartKind.PLATE, None) and (m.number is not None or m.code)
    ]
    crossed = f.role_parts("crosses_part_ids", crossing, "관통하는 판", (PartKind.PLATE,)) or []
    if crossed:
        span = (min(m.start for m in crossing), max(m.end for m in crossing))
        f.put("crosses_part_ids", tuple(crossed), FillMethod.RULE, span)
    if not removed and not added and not any(i.slot in ("removed_part_ids", "added_spool_spec_ids") for i in f.issues):
        f.issue("removed_part_ids", "빼거나 더할 스풀 없음")


def _add_penetration(f: Filler, targets: Sequence[TargetPick]) -> None:
    mentions = f.interp.refs.mentions
    f.used.update(m.span for m in mentions if m.number is None and m.code is None)
    plates = [m for m in mentions if m.kind is PartKind.PLATE and (m.number is not None or m.code)]
    pipes = [m for m in mentions if m.kind is PartKind.PIPE_SPOOL and m.number is not None]
    f.role_part("plate_part_id", plates[0] if len(plates) == 1 else None, "관통되는 판", (PartKind.PLATE,))
    f.role_part("pipe_part_id", pipes[0] if len(pipes) == 1 else None, "관통하는 배관", (PartKind.PIPE_SPOOL,))
    f.measure("diameter_mm", "diameter", None)


FILLERS: dict[str, Callable[[Filler, Sequence[TargetPick]], None]] = {
    "thickness": _thickness,
    "grade": _grade,
    "dimension": _dimension,
    "equipment_spec": _equipment_spec,
    "remove_part": _remove_part,
    "add_part": _add_part,
    "reroute_pipe": _reroute_pipe,
    "add_penetration": _add_penetration,
}
"""연산 이름(ripple.contracts.change.OP_NAMES 8종) → 슬롯 채우기."""
