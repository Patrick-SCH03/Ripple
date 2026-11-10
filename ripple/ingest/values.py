"""셀 값 해석: 지정 양식의 열 종류(글자·정수·숫자·날짜·예/아니오·코드·목록)대로 셀 하나를 계약 값으로 읽는다.

숫자 열은 원본 단위 배율을 곱하고, 읽지 못하면 무엇으로 읽으려 했는지(문제 문구)를 돌려준다. 행 읽기(rows.py)와
열 판단의 값 모양 검사(file_columns.py)가 같이 쓴다.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, time

from .normalize import convert, header_key, parse_date
from .template import Column, Kind, code_value
from .workbook import ExcelError, Uncomputed

TRUE_WORDS = frozenset({"true", "y", "yes", "o", "예", "1"})
FALSE_WORDS = frozenset({"false", "n", "no", "x", "아니오", "0"})
LIST_SPLIT = re.compile(r"[,;\n]+")
NUMBER = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")  # 쉼표는 천 단위 묶음만(1,5는 거부)


def parse(
    column: Column, value: object, factor: float = 1.0, epoch: datetime | None = None
) -> tuple[object, str | None]:
    """셀 값 → (계약 값, 문제). 빈칸은 (None, None). 숫자 열은 원본 단위 배율을 곱한다."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, None
    if isinstance(value, Uncomputed):
        return None, f"수식({value.formula})의 계산값(엑셀에서 열어 저장한 값)"
    if isinstance(value, ExcelError):
        return None, f"값(엑셀 오류 {value.code})"
    kind = column.kind
    if kind in (Kind.TEXT, Kind.LIST) and isinstance(value, (date, time)):
        return None, "글자(엑셀이 날짜·시각으로 바꾼 값일 수 있음 — 칸 서식을 텍스트로 두고 다시 기입)"
    if kind is Kind.TEXT:
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return str(value).strip(), None
    if kind is Kind.INT:
        return _integer(column, value, factor)
    if kind is Kind.FLOAT:
        number = number_of(value)
        return (None, "숫자") if number is None else (convert(float(number), factor), None)
    if kind is Kind.DATE:
        return parse_date(value, epoch) if epoch is not None else parse_date(value)
    if kind is Kind.BOOL:
        return _boolean(value)
    if kind is Kind.CODE:
        code = code_value(column, str(value))
        return (None, " / ".join(column.codes.values())) if code is None else (code, None)
    return tuple(item.strip() for item in LIST_SPLIT.split(str(value)) if item.strip()), None


def _integer(column: Column, value: object, factor: float) -> tuple[object, str | None]:
    number = number_of(value)
    if number is None:
        return None, "정수"
    converted = convert(float(number), factor) if factor != 1.0 else number
    if not float(converted).is_integer():
        return None, "정수" if factor == 1.0 else f"정수({column.unit} 단위로 바꾸면 {amount_text(converted)})"
    return int(converted), None


def _boolean(value: object) -> tuple[object, str | None]:
    if isinstance(value, bool):
        return value, None
    if number_of(value) in (0, 1):  # 숫자 칸에 1.0·0.0(글자 '1.0' 포함)으로 저장된 예/아니오
        return number_of(value) == 1, None
    word = header_key(value)
    if word in TRUE_WORDS or word in FALSE_WORDS:
        return word in TRUE_WORDS, None
    return None, "예/아니오"


def amount_text(number: float) -> str:
    """문제 문구의 숫자: 정수는 천 단위 쉼표, 소수는 유효 숫자 6자리(지수 표기 없이 읽히게)."""
    if float(number).is_integer():
        return f"{int(number):,}"
    return f"{number:,.6g}"


def number_of(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    text = str(value).strip()
    return float(text.replace(",", "")) if NUMBER.match(text) else None
