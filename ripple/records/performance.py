"""결재·현황의 성과(docs/records.md(기록·결재) 11·14절): 기간 안 업무 결정의 건수·처리 시간·기한 안 결재·대안 차액·
담당자별 업무량. 순수 계산이다.

- 결정 = 마지막 단계 승인 · 어느 단계든 반려·보류(중간 단계 승인은 결재선 진행이라 건수에 넣지 않는다. 반려는
  어느 단계에서든 검토를 끝내고, 보류도 그 단계 결재자의 결정 행위다).
- 처리 시간은 단계마다 그 단계가 시작된 때(검토 요청 또는 같은 검토의 앞 단계 승인)부터 그 단계의 결정까지.
- 개발 모드 요청·결정(actor.dev)은 뺀다(업무 기록이 아님) — recent는 호출자가 이미 거른 기간 안 업무 줄이다.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from ripple.contracts.manage import Performance, PersonStats, StepHours
from ripple.contracts.records import Actor, ApprovalStep, AuditEntry, EcnAction, EcnState

from .recorded import DECIDE, OPEN, Inputs, cheaper_by, decided_on, delay_cost


def performance(inputs: Inputs, recent: Sequence[AuditEntry]) -> Performance:
    decisions = [e for e in recent if final(e)]
    approvals = [e for e in decisions if e.action is EcnAction.APPROVE]
    rejected = sum(1 for e in decisions if e.action is EcnAction.REJECT)
    summary = _approvals(inputs, approvals)
    waits = _step_waits(inputs.audit, recent)
    return Performance(
        days=inputs.days,
        decided=len(decisions),
        approved=len(approvals),
        rejected=rejected,
        held=sum(1 for e in decisions if e.action is EcnAction.HOLD),
        reject_rate=round(rejected / len(decisions), 3) if decisions else None,
        record_to_request_hours=_median_hours(_record_to_request(inputs.audit, recent)),
        request_to_decision_hours=_median_hours([span for _step, span in waits]),
        steps=_step_hours(waits),
        settled=sum(1 for e in recent if e.action is EcnAction.SETTLE),
        on_time=summary.on_time,
        on_time_rate=round(summary.on_time / len(approvals), 3) if approvals else None,
        protected=summary.protected,
        protected_cases=summary.protected_cases,
        cheaper_cases=summary.cheaper_cases,
        cheaper_total=summary.cheaper_total,
        people=_people(inputs, recent),
    )


def final(entry: AuditEntry) -> bool:
    """결정으로 세는 줄: 마지막 단계 승인 · 어느 단계든 반려·보류(중간 단계 승인은 결재선 진행)."""
    if entry.action is EcnAction.APPROVE:
        return entry.detail.to_state is EcnState.APPROVED
    return entry.action in DECIDE


def _median_hours(spans: Sequence[timedelta]) -> float | None:
    return round(median(s.total_seconds() for s in spans) / 3600, 1) if spans else None


@dataclass
class _Approvals:
    on_time: int = 0
    protected: int = 0
    protected_cases: int = 0
    cheaper_cases: int = 0
    cheaper_total: int = 0


def _approvals(inputs: Inputs, approvals: Sequence[AuditEntry]) -> _Approvals:
    recorded = _recorded_at(inputs.audit)
    out = _Approvals()
    for entry in approvals:
        body = inputs.bodies.get(entry.record_id or "")
        made = recorded.get((entry.ecn_id, entry.revision or 0))
        if body is None or made is None:
            continue
        result = body.result
        if decided_on(body, entry.at, made, live=inputs.live) <= result.timing.deadline.last_day:
            out.on_time += 1
            late = delay_cost(result)
            if late is not None:
                out.protected += max(0, late[0])
                out.protected_cases += 1
        saving = cheaper_by(result)
        if saving:
            out.cheaper_cases += 1
            out.cheaper_total += saving
    return out


def _step_waits(audit: Sequence[AuditEntry], recent: Sequence[AuditEntry]) -> list[tuple[ApprovalStep, timedelta]]:
    """결정(중간 단계 승인 포함)마다 (단계, 그 단계가 시작된 때부터 걸린 시간). 단계 시작 = 검토 요청 또는 같은
    검토의 앞 단계 승인(보류는 단계를 다시 시작하지 않는다). 개발 모드로 요청한 검토는 뺀다."""
    by_seq = {e.seq: e for e in audit}
    started: dict[int, datetime] = {}  # 검토 순번 → 지금 단계가 시작된 시각
    waits: list[tuple[ApprovalStep, timedelta]] = []
    wanted = {e.seq for e in recent}
    for e in sorted(audit, key=lambda e: e.seq):
        if e.action is EcnAction.REQUEST_REVIEW:
            started[e.seq] = e.at
            continue
        request = by_seq.get(e.detail.review_seq or 0)
        if e.action not in DECIDE or request is None:
            continue
        begin = started.get(request.seq, request.at)
        if e.seq in wanted and not request.actor.dev:
            waits.append((e.detail.step or ApprovalStep.TEAM_LEAD, e.at - begin))
        if e.action is EcnAction.APPROVE and e.detail.to_state is EcnState.IN_REVIEW:
            started[request.seq] = e.at  # 다음 단계 시작
    return waits


def _step_hours(waits: Sequence[tuple[ApprovalStep, timedelta]]) -> tuple[StepHours, ...]:
    """결재선 순서(파트장 → 팀장 → 본부장)로 결정이 있던 단계만."""
    rows: list[StepHours] = []
    for step in ApprovalStep:
        spans = [span for s, span in waits if s is step]
        if spans:
            rows.append(StepHours(step=step, decisions=len(spans), median_hours=_median_hours(spans)))
    return tuple(rows)


def _recorded_at(audit: Sequence[AuditEntry]) -> dict[tuple[str, int], datetime]:
    """(ECN, 개정) → 그 개정을 기록한 시각."""
    return {(e.ecn_id, e.revision or 0): e.at for e in audit if e.action is EcnAction.RECORD}


def _record_to_request(audit: Sequence[AuditEntry], recent: Sequence[AuditEntry]) -> list[timedelta]:
    """업무 검토 요청마다 그 개정을 (업무로) 기록한 줄에서 요청까지 걸린 시간."""
    recorded = {(e.ecn_id, e.revision or 0): e.at for e in audit if e.action is EcnAction.RECORD and not e.actor.dev}
    return [
        e.at - recorded[(e.ecn_id, e.revision or 0)]
        for e in recent
        if e.action is EcnAction.REQUEST_REVIEW and (e.ecn_id, e.revision or 0) in recorded
    ]


def _people(inputs: Inputs, recent: Sequence[AuditEntry]) -> tuple[PersonStats, ...]:
    by_seq = {e.seq: e for e in inputs.audit}
    actors: dict[str, Actor] = {}
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for e in recent:
        if e.action in (EcnAction.RECORD, EcnAction.REQUEST_REVIEW):
            actors.setdefault(e.actor.login_id, e.actor)
            counts[e.actor.login_id]["recorded" if e.action is EcnAction.RECORD else "requested"] += 1
        request = by_seq.get(e.detail.review_seq or 0)
        if e.action is EcnAction.REJECT and request is not None and not request.actor.dev:
            actors.setdefault(request.actor.login_id, request.actor)
            counts[request.actor.login_id]["rejected"] += 1
    last = _last_recorders(inputs.audit)
    for item in inputs.items:
        who = last.get(item.status.ecn_id)
        if who is not None and item.status.state in OPEN:
            actors.setdefault(who.login_id, who)
            counts[who.login_id]["open"] += 1
    rows = [
        PersonStats(
            actor=actor,
            recorded=counts[login]["recorded"],
            requested=counts[login]["requested"],
            rejected=counts[login]["rejected"],
            open=counts[login]["open"],
        )
        for login, actor in actors.items()
    ]
    rows.sort(key=lambda r: (-(r.recorded + r.requested + r.open), r.actor.login_id))
    return tuple(rows)


def _last_recorders(audit: Sequence[AuditEntry]) -> dict[str, Actor]:
    """ECN마다 마지막으로 (업무로) 기록한 사람."""
    last: dict[str, Actor] = {}
    for e in sorted(audit, key=lambda e: e.seq):
        if e.action is EcnAction.RECORD and not e.actor.dev:
            last[e.ecn_id] = e.actor
    return last
