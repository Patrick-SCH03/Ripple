"""값 정규화(docs/input.md(판단 계층) 7절). 결정적이고 LLM을 쓰지 않는다.

1. 추출(value_exprs.py): 참조(부재 번호·코드·규격)가 차지한 자리를 뺀 숫자에서 값 표현을 찾는다.
   - 전후: '15→17', '15에서 17로', '15T를 17T로' / 변경 전 + 증감: '3200에서 400 줄여'
   - 증감: '+2', '2mm 증가', '1mm 얇게'(방향 단어) / 비율: '10% 늘려'
   - 절대: '17mm로'(목표 표시 '로·으로·까지'), '두께 17'
2. 정규화: 연산과 대상이 정해지면 슬롯 값을 만든다. 변경 전 값은 지도 현재값이 있으면 그것이고,
   증감은 현재값 + 증감, 비율은 현재값 × (1 ± 비율)이다('15에서 16.5로' ≡ '1.5 올림' ≡ '16.5mm로').
   표현이 모호하거나 지도와 맞지 않으면 추정(GUESS)으로 내고 이유를 붙인다 — 확인 카드로 간다.
값 표현 추출의 이름(Form·ValueExpr·extract_values)은 value_exprs에 있다.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from typing import Literal

from .text import overlaps
from .value_exprs import ARROW, FROM_JOIN, OBJECT_JOIN, TARGET_MARK, Form, Num, ValueExpr

__all__ = [
    "OUT_OF_RANGE",
    "PLAUSIBLE",
    "Certainty",
    "GradeToken",
    "Measure",
    "Normalized",
    "NormalizedText",
    "find_grades",
    "normalize_grade",
    "normalize_measure",
    "split_usable",
]
Measure = Literal["thickness", "length", "diameter", "mass"]
"""값의 종류. 단위 해석이 다르다: 두께의 t는 mm, 질량의 t는 톤."""

PLAUSIBLE: dict[Measure, tuple[float, float]] = {
    "thickness": (4.0, 60.0),
    "length": (10.0, 30000.0),
    "diameter": (10.0, 2000.0),
    "mass": (0.001, 500.0),
}
"""값으로 받아들이는 범위(mm·t). 밖이면 증감을 절대값으로 잘못 읽었을 수 있어 추정으로 본다."""

OUT_OF_RANGE = "통상 범위"
"""범위 밖 추정의 이유 문구에 든 말. 문서 접수는 이 추정을 '맞음'으로 넘기지 않는다(날짜 '2026'을 두께로 읽는 일)."""

_UNITS: dict[Measure, dict[str | None, float]] = {
    "thickness": {None: 1.0, "mm": 1.0, "t": 1.0},  # 현장 표기 15T = 15mm 두께
    "length": {None: 1.0, "mm": 1.0, "m": 1000.0},
    "diameter": {None: 1.0, "mm": 1.0},
    "mass": {None: 1.0, "t": 1.0, "kg": 0.001},
}

_EPS = 1e-9


class Certainty(StrEnum):
    RULE = "rule"  # 결정적
    GUESS = "guess"  # 추정(확인 필요)


@dataclass(frozen=True, slots=True)
class Normalized:
    """정규화한 전·후 값. after가 없으면 값을 못 정한 것(되묻기)."""

    before: float | None
    before_from_map: bool
    after: float | None
    certainty: Certainty | None  # 값이 없으면 None
    reason: str | None = None  # 추정·없음의 이유(명사형)
    span: tuple[int, int] | None = None  # 근거 조각
    map_mismatch: bool = False  # 문장에 적은 지금 값이 지도 현재값과 다름(문서 접수의 문제 표시)


_RANK = {Form.FROM_TO: 0, Form.FROM_DELTA: 0, Form.ABSOLUTE: 1, Form.DELTA: 2, Form.RATIO: 3}
_RATIO_TOLERANCE = 0.01
"""비율은 '약 18.9%'처럼 어림값이라 같이 적은 바꿀 값과 1% 안이면 맞는 것으로 본다."""


def normalize_measure(exprs: Sequence[ValueExpr], measure: Measure, current: float | None) -> Normalized:
    """연산의 전·후 값 하나를 정한다. current는 지도 현재값(없으면 None: 치수처럼 지도에 없는 값).

    변경 전 값은 지도 현재값, 없으면 문장에 적은 변경 전 값('3200에서')이다. 바꿀 값은 전후 > 목표 표시
    절대 > 증감 > 표시 없는 절대 > 비율 순으로 고르고, 쓸 수 있는 표현끼리 바꿀 값이 다르면('16 또는 17로')
    추정이다. 비율은 같이 적은 바꿀 값과 1% 안이면 맞는 것으로 본다.
    """
    units = _UNITS[measure]
    usable = [e for e in exprs if _units_ok(e, units, measure)]
    stated_values = sorted({_scaled(e.first, units) for e in usable if e.form in _STATES_BEFORE})
    stated = stated_values[0] if stated_values else None
    targets = [e for e in usable if e.form is not Form.FROM]
    if not targets:
        reason = "바꿀 값 없음" if stated is not None else "값 없음"
        before = current if current is not None else stated
        return Normalized(before, current is not None, None, None, reason)
    ranked = sorted(targets, key=lambda e: (_RANK[e.form], not e.marked, e.span))
    results = [(e, _apply(e, units, measure, current, stated)) for e in ranked]
    result = results[0][1]
    exact = {r.after for e, r in results if r.after is not None and e.form is not Form.RATIO}
    approx = [r.after for e, r in results if r.after is not None and e.form is Form.RATIO]
    if len(stated_values) > 1:
        return _guess(result, "변경 전 값 여럿")
    if len(exact) > 1:
        return _guess(result, "값 표현 여럿")
    if exact and any(abs(a - next(iter(exact))) > _RATIO_TOLERANCE * abs(next(iter(exact))) for a in approx):
        return _guess(result, "비율과 바꿀 값 불일치")
    if not exact and approx and max(approx) - min(approx) > _RATIO_TOLERANCE * abs(min(approx)):
        return _guess(result, "비율 표현 여럿")
    return result


_STATES_BEFORE = frozenset({Form.FROM, Form.FROM_TO, Form.FROM_DELTA})


def split_usable(exprs: Sequence[ValueExpr], measure: Measure) -> tuple[tuple[ValueExpr, ...], tuple[ValueExpr, ...]]:
    """값 종류에 단위가 맞는 표현과 맞지 않는 표현(예: 두께 연산의 '200kg')."""
    units = _UNITS[measure]
    usable = tuple(e for e in exprs if _units_ok(e, units, measure))
    return usable, tuple(e for e in exprs if e not in usable)


def _scaled(num: Num, units: dict[str | None, float]) -> float:
    return num.value * units[num.unit]


def _units_ok(expr: ValueExpr, units: dict[str | None, float], measure: Measure) -> bool:
    if expr.form is Form.RATIO:
        return measure == "length" or measure == "thickness"
    return all(n.unit in units for n in (expr.first, expr.second) if n is not None)


def _apply(
    expr: ValueExpr,
    units: dict[str | None, float],
    measure: Measure,
    current: float | None,
    stated: float | None,
) -> Normalized:
    """표현 하나로 바꿀 값을 낸다. stated는 문장의 다른 곳에 적은 변경 전 값('3200에서')."""
    span = expr.span
    if expr.form in (Form.FROM_TO, Form.FROM_DELTA):
        stated = _scaled(expr.first, units)
    before = current if current is not None else stated

    def done(after: float | None, reason: str | None = None) -> Normalized:
        from_map = current is not None
        if after is None:
            return Normalized(before, from_map, None, None, reason, span)
        if after <= 0:  # 줄이는 양이 지금 값보다 크다: 제안할 값이 없다
            return Normalized(before, from_map, None, None, "바꿀 값이 0 이하", span)
        if (
            reason is None
            and current is not None
            and stated is not None
            and not math.isclose(stated, current, abs_tol=_EPS)
        ):
            reason = f"지금 값이 지도({_fmt(current)})와 문장({_fmt(stated)})에서 다름"
        certainty = Certainty.GUESS if reason else Certainty.RULE
        mismatch = current is not None and stated is not None and not math.isclose(stated, current, abs_tol=_EPS)
        result = Normalized(before, from_map, _round(after), certainty, reason, span, mismatch)
        return result if reason else _checked(result, expr, measure)

    if expr.form is Form.FROM_TO:
        assert expr.second is not None
        return done(_scaled(expr.second, units))
    if expr.form is Form.FROM_DELTA:
        assert expr.second is not None and stated is not None
        if not expr.direction:
            return done(None, "증감 방향 불명")
        return done(stated + expr.direction * _scaled(expr.second, units))
    if expr.form in (Form.DELTA, Form.RATIO):
        base = current if current is not None else stated
        if base is None:
            return done(None, "지금 값 불명 · 바꿀 값 특정 불가")
        if not expr.direction:
            return done(None, "증감 방향 불명")
        amount = expr.first.value / 100 * base if expr.form is Form.RATIO else _scaled(expr.first, units)
        return done(base + expr.direction * amount)
    return done(*_absolute_after(expr, units, measure, before))


def _absolute_after(
    expr: ValueExpr, units: dict[str | None, float], measure: Measure, before: float | None
) -> tuple[float, str | None]:
    value = _scaled(expr.first, units)
    low, high = PLAUSIBLE[measure]
    if not expr.marked and not low <= value <= high and before is not None and low <= before + value <= high:
        return before + value, f"{_fmt(value)}로 변경인지 {_fmt(value)} 증가인지 모호"
    return value, None


def _checked(result: Normalized, expr: ValueExpr, measure: Measure) -> Normalized:
    """결정적으로 정한 값의 성질 확인: 범위 안, 방향 단어와 맞음, 전·후가 다름."""
    after, before = result.after, result.before
    assert after is not None
    low, high = PLAUSIBLE[measure]
    if not low <= after <= high:
        return _guess(result, f"바꿀 값 {_fmt(after)} — {OUT_OF_RANGE}({_fmt(low)}~{_fmt(high)}) 밖")
    if before is not None and math.isclose(after, before, abs_tol=_EPS):
        return _guess(result, "변경 전과 후가 같음")
    if before is not None and expr.direction and (after - before) * expr.direction < 0:
        return _guess(result, "증감 표현과 값의 방향 불일치")
    return result


def _guess(result: Normalized, reason: str) -> Normalized:
    if result.after is None:
        return result
    return Normalized(
        result.before, result.before_from_map, result.after, Certainty.GUESS, reason, result.span, result.map_mismatch
    )


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def _fmt(value: float) -> str:
    return f"{value:g}"


# ---------- 강종 ----------


@dataclass(frozen=True, slots=True)
class GradeToken:
    start: int
    end: int
    grade: str


def find_grades(text: str, grades: Sequence[str], occupied: Sequence[tuple[int, int]] = ()) -> list[GradeToken]:
    """강종 표기('EH36'·'eh-36'·'EH 36', 한 글자 강종은 'A급'·'강종 A'일 때만)."""
    found: list[GradeToken] = []
    for grade in sorted(grades, key=len, reverse=True):
        letters = re.match(r"[A-Za-z]+", grade)
        head = letters.group(0) if letters else grade
        tail = grade[len(head) :]
        if tail:
            pattern = rf"(?<![A-Za-z0-9]){re.escape(head)}[\s\-]?{re.escape(tail)}(?![A-Za-z0-9])"
        else:
            after_word = (
                rf"(?:(?<=강종\s)|(?<=강종)|(?<=재질\s)|(?<=재질))(?<![A-Za-z]){re.escape(head)}(?![A-Za-z0-9])"
            )
            before_suffix = (
                rf"(?<![A-Za-z0-9]){re.escape(head)}(?=\s?(?:급|등급|강재|강)|\s?(?:으로|로)(?![가-힣]{{2}}))"
            )
            after_arrow = rf"(?:(?<=→)|(?<=→\s)|(?<=->)|(?<=->\s)){re.escape(head)}(?![A-Za-z0-9])"
            pattern = f"{after_word}|{before_suffix}|{after_arrow}"
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            span = (match.start(), match.end())
            if any(overlaps(span, other) for other in occupied) or any(overlaps(span, (g.start, g.end)) for g in found):
                continue
            found.append(GradeToken(span[0], span[1], grade))
    return sorted(found, key=lambda g: g.start)


@dataclass(frozen=True, slots=True)
class NormalizedText:
    """강종·규격처럼 글자로 된 값의 전·후."""

    before: str | None
    before_from_map: bool
    after: str | None
    certainty: Certainty | None
    reason: str | None = None
    span: tuple[int, int] | None = None
    map_mismatch: bool = False  # 문장에 적은 지금 강종이 지도와 다름


def normalize_grade(text: str, tokens: Sequence[GradeToken], current: str | None) -> NormalizedText:
    """'AH36→EH36'·'AH36에서 EH36으로'는 전후, 'EH36으로'는 바꿀 강종. 지도 현재값과 맞춰 본다."""
    for a, b in pairwise(tokens):
        between = text[a.end : b.start]
        if (
            ARROW.fullmatch(between)
            or FROM_JOIN.fullmatch(between)
            or (OBJECT_JOIN.fullmatch(between) and TARGET_MARK.match(text, b.end))
        ):
            span = (a.start, b.end)
            if current is not None and a.grade != current:
                reason = f"지금 강종이 지도({current})와 문장({a.grade})에서 다름"
                return NormalizedText(current, True, b.grade, Certainty.GUESS, reason, span, map_mismatch=True)
            if a.grade == b.grade:
                return NormalizedText(a.grade, False, b.grade, Certainty.GUESS, "변경 전과 후가 같음", span)
            return NormalizedText(current or a.grade, current is not None, b.grade, Certainty.RULE, None, span)
    distinct = sorted({t.grade for t in tokens if t.grade != current})
    if not tokens:
        return NormalizedText(current, current is not None, None, None, "바꿀 강종 없음")
    if len(distinct) == 1:
        token = next(t for t in tokens if t.grade == distinct[0])
        return NormalizedText(current, current is not None, token.grade, Certainty.RULE, None, (token.start, token.end))
    if not distinct:
        token = tokens[0]
        return NormalizedText(
            current, True, None, None, f"지금 강종({current})과 같은 강종만 있음", (token.start, token.end)
        )
    first = next(t for t in tokens if t.grade == distinct[0])
    return NormalizedText(
        current, current is not None, first.grade, Certainty.GUESS, "강종 여럿", (first.start, first.end)
    )
