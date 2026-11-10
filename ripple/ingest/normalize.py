"""엑셀 값 정규화: 머리글의 단위 해석과 양식 단위 배율, 날짜 표기, 코드 표기(docs/input.md(엑셀 양식) 2절).

모호한 값은 추측하지 않는다.
- 단위: 아는 단위만 배율을 정한다. 차원이 다르거나(길이 칸에 kg) 바꿀 수 없는 단위(EA·inch·%)면 배율 없음(None)으로
  돌려 그 열을 확인 필요로 한다.
- 날짜: 네 자리 연도 표기(2026-10-20 · 2026.10.20 · 2026. 10. 20. · 2026/10/20 · 20261020 · 2026년 10월 20일)와
  엑셀 날짜 숫자만 읽는다. 두 자리 연도나 월·일 순서를 정할 수 없는 표기(10/20/26)는 읽지 않고 그 칸을 짚는다.
- 코드: 공백·하이픈·밑줄·점과 대소문자만 무시한다(라벨·계약 값 그대로).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType

from openpyxl.utils.datetime import CALENDAR_WINDOWS_1900, from_excel

UNITS: Mapping[str, tuple[str, float]] = MappingProxyType(
    {
        # 단위 표기(정규화) → (차원, 차원 기준 단위로의 배율)
        "mm": ("length", 0.001),
        "cm": ("length", 0.01),
        "m": ("length", 1.0),
        "kg": ("mass", 0.001),
        "t": ("mass", 1.0),
        "ton": ("mass", 1.0),
        "톤": ("mass", 1.0),
        "원": ("money", 1.0),
        "krw": ("money", 1.0),
        "천원": ("money", 1e3),
        "만원": ("money", 1e4),
        "백만원": ("money", 1e6),
        "일": ("days", 1.0),
        "day": ("days", 1.0),
        "days": ("days", 1.0),
        "dn": ("dn", 1.0),
    }
)
"""바꿀 수 있는 단위. 양식 단위(template.Column.unit)도 이 표에 있어야 한다(검사로 확인)."""

OTHER_UNITS = frozenset(
    {"ea", "pcs", "개", "inch", "in", "ft", "lb", "lbs", "usd", "달러", "%", "주", "개월", "월", "년", "hr", "h"}
    | {"시간"}
)
"""단위로 알아보지만 바꾸지 않는 표기. 머리글에 있으면 그 열은 확인 필요."""

_TAIL = re.compile(r"^(?P<base>.*?)\s*(?:\((?P<a>[^()]+)\)|\[(?P<b>[^\[\]]+)\]|_(?P<c>[^_\s()\[\]]+))\s*$")
"""단위 꼬리: 괄호 · 대괄호 · 밑줄. 밑줄 꼬리에는 괄호가 없다
('STIFF_SP(m)'은 밑줄 꼬리 'SP(m)'이 아니라 괄호 꼬리 'm')."""
_SPACE_TAIL = re.compile(r"^(?P<base>.+?)\s+(?P<unit>\S+)$")
_DATE = re.compile(
    r"^(?P<y>\d{4})\s*(?P<sep>[-./])\s*(?P<m>\d{1,2})\s*(?P=sep)\s*(?P<d>\d{1,2})\.?"
    r"(?:(?:\s+|T)\d{1,2}:\d{2}(?::\d{2})?)?$"
)
_KOREAN = re.compile(r"^(?P<y>\d{4})\s*년\s*(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일$")
_COMPACT = re.compile(r"^(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})$")
_TWO_DIGIT = re.compile(r"^\d{1,2}[-./]\d{1,2}[-./]\d{2,4}$")
SERIAL_RANGE = (36526, 73051)  # 엑셀 날짜 숫자 2000-01-01 ~ 2099-12-31(1900 체계)
COMPACT_RANGE = (20000101, 20991231)  # 8자리 날짜 숫자
DATE_HINT = "날짜(예: 2026-10-20, 2026.10.20, 20261020, 2026년 10월 20일)"


def unit_token(text: str) -> str:
    return "".join(str(text).split()).casefold()


def split_unit(header: object) -> tuple[str, str | None]:
    """머리글 → (단위를 뺀 이름, 단위 표기). 괄호·대괄호·밑줄 꼬리나 띄어 쓴 마지막 낱말이 아는 단위일 때만 단위로 본다
    ('발주일(확인)'의 '확인'은 단위가 아니라 이름의 일부)."""
    text = " ".join(str(header).split())
    tail = _TAIL.match(text)
    if tail:
        token = unit_token(tail["a"] or tail["b"] or tail["c"] or "")
        bracketed = tail["c"] is None  # 한 글자 단위(t·m)는 괄호·대괄호 안에서만: 'PL_T'의 T는 두께 약어일 수 있다
        if (token in UNITS or token in OTHER_UNITS) and (bracketed or len(token) > 1):
            return tail["base"].strip(), token
    spaced = _SPACE_TAIL.match(text)
    if spaced:
        token = unit_token(spaced["unit"])
        if (token in UNITS or token in OTHER_UNITS) and len(token) > 1:
            return spaced["base"].strip(), token
    return text, None


def unit_factor(source: str | None, target: str) -> float | None:
    """원본 단위 → 양식 단위 배율. 양식에 단위가 없으면 원본도 없어야 1, 같은 차원끼리만, 그 밖은 None(확인 필요)."""
    if not target:
        return 1.0 if source is None else None
    wanted = UNITS.get(unit_token(target))
    if wanted is None:
        raise ValueError(f"양식 단위 '{target}'가 단위 표에 없음")
    if source is None:
        return None
    given = UNITS.get(unit_token(source))
    if given is None or given[0] != wanted[0]:
        return None
    return float(_decimal(given[1]) / _decimal(wanted[1]))  # 10의 거듭제곱 그대로(0.01 / 0.001 = 10)


def convert(value: float, factor: float) -> float:
    """배율을 곱한다. 셀 값(엑셀에 적힌 십진수)과 배율을 십진수로 정확히 곱한 뒤 마지막에 한 번만 부동소수로 바꾼다:
    0.0135 m × 1000 = 13.5 mm(부동소수 곱의 13.499999… 없음), 12,345,678,901.234천원 × 1000 = 12,345,678,901,234원
    (유효 숫자를 자르지 않음). 배율이 1이면 값을 건드리지 않는다."""
    if factor == 1.0:
        return value
    return float(_decimal(value) * _decimal(factor))


def _decimal(number: float) -> Decimal:
    """부동소수를 그 값을 다시 만드는 가장 짧은 십진수로(엑셀에 적힌 값). 정수는 그대로."""
    return Decimal(number) if isinstance(number, int) else Decimal(repr(float(number)))


def parse_date(value: object, epoch: datetime = CALENDAR_WINDOWS_1900) -> tuple[date | None, str | None]:
    """셀 값 → (날짜, 문제). 문제는 '…(으)로 읽기 실패'에 넣는 말."""
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    if isinstance(value, bool):
        return None, DATE_HINT
    if isinstance(value, (int, float)):
        number = float(value)
        if number.is_integer() and COMPACT_RANGE[0] <= number <= COMPACT_RANGE[1]:
            return _calendar(str(int(number))[:4], str(int(number))[4:6], str(int(number))[6:])
        if SERIAL_RANGE[0] <= number < SERIAL_RANGE[1] and epoch == CALENDAR_WINDOWS_1900:
            moment = from_excel(number, epoch)
            if isinstance(moment, datetime):
                return moment.date(), None
        return None, DATE_HINT
    text = str(value).strip()
    found = _DATE.match(text) or _COMPACT.match(text) or _KOREAN.match(text)
    if found:
        return _calendar(found["y"], found["m"], found["d"])
    if _TWO_DIGIT.match(text):
        return None, "네 자리 연도 날짜(예: 2026-10-20 — 두 자리 연도·월/일 순서가 모호한 표기는 읽기 제외)"
    return None, DATE_HINT


def _calendar(year: str, month: str, day: str) -> tuple[date | None, str | None]:
    try:
        return date(int(year), int(month), int(day)), None
    except ValueError:
        return None, "있는 날짜"


def code_key(text: object) -> str:
    """코드 비교 키: 공백·하이픈·밑줄·점·대소문자를 무시한다."""
    return re.sub(r"[\s\-_.]+", "", str(text)).casefold()


def header_key(text: object) -> str:
    """머리글·시트 이름 비교 키: 공백·하이픈·밑줄·점·빗금·가운뎃점·쌍점·대소문자를 무시한다('Part No.' = 'PART_NO')."""
    return re.sub(r"[\s\-_./·:]+", "", str(text)).casefold()
