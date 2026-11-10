"""확인표 항목의 문제 달기(순수 계산, docs/input.md(문서 접수)): 해석기의 확인할 것 → 항목 문제, 빠진 칸, AI가 읽은
칸, 지도와 다른 도면 개정. 같은 칸의 같은 문제는 하나로 합친다."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from ripple.contracts.assistant import NUMBER_KINDS, ChangeDraft, FillMethod, SlotSpec
from ripple.contracts.intake import IntakeIssue, IntakeIssueCode, TargetCandidate
from ripple.nl.draft import Proposal
from ripple.nl.fill_types import TEXT_ISSUE
from ripple.nl.values import OUT_OF_RANGE

_DRAWING_REV = re.compile(r"\b([A-Z][A-Z0-9]*(?:-[A-Z0-9]+){1,4})\s*(?:@|Rev\.?\s*|개정\s*)([A-Z0-9]{1,3})\b")


def slot_issues(proposal: Proposal, draft: ChangeDraft, candidates: Sequence[TargetCandidate]) -> list[IntakeIssue]:
    specs = {s.name: s for s in draft.specs()}
    targets = {s.name for s in specs.values() if s.calibrated}
    issues: list[IntakeIssue] = []
    for found in proposal.issues:
        if found.slot == TEXT_ISSUE:
            issues.append(issue(IntakeIssueCode.TEXT_LEFTOVER, found.reason))
        elif found.map_mismatch:
            issues.append(issue(IntakeIssueCode.FROM_MISMATCH, f"{found.reason} — 확정하면 지도 값 사용", found.slot))
        elif found.slot in targets:
            issues.append(_target_issue(found.slot, specs[found.slot], candidates, found.reason))
        elif found.slot in draft.slots and draft.slots[found.slot].method is FillMethod.GUESS:
            if OUT_OF_RANGE in found.reason:  # 범위 밖 추정('2026-10-21'의 2026을 두께로)은 고치거나 빼야 확정
                message = f"{found.reason} — 값 수정 필요"
                issues.append(issue(IntakeIssueCode.VALUE_MISSING, message, found.slot))
            else:
                issues.append(issue(IntakeIssueCode.VALUE_UNCERTAIN, found.reason, found.slot))
        else:
            issues.append(_missing(specs.get(found.slot), found.slot, found.reason))
    for name in draft.missing():
        if name == "op":
            issues.append(issue(IntakeIssueCode.UNREADABLE, "변경 종류 읽기 실패 — 빼거나 비서로 넘기기"))
        elif name in targets:
            issues.append(_target_issue(name, specs[name], candidates, None))
        else:
            issues.append(_missing(specs.get(name), name, None))
    for name, fill in draft.slots.items():
        if fill.method is FillMethod.LLM:
            label = specs[name].label
            message = f"{label} — AI가 읽은 값 · 원문과 맞는지 확인 필요"
            issues.append(issue(IntakeIssueCode.VALUE_UNCERTAIN, message, name))
    return issues


def _target_issue(slot: str, spec: SlotSpec, candidates: Sequence[TargetCandidate], reason: str | None) -> IntakeIssue:
    if len(candidates) > 1:
        return issue(IntakeIssueCode.TARGET_AMBIGUOUS, f"{spec.label} 후보 여럿 — 후보에서 선택", slot)
    return issue(
        IntakeIssueCode.TARGET_UNRESOLVED,
        reason or f"지도에 {spec.label} 없음 — 직접 선택",
        slot,
    )


def _missing(spec: SlotSpec | None, slot: str, reason: str | None) -> IntakeIssue:
    label = spec.label if spec is not None else slot
    if spec is not None and spec.from_map:
        return issue(IntakeIssueCode.VALUE_MISSING, f"{label} — 대상 선택 시 지도 값으로 채워짐", slot)
    inline = spec is not None and spec.kind in NUMBER_KINDS
    tail = "값 입력 필요" if inline else "비서로 넘겨 정하기"
    return issue(IntakeIssueCode.VALUE_MISSING, f"{reason or f'{label} 미정'} — {tail}", slot)


def revision_issues(text: str, drawings: Mapping[str, frozenset[str]]) -> list[IntakeIssue]:
    """조각에 적힌 '도면번호 Rev.X'가 지도의 그 도면 개정과 다르면 알린다(정보 — 미반영 설계변경 의심)."""
    issues = []
    for match in _DRAWING_REV.finditer(text):
        number, revision = match.group(1), match.group(2).upper()
        known = drawings.get(number)
        if known and revision not in known:
            have = ", ".join(sorted(known))
            issues.append(
                issue(
                    IntakeIssueCode.REVISION_MISMATCH,
                    f"문서는 {number} 개정 {revision}, 지도는 개정 {have} — 지도가 최신인지 확인 필요",
                )
            )
    return issues


def issue(code: IntakeIssueCode, message: str, slot: str | None = None) -> IntakeIssue:
    return IntakeIssue(code=code, message=message[:300], slot=slot)


def dedupe(issues: Sequence[IntakeIssue]) -> tuple[IntakeIssue, ...]:
    """같은 칸의 같은 문제는 처음 것 하나만(칸이 없는 문제는 문장까지 같을 때만 합친다)."""
    seen: set[tuple[IntakeIssueCode, str | None, str]] = set()
    out = []
    for found in issues:
        key = (found.code, found.slot, "" if found.slot is not None else found.message)
        if key not in seen:
            seen.add(key)
            out.append(found)
    return tuple(out)
