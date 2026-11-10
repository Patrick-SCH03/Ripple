"""기록 비우기(운영, docs/operations.md(배포) 4절).

서버가 시작할 때 표지(RIPPLE_RESET_RECORDS)가 새 값이면 기록·실적·수정 기록 파일을 보관 폴더로 옮긴다.
시험으로 남긴 설계변경 기록·검토 요청·결재·감사 로그와 실적을 화면에서 비울 때 쓴다.
범위(RIPPLE_RESET_SCOPE)가 all이면 가져온 지도·활성 지도·상태 갱신 기록·열 매핑 기억도 함께 옮겨
기본 합성 지도로 시작한다.
지우지 않고 옮기므로, 되살리려면 서버를 멈춘 뒤 보관 폴더의 파일을 데이터 폴더로 되돌린다.
같은 표지로는 한 번만 한다(보관 폴더의 DONE 파일).
계정·세션은 어느 범위에서도 건드리지 않는다.
기록 저장소·실적 기록·지도 저장소가 파일을 열기 전에 불러야 한다(열린 SQLite 파일을 옮기지 않게).

시연 기록 자동 새로 채우기(docs/operations.md(서비스) 7절)는 서버가 도는 중에도 바꿔 끼운다(swap_records): 따로 채운
준비 폴더의 기록·실적·수정 기록 파일을 데이터 폴더 문(gate.py)을 혼자 잡은 채 지금 파일과 바꾸고, 지금 파일은
자동 보관 폴더(archive/records-auto-<KST 시각>, DONE에 auto)로 옮긴다. 자동 보관은 최근 14개만 남긴다(사람이 표지로
만든 보관은 그대로).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from ripple.config.files import replace_file
from ripple.config.settings import ResetScope

from .corrections import FILE_NAME as CORRECTIONS_FILE
from .gate import gate_of
from .outcomes import FILE_NAME as OUTCOMES_FILE
from .records import FILE_NAME as RECORDS_FILE
from .updates import FILE_NAME as UPDATES_FILE

LABEL = re.compile(r"^[0-9A-Za-z_-]{1,40}$")  # ripple/config/settings.py가 같은 꼴로 미리 확인
TARGETS = (RECORDS_FILE, OUTCOMES_FILE, CORRECTIONS_FILE)  # 1.27.0 수정 기록도 시험 기록과 함께 비운다
# 범위 all에서 더 옮기는 것: 상태 갱신 기록·활성 지도·열 매핑 기억·지도 폴더
WORKSPACE_TARGETS = (UPDATES_FILE, "active.json", "mappings.json", "snapshots")
SUFFIXES = ("", "-wal", "-shm", "-journal")  # SQLite 본 파일과 함께 다니는 파일
ARCHIVE_DIR = "archive"
DONE = "DONE"
AUTO_PREFIX = "records-auto-"  # 시연 기록 자동 새로 채우기의 보관 폴더(DONE에 "auto": true)
AUTO_KEEP = 14  # 자동 보관을 이만큼만 남긴다
STAGING = ".seed-staging"  # 시연 기록을 미리 채우는 준비 폴더(데이터 폴더 안 — 같은 볼륨이라 옮기기가 바꿔 끼우기)
KST = timezone(timedelta(hours=9))
log = logging.getLogger(__name__)


def check_label(label: str) -> str:
    if not LABEL.fullmatch(label):
        raise ValueError(f"RIPPLE_RESET_RECORDS 형식 오류 — 영문·숫자·_·- 1~40자만 가능: {label!r}")
    return label


def archive_folder(data_dir: Path, label: str) -> Path:
    return data_dir / ARCHIVE_DIR / f"records-{check_label(label)}"


def done_scope(data_dir: Path, label: str) -> str | None:
    """이 표지로 이미 비웠으면 그때의 범위(옛 DONE에는 범위가 없어 records), 아니면 None."""
    done = archive_folder(data_dir, label) / DONE
    if not done.exists():
        return None
    try:
        return str(json.loads(done.read_text(encoding="utf-8")).get("scope", "records"))
    except (OSError, ValueError):
        return "records"


def archive_records(
    data_dir: Path, label: str, *, scope: ResetScope = "records", now: datetime | None = None
) -> list[str] | None:
    """기록·실적 파일(범위 all이면 지도·상태 갱신·매핑 기억까지)을 보관 폴더로 옮기고 옮긴 이름을 돌려준다.
    이 표지로 이미 했으면 None(아무것도 안 함)."""
    folder = archive_folder(data_dir, label)
    done = folder / DONE
    if done.exists():
        return None
    folder.mkdir(parents=True, exist_ok=True)
    names = TARGETS + (WORKSPACE_TARGETS if scope == "all" else ())
    moved: list[str] = []
    for name in names:
        for suffix in SUFFIXES:
            source = data_dir / f"{name}{suffix}"
            if source.exists():
                replace_file(source, folder / source.name)  # 지도 폴더도 같은 볼륨 안이라 통째로 옮긴다
                moved.append(source.name)
    stamp = (now or datetime.now(UTC)).isoformat()
    record = {"label": label, "scope": scope, "at": stamp, "moved": moved}
    done.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return moved


# ---------- 시연 기록 자동 새로 채우기 ----------


def staging_folder(data_dir: Path) -> Path:
    """빈 준비 폴더(전에 남은 것은 지운다 — 멈춘 채우기의 찌꺼기)."""
    folder = data_dir / STAGING
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    return folder


def _files(folder: Path) -> list[Path]:
    return [
        folder / f"{name}{suffix}" for name in TARGETS for suffix in SUFFIXES if (folder / f"{name}{suffix}").exists()
    ]


def _auto_folder(data_dir: Path, now: datetime) -> Path:
    stamp = now.astimezone(KST).strftime("%Y%m%d-%H%M%S")
    folder = data_dir / ARCHIVE_DIR / f"{AUTO_PREFIX}{stamp}"
    n = 1
    while folder.exists():
        n += 1
        folder = data_dir / ARCHIVE_DIR / f"{AUTO_PREFIX}{stamp}-{n}"
    return folder


def swap_records(data_dir: Path, staged: Path, *, keep: bool, note: dict[str, object], now: datetime) -> Path | None:
    """준비 폴더의 기록·실적·수정 기록 파일을 데이터 폴더의 지금 파일과 바꿔 끼운다(데이터 폴더 문을 혼자 잡고).

    keep이면 지금 파일을 자동 보관 폴더로 옮기고(DONE에 note) 그 폴더를 돌려준다. 아니면(지금 기록이 비어 있음) 버린다.
    중간에 실패하면 옮긴 것을 되돌리고 예외를 그대로 낸다(지금 기록 그대로). 되돌리기마저 실패하면 남은 파일도 끝까지
    되돌려 본 뒤 로그(log.exception)를 남기고 원래 예외를 낸다(__cause__ = 되돌리기 실패). 준비 폴더는 지운다."""
    archive = _auto_folder(data_dir, now) if keep else data_dir / STAGING / ".old"
    done: list[tuple[Path, Path]] = []
    try:
        with gate_of(data_dir).exclusive():
            try:
                archive.mkdir(parents=True, exist_ok=True)
                for source in _files(data_dir):
                    target = archive / source.name
                    replace_file(source, target)
                    done.append((source, target))
                for source in _files(staged):
                    target = data_dir / source.name
                    replace_file(source, target)
                    done.append((source, target))
            except BaseException as error:
                # 되돌리기도 문을 잡은 채로: 새 연결이 반쯤 바뀐 폴더를 열지 않게(문을 놓으면 기다리던 연결이 들어온다)
                undo_error = _undo_swap(done, archive if keep else None)
                if undo_error is not None:
                    log.exception(
                        "시연 기록 바꿔 끼우기 되돌리기 실패 — 데이터 폴더 확인 필요(%s)", data_dir, exc_info=undo_error
                    )
                    raise error from undo_error
                raise
    finally:
        shutil.rmtree(data_dir / STAGING, ignore_errors=True)
    if not keep:
        return None
    moved = [target.name for _source, target in done if target.parent == archive]
    record = {"auto": True, "at": now.astimezone(UTC).isoformat(), "moved": moved, **note}
    (archive / DONE).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    prune_auto(data_dir)
    return archive


def _undo_swap(done: list[tuple[Path, Path]], archive: Path | None) -> Exception | None:
    """옮긴 것을 거꾸로 되돌린다. 하나가 실패해도 나머지는 계속 되돌리고 첫 실패를 돌려준다(없으면 None)."""
    first: Exception | None = None
    for source, target in reversed(done):
        try:
            if target.exists():
                replace_file(target, source)
        except Exception as failed:  # 남은 파일도 되돌려야 해서 첫 실패만 모아 둔다
            first = first or failed
    if archive is not None and archive.exists() and not any(archive.iterdir()):
        archive.rmdir()
    return first


def _is_auto(folder: Path) -> bool:
    if not folder.is_dir() or not folder.name.startswith(AUTO_PREFIX):
        return False
    try:
        return json.loads((folder / DONE).read_text(encoding="utf-8")).get("auto") is True
    except (OSError, ValueError, AttributeError):
        return False


def prune_auto(data_dir: Path, keep: int = AUTO_KEEP) -> list[str]:
    """자동 보관 폴더를 최근 keep개만 남기고 지운다(이름 = KST 시각이라 이름 순). 사람이 표지로 만든 보관
    (DONE에 auto 없음)은 이름이 records-auto-로 시작해도 그대로. 지운 폴더 이름을 돌려준다."""
    root = data_dir / ARCHIVE_DIR
    if not root.is_dir():
        return []
    autos = sorted((f for f in root.iterdir() if _is_auto(f)), key=lambda f: f.name)
    removed = autos[: max(0, len(autos) - keep)]
    for folder in removed:
        shutil.rmtree(folder, ignore_errors=True)
    return [folder.name for folder in removed]
