"""기록에서 계산하는 값(표를 읽지 않음): 기록 ID(본문 정규 JSON의 해시)와 그 대조, 상태 행의 투영, 개정 요약."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from ripple.contracts.identity import canonical_json
from ripple.contracts.records import Actor, EcnStatus, RecordBody, RevisionSummary
from ripple.records.flow import FlowError, Projection


def body_text(body: RecordBody) -> str:
    return canonical_json(body.model_dump(mode="json")).decode("utf-8")


def record_id_of(body: RecordBody) -> str:
    """기록 ID = 본문 전체(유효 데이터 모드 포함, 시각·기록한 사람 제외)의 정규 JSON 해시."""
    return text_record_id(body_text(body))


def text_record_id(text: str) -> str:
    return "R-" + hashlib.sha256(canonical_json(json.loads(text))).hexdigest()[:16]


def checked(record_id: str, text: str) -> RecordBody:
    """본문 해시 = ID를 대조한 뒤 읽는다(감사 줄은 그대로 두고 본문만 바꾼 것을 잡는다)."""
    if text_record_id(text) != record_id:
        raise FlowError(500, "integrity", "저장된 기록 본문이 기록 ID와 불일치 — 감사 로그 확인 필요")
    return RecordBody.model_validate_json(text)


def projection_of(status: EcnStatus) -> Projection:
    review = status.review
    return Projection(
        state=status.state,
        version=status.version,
        revision=status.revision,
        record_id=status.record_id,
        review_seq=review.seq if review else None,
        review_revision=review.revision if review else None,
        review_by=review.requested_by.login_id if review else None,
        approved_revision=status.approved_revision,
        approval_dev=status.approval_dev,
        review_steps=review.steps if review else (),
        review_step=review.step if review else None,
    )


def summary_of(revision: int, record_id: str, recorded_at: datetime, actor: Actor, body: RecordBody) -> RevisionSummary:
    result = body.result
    request = result.request
    return RevisionSummary(
        revision=revision,
        record_id=record_id,
        analysis_id=result.analysis_id,
        recorded_at=recorded_at,
        recorded_by=actor,
        snapshot_id=body.snapshot_id,
        data_mode=body.data_mode,
        title=request.change.title,
        intent=request.change.intent,
        verdict=result.verdict.level,
        total=result.total,
        deadline=result.timing.deadline,
        as_of=request.as_of,
        confirm_on=request.effective_confirm_on,
        holds=request.holds,
        alternatives=request.include_alternatives,
        checklist=len(body.checklist),
    )
