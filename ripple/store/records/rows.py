"""표 한 줄 읽기·쓰기(SQL): 저장 요청 결과, 상태 행, 기록 본문(ID 대조), 개정 요약, 감사 줄·머리."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable

from ripple.contracts.records import AuditEntry, EcnStatus, RecordBody, RecordSaved, RevisionSummary
from ripple.records import chain
from ripple.records.flow import FlowError

from .identity import checked

StatusRead = Callable[[sqlite3.Connection, str], EcnStatus | None]
StatusWrite = Callable[[sqlite3.Connection, EcnStatus], None]


def prior(db: sqlite3.Connection, request_id: str, ecn_id: str, analysis_id: str) -> RecordSaved | None:
    row = db.execute(
        "SELECT ecn_id, analysis_id, response FROM requests WHERE request_id = ?", (request_id,)
    ).fetchone()
    if row is None:
        return None
    if row[0] != ecn_id or row[1] != analysis_id:
        raise FlowError(422, "request_reused", "같은 저장 요청 ID를 다른 기록에 사용 — 다시 눌러 재시도")
    return RecordSaved.model_validate_json(row[2])


def read_status(db: sqlite3.Connection, ecn_id: str) -> EcnStatus | None:
    row = db.execute("SELECT status FROM ecns WHERE ecn_id = ?", (ecn_id,)).fetchone()
    return None if row is None else EcnStatus.model_validate_json(row[0])


def put_status(db: sqlite3.Connection, status: EcnStatus) -> None:
    db.execute(
        "INSERT INTO ecns (ecn_id, status) VALUES (?, ?) ON CONFLICT(ecn_id) DO UPDATE SET status = excluded.status",
        (status.ecn_id, status.model_dump_json()),
    )


def read_body(db: sqlite3.Connection, record_id: str) -> RecordBody:
    row = db.execute("SELECT body FROM records WHERE record_id = ?", (record_id,)).fetchone()
    if row is None:
        raise FlowError(500, "integrity", "개정이 가리키는 기록 없음 — 감사 로그 확인 필요")
    return checked(record_id, row[0])


def read_summary(db: sqlite3.Connection, ecn_id: str, revision: int) -> RevisionSummary:
    row = db.execute("SELECT summary FROM revisions WHERE ecn_id = ? AND revision = ?", (ecn_id, revision)).fetchone()
    if row is None:
        raise FlowError(500, "integrity", "개정 표에 없는 개정")
    return RevisionSummary.model_validate_json(row[0])


def next_seq(db: sqlite3.Connection) -> int:
    return int(db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM audit").fetchone()[0])


def read_head(db: sqlite3.Connection) -> chain.ChainHead:
    rows = dict(db.execute("SELECT key, value FROM meta WHERE key IN ('head_seq', 'head_digest')").fetchall())
    if not rows:
        return chain.ChainHead(seq=0, digest=chain.GENESIS)
    return chain.ChainHead(seq=int(rows["head_seq"]), digest=rows["head_digest"])


def entry_of(row: tuple[int, str, str, str]) -> AuditEntry:
    """감사 표 한 줄(순번·내용·앞 해시·이 해시) → 감사 줄. 순번 칸과 내용의 순번이 다르면 integrity."""
    seq, entry, prev, digest = row
    data = json.loads(entry)
    if data.get("seq") != seq:
        raise FlowError(500, "integrity", f"{seq}번째 감사 줄의 순번이 내용과 다름")
    return AuditEntry.model_validate({**data, "prev": prev, "digest": digest})
