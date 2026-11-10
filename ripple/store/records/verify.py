"""감사 검증: 사슬(순번·앞 해시·줄 해시·머리) + 참조 무결성(기록 본문 해시·개정 연결·감사 줄의 기록 = 개정·투영 = 재생).

문제 문장은 아래 단계 순서대로 쌓인다(사슬 → 기록 본문 → 개정 표 → 감사 줄 → 개정의 기록 줄 → 상태).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from ripple.contracts.domain import DataMode
from ripple.contracts.records import Actor, AuditCheck, AuditEntry, EcnAction, EcnStatus, RecordBody, RevisionSummary
from ripple.records import chain
from ripple.records.flow import FlowError, replay

from .connection import Transaction
from .identity import checked, projection_of, summary_of
from .rows import entry_of, read_body, read_head

Revisions = dict[tuple[str, int], str]  # (ECN, 개정) → 기록 ID
Recorded = dict[tuple[str, int], tuple[datetime, Actor]]  # (ECN, 개정) → 개정 표의 기록 시각·기록한 사람


def verify(read: Transaction) -> AuditCheck:
    """읽기 한 시점에서 표를 모두 읽어 단계별로 대조한다."""
    problems: list[str] = []
    with read() as db:
        rows = db.execute("SELECT seq, ecn_id, entry, prev, digest FROM audit ORDER BY seq").fetchall()
        links = [
            chain.ChainLink(seq=seq, prev=prev, digest=digest, entry=_object(entry))
            for seq, _e, entry, prev, digest in rows
        ]
        checked_chain = chain.verify(links, read_head(db))
        if not checked_chain.ok:
            problems.append(f"감사 사슬이 {checked_chain.broken_at}번째 줄에서 어긋남")
        records = db.execute("SELECT record_id, body, data_mode, snapshot_id FROM records").fetchall()
        bodies = _bodies(records, problems)
        revisions, recorded = _revisions(db, problems)
        entries = _entries(rows, revisions, problems)
        statuses = _statuses(db, problems)
    _record_lines(entries, revisions, recorded, problems)
    _states(statuses, entries, revisions, bodies, problems)
    return AuditCheck(
        ok=not problems,
        entries=len(rows),
        records=len(records),
        broken_at=checked_chain.broken_at,
        head=checked_chain.head,
        problems=tuple(problems),
    )


def _object(text: str) -> dict[str, Any]:
    """감사 줄 내용(JSON 객체). 깨졌으면 원문을 담은 객체 — 줄 해시가 맞지 않아 사슬이 그 줄에서 어긋난다."""
    try:
        data = json.loads(text)
    except ValueError:
        return {"unreadable": text}
    return data if isinstance(data, dict) else {"unreadable": text}


def _statuses(db: sqlite3.Connection, problems: list[str]) -> dict[str, EcnStatus | None]:
    """ECN 상태 칸. 읽지 못하면 None(문제에 적음)."""
    statuses: dict[str, EcnStatus | None] = {}
    for ecn, text in db.execute("SELECT ecn_id, status FROM ecns"):
        try:
            statuses[ecn] = EcnStatus.model_validate_json(text)
        except ValidationError:
            statuses[ecn] = None
            problems.append(f"{ecn}의 상태 읽기 불가")
    return statuses


def _bodies(records: list[Any], problems: list[str]) -> dict[str, RecordBody]:
    """기록 본문이 ID(본문 해시)와 맞고, 색인 칸(데이터 모드·지도)이 본문과 같은가."""
    bodies: dict[str, RecordBody] = {}
    for record_id, text, mode, snapshot_id in records:
        try:
            body = checked(record_id, text)
        except (FlowError, ValueError):  # ValueError: JSON이 깨짐(ValidationError 포함)
            problems.append(f"기록 {record_id}의 본문이 ID와 불일치")
            continue
        bodies[record_id] = body
        if body.data_mode.value != mode or body.snapshot_id != snapshot_id:
            problems.append(f"기록 {record_id}의 색인 값이 본문과 다름")
    return bodies


def _revisions(db: sqlite3.Connection, problems: list[str]) -> tuple[Revisions, Recorded]:
    """개정 표: 요약이 기록 본문과 같은가, ECN마다 개정 번호가 1부터 이어지는가."""
    revisions: Revisions = {}
    recorded: Recorded = {}
    for ecn, rev, record_id, recorded_at, actor, summary in db.execute(
        "SELECT ecn_id, revision, record_id, recorded_at, actor, summary FROM revisions"
    ):
        revisions[(ecn, rev)] = record_id
        try:
            when, who = datetime.fromisoformat(recorded_at), Actor.model_validate_json(actor)
            expected = summary_of(rev, record_id, when, who, read_body(db, record_id))
        except (ValidationError, ValueError, FlowError):
            problems.append(f"{ecn} 개정 {rev}의 기록 읽기 불가")
            continue
        recorded[(ecn, rev)] = (when, who)
        try:
            stored = RevisionSummary.model_validate_json(summary)
        except ValidationError:
            problems.append(f"{ecn} 개정 {rev}의 요약 읽기 불가")
            continue
        if stored != expected:
            problems.append(f"{ecn} 개정 {rev}의 요약이 기록 본문과 다름")
    for ecn in {ecn for ecn, _rev in revisions}:
        numbers = sorted(rev for e, rev in revisions if e == ecn)
        if numbers != list(range(1, len(numbers) + 1)):
            problems.append(f"{ecn}의 개정 번호가 끊김")
    return revisions, recorded


def _entries(rows: list[Any], revisions: Revisions, problems: list[str]) -> dict[str, list[AuditEntry]]:
    """감사 줄: 읽을 수 있고, ECN 색인·개정 표의 기록과 맞는가. ECN별 감사 줄(순번 순)을 돌려준다."""
    entries: dict[str, list[AuditEntry]] = {}
    for row in rows:
        try:
            entry = entry_of((row[0], row[2], row[3], row[4]))
        except (ValueError, AttributeError, FlowError):  # 깨진 JSON·객체가 아닌 JSON·형식 오류(ValidationError)
            problems.append(f"{row[0]}번째 감사 줄 읽기 불가")
            continue
        if entry.ecn_id != row[1]:
            problems.append(f"{entry.seq}번째 감사 줄의 ECN이 색인과 다름")
        if entry.revision is not None and revisions.get((entry.ecn_id, entry.revision)) != entry.record_id:
            problems.append(f"{entry.seq}번째 감사 줄의 기록이 개정 표와 다름")
        entries.setdefault(entry.ecn_id, []).append(entry)
    return entries


def _record_lines(
    entries: dict[str, list[AuditEntry]], revisions: Revisions, recorded: Recorded, problems: list[str]
) -> None:
    """개정 표의 줄마다 그 개정을 남긴 감사 줄(기록)이 있고, 기록한 사람·시각이 그 줄과 같은가.

    감사 줄 없이 끼워 넣은 개정 · 사슬은 그대로 두고 개정 표의 기록자·시각만 바꾼 것을 잡는다.
    """
    lines = {(e.ecn_id, e.revision): e for found in entries.values() for e in found if e.action is EcnAction.RECORD}
    for ecn, rev in sorted(set(revisions) - set(lines)):
        problems.append(f"{ecn} 개정 {rev}의 기록 감사 줄 없음")
    for key, (when, who) in sorted(recorded.items()):
        line = lines.get(key)
        if line is not None and (line.at != when or line.actor != who):
            problems.append(f"{key[0]} 개정 {key[1]}의 기록한 사람·시각이 감사 줄과 다름")


def _states(
    statuses: dict[str, EcnStatus | None],
    entries: dict[str, list[AuditEntry]],
    revisions: Revisions,
    bodies: dict[str, RecordBody],
    problems: list[str],
) -> None:
    """상태 = 감사 줄 재생, 투영 밖의 상태 칸(실데이터 표시·제목·지도)도 기록 본문에서 다시 만들어 대조한다."""
    for ecn, status in statuses.items():
        if status is None:  # 읽기 불가(문제는 _statuses가 적음)
            continue
        try:
            replayed = replay(entries.get(ecn, []))
        except ValueError as error:
            problems.append(f"{ecn}: {error}")
            continue
        if replayed != projection_of(status):
            problems.append(f"{ecn}의 상태가 감사 로그를 다시 돌린 결과와 다름")
        kept = [bodies[rid] for (e, _rev), rid in sorted(revisions.items()) if e == ecn and rid in bodies]
        if kept and (
            status.title != kept[-1].result.request.change.title or status.snapshot_id != kept[-1].snapshot_id
        ):
            problems.append(f"{ecn}의 제목·지도가 최신 기록과 다름")
        if status.real != any(body.data_mode is DataMode.REAL for body in kept):
            problems.append(f"{ecn}의 실데이터 표시가 기록과 다름")
    for ecn in set(entries) - set(statuses):
        problems.append(f"{ecn}의 감사 줄은 있는데 상태 없음")
