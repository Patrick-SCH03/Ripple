"""기록·승인·감사 저장소(SQLite 파일 하나, docs/records.md(기록·결재) 4절).

파일: RIPPLE_DATA_DIR/records.sqlite3(라이브는 Railway 볼륨 — 지도·계정과 같은 곳, 깃 제외).
형식 판 = PRAGMA user_version(지금 4, 판 올리기 규칙은 schema.py). 모르는 판이면 RecordStoreError로 시작을 멈춘다.

표
  records    record_id → body(본문 정규 JSON). 같은 내용은 한 줄. 읽을 때마다 본문 해시 = ID를 대조한다
  revisions  (ecn_id, revision) → record_id · recorded_at · actor(JSON) · summary(목록·이력용 요약, 검증이 본문과 대조)
  ecns       ecn_id → status(EcnStatus JSON = 투영)
  requests   request_id → ecn_id · analysis_id · response(RecordSaved JSON): 같은 저장 요청의 재시도는 처음 결과
  audit      seq → ecn_id · entry(정규 JSON, 해시 대상) · prev · digest — 덧붙이기만
  meta       head_seq · head_digest(끝 줄을 지운 것을 잡는 머리)

쓰기는 프로세스 잠금 + BEGIN IMMEDIATE 한 트랜잭션으로 기록·개정·투영·감사·머리·요청 결과를 함께 쓰고, 하나라도 실패하면
모두 되돌린다. 읽기는 잠금 없이(WAL). 서버 한 대 전제(복제본 없음)라 파일 하나로 충분하다.

모듈: schema(형식 판·표) · connection(연결·트랜잭션) · identity(기록 ID·투영·요약) · rows(표 한 줄) ·
audit(감사 줄 덧붙이기) · writes(저장·행동·통보) · reads(목록·상세·지표 재료) · verify(감사 검증).
RecordStore는 이들을 묶는 입구다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ripple.contracts.records import (
    Actor,
    AuditCheck,
    AuditEntry,
    EcnDetail,
    EcnList,
    EcnListItem,
    EcnRecord,
    EcnStatus,
    NoticeLog,
    RecordBody,
    RecordSaved,
)
from ripple.records.flow import Ask, Who

from .connection import Connections
from .identity import record_id_of, summary_of
from .reads import PlanOf, RecordReader
from .rows import put_status, read_status
from .schema import FILE_NAME, FORMAT_VERSION, SCHEMA, RecordStoreError, prepare
from .verify import verify
from .writes import RecordWriter


class RecordStore:
    """기록 저장소 입구: 열기·쓰기·읽기·검증을 협력 객체에 맡긴다. 메서드마다의 규칙은 맡은 쪽 설명에 있다
    (열기 schema.prepare · 쓰기 writes.RecordWriter · 읽기 reads.RecordReader · 검증 verify.verify).

    상태 행 읽기·쓰기(_status·_put_status)는 여기에 두고 쓰기·읽기가 늘 이 두 메서드를 거쳐 부른다(인스턴스에서
    바꿔 끼우면 그대로 쓰인다).
    """

    def __init__(self, data_dir: Path, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.path = data_dir / FILE_NAME
        self._files = Connections(self.path)
        self._writer = RecordWriter(
            self._files.write,
            lambda db, ecn_id: self._status(db, ecn_id),
            lambda db, status: self._put_status(db, status),
            clock,
        )
        self._reader = RecordReader(self._files.read, lambda db, ecn_id: self._status(db, ecn_id))

    # ---------- 열기 ----------

    def start(self) -> None:
        prepare(self._files)

    # ---------- 쓰기 ----------

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
        return self._writer.save(
            body, actor, who, request_id=request_id, analysis_id=analysis_id, expected_version=expected_version
        )

    def prior_save(self, request_id: str, *, ecn_id: str, analysis_id: str) -> RecordSaved | None:
        return self._reader.prior_save(request_id, ecn_id=ecn_id, analysis_id=analysis_id)

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
        return self._writer.act(
            ecn_id,
            ask,
            actor,
            who,
            active_snapshot_id=active_snapshot_id,
            same_version=same_version,
            login_mode=login_mode,
        )

    def notice(self, ecn_id: str, record_id: str, log: NoticeLog, actor: Actor, who: Who) -> AuditEntry:
        return self._writer.notice(ecn_id, record_id, log, actor, who)

    # ---------- 읽기 ----------

    def listing(self, *, include_real: bool) -> EcnList:
        return self._reader.listing(include_real=include_real)

    def detail(
        self,
        ecn_id: str,
        *,
        include_real: bool,
        same_version: Callable[[RecordBody], bool],
        plan: PlanOf | None = None,
    ) -> EcnDetail | None:
        return self._reader.detail(ecn_id, include_real=include_real, same_version=same_version, plan=plan)

    def overview_inputs(
        self, *, include_real: bool
    ) -> tuple[tuple[EcnListItem, ...], tuple[AuditEntry, ...], dict[str, RecordBody]]:
        return self._reader.overview_inputs(include_real=include_real)

    def record(self, record_id: str, *, include_real: bool, plan: PlanOf | None = None) -> EcnRecord | None:
        return self._reader.record(record_id, include_real=include_real, plan=plan)

    # ---------- 검증 ----------

    def verify(self) -> AuditCheck:
        return verify(self._files.read)

    # ---------- 상태 행 ----------

    @staticmethod
    def _status(db: sqlite3.Connection, ecn_id: str) -> EcnStatus | None:
        return read_status(db, ecn_id)

    @staticmethod
    def _put_status(db: sqlite3.Connection, status: EcnStatus) -> None:
        put_status(db, status)


__all__ = [
    "FILE_NAME",
    "FORMAT_VERSION",
    "SCHEMA",
    "PlanOf",
    "RecordStore",
    "RecordStoreError",
    "record_id_of",
    "summary_of",
]
