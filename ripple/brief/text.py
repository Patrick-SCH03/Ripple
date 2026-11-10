"""결정 도우미 문장의 표기: 금액·날짜·코드·조사(화면 web/src/lib의 money·format·labels와 같은 규칙, DESIGN.md 8절).

숫자를 만드는 함수는 여기와 ripple.explain.format뿐이다. 문장 검사(audit.py)는 이 함수를 쓰지 않고 따로 읽는다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date

from ripple.contracts.brief import BRIEF_TEXT_MAX
from ripple.contracts.result import Amount, AnalysisResult, OnboardOption
from ripple.explain.format import money, money_range

WEEKDAYS = "월화수목금토일"  # date.weekday(): 월요일 = 0
SHOWN_CODES = 3

MATERIAL_NAMES = {
    "plate": "판재",
    "section": "형강",
    "pipe": "배관",
    "valve": "밸브",
    "fitting": "배관 부속",
    "equipment": "장비",
}
PO_STATUS_NAMES = {
    "not_ordered": "미발주",
    "ordered": "발주",
    "material_secured": "자재 확보",
    "in_fabrication": "제작",
    "received": "입고",
    "processed": "가공",
}


def short_day(value: date) -> str:
    """첫 화면 날짜: 2026-10-27 → '10월 27일(화)'."""
    return f"{value.month}월 {value.day}일({WEEKDAYS[value.weekday()]})"


def code_of(entity_id: str) -> str:
    """'S-001:B31P' → 'B31P'(화면 labels.codeOf와 같게)."""
    return entity_id[entity_id.rfind(":") + 1 :]


def codes(ids: Sequence[str], limit: int = SHOWN_CODES) -> str:
    """'B31P, B32P 외 2개'(앞 limit개까지 이름, 나머지는 개수)."""
    shown = ", ".join(code_of(i) for i in ids[:limit])
    rest = len(ids) - limit
    return shown + (f" 외 {rest}개" if rest > 0 else "")


def amount_text(amount: Amount) -> str:
    """'298만원(66만~789만원)' — 범위가 없으면 대표값만."""
    shown = money(amount.value)
    if amount.low == amount.high:
        return shown
    return f"{shown}({money_range(amount.low, amount.high)})"


def hours_text(hours: float) -> str:
    """공수(MH) 첫 화면 표기(화면 lib/costSplit.ts formatHours와 같음): 100 이상은 정수(천 단위 쉼표), 그 아래는
    소수 첫째 자리(끝 .0은 지움). 반올림은 0.5에서 올림."""
    if hours >= 100:
        return f"{math.floor(hours + 0.5):,}"
    return f"{math.floor(hours * 10 + 0.5) / 10:.1f}".removesuffix(".0")


def split_text(result: AnalysisResult) -> str | None:
    """'추가 공수 807 MH · 재료비 327만원'(1.35.0 구분별 합, 화면 판단 요약 첫 줄과 같은 값).
    구분이 없는 옛 기록은 None."""
    split = result.cost_split
    if split is None:
        return None
    return f"추가 공수 {hours_text(split.labor_hours.value)} MH · 재료비 {money(split.material.value)}"


def loss_text(loss: Amount) -> str | None:
    """늘어나는 금액 한 마디(화면 deadline.lossText와 같게): 대표값이 있으면 그 값, 대표는 0이고 최대만 있으면
    '최대 n'. 늘지 않으면 None."""
    if loss.value > 0:
        return money(loss.value)
    if loss.high > 0:
        return f"최대 {money(loss.high)}"
    return None


def cost_change(delta: int) -> str:
    """총액 차이 한 마디: '비용 15만원 증가' · '비용 15만원 감소' · '비용 그대로'."""
    if delta > 0:
        return f"비용 {money(delta)} 증가"
    return f"비용 {money(-delta)} 감소" if delta < 0 else "비용 그대로"


def delay_changes(option: OnboardOption, *, only_shorter: bool = False) -> list[str]:
    """선상 설치 선택지의 지연 변화: '블록 탑재 지연 21일 → 1일' · '구역 출구 지연 7일 → 0일'(바뀐 것만,
    only_shorter면 줄어든 것만)."""
    pairs = (
        ("블록 탑재 지연", option.erection_delay_now_days, option.erection_delay_then_days),
        ("구역 출구 지연", option.exit_delay_now_days, option.exit_delay_then_days),
    )
    return [f"{name} {now}일 → {then}일" for name, now, then in pairs if (then < now if only_shorter else then != now)]


def ratio_text(ratio: float) -> str:
    """리드타임 배율: 1.2 → '1.2', 1.25 → '1.25'(화면 schedule.ratioText와 같게)."""
    return f"{round(ratio, 2):g}"


def risk_basis(ratios: dict[str, float]) -> str:
    """'판재 × 1.2, 배관 × 1.5'(분류 키 순)."""
    return ", ".join(f"{MATERIAL_NAMES.get(k, k)} × {ratio_text(v)}" for k, v in sorted(ratios.items()))


def _last_hangul(word: str) -> str:
    return word.rstrip().rstrip("'\"”’)]")[-1:]


def ro(word: str) -> str:
    """로/으로: 받침이 없거나 ㄹ받침이면 '로'."""
    last = _last_hangul(word)
    if "가" <= last <= "힣":
        tail = (ord(last) - 0xAC00) % 28
        return "로" if tail in (0, 8) else "으로"
    return "로" if last and last in "1245789" else "으로"  # 숫자 읽기: 일·이·사·오·칠·팔·구는 '로'


def clip(text: str, limit: int = BRIEF_TEXT_MAX) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
