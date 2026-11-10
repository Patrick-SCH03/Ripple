"""결재·현황 계약(계약 1.24.0, 1.25.0에서 결재 단계를 뺌, docs/records.md(기록·결재) 11절). 결재선(파트장 → 팀장 →
본부장, 14절)부터 결재함은 보는 사람의 단계 건만이고 성과의 처리 시간은 단계별이다.

GET /api/manage/overview가 돌려주는 묶음이다.

모두 읽을 때 기록 저장소에서 계산하는 값이고 저장하지 않는다. 날짜 기준은 기록마다 정한다:
실데이터 기록은 KST 오늘·실제 승인 날짜, 합성 기록은 그 분석의 기준일(지도 기준일)과 기록 뒤 지난 날수.
개발 모드에서 한 요청·결정은 성과·처리 시간·담당자별 집계에서 뺀다(업무 기록이 아님).
"""

from __future__ import annotations

from datetime import date

from pydantic import AwareDatetime, Field

from .base import Frozen
from .domain import DataMode
from .outcomes import OutcomeSummary
from .records import Actor, ApprovalPlan, ApprovalStep, EcnState, StepSign
from .result import Amount, DeadlineKind, VerdictLevel

URGENT_DAYS = 3  # 결재함·현황의 '마감 임박': 업무상 오늘부터 이 날수 이내(지난 것 포함)


class InboxItem(Frozen):
    """결재함 한 줄(검토·보류 중인 ECN의 진행 중 개정). 결재함은 보는 사람의 단계 건만 싣는다(팀장 = 팀장 단계,
    파트장 = 파트장 단계, 본부장 = 본부장 단계 — 팀장의 전결은 업무 화면 '결재를 기다리는 설계변경'에서)."""

    ecn_id: str
    title: str
    state: EcnState
    revision: int = Field(ge=1)
    record_id: str
    data_mode: DataMode
    verdict: VerdictLevel
    total: Amount
    deadline_kind: DeadlineKind
    deadline: date  # 추가손실 0 마감일(기간 안 손실이 없으면 탐색 기간 끝 날)
    as_of: date
    confirm_on: date
    days_left: int  # 업무상 오늘부터 마감일까지(0 = 오늘까지, 음수 = 지남)
    delay_cost: int | None = None  # 마감 다음 날 확정하면 기준일보다 늘어나는 금액(대표값). 기간 안 손실이 없으면 None
    delay_from: date | None = None  # 그 금액이 생기는 날(마감 다음 날)
    horizon_end: date  # 기록된 추가손실 곡선의 마지막 날('이날까지 손실 없음' 안내에 씀)
    requested_by: Actor
    requested_at: AwareDatetime
    waiting_hours: float = Field(ge=0)
    checklist: int = Field(ge=0)
    cheaper_by: int | None = None  # 더 싼 충족 대안(최적 조합)과의 차액(대표값). 없으면 None
    blocks: tuple[str, ...] = ()
    # 결재선(docs/records.md(기록·결재) 14절): 지금 단계 · 결재선 전체 · 앞 단계의 승인(전결 표시) · 남은 결재 소요
    step: ApprovalStep = ApprovalStep.TEAM_LEAD
    steps: tuple[ApprovalStep, ...] = (ApprovalStep.TEAM_LEAD,)
    signed: tuple[StepSign, ...] = ()
    step_since: AwareDatetime | None = None  # 지금 단계가 시작된 때(앞 단계 승인 또는 검토 요청) — 대기 일수
    step_waiting_hours: float = Field(default=0.0, ge=0)  # 지금 단계가 시작된 때부터 기다린 시간(1.33.0 안, 결재 대장)
    approval_plan: ApprovalPlan | None = None


class StateCount(Frozen):
    state: EcnState
    count: int = Field(ge=0)


class BlockLoad(Frozen):
    """블록별 아직 끝나지 않은(분석·검토·보류·승인·실행) 설계변경."""

    block_id: str
    open: int = Field(ge=0)
    total_value: int  # 그 ECN들 최신 개정 총변경비용 대표값 합(한 ECN이 여러 블록이면 블록마다 셈)


class Kpis(Frozen):
    waiting: int = Field(ge=0)  # 결재 대기(검토·보류)
    urgent: int = Field(ge=0)  # 그중 마감 URGENT_DAYS일 이내·지남
    undecided: int = Field(ge=0)  # 아직 결정 안 된(분석·검토·보류)
    undecided_total: Amount  # 그 최신 개정 총변경비용 합
    in_progress: int = Field(ge=0)
    recorded_recent: int = Field(ge=0)  # 기간 안 새 기록(개정, 개발 모드 제외)
    closed_recent: int = Field(ge=0)


class PersonStats(Frozen):
    """담당자별 업무량(업무 분배용 — 사람 평가용이 아님). 개발 모드 기록은 뺀다."""

    actor: Actor
    recorded: int = Field(ge=0)
    requested: int = Field(ge=0)
    rejected: int = Field(ge=0)  # 이 사람이 요청한 검토가 반려된 수
    open: int = Field(ge=0)  # 이 사람이 마지막으로 기록한 아직 끝나지 않은 ECN


class StepHours(Frozen):
    """결재 단계 하나의 처리 시간(그 단계가 시작된 때 — 검토 요청 또는 앞 단계 승인 — 부터 그 단계의 결정까지)."""

    step: ApprovalStep
    decisions: int = Field(ge=0)
    median_hours: float | None = None


class Performance(Frozen):
    """기간 안 결정의 성과(업무 결정만, 시각은 실제 시각). 결정 = 마지막 단계 승인·반려·보류(중간 단계 승인은
    결재선 진행이라 건수에 넣지 않고 단계별 처리 시간에만 넣는다)."""

    days: int | None = None  # None = 전체
    decided: int = Field(ge=0)
    approved: int = Field(ge=0)
    rejected: int = Field(ge=0)
    held: int = Field(ge=0)
    reject_rate: float | None = None
    record_to_request_hours: float | None = None  # 중앙값
    request_to_decision_hours: float | None = None  # 중앙값: 단계마다 그 단계가 시작된 때부터 결정까지
    steps: tuple[StepHours, ...] = ()  # 결재선 단계별 처리 시간(결정이 있던 단계만, 결재선 순)
    settled: int = Field(default=0, ge=0)  # 무비용 담당자 처리(결재선 없이 승인)
    on_time: int = Field(ge=0)  # 업무상 승인일 ≤ 그 개정의 추가손실 0 마감일
    on_time_rate: float | None = None
    protected: int = Field(ge=0)  # 마감 안 승인들의 '마감 다음 날 확정 시 늘어나는 금액' 합(대표값, 계산된 건만)
    protected_cases: int = Field(ge=0)  # 그 금액을 계산한 건수(기간 안 손실이 없던 건은 빠짐)
    cheaper_cases: int = Field(ge=0)  # 더 싼 충족 대안이 있던 승인
    cheaper_total: int = Field(ge=0)
    people: tuple[PersonStats, ...] = ()


class ManageOverview(Frozen):
    today: date  # KST 오늘(실데이터 기록의 기준)
    generated_at: AwareDatetime
    inbox: tuple[InboxItem, ...] = ()
    # 1.33.0 팀장 결재함 '다른 단계에서 기다리는 건(전결 가능)': 파트장·본부장 단계 건(결정은 열어서 전결, 감사 proxy).
    # 파트장·본부장에게는 비어 있다
    proxy: tuple[InboxItem, ...] = ()
    states: tuple[StateCount, ...] = ()
    kpis: Kpis
    blocks: tuple[BlockLoad, ...] = ()
    performance: Performance
    outcomes: OutcomeSummary = OutcomeSummary(count=0)  # 예측 대비 실적(기간과 무관, 실적을 넣은 ECN 전부)
