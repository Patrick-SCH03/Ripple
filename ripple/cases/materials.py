"""합성 과거 사례 재료 다듬기: 변경 방향과 목적이 모순되는 재료 빼기, 묶음 안에서 제목을 늘 고유하게.

생성기는 연산과 목적(intent)을 따로 뽑아 '두께를 줄이는 강도 보강' 같은 짝이 나온다(생성기는 고치지 않는다).
현장 사람이 보면 어색하므로 과거 사례 재료에서만 뺀다. 남은 재료의 목적은 방향과 맞아 '같은 변경 목적'으로
비교해도 된다.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from collections.abc import Sequence

from ripple.contracts.change import ChangeIntent, ChangeRequest, DimensionChange, GradeChange, ThicknessChange

from .features import op_parts
from .library import StoredCase

GRADE_ORDER: tuple[str, ...] = ("A", "AH32", "AH36", "DH36", "EH36")
"""강종 높낮이(항복강도·인성 등급 순, 생성기 강종 목록과 같은 다섯). 목록 밖 강종은 높낮이를 판단하지 않는다."""


def contradiction(change: ChangeRequest) -> str | None:
    """변경 방향과 목적이 맞지 않으면 그 이유. 연산 하나씩 본다(생성 사례는 연산 하나).

    - 두께를 줄이거나 강종을 낮추는데 목적이 강도 보강·규칙·선급 요구 등 → 모순(줄이는 쪽 목적은 중량 조정뿐)
    - 치수를 늘리는데 목적이 중량 조정 → 모순
    목적을 적지 않았으면(사유 미정) 모순으로 보지 않는다.
    """
    intent = change.intent
    if intent is None:
        return None
    for op in change.ops:
        if isinstance(op, ThicknessChange) and op.to_mm < op.from_mm and intent is not ChangeIntent.WEIGHT:
            return "두께 감소인데 목적이 중량 조정 아님"
        if isinstance(op, GradeChange) and _lower(op.from_grade, op.to_grade) and intent is not ChangeIntent.WEIGHT:
            return "강종 하향인데 목적이 중량 조정 아님"
        if isinstance(op, DimensionChange) and op.to_value > op.from_value and intent is ChangeIntent.WEIGHT:
            return "치수 증가인데 목적이 중량 조정"
    return None


def _lower(before: str, after: str) -> bool:
    if before not in GRADE_ORDER or after not in GRADE_ORDER:
        return False
    return GRADE_ORDER.index(after) < GRADE_ORDER.index(before)


def _short(part_id: str) -> str:
    """'S-001:E21C-SPCS-002' → 'SPCS-002'(블록 코드 뒤 부재 번호)."""
    tail = part_id.split(":")[-1]
    return tail.split("-", 1)[1] if "-" in tail else tail


def unique_titles(cases: Sequence[StoredCase]) -> tuple[StoredCase, ...]:
    """묶음 안 제목을 고유하게: 블록 코드로 시작하지 않으면 앞에 붙이고, 그래도 같으면 바꾸는 부재 번호, 그래도 같으면
    사례 번호를 덧붙인다(사례 번호 순으로 결정적)."""
    titled = [(s, _with_block(s)) for s in cases]
    counts = Counter(title for _, title in titled)
    detailed = [(s, f"{title} · {_parts(s)}" if counts[title] > 1 and _parts(s) else title) for s, title in titled]
    counts = Counter(title for _, title in detailed)
    out: list[StoredCase] = []
    for stored, title in detailed:
        final = f"{title} · {stored.case.case_id}" if counts[title] > 1 else title
        out.append(dataclasses.replace(stored, case=stored.case.model_copy(update={"title": final[:200]})))
    return tuple(out)


def _with_block(stored: StoredCase) -> str:
    title = stored.case.title
    codes = sorted({b.split(":")[-1] for b in stored.features.blocks})
    if not codes or any(title.startswith(code) for code in codes):
        return title
    return f"{'·'.join(codes)} {title}"


def _parts(stored: StoredCase) -> str:
    if stored.request is None:
        return ""
    return "·".join(_short(p) for op in stored.request.change.ops for p in op_parts(op))
