"""문장 정규화: 길이를 바꾸지 않는 글자 치환만 해서 원문 위치를 그대로 쓴다. 문장 안 자리의 겹침 도우미도 둔다."""

from __future__ import annotations

from collections.abc import Iterable

_SINGLE: dict[int, str] = {code: chr(code - 0xFEE0) for code in range(0xFF01, 0xFF5F)}  # 전각 ASCII → 반각
_SINGLE.update({ord(ch): "-" for ch in "‐‑‒–—―−"})
_SINGLE.update({ord(ch): "→" for ch in "⟶➔➝➞⇒⟹"})
_SINGLE.update({ord(ch): "·" for ch in "・ㆍ‧∙"})
_SINGLE.update({ord(ch): "~" for ch in "～〜∼"})
_SINGLE.update({ord(ch): " " for ch in "　 \t\r\n"})
_TABLE = str.maketrans(_SINGLE)


def normalize(text: str) -> str:
    """전각 글자·대시·화살표·가운뎃점·물결·공백 변형을 한 글자씩 바꾼다(길이 그대로)."""
    out = text.translate(_TABLE)
    if len(out) != len(text):  # 치환표가 한 글자 → 한 글자임을 지킨다
        raise AssertionError("정규화로 문장 길이 바뀜")
    return out


def overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


Span = tuple[int, int]
"""문장 안 자리(시작, 끝)."""


def free(span: Span, taken: Iterable[Span]) -> bool:
    """span이 이미 잡힌 자리(taken) 어느 것과도 겹치지 않음."""
    return not any(overlaps(span, other) for other in taken)
