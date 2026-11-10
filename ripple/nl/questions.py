"""판단 질문 만들기(docs/input.md(판단 계층) 3절 1·2): 해석 → 연산·의도·대상 부재 질문과 선택지별 특징.

특징은 이름 → 값의 성긴 묶음이다. 같은 이름의 특징은 선택지끼리 가중치를 나눠 쓰는 조건부 로지스틱의
입력이다(ripple.decide.scorer). '해당 없음' 선택지의 특징은 'none:'으로 시작해 따로 가중치를 갖는다.
대상 부재 후보는 휴리스틱 점수 상위 MAX_CANDIDATES개다(정답이 없으면 정답 라벨은 '해당 없음').
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ripple.contracts.assistant import INTENT_LABELS, OP_LABELS, OP_SLOTS
from ripple.contracts.change import ChangeIntent
from ripple.contracts.decision import NONE_OPTION, ChoiceQuestion, DecisionTopic, Option
from ripple.contracts.domain import PartKind

from .interpret import Interpretation
from .ref_types import Mention
from .resolve import deterministic_part, mention_candidates
from .vocab import MapVocabulary, PartEntry

Features = dict[str, float]
MAX_CANDIDATES = 50
NONE_LABEL = "해당 없음"


@dataclass(frozen=True, slots=True)
class Posed:
    """질문 하나와 선택지별 특징. 대상 질문이면 그 표현도 함께 둔다."""

    question: ChoiceQuestion
    features: dict[str, Features]
    mention: Mention | None = None


def evidence(interp: Interpretation) -> frozenset[str]:
    """연산을 가늠하는 문장 증거(판단 아님, 점수기 특징)."""
    found: set[str] = set()
    if interp.grades:
        found.add("grade_token")
    if interp.dimension_cues:
        found.add("dimension_cue")
        if any(h.value == "diameter_mm" for h in interp.dimension_cues):
            found.add("diameter_cue")
    found.update(_value_evidence(interp))
    if interp.values:
        found.add("number")
    if interp.increase or interp.decrease:
        found.add("direction")
    found.update(_reference_evidence(interp))
    return frozenset(found)


def has_op_clue(interp: Interpretation) -> bool:
    """연산을 가늠할 단서가 문장에 있는가: 연산 단서 말 또는 증거(부재·규격·수치·방향·강종·치수 —
    'no_mention'만은 아님).

    없으면('안녕하세요 오늘 날씨 어때요') 점수기의 치우침만으로 연산을 정하지 않는다 — 초안에 연산을 넣지 않고 '어떤
    변경?'만 묻는다(점검 D-3). '평형수 밸브 바꿔 주세요'처럼 부재가 있으면 단서다."""
    return bool(interp.op_cues) or bool(evidence(interp) - {"no_mention"})


def _value_evidence(interp: Interpretation) -> set[str]:
    found: set[str] = set()
    for expr in interp.values:
        unit = expr.first.unit
        value = expr.first.value
        if unit == "t" and value >= 4:
            found.add("t_unit")
        if unit == "kg" or (unit == "t" and value < 4):
            found.add("mass_unit")
        if unit == "mm" and value <= 60:
            found.add("small_mm")
        if value >= 100:
            found.add("large_number")
        if expr.form.value in ("delta", "from_delta", "ratio"):
            found.add("delta")
        if expr.form.value in ("from_to", "from_delta"):
            found.add("from_to")
    return found


def _reference_evidence(interp: Interpretation) -> set[str]:
    refs = interp.refs
    kinds = {m.kind for m in refs.mentions}
    found: set[str] = set()
    for kind, name in (
        (PartKind.VALVE, "valve_mention"),
        (PartKind.PIPE_SPOOL, "spool_mention"),
        (PartKind.PLATE, "plate_mention"),
        (PartKind.STIFFENER, "stiffener_mention"),
        (PartKind.BRACKET, "bracket_mention"),
    ):
        if kind in kinds:
            found.add(name)
    if refs.targets:
        found.add("target_description")
    found.update(_spec_evidence(interp))
    if any(m.number is None and m.code is None for m in refs.mentions):
        found.add("bare_kind")
    for mention in refs.mentions:
        if mention.role:
            found.add(f"role_{mention.role}")
    if not refs.mentions:
        found.add("no_mention")
    return found


def _spec_evidence(interp: Interpretation) -> set[str]:
    found: set[str] = set()
    refs = interp.refs
    for token in refs.specs:
        spec = token.spec_id
        if "profile" in token.attrs or (spec and spec.startswith("HP")):
            found.add("section_spec")
        if "dn" in token.attrs or "pclass" in token.attrs or (spec and spec.startswith("VL")):
            found.add("valve_spec")
        if spec and spec.startswith("SP"):
            found.add("spool_spec")
        if token.count:
            found.add("spec_count")
    return found


def op_question(interp: Interpretation, question_id: str) -> Posed:
    cued: dict[str, int] = {}
    for hit in interp.op_cues:
        cued[hit.value] = cued.get(hit.value, 0) + 1
    signals = evidence(interp)
    options = [Option(option_id=op, label=label) for op, label in OP_LABELS.items()]
    options.append(Option(option_id=NONE_OPTION, label=NONE_LABEL))
    features: dict[str, Features] = {}
    for op in OP_LABELS:
        f: Features = {f"bias:{op}": 1.0, "cue": float(min(cued.get(op, 0), 2))}
        if cued and op not in cued:
            f["other_cued"] = 1.0
        f.update({f"{op}|{s}": 1.0 for s in signals})
        features[op] = f
    features[NONE_OPTION] = {
        "none:bias": 1.0,
        "none:no_cue": float(not cued),
        "none:no_mention": float("no_mention" in signals),
    }
    question = ChoiceQuestion(
        question_id=question_id, topic=DecisionTopic.CHANGE_OP, mention=interp.text, options=tuple(options)
    )
    return Posed(question=question, features=features)


def intent_question(interp: Interpretation, op: str | None, question_id: str) -> Posed:
    cued: dict[str, int] = {}
    for hit in interp.intent_cues:
        cued[hit.value] = cued.get(hit.value, 0) + 1
    options = [Option(option_id=i.value, label=label) for i, label in INTENT_LABELS.items()]
    options.append(Option(option_id=NONE_OPTION, label=NONE_LABEL))
    features: dict[str, Features] = {}
    for intent in ChangeIntent:
        f: Features = {f"bias:{intent.value}": 1.0, "cue": float(min(cued.get(intent.value, 0), 2))}
        if cued and intent.value not in cued:
            f["other_cued"] = 1.0
        if op is not None:
            f[f"{op}|{intent.value}"] = 1.0
        features[intent.value] = f
    features[NONE_OPTION] = {"none:bias": 1.0, "none:no_cue": float(not cued)}
    question = ChoiceQuestion(
        question_id=question_id, topic=DecisionTopic.CHANGE_INTENT, mention=interp.text, options=tuple(options)
    )
    return Posed(question=question, features=features)


def target_mentions(interp: Interpretation, op: str) -> tuple[Mention, ...]:
    """보정 슬롯(대상 부재)에 들어갈 표현. 위치(~에)·관통 역할 표현은 빼고, 연산이 대상 슬롯을 갖는 경우만."""
    specs = {s.name: s for s in OP_SLOTS.get(op, ())}
    slot = specs.get("part_ids")
    if slot is None or not slot.calibrated:
        return ()
    return tuple(m for m in interp.refs.mentions if m.role not in ("at", "crosses"))


def target_questions(
    interp: Interpretation, op: str, vocab: MapVocabulary, ship_ids: Sequence[str], prefix: str
) -> tuple[Posed, ...]:
    slot = next((s for s in OP_SLOTS.get(op, ()) if s.name == "part_ids" and s.calibrated), None)
    if slot is None:
        return ()
    stated = _stated_before(interp, op)
    posed = []
    for index, mention in enumerate(target_mentions(interp, op)):
        scored = mention_candidates(mention, vocab, ship_ids, interp.text)
        top = scored[:MAX_CANDIDATES]
        det = deterministic_part(mention, vocab, ship_ids)
        features: dict[str, Features] = {}
        options = []
        for candidate in top:
            entry = vocab.parts[candidate.part_id]
            f = dict(candidate.features)
            f["kind_ok"] = float(not slot.part_kinds or entry.part.kind in slot.part_kinds)
            f["det"] = float(det == candidate.part_id)
            match = _value_match(op, entry, stated)
            if match is not None:
                f["value_match" if match else "value_mismatch"] = 1.0
            features[candidate.part_id] = f
            options.append(Option(option_id=candidate.part_id, label=entry.part.name, entity_id=candidate.part_id))
        heur = [c.score for c in top]
        features[NONE_OPTION] = {
            "none:bias": 1.0,
            "none:top": heur[0] if heur else 0.0,
            "none:gap": (heur[0] - heur[1]) if len(heur) > 1 else (heur[0] if heur else 0.0),
            "none:no_block": float(not mention.block_ids),
            "none:no_kind": float(mention.kind is None),
            "none:no_number_hit": float(mention.number is not None and not any(c.features.get("number") for c in top)),
            "none:empty": float(not top),
        }
        options.append(Option(option_id=NONE_OPTION, label=NONE_LABEL))
        question = ChoiceQuestion(
            question_id=f"{prefix}{index}",
            topic=DecisionTopic.TARGET_PART,
            mention=interp.text[mention.phrase[0] : mention.phrase[1]] or mention.text,
            options=tuple(options),
        )
        posed.append(Posed(question=question, features=features, mention=mention))
    return tuple(posed)


def _stated_before(interp: Interpretation, op: str) -> object:
    """문장에 적힌 변경 전 값(두께 mm·강종): 대상 후보의 지금 값과 맞는지 보는 특징용."""
    if op == "thickness":
        for expr in interp.values:
            if expr.form.value in ("from_to", "from_delta"):
                return expr.first.value
    if op == "grade" and len(interp.grades) >= 2:
        return interp.grades[0].grade
    return None


def _value_match(op: str, entry: PartEntry, stated: object) -> bool | None:
    if stated is None:
        return None
    if op == "thickness" and entry.part.thickness_mm is not None and isinstance(stated, float):
        return abs(entry.part.thickness_mm - stated) < 1e-9
    if op == "grade" and entry.part.grade is not None:
        return entry.part.grade == stated
    return None
