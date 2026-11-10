"""부재 번호 읽기: 종류 단어 바로 뒤('판 7'·'판 3, 5번'·'스풀 4~5번')나 바로 앞('7번 판')의 번호와 목록·범위.

범위는 사이 번호까지 모두 펼친다. 거꾸로이거나 MAX_RANGE개를 넘는 범위는 양 끝만 남기지 않고
읽지 못한 표현(unread)으로 돌려 확인받는다. 값은 (번호 자리, 번호, 목록·범위의 한 항목인지) 목록이다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .text import Span, free

_NOT_ID = r"(?!\s?(?:mm|㎜|밀리|[tT](?![A-Za-z])|톤|kg|%|\.\d|으로|로|에서|→|->|>|만큼|장|개|매|ea))"
_RIGHT_FIRST = re.compile(r"\s?(?:#|No\.?\s?|NO\.?\s?)?(?P<n>\d{1,3})(?!\d)(?:\s?번)?" + _NOT_ID)
_RIGHT_MORE = re.compile(r"\s?(?P<sep>,|·|/|및|과|와|~|-)\s?(?:#)?(?P<n>\d{1,3})(?!\d)(?:\s?번)?" + _NOT_ID)
_LEFT = re.compile(r"(?P<list>(?:\d{1,3}\s?번?\s?(?:,|·|/|및|과|와|~)\s?)*\d{1,3})\s?번?\s?$")
MAX_RANGE = 30
"""번호 범위 하나로 가리킬 수 있는 부재 수(이 지도의 블록당 부재는 종류마다 18개 이하)."""
_RANGE_PROBLEM = f"번호 범위 역순 또는 과다(한 번에 {MAX_RANGE}개까지)"


def _range_middle(low: int, high: int) -> list[int] | None:
    """범위 'low~high'의 사이 번호. 거꾸로이거나 MAX_RANGE개를 넘으면 None(읽지 못한 표현)."""
    if high <= low or high - low + 1 > MAX_RANGE:
        return None
    return list(range(low + 1, high))


def numbers_after(
    text: str, pos: int, occupied: Sequence[Span], unread: list[tuple[Span, str]]
) -> list[tuple[Span, int, bool]]:
    first = _RIGHT_FIRST.match(text, pos)
    if not first or not free(first.span("n"), occupied):
        return []
    found = [(first.span("n"), int(first.group("n")), False)]
    end = first.end()
    while (more := _RIGHT_MORE.match(text, end)) and free(more.span("n"), occupied):
        number = int(more.group("n"))
        if more.group("sep") in ("~", "-"):
            low_span, low, _ = found[-1]
            middle = _range_middle(low, number)
            if middle is None:
                unread.append(((low_span[0], more.end("n")), _RANGE_PROBLEM))
                break
            found += [((first.start("n"), more.end("n")), n, True) for n in middle]
        found.append((more.span("n"), number, True))
        end = more.end()
    if len(found) > 1:
        found[0] = (found[0][0], found[0][1], True)
    return found


def numbers_before(
    text: str, pos: int, occupied: Sequence[Span], unread: list[tuple[Span, str]]
) -> list[tuple[Span, int, bool]]:
    match = _LEFT.search(text[:pos])
    if not match:
        return []
    offset = match.start("list")
    if offset and (text[offset - 1] in ".,-_~" or (text[offset - 1].isascii() and text[offset - 1].isalnum())):
        return []
    spans = [
        ((offset + m.start(), offset + m.end()), int(m.group(0))) for m in re.finditer(r"\d{1,3}", match.group("list"))
    ]
    if not all(free(span, occupied) for span, _ in spans):
        return []
    found: list[tuple[Span, int]] = []
    for span, number in spans:
        if found and "~" in text[found[-1][0][1] : span[0]]:
            low_span, low = found[-1]
            middle = _range_middle(low, number)
            if middle is None:
                unread.append(((low_span[0], span[1]), _RANGE_PROBLEM))
                break
            found += [((spans[0][0][0], span[1]), n) for n in middle]
        found.append((span, number))
    listed = len(found) > 1
    return [(span, n, listed) for span, n in found]
