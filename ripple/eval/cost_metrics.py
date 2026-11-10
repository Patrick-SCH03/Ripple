"""2단계 관문 채점(docs/gate_cases.md): 손 계산 기대값과 분석 결과를 항목마다 비교한다.

금액은 대표값·최소·최대 각각 ±1%(작은 금액은 ±1원 바닥), 일은 ±0. 비용 줄은 줄 ID로 맞추고 빠진 줄·더한 줄은
불일치다. 계산 불가 이유·보류 권고는 집합으로, 판정 이유는 문장 집합으로 비교한다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from ripple.contracts.evaluation import ExpectedAmount, ExpectedOnboard, ExpectedTiming, GateCase
from ripple.contracts.result import Amount, AnalysisResult, CurvePoint, DeadlineKind, OnboardOption, ZeroLossDeadline

from .coverage import coverage_problems

TOLERANCE = 0.01  # 금액 ±1%
FLOOR_KRW = 1  # 반올림 차이를 위한 바닥


def close(expected: int, actual: int) -> bool:
    return abs(actual - expected) <= max(FLOOR_KRW, abs(expected) * TOLERANCE)


@dataclass(frozen=True, slots=True)
class Mismatch:
    item: str  # 무엇이 다른지(예: "줄 R-T01:po_change:PO-0078#1 대표값")
    expected: str
    actual: str

    def __str__(self) -> str:
        return f"{self.item}: 기대 {self.expected} · 엔진 {self.actual}"


@dataclass(frozen=True, slots=True)
class CostCaseScore:
    case_id: str
    mismatches: tuple[Mismatch, ...]

    @property
    def passed(self) -> bool:
        return not self.mismatches


@dataclass(frozen=True, slots=True)
class CostGateScore:
    cases: tuple[CostCaseScore, ...]
    required: tuple[str, ...]  # 사례 입력 폴더의 사례 ID 전부

    @property
    def problems(self) -> tuple[str, ...]:
        return coverage_problems((case.case_id for case in self.cases), self.required)

    def passed(self) -> bool:
        """관문: 필수 사례를 빠짐·겹침 없이 모두 채점했고 모두 통과."""
        return not self.problems and all(case.passed for case in self.cases)


def _won(value: int) -> str:
    return f"{value:,}"


def amount_mismatches(item: str, expected: ExpectedAmount, actual: Amount) -> list[Mismatch]:
    pairs = (
        ("대표값", expected.value_krw, actual.value),
        ("최소", expected.low, actual.low),
        ("최대", expected.high, actual.high),
    )
    return [Mismatch(f"{item} {label}", _won(want), _won(got)) for label, want, got in pairs if not close(want, got)]


def _deadline_text(deadline: ZeroLossDeadline) -> str:
    return f"{deadline.kind.value} {deadline.last_day.isoformat()}"


def _curve_total(item: str, expected: ExpectedAmount, curve: dict[date, CurvePoint], day: date) -> list[Mismatch]:
    point = curve.get(day)
    if point is None:
        return [Mismatch(item, f"{day.isoformat()}의 총액", "곡선에 그날이 없음")]
    return amount_mismatches(item, expected, point.total)


def _score_timing(timing: ExpectedTiming, result: AnalysisResult, out: list[Mismatch]) -> None:
    # 일정
    exits = {z.zone_id: z.delay_days for z in result.schedule.zone_exits if z.delay_days > 0}
    if exits != timing.zone_exit_delays:
        out.append(
            Mismatch(
                "구역 출구 지연(일)",
                str(dict(sorted(timing.zone_exit_delays.items()))),
                str(dict(sorted(exits.items()))),
            )
        )
    delivery = None if result.schedule.delivery is None else result.schedule.delivery.added_delay_days
    if delivery != timing.delivery_added_days:
        out.append(Mismatch("늘어난 인도 지연(일)", str(timing.delivery_added_days), str(delivery)))
    exposure = None if result.schedule.delivery is None else result.schedule.delivery.exposure
    out += _optional_amount("인도 지연 노출 금액", timing.delivery_exposure, exposure)
    ripple = None if result.delay_ripple is None else result.delay_ripple.amount
    out += _optional_amount("지연 파급 비용(총액 밖)", timing.delay_ripple, ripple)
    _score_onboard(timing.onboard, result.onboard, out)

    # 확정 시점: 마감일, 그날·다음 날 총액, 보류 권고
    deadline = result.timing.deadline
    if deadline != timing.deadline:
        out.append(Mismatch("추가손실 0 마감일", _deadline_text(timing.deadline), _deadline_text(deadline)))
    curve = {point.confirm_on: point for point in result.timing.curve}
    day = timing.deadline.last_day
    out += _curve_total(f"마감일({day.isoformat()}) 총액", timing.deadline_total, curve, day)
    if timing.next_day_total is not None and timing.deadline.kind is not DeadlineKind.NONE_IN_HORIZON:
        following = day + timedelta(days=1)
        out += _curve_total(f"마감일 다음 날({following.isoformat()}) 총액", timing.next_day_total, curve, following)
    holds = {hold.po_id: hold for hold in result.timing.holds}
    want_holds = {hold.po_id: hold for hold in timing.holds}
    if holds.keys() != want_holds.keys():
        out.append(Mismatch("보류 권고 발주", str(sorted(want_holds)), str(sorted(holds))))
    for po_id in sorted(holds.keys() & want_holds.keys()):
        got_hold, want_hold = holds[po_id], want_holds[po_id]
        if got_hold.max_hold_days != want_hold.max_hold_days:
            out.append(
                Mismatch(f"보류 {po_id} 가능 기간(일)", str(want_hold.max_hold_days), str(got_hold.max_hold_days))
            )
        if got_hold.hold_until != want_hold.hold_until:
            out.append(
                Mismatch(f"보류 {po_id} 기한", want_hold.hold_until.isoformat(), got_hold.hold_until.isoformat())
            )
        if got_hold.deadline_after != want_hold.deadline_after:
            out.append(
                Mismatch(
                    f"보류 {po_id} 뒤 마감일",
                    _deadline_text(want_hold.deadline_after),
                    _deadline_text(got_hold.deadline_after),
                )
            )


def _optional_amount(item: str, expected: ExpectedAmount | None, actual: Amount | None) -> list[Mismatch]:
    if expected is None or actual is None:
        return [] if (expected is None) == (actual is None) else [Mismatch(item, str(expected), str(actual))]
    return amount_mismatches(item, expected, actual)


def _score_onboard(expected: ExpectedOnboard | None, actual: OnboardOption | None, out: list[Mismatch]) -> None:
    """선상 설치 선택지(6-8): 있는지, 있으면 방향·대상·일수는 그대로, 총액 차이는 금액 허용 오차로."""
    if expected is None or actual is None:
        if (expected is None) != (actual is None):
            out.append(Mismatch("선상 설치 선택지", "있음" if expected else "없음", "있음" if actual else "없음"))
        return
    fields = (
        "direction",
        "block_ids",
        "part_ids",
        "on_board_days",
        "erection_delay_now_days",
        "erection_delay_then_days",
        "exit_delay_now_days",
        "exit_delay_then_days",
        "delivery_added_now_days",
        "delivery_added_then_days",
    )
    for name in fields:
        want, got = getattr(expected, name), getattr(actual, name)
        if want != got:
            out.append(Mismatch(f"선상 설치 선택지 {name}", str(want), str(got)))
    out += amount_mismatches("선상 설치 선택지 총액 차이", expected.total_change, actual.total_change)


def require_same_case(case: GateCase, result: AnalysisResult) -> None:
    """다른 지도·요청으로 계산한 결과는 채점하지 않는다(ValueError) — 2·3단계 채점이 같이 쓴다."""
    if result.versions.snapshot_id != case.snapshot.snapshot_id:
        raise ValueError(f"{case.case_id}: 결과의 지도가 사례의 지도와 달라요")
    if result.request != case.request:
        raise ValueError(f"{case.case_id}: 결과의 요청이 사례의 요청과 달라요")


def score_cost_case(case: GateCase, result: AnalysisResult) -> CostCaseScore:
    """한 사례를 채점한다. 다른 지도·요청으로 계산한 결과는 채점하지 않는다(ValueError)."""
    require_same_case(case, result)
    expected = case.expected
    if expected.total is None or expected.timing is None or expected.verdict is None:
        raise ValueError(f"{case.case_id}: 2단계 기대값이 없어요")
    out: list[Mismatch] = []

    # 비용 줄·총액
    lines = {line.line_id: line for line in result.cost_lines}
    wanted = {line.line_id: line for line in expected.cost_lines}
    out += [Mismatch(f"줄 {line_id}", "있음", "없음") for line_id in sorted(wanted.keys() - lines.keys())]
    out += [Mismatch(f"줄 {line_id}", "없음", "있음") for line_id in sorted(lines.keys() - wanted.keys())]
    for line_id in sorted(wanted.keys() & lines.keys()):
        want, got = wanted[line_id], lines[line_id]
        out += amount_mismatches(f"줄 {line_id}", want.amount, got.amount)
        if want.determinacy is not got.determinacy:
            out.append(Mismatch(f"줄 {line_id} 판단", want.determinacy.value, got.determinacy.value))
    out += amount_mismatches("총액", expected.total, result.total)

    # 계산하지 못한 이유
    want_unresolved = sorted((u.kind.value, u.entity_id or "") for u in expected.unresolved)
    got_unresolved = sorted((u.kind.value, u.entity_id or "") for u in result.unresolved)
    if want_unresolved != got_unresolved:
        out.append(Mismatch("계산 불가 이유", str(want_unresolved), str(got_unresolved)))

    _score_timing(expected.timing, result, out)

    # 요약 판정
    verdict = expected.verdict
    if result.verdict.level is not verdict.level:
        out.append(Mismatch("판정 수준", verdict.level.value, result.verdict.level.value))
    want_reasons = set(verdict.reasons)
    if set(result.verdict.reasons) != want_reasons:
        out.append(Mismatch("판정 이유", str(sorted(want_reasons)), str(sorted(result.verdict.reasons))))
    return CostCaseScore(case.case_id, tuple(out))


def score_cost_gate(scores: list[CostCaseScore], required: Iterable[str]) -> CostGateScore:
    return CostGateScore(tuple(scores), tuple(sorted(required)))
