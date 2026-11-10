"""값 표현 추출(docs/input.md(판단 계층) 7절): 참조(부재 번호·코드·규격)가 차지한 자리를 뺀 숫자에서 값 표현을 찾는다.

- 전후: '15→17', '15에서 17로', '15T를 17T로' / 변경 전 + 증감: '3200에서 400 줄여'
- 증감: '+2', '2mm 증가', '1mm 얇게'(방향 단어) / 비율: '10% 늘려'
- 절대: '17mm로'(목표 표시 '로·으로·까지'), '두께 17'
정규화(연산·대상이 정해진 뒤의 슬롯 값)는 values.py에 있다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from .text import overlaps

_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_.\-/#~])"
    r"(?P<sign>[+\-±])?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s?(?P<unit>mm|㎜|밀리|kg|㎏|킬로|톤|ton|m|t|T|%|퍼센트|프로))?"
    r"(?![A-Za-z0-9]|\.[A-Za-z0-9])"
)
_UNIT_NAMES = {
    "㎜": "mm",
    "밀리": "mm",
    "㎏": "kg",
    "킬로": "kg",
    "톤": "t",
    "ton": "t",
    "T": "t",
    "퍼센트": "%",
    "프로": "%",
}
ARROW = re.compile(r"\s*(?:→|->|=>|>)\s*")
"""두 값(또는 강종) 사이의 화살표."""
FROM_JOIN = re.compile(r"\s*(?:에서|부터)\s*")
"""두 값 사이의 '에서·부터'."""
OBJECT_JOIN = re.compile(r"\s*(?:을|를)\s*")
"""두 값 사이의 '을·를'('15T를 17T로')."""
TARGET_MARK = re.compile(r"\s*(?:으로|로|까지)")
"""값 뒤의 목표 표시."""
_FROM_MARK = re.compile(r"\s*(?:에서|부터)")
_FILLERS = re.compile(r"(?:\s*(?:만큼|정도|더|씩))*\s*")


@dataclass(frozen=True, slots=True)
class Num:
    start: int
    end: int
    value: float
    unit: str | None  # mm·m·t·kg·% 또는 없음
    sign: int  # 숫자 앞 +(1)·−(−1) 기호, 없으면 0


class Form(StrEnum):
    FROM = "from"  # 변경 전 값만('3200에서' 뒤에 비율·증감·바꿀 값이 따로 옴)
    ABSOLUTE = "absolute"  # 바꿀 값
    FROM_TO = "from_to"  # 변경 전 → 후
    FROM_DELTA = "from_delta"  # 변경 전 + 증감
    DELTA = "delta"  # 증감
    RATIO = "ratio"  # 비율 증감(%)


@dataclass(frozen=True, slots=True)
class ValueExpr:
    form: Form
    first: Num  # 절대: 그 값, 전후·전+증감: 변경 전, 증감·비율: 변화량
    second: Num | None = None  # 전후: 변경 후, 전+증감: 변화량
    direction: int = 0  # 방향 단어(+1 올림, −1 내림, 0 없음)
    marked: bool = False  # '로·으로·까지'로 목표값임을 밝힘

    @property
    def span(self) -> tuple[int, int]:
        end = self.second.end if self.second is not None else self.first.end
        return (self.first.start, end)


def numbers(text: str, occupied: Sequence[tuple[int, int]] = ()) -> list[Num]:
    found = []
    for match in _NUMBER.finditer(text):
        span = (match.start(), match.end())
        if any(overlaps(span, other) for other in occupied):
            continue
        raw_unit = match.group("unit")
        unit = _UNIT_NAMES.get(raw_unit, raw_unit) if raw_unit else None
        sign = {"+": 1, "-": -1}.get(match.group("sign") or "", 0)
        found.append(Num(span[0], span[1], float(match.group("num").replace(",", "")), unit, sign))
    return found


def extract_values(
    text: str,
    increase: Sequence[str],
    decrease: Sequence[str],
    occupied: Sequence[tuple[int, int]] = (),
) -> tuple[ValueExpr, ...]:
    """값 표현 목록(원문 순서). 방향 단어는 사전의 올림·내림 표현이다."""
    nums = numbers(text, occupied)
    words = sorted(((w, 1) for w in increase), key=lambda x: -len(x[0])) + sorted(
        ((w, -1) for w in decrease), key=lambda x: -len(x[0])
    )
    words.sort(key=lambda x: -len(x[0]))
    exprs, used = _paired_values(text, nums, words)
    for i, num in enumerate(nums):
        if i in used:
            continue
        marked = bool(TARGET_MARK.match(text, num.end))
        direction = _direction_after(text, _mark_end(text, num.end) if marked else num.end, words)
        if num.unit != "%" and not num.sign and _FROM_MARK.match(text, num.end):
            exprs.append(ValueExpr(Form.FROM, num))
        elif num.unit == "%":
            exprs.append(ValueExpr(Form.RATIO, num, direction=direction or num.sign))
        elif num.sign:
            exprs.append(ValueExpr(Form.DELTA, num, direction=num.sign))
        elif marked:
            exprs.append(ValueExpr(Form.ABSOLUTE, num, direction=direction, marked=True))
        elif direction:
            exprs.append(ValueExpr(Form.DELTA, num, direction=direction))
        else:
            exprs.append(ValueExpr(Form.ABSOLUTE, num))
    return tuple(sorted(exprs, key=lambda e: e.span))


def _paired_values(text: str, nums: list[Num], words: list[tuple[str, int]]) -> tuple[list[ValueExpr], set[int]]:
    exprs: list[ValueExpr] = []
    used: set[int] = set()
    for i, (a, b) in enumerate(pairwise(nums)):
        if i in used:
            continue
        between = text[a.end : b.start]
        if b.unit == "%":
            continue  # '3200에서 10% 줄여'는 변경 전 + 비율로 따로 읽는다
        marked = bool(TARGET_MARK.match(text, b.end))
        after_b = _direction_after(text, b.end, words)
        if ARROW.fullmatch(between) or (FROM_JOIN.fullmatch(between) and not (after_b and not marked)):
            exprs.append(ValueExpr(Form.FROM_TO, a, b, direction=_direction_after(text, _mark_end(text, b.end), words)))
        elif FROM_JOIN.fullmatch(between) and after_b:
            exprs.append(ValueExpr(Form.FROM_DELTA, a, b, direction=after_b))
        elif OBJECT_JOIN.fullmatch(between) and marked:
            exprs.append(ValueExpr(Form.FROM_TO, a, b, direction=_direction_after(text, _mark_end(text, b.end), words)))
        else:
            continue
        used.update({i, i + 1})
    return exprs, used


def _mark_end(text: str, pos: int) -> int:
    match = TARGET_MARK.match(text, pos)
    return match.end() if match else pos


def _direction_after(text: str, pos: int, words: Sequence[tuple[str, int]]) -> int:
    """pos 바로 뒤(채움말 '만큼·정도·더·씩' 건너뜀)의 방향 단어: +1·−1·0."""
    filler = _FILLERS.match(text, pos)
    start = filler.end() if filler else pos
    rest = text[start : start + 12]
    for word, sign in words:
        if rest.startswith(word):
            return sign
    return 0
