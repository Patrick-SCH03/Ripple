"""세 줄 요약: 바뀌는 내용(change) → 안 정하면 무엇을 잃나(loss) → 권고와 근거(advice). 세 줄 모두 규칙이 정한다.

- loss는 마감일 상황 하나(이미 지남 · 오늘 · 마감일까지 · 기간 안 손실 없음). 다음 날 늘어나는 금액은 결재함과 같은
  계산(records.metrics.delay_cost — 곡선의 마감 다음 날 대표값)이고, 대표값이 0 이하면 결재함 '미루면'과 같은 분기
  (금액은 그대로, 일정만)로 쓴다.
- advice는 우선순위가 고정이다: 더 저렴한 충족 대안(권고) → 보류 권고 → 선상 설치 → 판정. AI가 고르지 않는다 —
  같은 결과에서 상세의 대안 탭 권고와 어긋나는 권고가 나오지 않게.
숫자는 모두 기록 본문의 분석 결과 필드에서 text.py 표기로 쓴다.
"""

from __future__ import annotations

from datetime import timedelta

from ripple.contracts.brief import BRIEF_TITLE_SHOWN, BriefLine
from ripple.contracts.result import (
    REQUEST_ALT,
    VERDICT_NAMES,
    AnalysisResult,
    DeadlineKind,
    HoldAdvice,
    OnboardDirection,
    VerdictLevel,
)
from ripple.explain.format import money
from ripple.records.metrics import blocks_of, curve_point, delay_cost

from .facts import Facts
from .text import amount_text, clip, code_of, codes, cost_change, delay_changes, loss_text, short_day, split_text


def _line(kind: str, template_id: str, text: str) -> BriefLine:
    return BriefLine.model_validate({"kind": kind, "text": clip(text), "template_id": template_id})


def change_line(result: AnalysisResult) -> BriefLine:
    """'두께 변경 · … — 영향 12곳(블록 B31P, B32P) · 총변경비용 298만원(66만~789만원) · 추가 공수 42.5 MH ·
    재료비 120만원'. 구분별 합(1.35.0)이 없는 옛 기록은 총변경비용까지(고정 문장, 템플릿 ID 그대로)."""
    title = clip(result.request.change.title.strip(), BRIEF_TITLE_SHOWN)
    blocks = blocks_of(result)
    where = f"(블록 {codes(blocks)})" if blocks else ""
    split = split_text(result)
    tail = f" · {split}" if split else ""
    text = f"{title} — 영향 {len(result.impacts)}곳{where} · 총변경비용 {amount_text(result.total)}{tail}"
    return _line("change", "change.summary", text)


# ---------- 안 정하면 ----------


def _steady(result: AnalysisResult) -> str:
    """마감일까지 곡선이 모두 0이면 '비용 그대로', 줄어드는 날이 있으면 '비용 증가 없음'(화면 deadline.ts)."""
    last = result.timing.deadline.last_day
    flat = all(
        p.additional_loss.low == 0 and p.additional_loss.high == 0 for p in result.timing.curve if p.confirm_on <= last
    )
    return "비용 그대로" if flat else "비용 증가 없음"


def _next_day(result: AnalysisResult, when: str) -> str:
    """마감 다음 날(when = '내일'·'다음 날') 늘어나는 금액. 대표값이 0 이하면 결재함 '미루면'과 같은 분기."""
    late = delay_cost(result)
    point = curve_point(result.timing.curve, result.timing.deadline.last_day + timedelta(days=1))
    if late is not None and late[0] > 0:
        return f"{when}부터 {money(late[0])} 증가"
    if point is not None and point.additional_loss.high > 0:
        return f"{when}부터 대표 금액은 그대로 · 최대 {money(point.additional_loss.high)}까지 증가 가능"
    return f"{when}부터도 금액 그대로(일정만 지연 가능)"


def loss_line(facts: Facts) -> BriefLine:
    result = facts.result
    deadline = result.timing.deadline
    day = short_day(deadline.last_day)
    if deadline.kind is DeadlineKind.NONE_IN_HORIZON:
        return _line("loss", "loss.none", f"{day}까지 언제 확정해도 {_steady(result)} — 연기에 따른 추가손실 없음")
    left = (deadline.last_day - facts.today).days
    if left < 0:
        return _line("loss", "loss.passed", _passed(result, facts, day))
    if deadline.kind is DeadlineKind.CONFIRM_NOW:
        return _line("loss", "loss.today", f"오늘 {day} 미확정 시 {_next_day(result, '내일')}")
    head = f"오늘 {day}까지" if left == 0 else f"{day}까지(D-{left})"
    return _line("loss", "loss.by_date", f"{head} 확정 시 {_steady(result)} — {_next_day(result, '다음 날')}")


def _passed(result: AnalysisResult, facts: Facts, day: str) -> str:
    head = f"결정 기한 {day} 지남"
    point = curve_point(result.timing.curve, facts.today)
    if point is None:
        return f"{head} — 탐색 기간 끝도 지나 오늘 확정 시 금액은 재분석 필요"
    grown = loss_text(point.additional_loss)
    if grown is None:
        return f"{head} — 단, 오늘 확정해도 기준일 대비 증가 없음"
    return f"{head} — 오늘 확정 시 기준일 대비 {grown} 추가"


# ---------- 권고 ----------


def _cheaper(result: AnalysisResult) -> str | None:
    """권고가 요청안이 아닌 충족 대안이고 요청안보다 싸면.

    차액은 상세 대안 탭 권고 카드(web/src/lib/alternatives.ts)와 같은 공식: 요청안 최적 총액 − 권고 총액.
    """
    rec = result.recommendation
    if rec is None or rec.alt_id == REQUEST_ALT:
        return None
    chosen = next((a for a in result.alternatives if a.alt_id == rec.alt_id), None)
    request = next((a for a in result.alternatives if a.alt_id == REQUEST_ALT), None)
    if chosen is None or request is None:
        return None
    base = request.best_total or request.total
    saving = base.value - rec.total.value
    if saving <= 0:
        return None
    holds = " · ".join(f"{h.po_id} {h.hold_days}일" for h in rec.holds)
    together = f" · 발주 {holds} 보류 포함" if holds else ""
    return (
        f"더 저렴한 충족 대안 '{chosen.label}' — {short_day(rec.confirm_on)} 확정 시 {money(rec.total.value)}, "
        f"요청안({money(base.value)}) 대비 {money(saving)} 절감{together}"
    )


def _hold(result: AnalysisResult) -> str | None:
    """요청에 아직 넣지 않은 보류 권고 중 첫 번째(마감일이 늦춰지거나 피하는 손실이 있을 때)."""
    applied = {h.po_id for h in result.request.holds}
    advice: HoldAdvice | None = next((h for h in result.timing.holds if h.po_id not in applied), None)
    if advice is None:
        return None
    deadline = result.timing.deadline
    parts: list[str] = []
    if advice.deadline_after != deadline:
        if advice.deadline_after.kind is DeadlineKind.NONE_IN_HORIZON:
            parts.append("탐색 기간 안 추가손실 없음")
        else:
            parts.append(f"결정 기한 {short_day(deadline.last_day)} → {short_day(advice.deadline_after.last_day)} 연기")
    avoided = loss_text(advice.avoided)
    if avoided:
        parts.append(f"{avoided} 손실 회피")
    if not parts:
        return None
    head = f"{advice.po_id} 발주 최대 {advice.max_hold_days}일({short_day(advice.hold_until)}까지) 보류 시"
    return f"{head} {' · '.join(parts)}"


def _onboard(result: AnalysisResult) -> str | None:
    """선상 설치로 바꾸면 블록 탑재·구역 출구 지연이 줄 때(선택지는 엔진이 같은 확정일·보류로 평가한 값)."""
    option = result.onboard
    if option is None or option.direction is not OnboardDirection.TO_ON_BOARD:
        return None
    changes = delay_changes(option, only_shorter=True)
    if not changes:
        return None
    cost = cost_change(option.total_change.value)
    blocks = option.block_ids
    where = code_of(blocks[0]) + (f" 등 {len(blocks)}개" if len(blocks) > 1 else "")
    return f"{where} 블록 의장품 탑재 후 선상 설치 시 {' · '.join(changes)} · {cost}"


def _verdict(result: AnalysisResult, has_checks: bool) -> tuple[str, str]:
    level = result.verdict.level
    if level is VerdictLevel.APPROVE:
        tail = "서명 전 확인할 것만 맞으면 그대로 승인" if has_checks else "그대로 승인"
        return "advice.approve", f"판정 승인 가능 — {tail}"
    reason = result.verdict.reasons[0].rstrip(".")
    name = VERDICT_NAMES[level]
    return "advice.review", f"판정 {name} — {reason} · 담당자 근거 확인 후 결정"


def advice_line(result: AnalysisResult, *, has_checks: bool, alternatives: AnalysisResult | None = None) -> BriefLine:
    """고정 우선순위의 첫 권고. 판정 줄은 늘 성립하므로 권고는 늘 하나다.

    alternatives = 같은 지도·같은 계산 판으로 그 기록 요청을 대안 포함으로 계산한 결과(없으면 기록 본문만 — 기록이
    대안 포함일 때만 더 저렴한 대안 권고가 나온다)."""
    found = (
        ("advice.cheaper", _cheaper(alternatives if alternatives is not None else result)),
        ("advice.hold", _hold(result)),
        ("advice.onboard", _onboard(result)),
    )
    for template_id, text in found:
        if text:
            return _line("advice", template_id, text)
    template_id, text = _verdict(result, has_checks)
    return _line("advice", template_id, text)
