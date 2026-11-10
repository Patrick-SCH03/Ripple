"""기록 파일의 형식 판과 표 만들기(docs/records.md(기록·결재) 4절).

형식 판 = PRAGMA user_version(지금 4). 모르는 판이면 RecordStoreError로 시작을 멈춘다(계정 파일과 같은 정책 —
새 형식을 옛 코드가 조용히 고쳐 쓰지 않게). 판 1 → 2(계약 1.18.0): 표는 같지만 판 1 코드가 읽지 못하는 내용(감사 줄의
other_version, 기록 본문의 일정 위험)을 쓰기 시작하므로, 판 1 파일은 시작 때 판만 2로 올린다(본문·감사 사슬은 그대로) —
판 1만 받는 옛 코드는 이 파일에서 시작을 멈춘다. 판 2 → 3(계약 1.28.0): 같은 방식 — 통보 기록 줄(action notice,
detail.notice)과 기록 본문의 변경 원인을 쓰기 시작한다. 판 3 → 4(결재선, docs/records.md(기록·결재) 14절): 같은 방식 —
진행 중 검토의 결재선·지금 단계(ReviewInfo.steps·step), 감사 줄의 결재선·결정 단계·전결·무비용(detail.steps·step·proxy·
no_cost), 무비용 담당자 처리 줄(action settle)을 쓰기 시작한다. 옛 검토(단계 없음)는 팀장 한 단계(1/1단계)로 읽는다.
"""

from __future__ import annotations

import sqlite3

from .connection import Connections

FORMAT_VERSION = 4
UPGRADABLE = frozenset({1, 2, 3})  # 표가 같고 판만 낮은 옛 형식: 시작 때 판만 올린다
FILE_NAME = "records.sqlite3"

SCHEMA = """
CREATE TABLE records (
    record_id TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    data_mode TEXT NOT NULL,
    snapshot_id TEXT NOT NULL
);
CREATE TABLE revisions (
    ecn_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    record_id TEXT NOT NULL REFERENCES records(record_id),
    recorded_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    summary TEXT NOT NULL,
    PRIMARY KEY (ecn_id, revision)
);
CREATE TABLE ecns (ecn_id TEXT PRIMARY KEY, status TEXT NOT NULL);
CREATE TABLE requests (
    request_id TEXT PRIMARY KEY,
    ecn_id TEXT NOT NULL,
    analysis_id TEXT NOT NULL,
    response TEXT NOT NULL
);
CREATE TABLE audit (
    seq INTEGER PRIMARY KEY,
    ecn_id TEXT NOT NULL,
    entry TEXT NOT NULL,
    prev TEXT NOT NULL,
    digest TEXT NOT NULL
);
CREATE INDEX audit_by_ecn ON audit(ecn_id, seq);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class RecordStoreError(RuntimeError):
    """기록 파일을 열 수 없다(모르는 형식 판·손상). 메시지는 명사형."""


def prepare(files: Connections) -> None:
    """파일이 없으면 만들고, 있으면 형식 판을 확인한다(옛 판 1·2·3은 4로 올림). 모르는 판·손상이면 RecordStoreError."""
    files.path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with files.lock, files.open() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                tables = db.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
                if tables:
                    raise RecordStoreError("형식 판 없는 기록 파일 — 볼륨 백업 확인 필요")
                # 표 만들기와 형식 판을 한 트랜잭션으로(중간에 멈춰도 반쯤 만든 파일이 남지 않게)
                db.executescript(f"BEGIN IMMEDIATE;{SCHEMA}PRAGMA user_version = {FORMAT_VERSION};COMMIT;")
            elif version in UPGRADABLE:
                # 무엇을 쓰기 전에 판부터 올린다(한 트랜잭션) — 옛 코드가 새 내용이 섞인 파일로 시작하지 않게
                db.executescript(f"BEGIN IMMEDIATE;PRAGMA user_version = {FORMAT_VERSION};COMMIT;")
            elif version != FORMAT_VERSION:
                raise RecordStoreError(f"모르는 기록 파일 형식 판: {version}(되돌릴 때는 볼륨 백업도 함께)")
    except sqlite3.DatabaseError as error:
        raise RecordStoreError(f"기록 파일 열기 불가: {error}") from error
