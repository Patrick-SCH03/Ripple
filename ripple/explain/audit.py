"""E4 독립 검출기: 렌더링한 설명·알림의 숫자가 모두 수치 블록에서, 결과 필드 값으로 나왔는지.

렌더러와 따로 만든 검사다(문장 틀을 다시 쓰지 않고 숫자만 읽어 대조한다).
- 글 블록: 엔터티 이름을 뺀 글에 숫자·한글 수사·수량 표현이 없어야 한다.
- 수치 블록: 엔터티 이름을 뺀 글에서 읽은 금액(만원 반올림·원)·일수·개수·날짜가 모두 그 키의 결과 값과 맞아야 한다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date

from ripple.contracts.explain import METRICS, MetricUnit, RenderedText, quantity_expressions
from ripple.contracts.result import Amount, AnalysisResult, ZeroLossDeadline

from .format import man_units
from .metrics import metric_value

_DATE = re.compile(r"(\d{4})년 (\d{1,2})월 (\d{1,2})일")
_MONEY = re.compile(r"(?:(\d[\d,]*)억)?\s?(?:(\d[\d,]*)만)?(?=원|~|\))|(\d[\d,]*)(?=원)")
_DAYS = re.compile(r"(\d[\d,]*)일")
_COUNT = re.compile(r"(\d[\d,]*)개")


def audit(rendered: RenderedText, result: AnalysisResult, names: Mapping[str, str]) -> list[str]:
    """문제 목록(없으면 E4 통과)."""
    problems = []
    for index, block in enumerate(rendered.blocks):
        text = block.text
        for entity in block.entity_ids:
            text = text.replace(names.get(entity, entity), " ")
        if block.kind == "text":
            found = quantity_expressions(text)
            if found:
                problems.append(f"{index}: 글 블록에 숫자·수량 표현: {', '.join(found[:3])}")
            continue
        if block.metric is None or block.metric not in METRICS:
            problems.append(f"{index}: 수치 블록 키 없음")
            continue
        text = text.replace(METRICS[block.metric].label, " ")  # 고정 라벨('추가손실 0 마감일')의 글자는 값이 아님
        chosen = block.entity_ids[0] if block.entity_ids else None
        value = metric_value(result, block.metric, chosen)
        if value is None:
            problems.append(f"{index}: {block.metric} 값이 결과에 없음")
            continue
        wrong = _mismatches(text, METRICS[block.metric].unit, value)
        if wrong:
            problems.append(f"{index}: {block.metric} 숫자가 결과와 다름: {', '.join(wrong)}")
    return problems


def _mismatches(text: str, unit: MetricUnit, value: object) -> list[str]:
    """문장의 날짜 → (원 단위면) 금액 → 일수·건수 순으로 결과 값과 대조하고, 남은 숫자가 있으면 문제로 본다."""
    money, numbers, dates = _allowed(value)
    wrong, rest = _date_mismatches(text, dates)
    if unit is MetricUnit.KRW:
        rest = _money_mismatches(rest, money, wrong)
    for pattern in (_DAYS, _COUNT):
        for match in pattern.finditer(rest):
            if int(match.group(1).replace(",", "")) not in numbers:
                wrong.append(match.group(0))
            rest = rest.replace(match.group(0), " ", 1)
    leftovers = [ch for ch in rest if ch.isdigit()]
    if leftovers:
        wrong.append(f"남은 숫자 {''.join(leftovers)}")
    return wrong


def _allowed(value: object) -> tuple[set[int], set[int], set[date]]:
    """결과 값이 허용하는 금액(만원, 1만원 미만은 음수로 원 그대로) · 수 · 날짜."""
    money: set[int] = set()
    numbers: set[int] = set()
    dates: set[date] = set()
    if isinstance(value, Amount):
        for won in (value.value, value.low, value.high):
            money.add(man_units(abs(won)) if abs(won) >= 10_000 else -abs(won))
    elif isinstance(value, int):
        numbers.add(value)
    elif isinstance(value, ZeroLossDeadline):
        dates.add(value.last_day)
    elif isinstance(value, date):
        dates.add(value)
    return money, numbers, dates


def _date_mismatches(text: str, allowed: set[date]) -> tuple[list[str], str]:
    wrong: list[str] = []
    rest = text
    for match in _DATE.finditer(text):
        found = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if found not in allowed:
            wrong.append(match.group(0))
        rest = rest.replace(match.group(0), " ")
    return wrong, rest


def _money_mismatches(rest: str, allowed: set[int], wrong: list[str]) -> str:
    for match in _MONEY.finditer(rest):
        if match.group(3):
            amount = -int(match.group(3).replace(",", ""))  # 1만원 미만은 원 그대로
        elif match.group(1) or match.group(2):
            eok = int((match.group(1) or "0").replace(",", ""))
            man = int((match.group(2) or "0").replace(",", ""))
            amount = eok * 10_000 + man
        else:
            continue
        if amount not in allowed:
            wrong.append(match.group(0).strip())
        rest = rest.replace(match.group(0), " ", 1)
    return rest
