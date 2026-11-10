"""확정 검증(순수 계산): 사람의 항목별 결정을 서버가 다시 검증해 연산 목록으로 만든다.

화면이 보낸 값을 그대로 믿지 않는다 — 항목 초안은 서버에 둔 제안에서 꺼내고, 고친 대상은 지도에 있어야 하며,
고친 대상의 지금 값(두께·강종·규격)은 지도에서 다시 읽는다. 그대로 '맞음'으로 확정할 수 없는 문제(BLOCKING)가 남은
항목, 정하지 않은 항목, 항목끼리 겹치는 변경은 이유와 함께 돌려준다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import ValidationError

from ripple.contracts.assistant import NUMBER_KINDS, ChangeDraft, FillMethod, SlotFill, SlotKind
from ripple.contracts.change import ChangeOp
from ripple.contracts.intake import (
    IntakeIssueCode,
    IntakeItem,
    IntakeProposal,
    ItemAction,
    ItemDecision,
    ItemProblem,
)
from ripple.nl.draft import retarget
from ripple.nl.vocab import MapVocabulary

from .checks import cross_problems, op_of, part_ids_of

_TARGET_FIXES = frozenset({IntakeIssueCode.TARGET_UNRESOLVED, IntakeIssueCode.TARGET_AMBIGUOUS})
_VALUE_FIXES = frozenset(
    {IntakeIssueCode.VALUE_MISSING, IntakeIssueCode.LLM_RULE_DISAGREE, IntakeIssueCode.VALUE_UNCERTAIN}
)
_CROSS = frozenset({IntakeIssueCode.DUPLICATE, IntakeIssueCode.CONFLICT})


@dataclass(slots=True)
class Confirmed:
    entries: list[tuple[str, ChangeOp]] = field(default_factory=list)  # (항목 ID, 연산), 문서 순서
    problems: list[ItemProblem] = field(default_factory=list)
    dropped: int = 0
    drafts: dict[str, ChangeDraft] = field(default_factory=dict)  # 확정한 항목의 최종 초안(수정 기록용)


def confirm(proposal: IntakeProposal, decisions: Sequence[ItemDecision], vocab: MapVocabulary) -> Confirmed:
    out = Confirmed()
    by_id = {d.item_id: d for d in decisions}
    items = {i.item_id: i for i in proposal.items}
    for unknown in sorted(set(by_id) - set(items)):
        out.problems.append(ItemProblem(item_id=unknown, message=f"제안에 없는 항목 · {unknown}"))
    for item in proposal.items:
        decision = by_id.get(item.item_id)
        if decision is None:
            out.problems.append(ItemProblem(item_id=item.item_id, message="맞음·고침·뺌 중 선택 필요"))
            continue
        if decision.action is ItemAction.DROP:
            out.dropped += 1
            continue
        if any(i.code is IntakeIssueCode.UNSUPPORTED_OP for i in item.issues):  # 비서로도 8종에 억지로 넣지 않는다
            message = "지원하지 않는 변경 · 분석 불가 — 빼기 필요"
            out.problems.append(ItemProblem(item_id=item.item_id, message=message))
            continue
        draft = _decided_draft(item, decision, vocab, out)
        if draft is None:
            continue
        op, reason = _assembled(draft)
        if op is None:
            out.problems.append(ItemProblem(item_id=item.item_id, message=reason))
            continue
        missing = [p for p in part_ids_of(op) if p not in vocab.parts]
        if missing:
            out.problems.append(ItemProblem(item_id=item.item_id, message=f"지도에 없는 부재 · {', '.join(missing)}"))
            continue
        out.entries.append((item.item_id, op))
        out.drafts[item.item_id] = draft
    for item_id, issues in cross_problems(out.entries).items():
        out.problems.extend(ItemProblem(item_id=item_id, message=i.message) for i in issues)
    if not out.entries and not out.problems:
        out.problems.append(ItemProblem(item_id=None, message="분석할 항목 없음(모두 뺌)"))
    return out


def _decided_draft(
    item: IntakeItem, decision: ItemDecision, vocab: MapVocabulary, out: Confirmed
) -> ChangeDraft | None:
    if decision.draft is not None:  # 비서가 완성한 초안: 항목 문제는 비서 대화에서 풀렸다(항목 사이 검사는 다시 한다)
        return _confirmed(decision.draft)
    if item.draft is None:
        out.problems.append(ItemProblem(item_id=item.item_id, message="비서로 넘겨 고치거나 빼기 필요"))
        return None
    draft = item.draft
    fixed: set[IntakeIssueCode] = set()
    fixed_slots: set[str] = set()
    if decision.action is ItemAction.EDIT:
        edited = _apply_edits(item, decision, vocab, out)
        if edited is None:
            return None
        draft, fixed, fixed_slots = edited
    remaining = [
        i
        for i in item.issues
        if i.blocking
        and i.code not in _CROSS
        and not (i.code in fixed and (i.slot is None or i.slot in fixed_slots or i.code in _TARGET_FIXES))
    ]
    if remaining:
        out.problems.append(ItemProblem(item_id=item.item_id, message=remaining[0].message))
        return None
    return _confirmed(draft)


def _apply_edits(
    item: IntakeItem, decision: ItemDecision, vocab: MapVocabulary, out: Confirmed
) -> tuple[ChangeDraft, set[IntakeIssueCode], set[str]] | None:
    draft = item.draft
    assert draft is not None
    specs = {s.name: s for s in draft.specs()}
    slots = dict(draft.slots)
    fixed: set[IntakeIssueCode] = set()
    fixed_slots: set[str] = set()
    if decision.part_ids is not None:
        target = next((s for s in specs.values() if s.calibrated and s.kind is SlotKind.PARTS), None)
        if target is None:
            out.problems.append(ItemProblem(item_id=item.item_id, message="이 변경의 대상은 비서에서 수정 필요"))
            return None
        unknown = [p for p in decision.part_ids if p not in vocab.parts]
        if unknown or not decision.part_ids:
            out.problems.append(ItemProblem(item_id=item.item_id, message=f"지도에 없는 부재 · {', '.join(unknown)}"))
            return None
        moved = retarget(draft, target.name, decision.part_ids, vocab)  # 지금 값은 지도에서 다시, 증감 값은 비움
        if moved.mixed:
            label = specs[moved.mixed[0]].label
            message = f"고른 부재들의 {label} — 지도에서 하나로 특정 불가(서로 다르거나 없음)"
            out.problems.append(ItemProblem(item_id=item.item_id, message=message))
            return None
        left = [name for name in moved.stale if name not in decision.values]
        if left:
            label = specs[left[0]].label
            message = f"{label} — 원래 대상의 지금 값 기준 증감 값 · 대상을 바꾸면 {label} 직접 입력 필요"
            out.problems.append(ItemProblem(item_id=item.item_id, message=message))
            return None
        slots = moved.slots
        fixed_slots |= {s.name for s in specs.values() if s.from_map}
        fixed |= _TARGET_FIXES | {IntakeIssueCode.VALUE_MISSING, IntakeIssueCode.FROM_MISMATCH}
        fixed_slots.add(target.name)
    for name, value in decision.values.items():
        spec = specs.get(name)
        if spec is None or spec.kind not in NUMBER_KINDS or spec.from_map:  # 지금 값은 지도에서만
            out.problems.append(
                ItemProblem(item_id=item.item_id, message=f"표에서 고칠 수 없는 칸 · {name} — 비서로 넘기기")
            )
            return None
        slots[name] = SlotFill(value=float(value), method=FillMethod.USER)
        fixed |= _VALUE_FIXES
        fixed_slots.add(name)
    try:
        updated = ChangeDraft.model_validate({**draft.model_dump(), "slots": slots})
    except ValueError as error:
        out.problems.append(ItemProblem(item_id=item.item_id, message=f"고친 값 오류 · {error}"[:300]))
        return None
    return updated, fixed, fixed_slots


def _assembled(draft: ChangeDraft) -> tuple[ChangeOp | None, str]:
    """초안 → 연산. 못 만들면 사람이 고칠 수 있는 이유: 빠진 칸 이름, 또는 연산 규칙 위반(예: 고른 부재의 지금 두께가
    바꿀 두께와 같음 — '빠진 칸'으로 잘못 안내하지 않게)."""
    missing = draft.missing()
    if missing:
        labels = {s.name: s.label for s in draft.specs()}
        names = ", ".join(labels.get(name, "변경 종류") for name in missing)
        return None, f"빈 칸 · {names}"
    op = op_of(draft)
    if op is not None:
        return op, ""
    try:
        draft.to_change(ecn_id="CHECK", title="check")
    except ValidationError as error:
        detail = str(error.errors()[0].get("msg", "")).removeprefix("Value error, ")
        return None, f"이 값으로 계산 불가 — {detail}"[:300]
    except ValueError as error:
        return None, f"이 값으로 계산 불가 — {error}"[:300]
    return None, "이 값으로 계산 불가"


def _confirmed(draft: ChangeDraft) -> ChangeDraft:
    """사람이 확정한 초안: 추정·AI 값은 사용자 확인이 된다(지도·규칙 값은 그대로)."""

    def promote(fill: SlotFill) -> SlotFill:
        if fill.method in (FillMethod.GUESS, FillMethod.LLM):
            return fill.model_copy(update={"method": FillMethod.USER})
        return fill

    update: dict[str, object] = {"slots": {k: promote(v) for k, v in draft.slots.items()}}
    if draft.op is not None:
        update["op"] = promote(draft.op)
    return draft.model_copy(update=update)
