"""한 줄 교훈(사례마다)과 한 줄 요약(비슷한 사례 묶음) — 서버 템플릿, 명사형, 숫자는 사례 값에서만.

교훈은 데이터가 맞을 때만 고른다(예: '늦게 결정 — 예측 비용 증가'는 실제로 마감 뒤였고, 엔진 곡선에서
마감일보다 늘었고, 숨긴 실제 모델에서도 마감일에 정했을 때보다 실적이 컸을 때만).
요약은 건수와 사실만 쓴다 — 오차율 중앙값·%는 쓰지 않는다(합성 실적의 오차는 넣은 잡음을 다시 잰 것이라 정확도로
읽히면 안 된다, docs/evaluation.md E2a 해석 주의).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ripple.contracts.brief import PastCase
from ripple.contracts.result import Amount
from ripple.explain.format import money

from .settings import Choice

CHOSEN: dict[Choice, str] = {
    Choice.AS_REQUESTED: "요청대로 승인",
    Choice.HOLD_PO: "발주 보류 뒤 승인",
    Choice.REJECT: "반려",
    Choice.HOLD: "결정 보류",
}


@dataclass(frozen=True, slots=True)
class CaseFacts:
    """교훈을 고르는 데 쓰는 사례 값. 금액은 원(대표값)."""

    choice: Choice
    days_before: int | None  # 마감보다 며칠 먼저 결정(음수 = 마감 뒤, None = 기간 안에 마감 없음)
    predicted: Amount  # 결정한 날 확정할 때의 엔진 총변경비용
    actual: int | None  # 실적(승인한 사례만)
    at_deadline: int | None = None  # 엔진: 마감일에 확정했을 때(마감이 있을 때)
    actual_at_deadline: int | None = None  # 숨긴 모델: 마감일에 확정했을 때(마감 뒤 승인 사례만)
    without_hold: int | None = None  # 엔진: 같은 날 발주 보류 없이 확정했을 때(발주 보류 사례만)
    no_deadline: bool = False  # 탐색 기간 안에 추가손실이 없어 마감이 없음(days_before가 None인 까닭이 이것일 때만 참)


def note_of(facts: CaseFacts) -> tuple[str, str]:
    """(템플릿 ID, 문장). 앞의 조건부터 차례로 보고 처음 맞는 것."""
    if facts.choice is Choice.REJECT:
        return "rejected", "반려 — 변경 미진행"
    if facts.choice is Choice.HOLD:
        return "held", "결정 보류 — 실적 없음"
    late = facts.days_before is not None and facts.days_before < 0
    if late and facts.days_before is not None:
        return _late(facts, -facts.days_before)
    saved = (facts.without_hold or 0) - facts.predicted.value
    if facts.choice is Choice.HOLD_PO and facts.without_hold is not None and saved > 0:
        return "hold_saved", f"발주 보류 후 승인 — 예측 비용 {money(saved)} 절감"
    if facts.actual is not None and facts.actual > facts.predicted.high:
        return "over_range", f"실적이 예측 범위 최대({money(facts.predicted.high)}) 초과"
    if facts.days_before is None:  # 마감이 없거나 결정 날짜를 모름
        return ("no_deadline", "탐색 기간 안에서는 늦어져도 추가 비용이 없던 건") if facts.no_deadline else ("none", "")
    if facts.days_before == 0:
        return "on_deadline", "결정 기한 당일 결정 — 지연 비용 없이 진행"
    return "on_time", f"결정 기한 {facts.days_before}일 전 결정 — 지연 비용 없이 진행"


def _late(facts: CaseFacts, days: int) -> tuple[str, str]:
    """마감 뒤 승인: 엔진 곡선과 숨긴 모델이 함께 늘었을 때만 '증가', 함께 그대로일 때만 '없음'."""
    if facts.at_deadline is not None and facts.actual is not None and facts.actual_at_deadline is not None:
        grew = facts.predicted.value - facts.at_deadline
        if grew > 0 and facts.actual > facts.actual_at_deadline:
            return "late_cost", f"결정 기한보다 {days}일 늦게 결정 — 예측 비용 {money(grew)} 증가"
        if grew == 0 and facts.actual <= facts.actual_at_deadline:
            return "late_flat", f"결정 기한보다 {days}일 늦게 결정 — 지연으로 늘어난 비용 없음"
    return "late", f"결정 기한보다 {days}일 늦게 결정"


def grew(actual: int, predicted: int) -> bool:
    """실적이 예측보다 컸나 — 화면의 차이 %(web/src/lib/brief.ts outcomeText, 반올림)와 같은 기준: 반올림한 % > 0.
    예측이 0 이하면 %가 없어 금액으로 본다. 그래서 요약 '예측 초과'와 사례 줄 '(±0%)'가 함께 나오지 않는다."""
    if predicted <= 0:
        return actual > predicted
    return math.floor((actual - predicted) / predicted * 100 + 0.5) > 0


def summarize(items: Sequence[PastCase]) -> str | None:
    """비슷한 사례 묶음의 한 줄: 실적이 예측보다 컸던 건수와 마감 뒤에 결정한 건수(사실만). 사례가 없으면 None."""
    if not items:
        return None
    n = len(items)
    measured = [i for i in items if i.actual_krw is not None]
    larger = sum(1 for i in measured if i.actual_krw is not None and grew(i.actual_krw, i.predicted.value))
    late = sum(1 for i in items if i.days_before_deadline is not None and i.days_before_deadline < 0)
    on_time = sum(1 for i in items if i.days_before_deadline is not None and i.days_before_deadline >= 0)
    if not measured:
        first = f"비슷한 {n}건 모두 반려·보류 — 실적 없음"
    elif larger:
        first = f"비슷한 {n}건 중 {larger}건은 실적이 예측 초과"
    elif len(measured) == n:
        first = f"비슷한 {n}건 모두 실적이 예측 이하"
    else:
        first = f"비슷한 {n}건 중 실적이 있는 {len(measured)}건 모두 예측 이하"
    if late:
        return f"{first} · {late}건은 결정 기한 뒤 결정"
    if on_time == n:
        return f"{first} · 모두 결정 기한 안에 결정"
    return first
