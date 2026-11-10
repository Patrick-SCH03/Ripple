"""감사 사슬에 줄 덧붙이기(덧붙이기만): 순번·앞 해시·줄 해시와 머리를 쓰기 트랜잭션 안에서 함께 쓴다."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from pydantic import AwareDatetime, Field

from ripple.contracts.base import Frozen
from ripple.contracts.identity import canonical_json
from ripple.contracts.records import Actor, AuditDetail, EcnAction
from ripple.records import chain
from ripple.records.flow import FlowError

from .rows import next_seq, read_head


class _EntryBody(Frozen):
    """감사 줄의 해시 대상(순번 포함, 앞 해시·이 해시 제외)."""

    seq: int = Field(ge=1)
    at: AwareDatetime
    actor: Actor
    action: EcnAction
    ecn_id: str
    revision: int | None = None
    record_id: str | None = None
    detail: AuditDetail


def append(
    db: sqlite3.Connection,
    at: datetime,
    actor: Actor,
    action: EcnAction,
    ecn_id: str,
    revision: int | None,
    record_id: str | None,
    detail: AuditDetail,
) -> int:
    """다음 순번으로 한 줄을 덧붙이고 머리를 옮긴다. 머리가 마지막 줄과 다르면(끝 줄을 지운 파일) integrity."""
    seq = next_seq(db)
    head = read_head(db)
    if head.seq != seq - 1:
        raise FlowError(500, "integrity", "감사 로그 머리가 마지막 줄과 다름 — 감사 로그 확인 필요")
    entry = _EntryBody(
        seq=seq,
        at=at,
        actor=actor,
        action=action,
        ecn_id=ecn_id,
        revision=revision,
        record_id=record_id,
        detail=detail,
    ).model_dump(mode="json")
    digest = chain.entry_hash(head.digest, entry)
    db.execute(
        "INSERT INTO audit (seq, ecn_id, entry, prev, digest) VALUES (?, ?, ?, ?, ?)",
        (seq, ecn_id, canonical_json(entry).decode("utf-8"), head.digest, digest),
    )
    db.execute(
        "INSERT INTO meta (key, value) VALUES ('head_seq', ?), ('head_digest', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(seq), digest),
    )
    return seq
