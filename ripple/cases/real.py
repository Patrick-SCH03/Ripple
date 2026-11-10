"""실데이터 모드의 과거 사례: 합성 사례를 만들지 않고, 기록 중 실적(OutcomeEntry)이 있는 끝난(종료) 실데이터 ECN만.

요청마다 기록·실적 저장소에서 바로 만든다(지도 캐시 아님). 예측 = 승인한 개정의 기록 본문(분석 결과),
실적 = 담당자가 넣은 지금 값, 결정 날짜 = 승인 감사 줄(ripple/records/metrics.py decided_on과 같은 규칙).
없으면 빈 묶음(synthetic=False).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime

from ripple.contracts.brief import PastCase
from ripple.contracts.domain import DataMode
from ripple.contracts.outcomes import OutcomeEntry
from ripple.contracts.records import AuditEntry, EcnAction, EcnListItem, EcnState, RecordBody
from ripple.contracts.result import DeadlineKind
from ripple.records.metrics import decided_on
from ripple.store.outcomes import OutcomeLog
from ripple.store.records import RecordStore

from .features import MapLookup, features_of
from .library import CaseLibrary, StoredCase
from .notes import CHOSEN, CaseFacts, note_of
from .settings import Choice, Similarity


def real_library(records: RecordStore, outcomes: OutcomeLog, similarity: Similarity, lookup: MapLookup) -> CaseLibrary:
    """기록·실적 저장소를 지금 읽어 만든 실데이터 과거 사례 묶음."""
    items, audit, bodies = records.overview_inputs(include_real=True)
    cases = real_cases(items, audit, bodies, outcomes.latest(), lookup)
    return CaseLibrary(
        snapshot_id=None, status="ready", synthetic=False, similarity=similarity, cases=cases, lookup=lookup
    )


def real_cases(
    items: Iterable[EcnListItem],
    audit: Iterable[AuditEntry],
    bodies: Mapping[str, RecordBody],
    outcomes: Mapping[str, OutcomeEntry],
    lookup: MapLookup,
) -> tuple[StoredCase, ...]:
    """종료 상태 · 실적 있음 · 승인한 개정의 본문이 실데이터인 ECN만(ECN 번호 순)."""
    entries = list(audit)
    recorded = _last(entries, EcnAction.RECORD)
    approved = _last(entries, EcnAction.APPROVE)
    cases: list[StoredCase] = []
    for item in sorted(items, key=lambda i: i.status.ecn_id):
        status = item.status
        entry = outcomes.get(status.ecn_id)
        body = bodies.get(entry.record_id) if entry is not None else None
        if status.state is not EcnState.CLOSED or entry is None or body is None or body.data_mode is not DataMode.REAL:
            continue
        key = (status.ecn_id, entry.revision)
        stored = _case(status.title, body, entry, approved.get(key), recorded.get(key), lookup)
        cases.append(stored)
    return tuple(cases)


def _last(audit: list[AuditEntry], action: EcnAction) -> dict[tuple[str, int], datetime]:
    """(ECN, 개정) → 그 행동의 마지막 시각."""
    found: dict[tuple[str, int], datetime] = {}
    for e in sorted(audit, key=lambda e: e.seq):
        if e.action is action and e.revision is not None:
            found[(e.ecn_id, e.revision)] = e.at
    return found


def _case(
    title: str,
    body: RecordBody,
    entry: OutcomeEntry,
    approved_at: datetime | None,
    recorded_at: datetime | None,
    lookup: MapLookup,
) -> StoredCase:
    result = body.result
    request = result.request
    deadline = result.timing.deadline
    decided = decided_on(body, approved_at, recorded_at) if approved_at and recorded_at else None
    days_before = (
        None if decided is None or deadline.kind is DeadlineKind.NONE_IN_HORIZON else (deadline.last_day - decided).days
    )
    facts = CaseFacts(
        choice=Choice.AS_REQUESTED,
        days_before=days_before,
        predicted=result.total,
        actual=entry.cost_krw,
        no_deadline=decided is not None and deadline.kind is DeadlineKind.NONE_IN_HORIZON,
    )
    note_id, note = note_of(facts)
    chosen = (
        CHOSEN[Choice.HOLD_PO]
        if request.holds
        else "선상 설치로 승인"
        if request.outfit_on_board
        else CHOSEN[Choice.AS_REQUESTED]
    )
    case = PastCase(
        case_id=entry.ecn_id,
        title=title,
        decision=EcnAction.APPROVE,
        chosen=chosen,
        predicted=result.total,
        actual_krw=entry.cost_krw,
        predicted_delay_days=result.schedule.max_exit_delay_days,
        actual_delay_days=entry.exit_delay_days,
        days_before_deadline=days_before,
        note=note,
        synthetic=False,
    )
    return StoredCase(case, features_of(result, lookup), entry.ecn_id, None, facts, note_id)
