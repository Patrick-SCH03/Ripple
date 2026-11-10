"""결재선·무비용·결재 소요(순수 계산, docs/records.md(기록·결재) 14절).

- 결재선(추가 비용 건) = 파트장 → 팀장 → 본부장·실장. 검토를 요청할 때 그 검토에 고정한다(ReviewInfo.steps) — 이 상수가
  바뀌어도 진행 중 검토의 단계 수는 그대로다.
- 역할 → 단계: 파트장·팀장·본부장은 자기 단계를 결정하고, 팀장은 파트장·본부장 단계를 대신 결정할 수 있다(전결 — 감사
  세부 proxy와 원래 단계). 개발 모드는 모든 단계를 자기 단계로.
- 무비용 = 비용 줄이 도면 개정(R-D01)뿐이고 판단 불가 줄·지체상금 노출 금액이 없으며 판정이 '승인 가능'(경고·검토
  필요면 일정·납기 위험이 있어 결재선으로) → 결재선 없이 담당자 처리(settle).
- 결재 소요 = 남은 단계 × 단계당 근무일(1~2일, 대표 2) — 엔진 밖 설정이라 분석·관문 값은 그대로다.
  결재 올릴 기한 = plus_workdays(그날, 근무일) ≤ 결정 기한인 마지막 근무일 — 기한을 그날 이하 마지막 근무일로
  내린 뒤(토·일이면 금요일) 근무일만큼 앞(주말 제외, 공휴일 무시). 지남(late) = 오늘 올려도 결재가 결정 기한 안에
  끝나지 않음(plus_workdays(업무상 오늘, 근무일) > 결정 기한 — 날짜 비교로 세면 업무상 오늘이 토·일일 때 바로 앞 금요일
  기한을 거짓으로 '지남'이라 함). 지났으면 '오늘 올려도 결정은 빨라야'와 그날 추가손실.
  같은 규칙으로 단계당 1근무일(DAYS_PER_STEP_LOW)이면의 결재 올릴 기한·지남(submit_by_low·late_low)과, 확정 단추가
  주말을 권하지 않게 결정 기한 이하 마지막 근무일(decide_by_workday — 업무상 오늘보다 앞이면 없음)도 싣는다.
- 결재선: 검토 전이면 검토를 요청할 때 고정될 결재선(APPROVAL_LINE), 검토 중이면 그 검토에 고정한 결재선(무비용
  개정을 검토 요청했어도 그대로 — 남은 단계·결재 기간 모두 결재선 기준).
- 보류 권고의 결재 기간: 기준일부터 결재선 전체 근무일이 지나는 날과 권고 보류 마지막 날을 견줘
  '결재 중엔 보류 유지 가능 · 권고 기간까지는 공급사 협의' 문구를 만든다(엔진 보류 권고는 그대로).
  검토 전 무비용이면 '담당자 처리 — 결재 없음'.
- 이 규칙은 여기 한 곳뿐이다: 분석 응답·기록 상세·결재함·기록 조회·엑셀 내보내기가 이 계산 값(ApprovalPlan)을
  그대로 쓴다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from ripple.contracts.approval import LEGACY_LINE, ApprovalPlan, ApprovalStep, HoldApproval
from ripple.contracts.auth import Role
from ripple.contracts.records import ReviewInfo
from ripple.contracts.result import AnalysisResult, DeadlineKind, Determinacy, HoldAdvice, VerdictLevel

APPROVAL_LINE: tuple[ApprovalStep, ...] = (ApprovalStep.PART_LEAD, ApprovalStep.TEAM_LEAD, ApprovalStep.EXECUTIVE)
DAYS_PER_STEP = 2  # 단계당 결재 근무일(대표) — 결재 라인별 1~2일 내 결재가 관례(현업 답변)
DAYS_PER_STEP_LOW = 1
DRAWING_RULE = "R-D01"  # 도면 개정 비용 줄(무비용 판정에서 결재 없이 둘 수 있는 유일한 줄)

STEP_OF_ROLE: Mapping[Role, ApprovalStep] = {
    Role.PART_LEAD: ApprovalStep.PART_LEAD,
    Role.ADMIN: ApprovalStep.TEAM_LEAD,
    Role.EXECUTIVE: ApprovalStep.EXECUTIVE,
}
PROXY_OF_ROLE: Mapping[Role, frozenset[ApprovalStep]] = {
    Role.ADMIN: frozenset({ApprovalStep.PART_LEAD, ApprovalStep.EXECUTIVE}),  # 팀장 전결
}
STEP_LABEL: Mapping[ApprovalStep, str] = {
    ApprovalStep.PART_LEAD: "파트장",
    ApprovalStep.TEAM_LEAD: "팀장",
    ApprovalStep.EXECUTIVE: "본부장",
}


def steps_of(role: Role, *, dev: bool = False) -> tuple[frozenset[ApprovalStep], frozenset[ApprovalStep]]:
    """역할 → (자기 단계로 결정할 단계, 전결로 결정할 단계). 개발 모드는 모든 단계를 자기 단계로."""
    if dev:
        return frozenset(ApprovalStep), frozenset()
    own = STEP_OF_ROLE.get(role)
    return (frozenset({own}) if own is not None else frozenset()), PROXY_OF_ROLE.get(role, frozenset())


def line_or_legacy(steps: Sequence[ApprovalStep]) -> tuple[ApprovalStep, ...]:
    """감사 줄의 결재선: 비었으면(형식 판 3까지의 검토 요청) 팀장 한 단계."""
    return tuple(steps) or LEGACY_LINE


def no_cost(result: AnalysisResult) -> bool:
    """비용 줄이 도면 개정뿐이고(다른 규칙 줄 없음) 판단 불가 줄·지체상금 노출 금액이 없으며 판정이 '승인 가능'인가
    (줄이 없어도 무비용). 경고·검토 필요 판정(구역 출구 지연·자재 납기 위험 등)은 도면 개정뿐이어도 결재선으로."""
    lines_ok = all(line.rule_id == DRAWING_RULE and line.determinacy is Determinacy.KNOWN for line in result.cost_lines)
    schedule = result.schedule
    deliveries = (schedule.delivery, schedule.risk.delivery if schedule.risk else None)
    exposed = any(d is not None and d.exposure is not None for d in deliveries)
    return lines_ok and not exposed and result.verdict.level is VerdictLevel.APPROVE


def last_workday(day: date) -> date:
    """day 이하 마지막 근무일(토·일이면 그 앞 금요일, 공휴일은 무시)."""
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def submit_by_of(deadline: date, workdays: int) -> date:
    """결재 올릴 기한: plus_workdays(그날, workdays) ≤ deadline인 마지막 근무일. 기한을 그날 이하 마지막 근무일로
    내린 뒤 근무일 workdays개만큼 앞(토·일 기한에서 바로 세면 결재가 기한 다음 월요일에 끝나 하루 늦음)."""
    return minus_workdays(last_workday(deadline), workdays)


def minus_workdays(day: date, count: int) -> date:
    """day에서 근무일(월~금) count개만큼 앞 날(주말은 세지 않고 건너뜀, 공휴일은 무시)."""
    for _ in range(count):
        day -= timedelta(days=1)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
    return day


def plus_workdays(day: date, count: int) -> date:
    """day에서 근무일 count개만큼 뒤 날(주말 건너뜀, 공휴일 무시)."""
    for _ in range(count):
        day += timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
    return day


def overdue(today: date, workdays: int, deadline: date) -> bool:
    """오늘 올려도 결재(근무일 workdays)가 결정 기한 안에 끝나지 않는가 — 결재 올릴 기한이 지났다는 뜻. 업무상 오늘이
    평일이면 '결재 올릴 기한 < 오늘'과 같고, 토·일이면 그 앞 금요일에 올린 것과 같다(plus_workdays(토, n) =
    plus_workdays(금, n) — 결재 올릴 기한이 바로 앞 금요일이어도 주말에는 아직 지나지 않음)."""
    return plus_workdays(today, workdays) > deadline


def remaining(steps: Sequence[ApprovalStep], step: int) -> tuple[ApprovalStep, ...]:
    """진행 중 검토의 남은 단계(지금 단계부터)."""
    return tuple(steps[step - 1 :])


NO_COST_TEXT = "담당자 처리 — 결재 없음"


def hold_approval(advice: HoldAdvice, as_of: date, line_steps: int) -> HoldApproval:
    """보류 권고 하나의 결재 기간 문구. 결재 기간 = 기준일부터 근무일(결재선 전체 단계 × 단계당 대표)."""
    if line_steps == 0:
        return HoldApproval(po_id=advice.po_id, text=NO_COST_TEXT, short=NO_COST_TEXT)
    workdays = line_steps * DAYS_PER_STEP
    end = plus_workdays(as_of, workdays)
    period = f"약 {workdays}근무일 — 결재 {line_steps}단계 × {DAYS_PER_STEP_LOW}~{DAYS_PER_STEP}일"
    days = advice.max_hold_days
    if advice.hold_until > end:
        text = f"결재 중({period})에는 보류 유지 가능 · 권고 {days}일까지 보류 시 공급사 협의 필요"
        return HoldApproval(
            po_id=advice.po_id,
            outlasts=True,
            approval_end=end,
            text=text,
            short=f"결재 중 보류 가능 · {days}일까지는 공급사 협의",
        )
    text = f"권고 {days}일은 결재 기간({period})보다 짧은 보류 · 그 안에 결재 완료 시 손실 회피"
    return HoldApproval(po_id=advice.po_id, approval_end=end, text=text, short="결재 기간보다 짧은 보류")


def approval_plan(result: AnalysisResult, today: date, review: ReviewInfo | None) -> ApprovalPlan:
    """결재 소요와 결재 올릴 기한. today = 그 기록의 업무상 오늘(records.recorded.business_today).
    review = 진행 중 검토(검토·보류 — 그 검토에 고정한 결재선과 지금 단계), 없으면 검토 전.

    - 검토 전: 결재선 = 검토를 요청하면 고정될 APPROVAL_LINE, 남은 단계 = 결재선 전체(무비용이면 없음).
    - 검토 중: 결재선 = 그 검토의 결재선(무비용 개정이어도 결재 중이므로 그대로), 남은 단계 = 지금 단계부터.
    보류 권고의 결재 기간은 결재선 전체 단계 수(line_steps — 검토 전 무비용이면 0)로 센다."""
    free = no_cost(result)
    if review is not None:
        line, left = review.steps, remaining(review.steps, review.step)
        line_steps = len(line)
    else:
        line, left = APPROVAL_LINE, (() if free else APPROVAL_LINE)
        line_steps = len(left)
    workdays = len(left) * DAYS_PER_STEP
    workdays_low = len(left) * DAYS_PER_STEP_LOW
    deadline = result.timing.deadline
    dated = deadline.kind is not DeadlineKind.NONE_IN_HORIZON
    submit_by = submit_by_low = None
    if left and dated:
        submit_by = submit_by_of(deadline.last_day, workdays)
        submit_by_low = submit_by_of(deadline.last_day, workdays_low)
    late = submit_by is not None and overdue(today, workdays, deadline.last_day)
    late_low = submit_by_low is not None and overdue(today, workdays_low, deadline.last_day)
    earliest = plus_workdays(today, workdays) if late else None
    point = next((p for p in result.timing.curve if p.confirm_on == earliest), None) if earliest else None
    workday = last_workday(deadline.last_day) if dated else None
    return ApprovalPlan(
        no_cost=free,
        line=line,
        steps=left,
        line_steps=line_steps,
        days_per_step_low=DAYS_PER_STEP_LOW,
        days_per_step=DAYS_PER_STEP,
        workdays=workdays,
        submit_by=submit_by,
        late=late,
        earliest=earliest,
        earliest_loss=point.additional_loss.value if point is not None else None,
        holds=tuple(hold_approval(a, result.request.as_of, line_steps) for a in result.timing.holds),
        submit_by_low=submit_by_low,
        late_low=late_low,
        decide_by_workday=workday if workday is not None and workday >= today else None,
    )
