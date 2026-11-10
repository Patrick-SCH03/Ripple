"""답 읽기와 반영(docs/input.md(판단 계층) 3절 6 경로 표): 질문 종류마다 답을 대화 상태의 결정으로 바꾼다.

- 연산·의도: 보여 준 선택지나 그 이름을 적은 글. '해당 없음'이면 전체 선택지로 다시 묻는다.
- 대상 부재: 고른 부재, 또는 다시 설명한 글(결정적으로 정해지거나 후보 몇 개).
- 슬롯: 추정 값 확인('맞음'), 수치는 문장 해석과 같은 규칙으로(추정이면 한 번 더 확인), 그 밖은 직접 입력.
받을 수 없는 답은 AssistantError(명사형)로 거절한다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ripple.contracts.assistant import (
    INTENT_LABELS,
    OP_LABELS,
    OP_SLOTS,
    YES,
    Answer,
    ChangeDraft,
    FillMethod,
    SlotFill,
    SlotKind,
    SlotSpec,
    SlotValue,
)
from ripple.contracts.change import ChangeIntent
from ripple.contracts.decision import NONE_OPTION
from ripple.nl.aliases import find_aliases
from ripple.nl.fill_types import NUMERIC_SLOTS
from ripple.nl.refs import find_references
from ripple.nl.resolve import deterministic_part, mention_candidates
from ripple.nl.specs import find_spec_tokens
from ripple.nl.text import normalize
from ripple.nl.value_exprs import Form, ValueExpr, extract_values
from ripple.nl.values import Certainty, Measure, find_grades, normalize_measure, split_usable

from .errors import AssistantError
from .questions import MAX_CHOICES
from .resources import AssistantResources
from .state import Asked, ConversationState

NUMBER_KINDS = (SlotKind.MILLIMETER, SlotKind.QUANTITY)
_BEFORE_OF = {"to_mm": "from_mm", "to_value": "from_value"}
_CURRENT_SLOTS = frozenset({"from_mm", "from_value"})
_UNIT_HINT: dict[Measure, str] = {"thickness": "mm", "length": "mm", "diameter": "mm", "mass": "t"}

# ---------- 답 반영 ----------


def apply_choice(state: ConversationState, key: str, answer: Answer) -> None:
    """연산('op')·의도('intent') 질문의 답."""
    labels = OP_LABELS if key == "op" else {i.value: label for i, label in INTENT_LABELS.items()}
    option = answer.option_id
    if option == NONE_OPTION or option is None:
        state.expanded.add(key)
        if option == NONE_OPTION:
            return
    if option is not None and option in labels:
        if key == "op":
            state.fixed_op = option
            state.fixed_targets.clear()  # 연산이 바뀌면 대상 질문도 다시 만든다
            names = {s.name for s in OP_SLOTS[option]}
            state.overrides = {k: v for k, v in state.overrides.items() if k in names}
            state.value_checks = {k: v for k, v in state.value_checks.items() if k in names}
        else:
            state.fixed_intent = ChangeIntent(option).value
        return
    if answer.text is not None:
        chosen = [v for v, label in labels.items() if label in answer.text or v in answer.text]
        if len(chosen) == 1:
            if key == "op":
                state.fixed_op = chosen[0]
            else:
                state.fixed_intent = chosen[0]
            return
    raise AssistantError("선택지에서 선택 필요")


def apply_target(state: ConversationState, index: int, answer: Answer, resources: AssistantResources) -> None:
    """대상 질문 index번의 답."""
    option = answer.option_id
    if option == NONE_OPTION:
        state.target_choices.pop(index, None)
        state.restate_targets.add(index)
        return
    if option is not None:
        if option not in resources.vocab.parts:
            raise AssistantError("선택지에서 선택 필요")
        state.fixed_targets[index] = option
        state.target_choices.pop(index, None)
        state.restate_targets.discard(index)
        return
    assert answer.text is not None
    exact, candidates = resolve_target_text(answer.text, resources, state.context.ship_ids)
    if exact is not None:
        state.fixed_targets[index] = exact
        state.restate_targets.discard(index)
    elif candidates:
        state.target_choices[index] = candidates
        state.restate_targets.discard(index)
    else:
        raise AssistantError("해당 부재 없음 · 블록 코드와 부재 번호 함께 입력(예: T31C 판 7번)")


def apply_slot(
    state: ConversationState,
    slot: str,
    asked: Asked,
    answer: Answer,
    draft: ChangeDraft,
    resources: AssistantResources,
) -> None:
    """슬롯 질문의 답. draft는 지금 차례까지 사용자가 정한 것을 넣은 초안(수치 증감의 기준 값)."""
    op_name = state.fixed_op or (str(draft.op.value) if draft.op is not None else None)
    spec = next((s for s in OP_SLOTS.get(op_name or "", ()) if s.name == slot), None)
    if spec is None or op_name is None:
        raise AssistantError("만료된 질문 · 화면 새로 고침 필요")
    if answer.option_id == YES and asked.proposal_value is not None:
        state.overrides[slot] = user_fill(asked.proposal_value)
        state.value_checks.pop(slot, None)
        return
    if spec.kind in NUMBER_KINDS:
        if answer.text is None:
            raise AssistantError(f"{spec.label} — 숫자로 입력")
        reading = read_measure(op_name, slot, answer.text, draft, resources)
        if reading.value is None:
            raise AssistantError(f"{spec.label} 읽기 실패 · {reading.reason}")
        if reading.reason is None:
            state.overrides[slot] = user_fill(reading.value)
            state.value_checks.pop(slot, None)
        else:  # 추정이면 그 값으로 한 번 더 확인받는다
            state.value_checks[slot] = (reading.value, reading.reason)
        return
    if answer.option_id is not None and answer.option_id != YES:
        value = parse_slot_value(spec, answer.option_id, resources, state.context.ship_ids)
        state.overrides[slot] = user_fill(value if value is not None else answer.option_id)
        return
    value = parse_slot_value(spec, answer.text or "", resources, state.context.ship_ids)
    if value is None:
        raise AssistantError(f"{spec.label} 읽기 실패 · 다시 입력")
    state.overrides[slot] = user_fill(value)


# ---------- 답 읽기 ----------


@dataclass(frozen=True, slots=True)
class MeasureAnswer:
    """직접 입력한 수치 답. reason이 있으면 값을 못 정했거나(value 없음) 추정이라 확인받는다."""

    value: float | None
    reason: str | None = None


def read_measure(op: str, slot: str, text: str, draft: ChangeDraft, resources: AssistantResources) -> MeasureAnswer:
    """수치 슬롯의 직접 입력을 문장 해석과 같은 규칙으로 읽는다(ripple.nl.values).

    바꿀 값의 증감·비율('+2mm'·'2mm 올려')은 지금 값에 더하고, 단위가 값 종류와 맞지 않거나('17kg' → 두께)
    모호하거나 보통 범위 밖이면 정하지 않는다. 지금 값을 묻는 슬롯은 숫자 하나만 받는다.
    """
    measure: Measure = NUMERIC_SLOTS[op]
    field = draft.slots.get("field")
    if op == "dimension" and field is not None and field.value == "diameter_mm":
        measure = "diameter"
    hint = f"{_UNIT_HINT[measure]} 단위 숫자로 입력"
    exprs = extract_values(normalize(text), resources.lexicon.increase, resources.lexicon.decrease)
    usable, unusable = split_usable(exprs, measure)
    if unusable:
        return MeasureAnswer(None, f"단위 불일치 · {hint}")
    if not usable:
        return MeasureAnswer(None, f"숫자 없음 · {hint}")
    current: float | None = None
    if slot in _CURRENT_SLOTS:
        if len(usable) != 1 or usable[0].form not in (Form.ABSOLUTE, Form.FROM):
            return MeasureAnswer(None, "지금 값은 숫자 하나로 입력")
        usable = (ValueExpr(Form.ABSOLUTE, usable[0].first, marked=True),)
    else:
        before = draft.slots.get(_BEFORE_OF.get(slot, ""))
        current = before.value if before is not None and isinstance(before.value, float) else None
    result = normalize_measure(usable, measure, current)
    if result.after is None:
        return MeasureAnswer(None, result.reason or "값 읽기 실패")
    if current is not None and math.isclose(result.after, current):
        return MeasureAnswer(None, "지금 값과 같음 · 바꿀 값 입력")
    if result.certainty is Certainty.GUESS:
        return MeasureAnswer(result.after, result.reason or "값 확인 필요")
    return MeasureAnswer(result.after)


def parse_slot_value(
    spec: SlotSpec, text: str, resources: AssistantResources, ship_ids: Sequence[str]
) -> SlotValue | None:
    """직접 입력한 값을 슬롯 값으로(읽지 못하면 None). 수치 슬롯은 read_measure로 읽는다."""
    clean = normalize(text)
    lexicon, vocab = resources.lexicon, resources.vocab
    if spec.kind is SlotKind.GRADE:
        grades = find_grades(clean, lexicon.grades)
        return grades[-1].grade if grades else None
    if spec.kind in (SlotKind.SPEC, SlotKind.SPECS):
        tokens = [t for t in find_spec_tokens(clean, vocab) if t.spec_id]
        if not tokens:
            return None
        if spec.kind is SlotKind.SPEC:
            return tokens[0].spec_id
        return tuple(t.spec_id for t in tokens for _ in range(t.count or 1) if t.spec_id)
    if spec.kind in (SlotKind.PART, SlotKind.PARTS):
        refs = find_references(clean, vocab, lexicon, ship_ids)
        found = [deterministic_part(m, vocab, ship_ids) for m in refs.mentions]
        if not found or any(f is None for f in found):
            return None
        ids = tuple(dict.fromkeys(f for f in found if f))
        return ids if spec.kind is SlotKind.PARTS else (ids[0] if len(ids) == 1 else None)
    if spec.kind is SlotKind.BLOCK:
        refs = find_references(clean, vocab, lexicon, ship_ids)
        blocks = {c.value for c in refs.cues if c.kind == "block"}
        return next(iter(blocks)) if len(blocks) == 1 else None
    if spec.kind is SlotKind.DIMENSION:
        hits = {h.value for h in find_aliases(clean, {str(k): v for k, v in lexicon.dimensions.items()})}
        return next(iter(hits)) if len(hits) == 1 else None
    if spec.kind is SlotKind.PART_KIND:
        hits = {
            h.value for h in find_aliases(clean, {k.value: v for k, v in lexicon.part_kinds.items()}, kind_words=True)
        }
        return next(iter(hits)) if len(hits) == 1 else None
    return None


def resolve_target_text(
    text: str, resources: AssistantResources, ship_ids: Sequence[str]
) -> tuple[str | None, tuple[str, ...]]:
    """다시 설명한 대상: (결정적으로 정해진 부재, 아니면 후보 몇 개)."""
    clean = normalize(text)
    refs = find_references(clean, resources.vocab, resources.lexicon, ship_ids)
    if not refs.mentions:
        return None, ()
    mention = refs.mentions[0]
    exact = deterministic_part(mention, resources.vocab, ship_ids)
    if exact is not None:
        return exact, (exact,)
    ranked = mention_candidates(mention, resources.vocab, ship_ids, clean)
    return None, tuple(c.part_id for c in ranked[:MAX_CHOICES])


def user_fill(value: SlotValue) -> SlotFill:
    return SlotFill(value=value, method=FillMethod.USER)
