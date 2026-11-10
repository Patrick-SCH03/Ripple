"""사용자가 정한 것을 초안에 반영: 문서 접수 씨앗, 직접 정한 슬롯 값·확인할 수치, 외부 모델이 다시 쓴 해석 표시."""

from __future__ import annotations

from ripple.contracts.assistant import OP_SLOTS, AssistantTurnRequest, ChangeDraft, FillMethod, SlotFill, SlotKind
from ripple.nl.draft import Proposal, retarget
from ripple.nl.fill_types import TEXT_ISSUE, SlotIssue
from ripple.nl.vocab import MapVocabulary

from .state import ConversationState


def seeded_overrides(request: AssistantTurnRequest, vocab: MapVocabulary) -> dict[str, SlotFill]:
    """씨앗 슬롯 값(사용자가 정함). 고른 대상들의 지도 지금 값이 하나로 정해지지 않으면 대상 씨앗은 버린다 —
    비서가 대상을 다시 묻게(옛 대상의 지금 값으로 초안을 마치지 않게)."""
    seed = request.seed
    assert seed is not None and request.message is not None
    overrides = {k: v.model_copy(update={"method": FillMethod.USER}) for k, v in seed.overrides.items()}
    if seed.fixed_op is None:
        return overrides
    probe = ChangeDraft(
        text=request.message,
        ship_ids=request.context.ship_ids,
        op=SlotFill(value=seed.fixed_op, method=FillMethod.USER),
    )
    for spec in probe.specs():
        parts = overrides[spec.name].value if spec.name in overrides else None
        if not (spec.calibrated and spec.kind is SlotKind.PARTS and isinstance(parts, tuple)):
            continue
        if retarget(probe, spec.name, parts, vocab).mixed:
            del overrides[spec.name]
    return overrides


def with_overrides(proposal: Proposal, state: ConversationState, vocab: MapVocabulary) -> Proposal:
    """사용자가 정한 슬롯 값을 초안에 넣고, 그 슬롯의 확인할 것은 지운다. 확인할 수치 답은 추정 값과
    확인할 것으로 넣는다. 사용자가 대상을 정했으면 지금 값은 그 대상의 지도 값으로 다시 읽고, 원래 대상 기준
    증감으로 계산한 바꿀 값은 비워 다시 묻는다(retarget). 조립을 다시 시험한다."""
    draft = proposal.draft
    if not (state.overrides or state.value_checks) or draft.op is None:
        return proposal
    names = {s.name for s in OP_SLOTS[str(draft.op.value)]}
    overrides = {k: v for k, v in state.overrides.items() if k in names}
    checks = {k: v for k, v in state.value_checks.items() if k in names and k not in overrides}
    guessed = {k: SlotFill(value=value, method=FillMethod.GUESS) for k, (value, _) in checks.items()}
    slots = {**draft.slots, **guessed, **overrides}
    redo: list[SlotIssue] = []
    target = next((s for s in draft.specs() if s.calibrated and s.kind is SlotKind.PARTS and s.name in overrides), None)
    target_value = overrides[target.name].value if target is not None else None
    if target is not None and isinstance(target_value, tuple):
        moved = retarget(draft.model_copy(update={"slots": slots}), target.name, target_value, vocab)
        slots = {**moved.slots, **overrides}
        redo += [
            SlotIssue(slot=name, reason="대상 바뀜 · 원래 대상 기준으로 계산한 값 다시 정하기 필요")
            for name in moved.stale
            if name not in overrides
        ]
        redo += [SlotIssue(slot=name, reason="고른 부재들의 지금 값이 서로 다름") for name in moved.mixed]
    updated = ChangeDraft.model_validate(draft.model_copy(update={"slots": slots}).model_dump())
    refilled = {s.name for s in draft.specs() if s.from_map} if target is not None else set()
    issues = [i for i in proposal.issues if i.slot not in overrides and i.slot not in checks and i.slot not in refilled]
    issues += [SlotIssue(slot=k, reason=reason, proposal=value) for k, (value, reason) in checks.items()]
    issues += redo
    if updated.ready and not issues:
        try:
            updated.to_change(ecn_id="CHECK", title="check")
        except ValueError as error:
            issues.append(SlotIssue(slot=TEXT_ISSUE, reason=f"요청 조립 불가 · {error}"))
    return Proposal(draft=updated, issues=tuple(issues))


def as_llm(proposal: Proposal) -> Proposal:
    """외부 모델이 다시 쓴 문장에서 읽은 초안: 지도·화면 맥락 값 말고는 LLM이 채운 것으로 둔다(자동 진행 없음)."""
    draft = proposal.draft

    def mark(fill: SlotFill | None) -> SlotFill | None:
        if fill is None or fill.method in (FillMethod.MAP, FillMethod.CONTEXT, FillMethod.USER):
            return fill
        return SlotFill(value=fill.value, method=FillMethod.LLM)

    slots = {name: mark(fill) for name, fill in draft.slots.items()}
    marked = draft.model_copy(
        update={"op": mark(draft.op), "intent": mark(draft.intent), "slots": {k: v for k, v in slots.items() if v}}
    )
    return Proposal(draft=ChangeDraft.model_validate(marked.model_dump()), issues=proposal.issues)
