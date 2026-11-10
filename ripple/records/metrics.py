"""결재자(파트장·팀장·본부장) 결재·현황 지표(docs/records.md(기록·결재) 11절). 순수 계산이다(파일·DB를 모름).

저장소가 상태·개정 요약·감사 줄·필요한 본문을 읽어 넘기고, 같은 입력이면 같은 묶음이 나온다.
- 날짜 기준은 기록마다: 실데이터 = KST 오늘·실제 승인 날짜, 합성 = 분석 기준일 + 기록 뒤 지난 날수
  (지도 시계와 실제 시계가 달라서).
- '미루면': 그 개정의 추가손실 곡선에서 마감 다음 날 값(기준일보다 늘어나는 금액, 대표값).
  기간 안 손실이 없으면 계산하지 않는다.
- 개발 모드 요청·결정(actor.dev)은 성과·처리 시간·담당자별 집계에서 뺀다.
- 결재선(14절): 결재함은 보는 사람의 단계 건만(Inputs.steps), 줄마다 앞 단계 승인·남은 결재 소요(결재 계획).
  성과의 결정은 마지막 단계 승인·반려·보류이고 처리 시간은 단계마다 그 단계가 시작된 때부터 잰다.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, date, timedelta
from statistics import median

from ripple.contracts.manage import URGENT_DAYS, BlockLoad, InboxItem, Kpis, ManageOverview, StateCount
from ripple.contracts.outcomes import OutcomeRow, OutcomeSummary
from ripple.contracts.records import ApprovalStep, AuditEntry, EcnAction, EcnListItem, EcnState, StepSign
from ripple.contracts.result import Amount, DeadlineKind

from .approval import approval_plan
from .performance import performance
from .recorded import (
    OPEN,
    UNDECIDED,
    WAITING,
    Inputs,
    blocks_of,
    business_today,
    cheaper_by,
    curve_point,
    decided_on,
    delay_cost,
    kst_date,
)

TOP_BLOCKS = 10


def overview(inputs: Inputs) -> ManageOverview:
    today = kst_date(inputs.now)
    since = inputs.now - timedelta(days=inputs.days) if inputs.days is not None else None
    recent = [e for e in inputs.audit if (since is None or e.at >= since) and not e.actor.dev]
    return ManageOverview(
        today=today,
        generated_at=inputs.now.astimezone(UTC),
        inbox=_inbox(inputs, today, inputs.steps),
        proxy=_inbox(inputs, today, inputs.proxy_steps) if inputs.proxy_steps else (),
        states=_states(inputs.items),
        kpis=_kpis(inputs, recent, today),
        blocks=_blocks(inputs),
        performance=performance(inputs, recent),
        outcomes=outcome_summary(inputs),
    )


def _error_rate(actual: int, predicted: int) -> float | None:
    """(실제 − 예측) ÷ 예측. 예측이 0 이하면 비율을 정의하지 않는다."""
    return round((actual - predicted) / predicted, 4) if predicted > 0 else None


def outcome_summary(inputs: Inputs) -> OutcomeSummary:
    """예측(승인한 개정) 대비 실적(최근에 넣은 순). 보이는 ECN(목록 규칙)만, 승인 본문이 없으면 뺀다."""
    titles = {item.status.ecn_id: item.status.title for item in inputs.items}
    rows: list[OutcomeRow] = []
    for ecn_id, entry in sorted(inputs.outcomes.items()):
        body = inputs.bodies.get(entry.record_id)
        if ecn_id not in titles or body is None:
            continue
        predicted = body.result.total
        rows.append(
            OutcomeRow(
                ecn_id=ecn_id,
                title=titles[ecn_id],
                revision=entry.revision,
                predicted=predicted,
                actual_krw=entry.cost_krw,
                error_rate=_error_rate(entry.cost_krw, predicted.value),
                in_range=predicted.low <= entry.cost_krw <= predicted.high,
                predicted_delay_days=body.result.schedule.max_exit_delay_days,
                actual_delay_days=entry.exit_delay_days,
                entered_at=entry.entered_at,
            )
        )
    rows.sort(key=lambda r: (r.entered_at, r.ecn_id), reverse=True)
    errors = [abs(r.error_rate) for r in rows if r.error_rate is not None]
    return OutcomeSummary(
        count=len(rows),
        median_abs_error=round(median(errors), 4) if errors else None,
        in_range_rate=round(sum(r.in_range for r in rows) / len(rows), 3) if rows else None,
        rows=tuple(rows),
    )


def _signed(audit: Sequence[AuditEntry], review_seq: int) -> tuple[StepSign, ...]:
    """그 검토에서 앞 단계를 넘긴 승인(순번 순): 단계 · 결정한 사람 · 시각 · 전결."""
    return tuple(
        StepSign(step=e.detail.step or ApprovalStep.TEAM_LEAD, actor=e.actor, at=e.at, proxy=e.detail.proxy)
        for e in sorted(audit, key=lambda e: e.seq)
        if e.action is EcnAction.APPROVE and e.detail.review_seq == review_seq and e.detail.to_state in WAITING
    )


def _inbox(inputs: Inputs, today: date, steps: frozenset[ApprovalStep] | None) -> tuple[InboxItem, ...]:
    """검토·보류 중 개정 가운데 지금 단계가 steps인 건(None = 모든 단계). 결재함 = 자기 단계, 전결 묶음 = 전결 단계."""
    rows: list[InboxItem] = []
    for item in inputs.items:
        status, latest = item.status, item.latest
        body = inputs.bodies.get(status.record_id)
        if status.state not in WAITING or status.review is None or body is None:
            continue
        review = status.review
        if steps is not None and review.current not in steps:
            continue  # 다른 단계의 결재(팀장은 전결 묶음으로 따로)
        result = body.result
        late = delay_cost(result)
        base = business_today(body, today, live=inputs.live)
        signed = _signed(inputs.audit, review.seq)
        since = signed[-1].at if signed else review.requested_at
        rows.append(
            InboxItem(
                ecn_id=status.ecn_id,
                title=status.title,
                state=status.state,
                revision=status.revision,
                record_id=status.record_id,
                data_mode=body.data_mode,
                verdict=latest.verdict,
                total=latest.total,
                deadline_kind=latest.deadline.kind,
                deadline=latest.deadline.last_day,
                as_of=latest.as_of,
                confirm_on=latest.confirm_on,
                days_left=(latest.deadline.last_day - base).days,
                delay_cost=late[0] if late else None,
                delay_from=late[1] if late else None,
                horizon_end=result.timing.curve[-1].confirm_on,
                requested_by=review.requested_by,
                requested_at=review.requested_at,
                waiting_hours=_hours(inputs.now - review.requested_at),
                checklist=latest.checklist,
                cheaper_by=cheaper_by(result),
                blocks=blocks_of(result),
                step=review.current,
                steps=review.steps,
                signed=signed,
                step_since=since,
                step_waiting_hours=_hours(inputs.now - since),
                approval_plan=approval_plan(result, base, review),
            )
        )
    rows.sort(key=lambda r: (r.days_left, r.requested_at, r.ecn_id))
    return tuple(rows)


def _hours(span: timedelta) -> float:
    """기다린 시간(시간, 소수 한 자리, 음수면 0)."""
    return round(max(0.0, span.total_seconds() / 3600), 1)


def _states(items: Iterable[EcnListItem]) -> tuple[StateCount, ...]:
    counts = Counter(item.status.state for item in items)
    return tuple(StateCount(state=s, count=counts.get(s, 0)) for s in EcnState if s is not EcnState.REQUESTED)


def _sum(amounts: Iterable[Amount]) -> Amount:
    value = low = high = 0
    for amount in amounts:
        value, low, high = value + amount.value, low + amount.low, high + amount.high
    return Amount(value=value, low=low, high=high)


def _kpis(inputs: Inputs, recent: Sequence[AuditEntry], today: date) -> Kpis:
    items = inputs.items
    waiting = [i for i in items if i.status.state in WAITING]
    undecided = [i for i in items if i.status.state in UNDECIDED]

    def urgent(item: EcnListItem) -> bool:
        # 탐색 기간 끝까지 손실이 없는 건은 마감이 없다(결재함 '마감 3일 이내' 거르기와 같게)
        if item.latest.deadline.kind is DeadlineKind.NONE_IN_HORIZON:
            return False
        body = inputs.bodies.get(item.status.record_id)
        base = business_today(body, today, live=inputs.live) if body is not None else item.latest.as_of
        return (item.latest.deadline.last_day - base).days <= URGENT_DAYS

    return Kpis(
        waiting=len(waiting),
        urgent=sum(1 for i in waiting if urgent(i)),
        undecided=len(undecided),
        undecided_total=_sum(i.latest.total for i in undecided),
        in_progress=sum(1 for i in items if i.status.state is EcnState.IN_PROGRESS),
        recorded_recent=sum(1 for e in recent if e.action is EcnAction.RECORD),
        closed_recent=sum(1 for e in recent if e.action is EcnAction.CLOSE),
    )


def _blocks(inputs: Inputs) -> tuple[BlockLoad, ...]:
    load: dict[str, list[int]] = defaultdict(list)
    for item in inputs.items:
        body = inputs.bodies.get(item.status.record_id)
        if item.status.state in OPEN and body is not None:
            for block in blocks_of(body.result):
                load[block].append(item.latest.total.value)
    rows = [BlockLoad(block_id=b, open=len(v), total_value=sum(v)) for b, v in load.items()]
    rows.sort(key=lambda r: (-r.open, -r.total_value, r.block_id))
    return tuple(rows[:TOP_BLOCKS])


__all__ = [
    "Inputs",
    "blocks_of",
    "business_today",
    "cheaper_by",
    "curve_point",
    "decided_on",
    "delay_cost",
    "kst_date",
    "outcome_summary",
    "overview",
]
