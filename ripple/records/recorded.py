"""기록 한 건에서 뽑는 값과 결재·현황 지표의 입력(docs/records.md(기록·결재) 11절). 순수 계산이다.

결재·현황(metrics.py)·성과(performance.py)·결정 도우미·과거 사례가 같은 기준으로 쓴다.
- 날짜 기준은 기록마다: 실데이터 = KST 오늘·실제 승인 날짜, 합성 = 분석 기준일 + 기록 뒤 지난 날수
  (지도 시계와 실제 시계가 달라서).
- '미루면': 그 개정의 추가손실 곡선에서 마감 다음 날 값(기준일보다 늘어나는 금액, 대표값).
  기간 안 손실이 없으면 계산하지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from ripple.contracts.domain import DataMode, EntityType
from ripple.contracts.outcomes import OutcomeEntry
from ripple.contracts.records import ApprovalStep, AuditEntry, EcnAction, EcnListItem, EcnState, RecordBody
from ripple.contracts.result import AlternativeOrigin, AnalysisResult, CurvePoint, DeadlineKind, Eligibility

KST = timezone(timedelta(hours=9))  # 서머타임 없음
WAITING = (EcnState.IN_REVIEW, EcnState.ON_HOLD)
UNDECIDED = (EcnState.ANALYZED, EcnState.IN_REVIEW, EcnState.ON_HOLD)
OPEN = (*UNDECIDED, EcnState.APPROVED, EcnState.IN_PROGRESS)
DECIDE = (EcnAction.APPROVE, EcnAction.REJECT, EcnAction.HOLD)


def curve_point(curve: Sequence[CurvePoint], day: date) -> CurvePoint | None:
    """추가손실 곡선에서 그날 확정하는 점(곡선 밖이면 None)."""
    return next((p for p in curve if p.confirm_on == day), None)


def delay_cost(result: AnalysisResult) -> tuple[int, date] | None:
    """마감 다음 날 확정하면 기준일보다 늘어나는 금액(대표값)과 그날. 기간 안 손실이 없거나 곡선 밖이면 None."""
    deadline = result.timing.deadline
    if deadline.kind is DeadlineKind.NONE_IN_HORIZON:
        return None
    day = deadline.last_day + timedelta(days=1)
    point = curve_point(result.timing.curve, day)
    return (point.additional_loss.value, day) if point is not None else None


def cheaper_by(result: AnalysisResult) -> int | None:
    """충족한 대안(요청안 제외)의 최적 조합 중 최저 비용 것이 요청안보다 싸면 그 차액(대표값)."""
    costs = [
        alt.best_total.value
        for alt in result.alternatives
        if alt.origin is not AlternativeOrigin.REQUEST
        and alt.eligibility.status is Eligibility.MEETS
        and alt.best_total is not None
    ]
    saving = result.total.value - min(costs) if costs else 0
    return saving if saving > 0 else None


def blocks_of(result: AnalysisResult) -> tuple[str, ...]:
    """영향받는 블록(ID 순)."""
    return tuple(sorted({i.entity_id for i in result.impacts if i.entity_type is EntityType.BLOCK}))


def kst_date(moment: datetime) -> date:
    return moment.astimezone(KST).date()


def business_today(body: RecordBody, today: date, *, live: bool = False) -> date:
    """그 기록의 업무상 오늘: 실데이터·실시간 시연 세계 = KST 오늘, 날짜에 멈춘 합성 = 분석 기준일(지도 기준일 —
    업무 화면의 D-n과 같은 기준)."""
    return today if live or body.data_mode is DataMode.REAL else body.result.request.as_of


def decided_on(body: RecordBody, decided_at: datetime, recorded_at: datetime, *, live: bool = False) -> date:
    """결정한 업무상 날짜: 실데이터·실시간 시연 세계 = 실제 결정 KST 날짜, 날짜에 멈춘 합성 = 분석 기준일 + 기록 뒤
    지난 날수."""
    if live or body.data_mode is DataMode.REAL:
        return kst_date(decided_at)
    return body.result.request.as_of + (kst_date(decided_at) - kst_date(recorded_at))


@dataclass(frozen=True, slots=True)
class Inputs:
    """저장소가 읽어 넘기는 것. bodies = 기록 ID → 본문(최신 개정 · 승인한 개정)."""

    items: Sequence[EcnListItem]
    audit: Sequence[AuditEntry]
    bodies: Mapping[str, RecordBody]
    now: datetime
    days: int | None
    outcomes: Mapping[str, OutcomeEntry] = field(default_factory=dict)  # ECN → 실적 지금 값
    live: bool = False  # 합성 지도도 실시간(한국 시간 오늘)으로 도는 시연 세계인가
    # 결재함에 싣는 결재 단계(보는 사람의 단계, docs/records.md(기록·결재) 14절). None = 모든 단계(개발 모드)
    steps: frozenset[ApprovalStep] | None = None
    # 전결 묶음에 싣는 단계(팀장 = 파트장·본부장). 비면 묶음 없음(파트장·본부장·개발 모드)
    proxy_steps: frozenset[ApprovalStep] = frozenset()
