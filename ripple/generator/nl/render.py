"""문장 조립(docs/data.md(생성기) 7-1 사유·어순·잡음·조립): 대상·연산 단서·값·사유 배치, 글자 잡음, 조각 위치."""

from __future__ import annotations

import random

from ripple.contracts.change import ChangeOp, DimensionChange, EquipmentSpecChange, GradeChange, ThicknessChange
from ripple.contracts.dataset import MentionTruth, ValueForm
from ripple.contracts.domain import Part, PartKind

from .lexicon import NlLexicon
from .pieces import Piece, pick
from .targets import target_pieces
from .values import value_form, value_pieces


def _add_typo(rng: random.Random, lexicon: NlLexicon, pieces: list[Piece], noise: set[str]) -> None:
    # 문자 잡음은 비정답 조각에만 넣어 위치와 값 글자를 보존한다.
    if rng.random() < 0.15:
        options = [
            i
            for i, piece in enumerate(pieces)
            if piece.slot is None and len(piece.text.strip()) >= 2 and any(c.isalpha() for c in piece.text)
        ]
        if options:
            i = rng.choice(options)
            original = pieces[i].text
            for word, variants in lexicon.typos.items():
                if word in original:
                    pieces[i] = Piece(original.replace(word, pick(rng, variants), 1))
                    break
            else:
                korean = [j for j, c in enumerate(original) if "가" <= c <= "힣"]
                if korean:
                    j = rng.choice(korean)
                    mode = rng.choice(("repeat", "drop", "swap"))
                    if mode == "drop" and len(korean) > 1:
                        changed = original[:j] + original[j + 1 :]
                    elif mode == "swap" and j + 1 in korean:
                        changed = original[:j] + original[j + 1] + original[j] + original[j + 2 :]
                    else:
                        changed = original[:j] + original[j] + original[j:]
                    pieces[i] = Piece(changed)
            if pieces[i].text != original:
                noise.add("typo")


def _text_mentions(pieces: list[Piece], op: ChangeOp, form: ValueForm) -> tuple[str, tuple[MentionTruth, ...]]:
    text_parts: list[str] = []
    mentions: list[MentionTruth] = []
    offset = 0
    for piece in pieces:
        if piece.slot is not None:
            mentions.append(
                MentionTruth(
                    slot=piece.slot, start=offset, end=offset + len(piece.text), value=piece.value, exists=piece.exists
                )
            )
        text_parts.append(piece.text)
        offset += len(piece.text)
    if isinstance(op, DimensionChange) and form != "none":
        for mention in mentions:
            if mention.slot == "to_value":
                mentions.append(
                    MentionTruth(slot="from_value", start=mention.start, end=mention.end, value=op.from_value)
                )
                break
    mentions.sort(key=lambda mention: (mention.start, mention.slot))
    return "".join(text_parts), tuple(mentions)


def _place_reason(rng: random.Random, reason: list[Piece], sections: list[list[Piece]]) -> None:
    if reason:
        placement = rng.randrange(3)
        if placement == 0:
            sections.insert(0, [*reason, Piece(" 때문에")])
        elif placement == 1:
            sections.append([Piece("("), *reason, Piece(")")])
        else:
            sections.append([*reason, Piece(" 사유로")])


def render(
    rng: random.Random,
    op: ChangeOp,
    intent: str,
    parts: dict[str, Part],
    blocks: dict[str, str],
    lexicon: NlLexicon,
    specs: tuple[str, ...] = (),
) -> tuple[str, tuple[MentionTruth, ...], ValueForm, bool, tuple[str, ...]]:
    noise: set[str] = set()
    target = target_pieces(rng, op, parts, blocks, lexicon, noise)
    form = value_form(rng, op)
    # 치수는 지도에 원래 값이 없어 문장의 변경 전 값이 유일한 근거라 지도와 다르게 적는 잡음을 넣지 않는다
    stale = form == "from_to" and rng.random() < 0.02 and not isinstance(op, DimensionChange)
    if stale:
        noise.add("stale_before")
    valve_specs = tuple(sorted(p.spec_id for p in parts.values() if p.kind is PartKind.VALVE) + sorted(specs))
    value = value_pieces(rng, op, form, stale, tuple(sorted(set(valve_specs))), lexicon)
    cues = lexicon.operations[op.op]
    if isinstance(op, ThicknessChange):
        forbidden = "감후" if op.to_mm > op.from_mm else "증후"
        cues = tuple(cue for cue in cues if cue != forbidden)
    cue_text = pick(rng, cues)
    cue = [Piece(cue_text, "op", op.op)]
    if value and isinstance(op, ThicknessChange | GradeChange | EquipmentSpecChange) and rng.random() < 0.10:
        cue = []
    incompatible_reason = (intent == "strength" and isinstance(op, ThicknessChange) and op.to_mm < op.from_mm) or (
        intent == "weight" and isinstance(op, DimensionChange) and op.to_value > op.from_value
    )
    stated = rng.random() < 0.70 and not incompatible_reason
    reason = [Piece(pick(rng, lexicon.intents[intent]), "intent", intent)] if stated else []
    if isinstance(op, DimensionChange):
        if cue_text.startswith("길이"):
            cue = [Piece("길이", "field", op.field), Piece(cue_text[len("길이") :], "op", op.op)]
        else:
            cue = [Piece("길이", "field", op.field), Piece(" "), *cue]
    ending = pick(rng, lexicon.endings)
    sections = [target, cue, value]
    _place_reason(rng, reason, sections)
    if value and rng.random() < 0.20:
        sections.remove(value)
        sections.insert(0, value)
        noise.add("order")
    sections = [s for s in sections if s]
    if ending:
        sections.append([Piece(ending)])
    pieces: list[Piece] = []
    for i, section in enumerate(sections):
        if i:
            separator = " "
            if rng.random() < 0.08:
                separator = "" if rng.random() < 0.5 else "  "
                noise.add("spacing")
            pieces.append(Piece(separator))
        pieces.extend(section)
    _add_typo(rng, lexicon, pieces, noise)
    text, mentions = _text_mentions(pieces, op, form)
    return text, mentions, form, stated, tuple(sorted(noise))
