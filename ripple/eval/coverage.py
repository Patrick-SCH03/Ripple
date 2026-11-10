"""관문 사례의 빠짐·겹침 확인: 관문은 사례 입력 폴더의 사례 전부를 한 번씩 채점했을 때만 판정한다."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable


def coverage_problems(scored: Iterable[str], required: Iterable[str]) -> tuple[str, ...]:
    """채점한 사례 ID와 필수 사례 ID를 비교한 문제 목록(빈 목록이면 빠짐·겹침·모르는 사례가 없음)."""
    counts = Counter(scored)
    needed = set(required)
    problems: list[str] = []
    missing = sorted(needed - counts.keys())
    if missing:
        problems.append(f"채점하지 않은 사례(없거나 검토·승인 전): {', '.join(missing)}")
    twice = sorted(case_id for case_id, n in counts.items() if n > 1)
    if twice:
        problems.append(f"두 번 채점한 사례: {', '.join(twice)}")
    unknown = sorted(counts.keys() - needed)
    if unknown:
        problems.append(f"사례 입력에 없는 사례: {', '.join(unknown)}")
    if not needed:
        problems.append("필수 사례 목록이 비어 있어요")
    return tuple(problems)
