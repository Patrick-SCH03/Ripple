"""결정 도우미 검사(렌더 뒤, 계약 검증이 보지 않는 것): 줄 순서 · 확인할 것 키 · 글 속 숫자의 출처.

문장을 만든 코드(lines·checks·text)를 쓰지 않고 따로 읽는다(ripple.explain.audit와 같은 생각):
- 줄은 change · loss · advice 순서로 정확히 3개, 확인할 것은 3개 이하에 키가 겹치지 않는다.
- 기록 값의 이름(제목·엔터티 ID·블록 코드·상태 이름·대안 이름·판정 이유·확인 목록 글)을 뺀 글에서 읽은 날짜(요일까지)·
  D-n·배율·금액(만원 반올림·원)·일수·개수가 모두 기록 본문의 분석 결과 값에서 나온 것이어야 한다.
- 다시 계산한 값이 아닌(computed 거짓) 확인할 것의 '틀리면'에는 숫자가 없어야 한다.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from ripple.contracts.brief import BRIEF_TEXT_MAX, BRIEF_TITLE_SHOWN, DecisionBrief
from ripple.contracts.domain import EntityType
from ripple.contracts.records import RecordBody
from ripple.contracts.result import REQUEST_ALT, Amount, AnalysisResult
from ripple.explain.format import man_units

WEEKDAYS = "월화수목금토일"
ORDER = ("change", "loss", "advice")
_DATE = re.compile(r"(\d{1,2})월 (\d{1,2})일(?:\(([월화수목금토일])\))?")
_D_DAY = re.compile(r"D-(\d+)")
_RATIO = re.compile(r"× (\d+(?:\.\d+)?)")
_MONEY = re.compile(r"(?:(\d[\d,]*)억)?\s?(?:(\d[\d,]*)만)?(?=원|~)|(\d[\d,]*)(?=원)")
_DAYS = re.compile(r"(\d[\d,]*)일")
_COUNT = re.compile(r"(\d[\d,]*)(?:곳|개|건)")
_HOURS = re.compile(r"(\d[\d,]*(?:\.\d+)?) MH")


@dataclass
class Allowed:
    """기록 본문이 허용하는 값."""

    dates: set[date] = field(default_factory=set)
    left: set[int] = field(default_factory=set)  # D-n
    ratios: set[float] = field(default_factory=set)
    money: set[int] = field(default_factory=set)  # 만원 반올림(1만원 미만은 음수로 원 그대로)
    days: set[int] = field(default_factory=set)
    counts: set[int] = field(default_factory=set)
    hours: set[float] = field(default_factory=set)  # 1.35.0 추가 공수(MH) 대표·최소·최대
    names: set[str] = field(default_factory=set)

    def add_amount(self, amount: Amount | None) -> None:
        if amount is None:
            return
        for won in (amount.value, amount.low, amount.high):
            self.money.add(man_units(abs(won)) if abs(won) >= 10_000 else -abs(won))


def audit(brief: DecisionBrief, body: RecordBody, today: date, alternatives: AnalysisResult | None = None) -> list[str]:
    """문제 목록(없으면 통과). alternatives(같은 요청을 대안 포함으로 계산한 결과)의 대안 값·이름도 허용한다."""
    problems: list[str] = []
    if tuple(line.kind for line in brief.lines) != ORDER:
        problems.append("세 줄 순서 오류 — change · loss · advice 순서 필요")
    keys = [check.key for check in brief.checks]
    if len(keys) > 3 or len(set(keys)) != len(keys):
        problems.append("확인할 것 3개 초과 또는 키 중복")
    if brief.ecn_id != body.ecn_id or brief.data_mode is not body.data_mode:
        problems.append("기록과 다른 설계변경·데이터 모드")
    allowed = allowed_of(body, today, alternatives)
    texts = [(f"줄 {line.kind}", line.text) for line in brief.lines]
    for check in brief.checks:
        texts += [(f"확인 {check.key}", check.text), (f"틀리면 {check.key}", check.why)]
        if not check.computed and any(ch.isdigit() for ch in _strip(check.why, allowed.names)):
            problems.append(f"다시 계산한 값이 아닌 '틀리면'에 숫자 있음: {check.key}")
    for where, text in texts:
        wrong = numbers_problem(text, allowed)
        if wrong:
            problems.append(f"{where}: 기록에 없는 숫자 — {', '.join(wrong[:3])}")
    return problems


def allowed_of(body: RecordBody, today: date, alternatives: AnalysisResult | None = None) -> Allowed:
    result = body.result
    allowed = Allowed()
    if alternatives is not None:
        _alternatives(allowed, alternatives)
        allowed.names |= {a.label for a in alternatives.alternatives}
        if alternatives.recommendation is not None:
            allowed.names |= {h.po_id for h in alternatives.recommendation.holds}
    _names(allowed, body)
    _timing(allowed, result, today)
    _schedule(allowed, result)
    _alternatives(allowed, result)
    for line in result.cost_lines:
        allowed.add_amount(line.amount)
    allowed.add_amount(result.total)
    split = result.cost_split
    if split is not None:
        for amount in (split.labor, split.material, split.material_diff, split.purchase, split.damages):
            allowed.add_amount(amount)
        allowed.hours |= {split.labor_hours.value, split.labor_hours.low, split.labor_hours.high}
    blocks = sorted({i.entity_id for i in result.impacts if i.entity_type is EntityType.BLOCK})
    allowed.counts |= {len(result.impacts), len(blocks), max(0, len(blocks) - 3), len(result.request.holds)}
    if result.onboard is not None:
        allowed.counts.add(len(result.onboard.block_ids))
    allowed.counts |= {item.ncr_count for item in result.prechecks if item.ncr_count is not None}
    return allowed


def _names(allowed: Allowed, body: RecordBody) -> None:
    result = body.result
    allowed.names.add("추가손실 0 마감일")  # 고정 용어(글자 0은 값이 아님)
    title = result.request.change.title.strip()
    allowed.names |= {title, title[: BRIEF_TITLE_SHOWN - 1], *result.verdict.reasons}  # 줄은 긴 제목을 잘라 쓴다
    allowed.names |= {item.text for item in body.checklist} | {
        item.text[: BRIEF_TEXT_MAX - 1] for item in body.checklist
    }
    allowed.names |= {row.label for row in result.state_basis} | {row.entity_id for row in result.state_basis}
    allowed.names |= {a.label for a in result.alternatives}
    # 사전 점검 항목의 글은 기록 본문 값(엔진이 지도 이름으로 만든 글)이라 확인 목록 글처럼 이름으로 본다
    for item in result.prechecks:
        allowed.names |= {item.finding, item.text, item.text[: BRIEF_TEXT_MAX - 1], item.reason}
    ids = {i.entity_id for i in result.impacts} | {h.po_id for h in result.timing.holds}
    ids |= {h.po_id for h in result.request.holds}
    if result.recommendation is not None:
        ids |= {h.po_id for h in result.recommendation.holds}
    if result.onboard is not None:
        ids |= set(result.onboard.block_ids)
    allowed.names |= ids | {i[i.rfind(":") + 1 :] for i in ids}


def _timing(allowed: Allowed, result: AnalysisResult, today: date) -> None:
    timing, request = result.timing, result.request
    allowed.dates |= {timing.deadline.last_day, today, request.as_of, request.effective_confirm_on}
    allowed.dates.add(timing.curve[-1].confirm_on)
    allowed.left.add((timing.deadline.last_day - today).days)
    allowed.add_amount(timing.base_cost)
    for point in timing.curve:
        allowed.add_amount(point.total)
        allowed.add_amount(point.additional_loss)
    for hold in timing.holds:
        allowed.dates |= {hold.hold_until, hold.deadline_after.last_day}
        allowed.days.add(hold.max_hold_days)
        allowed.add_amount(hold.avoided)
    allowed.days |= {h.hold_days for h in request.holds}


def _schedule(allowed: Allowed, result: AnalysisResult) -> None:
    schedule = result.schedule
    allowed.days.add(schedule.max_exit_delay_days)
    allowed.days |= {z.delay_days for z in schedule.zone_exits}
    deliveries = [schedule.delivery]
    if schedule.risk is not None:
        allowed.days.add(schedule.risk.max_exit_delay_days)
        allowed.ratios |= {round(r, 2) for r in schedule.risk.ratios.values()}
        deliveries.append(schedule.risk.delivery)
    for delivery in deliveries:
        if delivery is not None:
            allowed.days |= {
                delivery.added_delay_days,
                delivery.forecast_delay_before_days,
                delivery.forecast_delay_after_days,
            }
            allowed.add_amount(delivery.exposure)
    option = result.onboard
    if option is not None:
        allowed.days |= {
            option.erection_delay_now_days,
            option.erection_delay_then_days,
            option.exit_delay_now_days,
            option.exit_delay_then_days,
            option.on_board_days,
        }
        allowed.add_amount(option.total_change)


def _alternatives(allowed: Allowed, result: AnalysisResult) -> None:
    for alt in result.alternatives:
        allowed.add_amount(alt.total)
        allowed.add_amount(alt.best_total)
    rec = result.recommendation
    if rec is None:
        return
    allowed.add_amount(rec.total)
    allowed.dates.add(rec.confirm_on)
    allowed.days |= {h.hold_days for h in rec.holds}
    request = next((a for a in result.alternatives if a.alt_id == REQUEST_ALT), None)
    if request is not None:  # 상세 대안 탭 권고 카드의 차액(요청안 최적 총액 − 권고 총액)
        base = request.best_total or request.total
        allowed.add_amount(Amount.exact(base.value - rec.total.value) if base.value >= rec.total.value else None)


def _strip(text: str, names: set[str]) -> str:
    for name in sorted((n for n in names if n), key=len, reverse=True):
        text = text.replace(name, " ")
    return text


def numbers_problem(text: str, allowed: Allowed) -> list[str]:
    """이름을 뺀 글의 숫자 중 기록 값이 아닌 것."""
    rest = _strip(text, allowed.names)
    wrong: list[str] = []
    shown = {(d.month, d.day): WEEKDAYS[d.weekday()] for d in allowed.dates}
    for match in _DATE.finditer(rest):
        key = (int(match.group(1)), int(match.group(2)))
        if key not in shown or (match.group(3) and match.group(3) != shown[key]):
            wrong.append(match.group(0))
    rest = _DATE.sub(" ", rest)
    rest = _take(rest, _D_DAY, lambda m: int(m.group(1)) in allowed.left, wrong)
    rest = _take(rest, _RATIO, lambda m: round(float(m.group(1)), 2) in allowed.ratios, wrong)
    rest = _take(rest, _HOURS, lambda m: _hours_ok(m.group(1), allowed.hours), wrong)
    rest = _take(rest, _MONEY, lambda m: _money_ok(m, allowed.money), wrong)
    rest = _take(rest, _DAYS, lambda m: _int(m.group(1)) in allowed.days, wrong)
    rest = _take(rest, _COUNT, lambda m: _int(m.group(1)) in allowed.counts, wrong)
    leftovers = "".join(ch for ch in rest if ch.isdigit())
    if leftovers:
        wrong.append(f"남은 숫자 {leftovers}")
    return wrong


def _hours_ok(text: str, allowed: set[float]) -> bool:
    """글 속 공수(MH)가 기록의 공수를 표기 규칙대로 반올림한 값인가(100 이상은 정수, 그 아래는 소수 첫째 자리)."""
    shown = float(text.replace(",", ""))
    return any(abs(shown - hours) <= (0.5 if hours >= 99.95 else 0.05) + 1e-9 for hours in allowed)


def _int(text: str) -> int:
    return int(text.replace(",", ""))


def _money_ok(match: re.Match[str], allowed: set[int]) -> bool:
    if match.group(3):
        return -_int(match.group(3)) in allowed
    if not (match.group(1) or match.group(2)):
        return True  # 빈 일치(숫자 없음)
    return _int(match.group(1) or "0") * 10_000 + _int(match.group(2) or "0") in allowed


def _take(text: str, pattern: re.Pattern[str], ok: Callable[[re.Match[str]], bool], wrong: list[str]) -> str:
    """일치마다 ok로 보고 지운다(남은 숫자 검사가 같은 숫자를 다시 세지 않게)."""
    for match in pattern.finditer(text):
        if match.group(0).strip() and not ok(match):
            wrong.append(match.group(0).strip())
    return pattern.sub(" ", text)
