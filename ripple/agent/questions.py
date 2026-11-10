"""질문 만들기(docs/input.md(판단 계층) 3절 6 경로 표). 답 읽기와 반영은 answers.py.

질문 순서: 연산 → 대상 부재 → 확인할 슬롯 → (남은 것이 미리 채운 판단뿐이면) 요약 확인.
변경 사유(의도)는 분석 뒤에 묻는다(reason_question).
- 판단 질문: 고르기(되묻기 집합 + '해당 없음'), 다시 설명(자유 입력), 확인(최상위 하나 + '해당 없음').
- 슬롯 질문: 추정 값 확인(맞음 또는 직접 입력), 후보 고르기, 값 입력.
'해당 없음'을 고르면 연산·의도는 전체 선택지로, 대상은 다시 설명으로 묻는다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ripple.contracts.assistant import (
    INTENT_LABELS,
    OP_LABELS,
    OP_SLOTS,
    YES,
    ChangeDraft,
    Question,
    QuestionKind,
    QuestionOption,
    SlotFill,
    SlotKind,
    SlotSpec,
    SlotValue,
)
from ripple.contracts.change import ChangeIntent
from ripple.contracts.decision import NONE_OPTION, DecisionAnswer, Route
from ripple.contracts.domain import PartKind
from ripple.explain.format import topic_particle
from ripple.nl.draft import Proposal
from ripple.nl.fill_types import TEXT_ISSUE, SlotIssue
from ripple.nl.pipeline import Reading

from .resources import AssistantResources
from .state import Asked, ConversationState

NONE_LABEL = "해당 없음"
MAX_CHOICES = 7
NO_CLUE_REASON = "문장에 변경 종류 단서 없음 · 선택지에서 고르거나 요청 다시 입력"
"""연산 단서가 없는 문장의 연산 질문 이유(연산·슬롯을 짐작하지 않음)."""


def decision_keys(reading: Reading) -> list[str]:
    """판단 순서대로의 질문 키: 'op', 'target#0' …(Reading.decisions와 같은 순서)."""
    return ["op", *(f"target#{i}" for i in range(len(reading.targets)))]


def build_questions(
    state: ConversationState,
    reading: Reading,
    answers: Sequence[DecisionAnswer],
    proposal: Proposal,
    resources: AssistantResources,
    unit_auto: bool,
) -> list[Asked]:
    asked: list[Asked] = []
    by_key = dict(zip(decision_keys(reading), answers, strict=True))
    if state.fixed_op is None and not reading.op_clue:
        # 연산 단서가 없는 문장(점검 D-3): 연산·슬롯을 짐작하지 않고 연산 하나만 전체 선택지로 묻는다
        choice = _choice("op", "변경 종류는?", by_key["op"], OP_LABELS, True)
        question = choice.question.model_copy(update={"reason": NO_CLUE_REASON})
        return [Asked(question=question)]
    if not unit_auto:
        op = by_key["op"]
        if state.fixed_op is None and ("op" in state.expanded or op.route in (Route.CHOOSE, Route.RESTATE)):
            asked.append(_choice("op", "변경 종류는?", op, OP_LABELS, "op" in state.expanded))
        asked.extend(_target_questions(state, reading, by_key, resources))
    op_name = proposal.draft.op.value if proposal.draft.op else None
    for issue in proposal.issues:
        if issue.slot in state.overrides:
            continue
        asked.append(_slot_question(issue, str(op_name) if op_name else None, resources))
    if not asked and not unit_auto and not state.confirmed:
        pending = [k for k, a in by_key.items() if a.route is Route.CONFIRM and not _fixed(state, k)]
        if state.detail:
            for key in pending:
                asked.append(_confirm_one(key, by_key[key], reading, resources))
        elif pending:
            asked.append(summary_question(proposal.draft, resources))
    return _dedupe(asked)


def _target_questions(
    state: ConversationState, reading: Reading, by_key: Mapping[str, DecisionAnswer], resources: AssistantResources
) -> list[Asked]:
    asked: list[Asked] = []
    if "part_ids" in state.overrides:  # 문서 접수 확인표에서 대상을 이미 골라 넘긴 항목(1.27.0)
        return asked
    for index, scored in enumerate(reading.targets):
        if index in state.fixed_targets:
            continue
        answer = by_key[f"target#{index}"]
        mention = scored.posed.question.mention
        if index in state.target_choices:
            asked.append(_target_choice(index, mention, state.target_choices[index], resources))
        elif answer.route is Route.RESTATE or index in state.restate_targets:
            prompt = f"'{mention}'{topic_particle(mention)} 정확히 어느 부재? 블록 코드·부재 번호까지"
            asked.append(_restate(f"target#{index}", prompt))
        elif answer.route is Route.CHOOSE:
            asked.append(_target_choice(index, mention, answer.prediction_set, resources))
    return asked


def _dedupe(asked: list[Asked]) -> list[Asked]:
    seen: set[str] = set()
    out = []
    for item in asked:
        if item.question.target not in seen:
            seen.add(item.question.target)
            out.append(item)
    return out


def _fixed(state: ConversationState, key: str) -> bool:
    if key == "op":
        return state.fixed_op is not None
    return int(key.split("#")[1]) in state.fixed_targets


def _choice(key: str, prompt: str, answer: DecisionAnswer, labels: Mapping[str, str], everything: bool) -> Asked:
    ids = (
        list(labels)
        if everything or answer.route is Route.RESTATE
        else [i for i in answer.prediction_set if i in labels]
    )
    if not ids:
        ids = list(labels)
    options = [QuestionOption(option_id=i, label=labels[i]) for i in ids]
    options.append(QuestionOption(option_id=NONE_OPTION, label=NONE_LABEL))
    question = Question(
        question_id=key, kind=QuestionKind.CHOOSE, target=key, prompt=prompt, options=tuple(options), route=answer.route
    )
    return Asked(question=question)


def _target_choice(index: int, mention: str, part_ids: Sequence[str], resources: AssistantResources) -> Asked:
    ids = [p for p in part_ids if p != NONE_OPTION and p in resources.vocab.parts][:MAX_CHOICES]
    options = [_part_option(p, resources) for p in ids]
    options.append(QuestionOption(option_id=NONE_OPTION, label=f"{NONE_LABEL} — 다시 설명"))
    key = f"target#{index}"
    question = Question(
        question_id=key,
        kind=QuestionKind.CHOOSE,
        target=key,
        prompt=f"'{mention}'{topic_particle(mention)} 어느 부재?",
        options=tuple(options),
        route=Route.CHOOSE,
    )
    return Asked(question=question)


def _part_option(part_id: str, resources: AssistantResources) -> QuestionOption:
    entry = resources.vocab.parts[part_id]
    part = entry.part
    details = [entry.block_code or part.block_id.split(":")[-1]]
    if part.thickness_mm is not None:
        details.append(f"{part.thickness_mm:g}mm")
    if part.grade:
        details.append(part.grade)
    if part.kind in (PartKind.VALVE, PartKind.PIPE_SPOOL):
        details.append(part.spec_id)
    return QuestionOption(option_id=part_id, label=part.name, detail=" · ".join(details))


def _restate(key: str, prompt: str, reason: str | None = None) -> Asked:
    question = Question(question_id=key, kind=QuestionKind.RESTATE, target=key, prompt=prompt, reason=reason)
    return Asked(question=question)


def _slot_question(issue: SlotIssue, op: str | None, resources: AssistantResources) -> Asked:
    if issue.slot == TEXT_ISSUE or op is None:
        return _restate("text", "요청 다시 입력 — 더 구체적으로", issue.reason)
    spec = next((s for s in OP_SLOTS[op] if s.name == issue.slot), None)
    label = spec.label if spec else issue.slot
    key = f"slot:{issue.slot}"
    if issue.proposal is not None:
        shown = show_value(spec, issue.proposal, resources)
        options = [QuestionOption(option_id=YES, label=f"맞음 — {shown}")]
        options += [
            QuestionOption(option_id=o, label=show_value(spec, o, resources)) for o in issue.options[:MAX_CHOICES]
        ]
        question = Question(
            question_id=key,
            kind=QuestionKind.VALUE,
            target=issue.slot,
            prompt=f"{label} 확인",
            proposal=shown,
            reason=issue.reason,
            options=tuple(options),
        )
        return Asked(question=question, proposal_value=issue.proposal)
    if issue.options:
        options = [
            QuestionOption(option_id=o, label=show_value(spec, o, resources)) for o in issue.options[:MAX_CHOICES]
        ]
        question = Question(
            question_id=key,
            kind=QuestionKind.CHOOSE,
            target=issue.slot,
            prompt=f"{label}{topic_particle(label)}?",
            reason=issue.reason,
            options=tuple(options),
        )
        return Asked(question=question)
    question = Question(
        question_id=key,
        kind=QuestionKind.VALUE,
        target=issue.slot,
        prompt=f"{label}{topic_particle(label)}?",
        reason=issue.reason,
    )
    return Asked(question=question)


def _confirm_one(key: str, answer: DecisionAnswer, reading: Reading, resources: AssistantResources) -> Asked:
    if key == "op":
        label, prompt = OP_LABELS.get(answer.top, answer.top), "변경 종류 확인"
    else:
        label = resources.vocab.parts[answer.top].part.name if answer.top in resources.vocab.parts else answer.top
        mention = reading.targets[int(key.split("#")[1])].posed.question.mention
        prompt = f"'{mention}' 대상 부재 확인"
    options = (
        QuestionOption(option_id=answer.top, label=label),
        QuestionOption(option_id=NONE_OPTION, label=NONE_LABEL),
    )
    question = Question(
        question_id=key,
        kind=QuestionKind.CONFIRM,
        target=key,
        prompt=prompt,
        proposal=label,
        options=options,
        route=Route.CONFIRM,
    )
    return Asked(question=question)


def summary_question(draft: ChangeDraft, resources: AssistantResources) -> Asked:
    question = Question(
        question_id="summary",
        kind=QuestionKind.CONFIRM,
        target="summary",
        prompt="이해한 내용 확인 · 맞으면 분석 시작",
        proposal=summarize(draft, resources),
        options=(
            QuestionOption(option_id=YES, label="맞음 · 분석 시작"),
            QuestionOption(option_id=NONE_OPTION, label="고치기"),
        ),
    )
    return Asked(question=question)


REASON_KEY = "reason"
"""분석 뒤 질문(변경 사유 기록·바꾸기)의 키."""


def reason_question(answer: DecisionAnswer, recorded: ChangeIntent | None) -> Question:
    """분석 뒤 변경 사유 질문: 선택지는 사유 여섯 가지 전부(판단 확률 높은 순), 기록한 사유가 있으면 '바꾸기'."""
    order = sorted(INTENT_LABELS, key=lambda intent: -answer.probabilities.get(intent.value, 0.0))
    options = tuple(QuestionOption(option_id=intent.value, label=INTENT_LABELS[intent]) for intent in order)
    prompt = "기록에 남길 변경 사유는?" if recorded is None else "바꿀 변경 사유는?"
    return Question(
        question_id=REASON_KEY,
        kind=QuestionKind.CHOOSE,
        target=REASON_KEY,
        prompt=prompt,
        proposal=None if recorded is None else INTENT_LABELS[recorded],
        options=options,
        reason="승인 기록용 · 비용·일정 계산에는 미반영",
    )


def summarize(draft: ChangeDraft, resources: AssistantResources, unrecorded: bool = False, reason: bool = True) -> str:
    """초안을 한 줄로: '두께 변경 · No.3 COT 횡격벽 판 7 · 15mm → 17mm · 강도 보강'.

    unrecorded면(분석했는데 사유를 아직 기록하지 않음) 끝에 '사유 미정'을 붙인다. reason=False면 사유 조각을 빼고
    무엇을 얼마로 바꾸는지까지만(ECN 제목).
    """
    parts: list[str] = []
    if draft.op is not None:
        op = str(draft.op.value)
        parts.append(OP_LABELS[op])
        specs = {s.name: s for s in OP_SLOTS[op]}
        slots = draft.slots
        for name, fill in slots.items():
            spec = specs[name]
            if spec.from_map or name in ("from_value",):
                continue
            shown = show_value(spec, fill.value, resources)
            before = _before_of(op, slots, specs, resources)
            parts.append(
                f"{before} → {shown}" if before and name in ("to_mm", "to_grade", "to_spec_id", "to_value") else shown
            )
    if not reason:
        return " · ".join(parts)
    if draft.intent is not None:
        parts.append(INTENT_LABELS[ChangeIntent(str(draft.intent.value))])
    elif unrecorded and parts:
        parts.append("사유 미정")
    return " · ".join(parts)


def _before_of(
    op: str, slots: dict[str, SlotFill], specs: dict[str, SlotSpec], resources: AssistantResources
) -> str | None:
    for name in ("from_mm", "from_grade", "from_spec_id", "from_value"):
        if name in slots and name in specs:
            return show_value(specs[name], slots[name].value, resources)
    return None


def show_value(spec: SlotSpec | None, value: SlotValue, resources: AssistantResources) -> str:
    if spec is None:
        return str(value)
    if spec.kind is SlotKind.MILLIMETER and isinstance(value, float):
        return f"{value:g}mm"
    if spec.kind is SlotKind.QUANTITY and isinstance(value, float):
        return f"{value:g}"
    if spec.kind in (SlotKind.PART, SlotKind.PARTS):
        ids = value if isinstance(value, tuple) else (str(value),)
        return ", ".join(resources.vocab.parts[i].part.name if i in resources.vocab.parts else i for i in ids)
    if spec.kind is SlotKind.BLOCK and isinstance(value, str):
        return resources.directory.names.get(value, value)
    if spec.kind is SlotKind.SPECS and isinstance(value, tuple):
        return ", ".join(value)
    if spec.kind is SlotKind.DIMENSION and isinstance(value, str):
        return {"length_mm": "길이", "width_mm": "폭", "height_mm": "높이", "diameter_mm": "지름"}.get(value, value)
    return str(value)
