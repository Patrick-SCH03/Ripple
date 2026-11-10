"""대상 표기(docs/data.md(생성기) 7-1 부재 표기): 부재 코드·블록 이름·번호, 목록·연속 번호, 연산 대상,
지도에 없는 번호로 바꾸기."""

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
from ripple.contracts.domain import Part, PartKind

from .lexicon import NlLexicon
from .pieces import ABBREVIATIONS, Piece, pick

_PART_CODE = re.compile(r"^([A-Z]\d+[CPS])-([A-Z]+)-(\d+)$")
_PART_FIELDS = (
    "part_ids",
    "removed_part_ids",
    "crosses_part_ids",
    "plate_part_id",
    "pipe_part_id",
    "attach_to_part_id",
)


def _alias(rng: random.Random, name: str, lexicon: NlLexicon, noise: set[str]) -> str:
    result = name
    for key in sorted(lexicon.blocks, key=len, reverse=True):
        if key in result:
            replacement = pick(rng, lexicon.blocks[key])
            result = result.replace(key, replacement)
            if replacement in ABBREVIATIONS or replacement == "NO.3 C.O.T":
                noise.add("abbreviation")
    return result


def _part_phrase(
    rng: random.Random,
    part_id: str,
    slot: str,
    catalog: dict[str, Part],
    blocks: dict[str, str],
    lexicon: NlLexicon,
    noise: set[str],
) -> list[Piece]:
    part = catalog.get(part_id)
    if part and rng.random() < 0.04 and sum(p.name == part.name for p in catalog.values()) == 1:
        return [Piece(part.name, slot, part_id)]
    code = part_id.rsplit(":", 1)[-1]
    match = _PART_CODE.fullmatch(code)
    if match is None:
        return [Piece(code, slot, part_id, part is not None)]
    block_code, prefix, serial = match.groups()
    if rng.random() < 0.30:
        rendered = code.lower() if rng.random() < 0.17 else code
        if rendered != code:
            noise.add("case")
        separator = "_" if rng.random() < 0.10 else "-"
        if separator != "-":
            noise.add("spacing")
        rendered = rendered.replace("-", separator)
        head = rendered[: len(block_code) + 1]
        return [Piece(head), Piece(rendered[len(head) :], slot, part_id, part is not None)]
    block_name = blocks.get(part.block_id, block_code) if part else block_code
    location = _alias(rng, block_name, lexicon, noise) if rng.random() < 0.75 else block_code
    kind = part.kind.value if part else _kind_from_prefix(prefix)
    kind_word = pick(rng, lexicon.kinds[kind])
    if kind_word in ABBREVIATIONS:
        noise.add("abbreviation")
    if part and part.system and rng.random() < 0.70:
        system = pick(rng, lexicon.systems[part.system])
        if system in ABBREVIATIONS:
            noise.add("abbreviation")
        location += " " + system
        valve_type = part.pid_class.removesuffix("_valve") if part.pid_class else ""
        if part.kind is PartKind.VALVE and valve_type in lexicon.valves:
            valve = pick(rng, lexicon.valves[valve_type])
            if valve in ABBREVIATIONS:
                noise.add("abbreviation")
            location += " " + valve
    marker = pick(rng, (f"{int(serial)}번", f"#{int(serial)}", serial))
    return [Piece(location + " " + kind_word + " "), Piece(marker, slot, part_id, part is not None)]


def _kind_from_prefix(prefix: str) -> str:
    return {
        "PL": "plate",
        "ST": "stiffener",
        "BR": "bracket",
        "SPCS": "pipe_spool",
        "SPBW": "pipe_spool",
        "VLCS": "valve",
        "VLBW": "valve",
        "PSCS": "pipe_support",
        "PSBW": "pipe_support",
    }.get(prefix, "plate")


def _part_list(
    rng: random.Random,
    ids: tuple[str, ...],
    slot: str,
    catalog: dict[str, Part],
    blocks: dict[str, str],
    lexicon: NlLexicon,
    noise: set[str],
) -> list[Piece]:
    selected = [catalog.get(part_id) for part_id in ids]
    if (
        len(ids) > 1
        and all(part is not None for part in selected)
        and len({(part.block_id, part.kind) for part in selected if part is not None}) == 1
        and rng.random() < 0.45
    ):
        anchor = selected[0]
        assert anchor is not None
        location = _alias(rng, blocks[anchor.block_id], lexicon, noise)
        if anchor.system and rng.random() < 0.7:
            system = pick(rng, lexicon.systems[anchor.system])
            location += " " + system
            if system in ABBREVIATIONS:
                noise.add("abbreviation")
        kind_word = pick(rng, lexicon.kinds[anchor.kind.value])
        if kind_word in ABBREVIATIONS:
            noise.add("abbreviation")
        compact = [Piece(location + " " + kind_word + " ")]
        consecutive = (
            len(ids) == 2
            and int(ids[1].rsplit("-", 1)[-1]) == int(ids[0].rsplit("-", 1)[-1]) + 1
            and rng.random() < 0.5
        )
        for i, part_id in enumerate(ids):
            if i:
                compact.append(Piece("~" if consecutive else ", "))
            serial = int(part_id.rsplit("-", 1)[-1])
            compact.append(Piece(f"{serial}번" if i == len(ids) - 1 else str(serial), slot, part_id))
        return compact
    result: list[Piece] = []
    for i, part_id in enumerate(ids):
        if i:
            result.append(Piece(", "))
        result.extend(_part_phrase(rng, part_id, slot, catalog, blocks, lexicon, noise))
    return result


def nonexistent(op: ChangeOp, rng: random.Random, parts: dict[str, Part]) -> ChangeOp:
    candidates: list[tuple[str, str, int | None]] = []
    for field in _PART_FIELDS:
        value = getattr(op, field, None)
        if isinstance(value, tuple):
            candidates.extend((field, part_id, i) for i, part_id in enumerate(value))
        elif isinstance(value, str):
            candidates.append((field, value, None))
    if not candidates:
        return op
    field, old, position = rng.choice(candidates)
    match = _PART_CODE.fullmatch(old.rsplit(":", 1)[-1])
    if match is None:
        return op
    prefix = old[: old.rfind("-") + 1]
    numbers = [int(part_id.rsplit("-", 1)[-1]) for part_id in parts if part_id.startswith(prefix)]
    number = max(numbers, default=0) + rng.randint(1, 3)
    replacement = f"{prefix}{number:03d}"
    current = getattr(op, field)
    if position is None:
        new_value: str | tuple[str, ...] = replacement
    else:
        values = list(current)
        values[position] = replacement
        new_value = tuple(values)
    return type(op).model_validate({**op.model_dump(), field: new_value})


def target_pieces(
    rng: random.Random,
    op: ChangeOp,
    parts: dict[str, Part],
    blocks: dict[str, str],
    lexicon: NlLexicon,
    noise: set[str],
) -> list[Piece]:
    if isinstance(op, ThicknessChange | GradeChange | DimensionChange | RemovePart | EquipmentSpecChange):
        return _part_list(rng, op.part_ids, "part_ids", parts, blocks, lexicon, noise)
    if isinstance(op, AddPart):
        block_code = op.block_id.rsplit(":", 1)[-1]
        block_name = blocks[op.block_id]
        label = _alias(rng, block_name, lexicon, noise) if rng.random() < 0.70 else block_code
        kind = pick(rng, lexicon.kinds[op.kind.value])
        result = [Piece(label, "block_id", op.block_id), Piece(" "), Piece(kind, "kind", op.kind.value)]
        if op.attach_to_part_id:
            result.append(Piece(" ("))
            result.extend(_part_phrase(rng, op.attach_to_part_id, "attach_to_part_id", parts, blocks, lexicon, noise))
            result.append(Piece("에 부착)"))
        return result
    if isinstance(op, ReroutePipe):
        result = _part_list(rng, op.removed_part_ids, "removed_part_ids", parts, blocks, lexicon, noise)
        if op.crosses_part_ids:
            result.append(Piece(" / 관통 판 "))
            result.extend(_part_list(rng, op.crosses_part_ids, "crosses_part_ids", parts, blocks, lexicon, noise))
        return result
    if isinstance(op, AddPenetration):
        result = _part_phrase(rng, op.plate_part_id, "plate_part_id", parts, blocks, lexicon, noise)
        result.append(Piece(" / 배관 "))
        result.extend(_part_phrase(rng, op.pipe_part_id, "pipe_part_id", parts, blocks, lexicon, noise))
        return result
    return []
