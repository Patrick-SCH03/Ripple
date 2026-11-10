"""변경 초안 채우기(docs/input.md(판단 계층) 7절): 해석 + 판단 최상위 → 슬롯과 채움 방법, 확인할 것.

- 대상 부재(보정 슬롯)는 판단 계층의 최상위로 채운다(DECISION). '해당 없음'이면 비워 두고 다시 묻는다.
- 변경 전 값은 지도 현재값(MAP), 바꿀 값은 값 정규화(RULE, 모호하면 GUESS).
- 블록·규격·역할 부재는 결정적 일치(RULE)일 때만 채우고, 아니면 확인할 것(SlotIssue)으로 돌려준다.
슬롯 이름과 필수 여부는 ripple.contracts.assistant.OP_SLOTS를 따른다. 연산별 채우기는 fill_ops, 채우기 도구는
filler, 주고받는 값은 fill_types에 있다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ripple.contracts.assistant import NUMBER_KINDS, ChangeDraft, FillMethod, SlotFill

from .fill_ops import fill
from .fill_types import TEXT_ISSUE, SlotIssue, TargetPick
from .filler import Filler
from .interpret import Interpretation
from .vocab import MapVocabulary

__all__ = [
    "MAP_ATTRIBUTES",
    "RELATIVE_WORDS",
    "Proposal",
    "Retargeted",
    "build_draft",
    "retarget",
]


@dataclass(frozen=True, slots=True)
class Proposal:
    draft: ChangeDraft
    issues: tuple[SlotIssue, ...]

    @property
    def ready(self) -> bool:
        """자동 진행 자격(판단 밖): 초안 자격(빠진 슬롯·추정·LLM 없음)이고 확인할 것도 없음.

        문장에 적었는데 정하지 못한 선택 슬롯(관통 판·붙일 판)도 막는다. 보정 단위(policy.Unit.ready)와
        실행 라우터가 이 값 하나를 쓴다.
        """
        return self.draft.ready and not self.issues


def build_draft(
    interp: Interpretation,
    original: str,
    ship_ids: tuple[str, ...],
    op: SlotFill | None,
    intent: SlotFill | None,
    targets: Sequence[TargetPick],
    vocab: MapVocabulary,
) -> Proposal:
    """초안과 확인할 것. 원문(original)은 정규화 전 문장이다(위치는 같다)."""
    slots: dict[str, SlotFill] = {}
    issues: list[SlotIssue] = []
    if op is not None:
        fill(Filler(interp, original, ship_ids, vocab, slots, issues), str(op.value), targets)
    draft = ChangeDraft(text=original, ship_ids=ship_ids, op=op, intent=intent, slots=slots)
    if draft.ready and not issues:
        try:  # 자격이 있으면 조립도 반드시 된다(예: 바꿀 규격이 지금 규격과 같으면 연산 계약이 거부)
            draft.to_change(ecn_id="CHECK", title="check")
        except ValueError as error:
            issues.append(SlotIssue(slot=TEXT_ISSUE, reason=f"요청 조립 불가 · {_first_error(error)}"))
    return Proposal(draft=draft, issues=tuple(issues))


def _first_error(error: ValueError) -> str:
    errors = getattr(error, "errors", None)
    if callable(errors):
        found = errors()
        if found:
            message = str(found[0].get("msg", ""))
            return message.removeprefix("Value error, ")
    return str(error)


MAP_ATTRIBUTES: dict[str, str] = {"from_mm": "thickness_mm", "from_grade": "grade", "from_spec_id": "spec_id"}
"""지도에서 읽는 지금 값 슬롯 → 부재 속성."""
RELATIVE_WORDS = re.compile(r"증가|감소|늘|줄|올려|올리|내려|내리|올림|내림|증후|감후|키워|키우|%|퍼센트")
"""바꿀 값이 지금 값에 더하고 뺀(증감·비율) 표현이라는 단서."""


@dataclass(frozen=True, slots=True)
class Retargeted:
    slots: dict[str, SlotFill]
    stale: tuple[str, ...]  # 옛 대상의 지금 값에 기대어 계산해 다시 정해야 하는 바꿀 값 칸
    mixed: tuple[str, ...]  # 새 대상들의 지도 지금 값이 하나가 아니라 채울 수 없는 지금 값 칸


def retarget(draft: ChangeDraft, slot: str, part_ids: Sequence[str], vocab: MapVocabulary) -> Retargeted:
    """사람이 대상을 바꿨을 때(확인표 고침·비서 씨앗): 대상 칸을 바꾸고, 지금 값 칸은 새 대상의 지도 값으로 다시
    읽고, 지금 값에 기대어 증감·비율로 계산한 바꿀 값 칸은 비운다 — 옛 대상 기준 값이 그대로 남아 경고 없이 틀린 요청이
    되지 않게(예: '3mm 증가'를 17mm 판에서 15.5mm 판으로 바꾸면 20이 남는다)."""
    slots = dict(draft.slots)
    slots[slot] = SlotFill(value=tuple(sorted(set(part_ids))), method=FillMethod.USER)
    specs = draft.specs()
    mixed: list[str] = []
    for spec in specs:
        attribute = MAP_ATTRIBUTES.get(spec.name)
        if not spec.from_map or attribute is None:
            continue
        values = {getattr(vocab.parts[p].part, attribute) for p in part_ids if p in vocab.parts}
        value = next(iter(values)) if len(values) == 1 else None
        if isinstance(value, str) and value:
            slots[spec.name] = SlotFill(value=value, method=FillMethod.MAP)
        elif isinstance(value, int | float) and value > 0:
            slots[spec.name] = SlotFill(value=float(value), method=FillMethod.MAP)
        else:
            slots.pop(spec.name, None)
            mixed.append(spec.name)
    stale: list[str] = []
    if any(s.from_map and s.kind in NUMBER_KINDS for s in specs):
        for spec in specs:
            fill = slots.get(spec.name)
            if spec.from_map or spec.kind not in NUMBER_KINDS or fill is None or fill.span is None:
                continue
            near = draft.text[fill.span.start : fill.span.end + 6]  # 근거 위치('3mm')와 바로 뒤('증가')
            if fill.method in (FillMethod.RULE, FillMethod.GUESS, FillMethod.LLM) and RELATIVE_WORDS.search(near):
                slots.pop(spec.name)
                stale.append(spec.name)
    return Retargeted(slots, tuple(stale), tuple(mixed))
