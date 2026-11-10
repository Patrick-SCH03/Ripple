"""쓰기: 기록 저장·결재 행동·통보 기록(docs/records.md(기록·결재) 2·3절).

쓰기마다 한 트랜잭션으로 기록·개정·투영·감사·머리·요청 결과를 함께 쓰고, 하나라도 실패하면 모두 되돌린다.
상태 행은 받은 함수(read_status·put_status)로만 읽고 쓴다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ripple.contracts.domain import DataMode
from ripple.contracts.records import (
    Actor,
    AuditEntry,
    EcnAction,
    EcnStatus,
    NoticeLog,
    RecordBody,
    RecordSaved,
    ReviewInfo,
)
from ripple.records.approval import APPROVAL_LINE, no_cost
from ripple.records.flow import Ask, FlowError, Projection, Who, act, check_record, notice, record

from .audit import append
from .connection import Transaction
from .identity import body_text, projection_of, summary_of, text_record_id
from .rows import StatusRead, StatusWrite, entry_of, next_seq, prior, read_body, read_summary

KST = timezone(timedelta(hours=9))  # 통보 날짜가 '앞날'인지 가르는 오늘(서머타임 없음)


@dataclass(frozen=True, slots=True)
class Incoming:
    """저장 요청 하나: 본문과 그 정규 JSON·기록 ID(본문 해시), 기록한 사람."""

    body: RecordBody
    text: str
    record_id: str
    actor: Actor
    who: Who

    @classmethod
    def of(cls, body: RecordBody, actor: Actor, who: Who) -> Incoming:
        text = body_text(body)
        return cls(body, text, text_record_id(text), actor, who)


def _review_after(
    review: ReviewInfo | None, action: EcnAction, nxt: Projection, actor: Actor, now: datetime
) -> ReviewInfo | None:
    """행동 뒤 상태 행의 진행 중 검토: 검토 요청은 새 검토(결재선 고정, 1단계), 검토가 닫혔으면 없음, 앞 단계 승인은
    다음 단계로(요청한 사람·시각은 그대로)."""
    if action is EcnAction.REQUEST_REVIEW:
        assert nxt.review_seq is not None and nxt.review_revision is not None
        return ReviewInfo(
            seq=nxt.review_seq,
            revision=nxt.review_revision,
            requested_by=actor,
            requested_at=now,
            steps=nxt.review_steps,
            step=1,
        )
    if nxt.review_seq is None:
        return None
    if review is not None and nxt.review_step is not None and nxt.review_step != review.step:
        return review.model_copy(update={"step": nxt.review_step})
    return review


class RecordWriter:
    """쓰기 트랜잭션·상태 행 함수·시계를 받아 저장·행동·통보를 한다(시계는 쓸 때마다 한 번 부른다)."""

    def __init__(
        self, write: Transaction, read_status: StatusRead, put_status: StatusWrite, clock: Callable[[], datetime]
    ) -> None:
        self._write = write
        self._read_status = read_status
        self._put_status = put_status
        self._clock = clock

    def save(
        self,
        body: RecordBody,
        actor: Actor,
        who: Who,
        *,
        request_id: str,
        analysis_id: str,
        expected_version: int,
    ) -> RecordSaved:
        """기록 저장. 같은 저장 요청 ID의 재시도는 처음 결과를, 최신 개정과 같은 본문이면 그 개정을
        (새 개정 없음) 돌려준다."""
        incoming = Incoming.of(body, actor, who)
        ecn_id = body.ecn_id
        with self._write() as db:
            earlier = prior(db, request_id, ecn_id, analysis_id)
            if earlier is not None:
                return earlier
            status = self._read_status(db, ecn_id)
            current = projection_of(status) if status is not None else None
            if (current.version if current else 0) != expected_version:
                raise FlowError(409, "ecn_changed", "설계변경 상태 변경됨 — 다시 불러온 뒤 재시도")
            stored = db.execute("SELECT body FROM records WHERE record_id = ?", (incoming.record_id,)).fetchone()
            if stored is not None and stored[0] != incoming.text:
                raise FlowError(500, "integrity", "같은 기록 ID에 다른 본문 저장됨 — 감사 로그 확인 필요")
            if status is not None and current is not None and current.record_id == incoming.record_id:
                check_record(current, who)
                saved = RecordSaved(status=status, revision=read_summary(db, ecn_id, current.revision), created=False)
            else:
                saved = self._revise(db, incoming, status, current, new_body=stored is None)
            db.execute(
                "INSERT INTO requests (request_id, ecn_id, analysis_id, response) VALUES (?, ?, ?, ?)",
                (request_id, ecn_id, analysis_id, saved.model_dump_json()),
            )
            return saved

    def _revise(
        self,
        db: sqlite3.Connection,
        incoming: Incoming,
        status: EcnStatus | None,
        current: Projection | None,
        *,
        new_body: bool,
    ) -> RecordSaved:
        """새 개정: (처음 보는 본문이면) 기록 → 개정 → 감사 줄 → 상태 행."""
        body, record_id, actor = incoming.body, incoming.record_id, incoming.actor
        ecn_id = body.ecn_id
        revision = 1 if current is None else current.revision + 1
        outcome = record(current, revision, record_id, incoming.who)
        now = self._clock()
        if new_body:
            db.execute(
                "INSERT INTO records (record_id, body, data_mode, snapshot_id) VALUES (?, ?, ?, ?)",
                (record_id, incoming.text, body.data_mode.value, body.snapshot_id),
            )
        summary = summary_of(revision, record_id, now, actor, body)
        db.execute(
            "INSERT INTO revisions (ecn_id, revision, record_id, recorded_at, actor, summary) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ecn_id, revision, record_id, now.isoformat(), actor.model_dump_json(), summary.model_dump_json()),
        )
        append(db, now, actor, EcnAction.RECORD, ecn_id, revision, record_id, outcome.detail)
        new_status = EcnStatus(
            ecn_id=ecn_id,
            title=body.result.request.change.title,
            state=outcome.projection.state,
            version=outcome.projection.version,
            revision=revision,
            record_id=record_id,
            snapshot_id=body.snapshot_id,
            real=(status.real if status else False) or body.data_mode is DataMode.REAL,
            updated_at=now,
        )
        self._put_status(db, new_status)
        return RecordSaved(status=new_status, revision=summary, created=True)

    def act(
        self,
        ecn_id: str,
        ask: Ask,
        actor: Actor,
        who: Who,
        *,
        active_snapshot_id: str,
        same_version: Callable[[RecordBody], bool],
        login_mode: bool,
    ) -> EcnStatus:
        """검토 요청·취소·결정·무비용 담당자 처리·실행·종료. 지도 대조는 호출자가 잡은 작업 공간(커밋 시점)의 지도로,
        계산 판 대조는 호출자가 준 함수로(최신 개정 본문을 트랜잭션 안에서 읽어 넘긴다) 한다. 무비용 여부도 그 본문으로
        보고, 검토 요청은 지금의 결재선(APPROVAL_LINE)을 그 검토에 고정한다."""
        with self._write() as db:
            status = self._read_status(db, ecn_id)
            if status is None:
                raise FlowError(404, "not_found", "기록 없는 설계변경")
            current = projection_of(status)
            body = read_body(db, current.record_id)
            seq = next_seq(db)
            outcome = act(
                current,
                ask,
                who,
                checklist=frozenset(item.key for item in body.checklist),
                same_map=body.snapshot_id == active_snapshot_id,
                same_version=same_version(body),
                login_mode=login_mode,
                seq=seq,
                no_cost=no_cost(body.result),
                line=APPROVAL_LINE,
            )
            now = self._clock()
            appended = append(db, now, actor, ask.action, ecn_id, current.revision, current.record_id, outcome.detail)
            assert appended == seq
            nxt = outcome.projection
            review = _review_after(status.review, ask.action, nxt, actor, now)
            new_status = status.model_copy(
                update={
                    "state": nxt.state,
                    "version": nxt.version,
                    "review": review,
                    "approved_revision": nxt.approved_revision,
                    "approval_dev": nxt.approval_dev,
                    "updated_at": now,
                }
            )
            new_status = EcnStatus.model_validate(new_status.model_dump())  # 상태별 규칙을 다시 검사
            self._put_status(db, new_status)
            return new_status

    def notice(self, ecn_id: str, record_id: str, log: NoticeLog, actor: Actor, who: Who) -> AuditEntry:
        """통보 기록 한 줄(1.28.0)을 감사 사슬에 덧붙인다. 상태·버전은 그대로라 상태 행은 쓰지 않는다."""
        with self._write() as db:
            status = self._read_status(db, ecn_id)
            if status is None:
                raise FlowError(404, "not_found", "기록 없는 설계변경 — 먼저 기록 필요")
            current = projection_of(status)
            now = self._clock()
            detail = notice(current, record_id, log, who, now.astimezone(KST).date())
            seq = append(db, now, actor, EcnAction.NOTICE, ecn_id, current.revision, current.record_id, detail)
            row = db.execute("SELECT entry, prev, digest FROM audit WHERE seq = ?", (seq,)).fetchone()
        return entry_of((seq, row[0], row[1], row[2]))
