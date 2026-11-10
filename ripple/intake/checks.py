"""항목 사이 검사(순수 계산): 같은 변경 두 번, 같은 부재를 같은 성질로 두 번, 뺀 부재를 다른 항목이 가리킴.

엔진 요청 검증(engine/validate.py)이 문서 전체로 거절하는 경우를 확정 전에 항목 단위로 미리 보인다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ripple.contracts.assistant import ChangeDraft
from ripple.contracts.change import AddPart, ChangeOp, FieldChange, referenced_part_ids, removed_part_ids
from ripple.contracts.identity import canonical_json, normalized_op
from ripple.contracts.intake import IntakeIssue, IntakeIssueCode, IntakeItem
from ripple.explain.format import subject_particle


def op_of(draft: ChangeDraft | None) -> ChangeOp | None:
    """초안을 연산으로 조립한다(빠진 칸이 있거나 연산 계약에 어긋나면 None)."""
    if draft is None or draft.missing():
        return None
    try:
        return draft.to_change(ecn_id="CHECK", title="check").ops[0]
    except ValueError:
        return None


def cross_problems(entries: Sequence[tuple[str, ChangeOp]]) -> dict[str, list[IntakeIssue]]:
    """항목 ID → 다른 항목과 겹치는 문제. 먼저 나온 항목은 그대로 두고 뒤 항목에 붙인다."""
    out: dict[str, list[IntakeIssue]] = {}
    shapes: dict[bytes, str] = {}
    edited: dict[tuple[str, str], str] = {}
    removed: dict[str, str] = {}
    for item_id, op in entries:
        shape = canonical_json(normalized_op(op))
        if shape in shapes:
            hint = "수량을 합쳐 하나로 고치거나 하나 빼기" if isinstance(op, AddPart) else "하나 빼기"
            _add(
                out,
                item_id,
                IntakeIssueCode.DUPLICATE,
                f"{shapes[shape]}{_with(shapes[shape])} 같은 변경 — {hint}",
            )
            continue
        shapes[shape] = item_id
        if isinstance(op, FieldChange):
            for part_id in op.part_ids:
                key = (op.op, part_id)
                if key in edited:
                    _add(
                        out,
                        item_id,
                        IntakeIssueCode.CONFLICT,
                        f"{edited[key]}에서도 {part_id}의 같은 성질 변경",
                    )
                else:
                    edited[key] = item_id
        for part_id in removed_part_ids(op):
            removed.setdefault(part_id, item_id)
    for item_id, op in entries:
        for part_id in referenced_part_ids(op):
            if part_id in removed and removed[part_id] != item_id:
                _add(
                    out,
                    item_id,
                    IntakeIssueCode.CONFLICT,
                    f"이 항목이 {removed[part_id]}에서 빼는 {part_id} 참조",
                )
    return out


def with_cross_issues(items: Sequence[IntakeItem]) -> tuple[IntakeItem, ...]:
    """항목 사이 문제를 붙인다. 초안을 다 채우지 못한 항목(대상을 아직 못 정함)도 원문 조각이 같으면 '같은 변경'으로
    본다 — 연산으로 비교할 수 없어 놓치기 쉬운 경우."""
    entries = [(i.item_id, op) for i in items if (op := op_of(i.draft)) is not None]
    found = cross_problems(entries)
    texts: dict[str, str] = {}
    for item in items:
        key = re.sub(r"\s+", " ", item.source.text).strip()
        first = texts.setdefault(key, item.item_id)
        already = any(x.code is IntakeIssueCode.DUPLICATE for x in found.get(item.item_id, ()))
        if first != item.item_id and not already:
            _add(
                found,
                item.item_id,
                IntakeIssueCode.DUPLICATE,
                f"{first}{_with(first)} 같은 글 — 하나 빼기",
            )
    return tuple(
        item.model_copy(update={"issues": (*item.issues, *found[item.item_id])}) if item.item_id in found else item
        for item in items
    )


def part_ids_of(op: ChangeOp) -> tuple[str, ...]:
    """연산이 가리키는 기존 부재 전부(지도 존재 확인용)."""
    return (*removed_part_ids(op), *referenced_part_ids(op))


def _add(out: dict[str, list[IntakeIssue]], item_id: str, code: IntakeIssueCode, message: str) -> None:
    out.setdefault(item_id, []).append(IntakeIssue(code=code, message=message[:300]))


def _with(word: str) -> str:
    """과/와(받침 있으면 '과'): 받침 판단은 이/가와 같다."""
    return {"이": "과", "가": "와"}.get(subject_particle(word), "과(와)")
