"""지도 저장소(파일): 가져온 지도와 활성 지도 기록을 데이터 폴더에 남겨 서버를 다시 켜도 그대로 쓴다.

폴더(설정 RIPPLE_DATA_DIR, 기본 `<프로젝트>/.data` — 깃 제외, 실데이터가 들어간다):
  snapshots/<지도 ID>.json        지도(GraphSnapshot)
  snapshots/<지도 ID>.info.json   지도 정보(SnapshotInfo: 이름·가져온 시각·품질 리포트)
  active.json                    {"snapshot_id": <지도 ID> | null} — null이면 기본 지도(설정의 지도 파일)

- 쓰기는 같은 폴더의 임시 파일에 쓰고 디스크에 내린 뒤 바꿔 끼운다(쓰다 멈춰도 반쯤 쓴 파일이 남지 않게).
  바꿔 끼우기는 ripple/config/files.py replace_file(Windows의 짧은 잠금이면 1초 안에서 다시 시도).
- 읽을 때 지도 내용 해시를 ID와 대조한다(손상·변조된 지도로 계산하지 않게). 읽기 실패(없음·글자 인코딩 손상·형식
  오류)는 모두 SnapshotStoreError라 시작 복구·목록이 그 파일만 건너뛴다.
- 경로에 쓰는 ID는 지도 ID 형식(G-16자리 16진수)인지 먼저 본다(`../` 같은 경로 조작 차단).
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import ValidationError

from ripple.config.files import write_atomic as write_atomic  # 저장소 쪽 import 경로(accounts·mappings)도 그대로
from ripple.contracts.base import Frozen
from ripple.contracts.domain import GraphSnapshot
from ripple.contracts.identity import snapshot_id
from ripple.contracts.workspace import SNAPSHOT_ID_PATTERN, SnapshotId, SnapshotInfo

_ID = re.compile(SNAPSHOT_ID_PATTERN)


class SnapshotStoreError(ValueError):
    """저장된 지도·기록을 쓸 수 없다(없음·손상·내용 불일치·형식이 아닌 ID). 메시지는 명사형."""


class ActivePointer(Frozen):
    """active.json: 활성 지도 ID. None이면 기본 지도."""

    snapshot_id: SnapshotId | None = None


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.folder = root / "snapshots"

    # ---------- 지도 ----------

    def save(self, snapshot: GraphSnapshot, info: SnapshotInfo) -> SnapshotInfo:
        """지도와 정보를 저장하고 저장된 정보를 돌려준다.

        같은 ID가 이미 온전히 있으면(내용 해시가 같으니 같은 지도) 처음 저장한 정보를 그대로 둔다.
        있던 사본이 손상됐으면 새 내용으로 바꾼다.
        """
        key = checked_id(snapshot.snapshot_id)
        if snapshot_id(snapshot) != key:
            raise SnapshotStoreError(f"지도 내용이 ID와 불일치 — 저장 안 함: {key}")
        if info.snapshot_id != key:
            raise SnapshotStoreError(f"지도 정보의 ID({info.snapshot_id})가 지도({key})와 다름")
        try:
            self.load(key)
            return self.info(key)
        except SnapshotStoreError:
            pass  # 없거나 손상: 새로 쓴다
        self.folder.mkdir(parents=True, exist_ok=True)
        write_atomic(self._snapshot_path(key), snapshot.model_dump_json())
        write_atomic(self._info_path(key), info.model_dump_json())
        return info

    def load(self, key: str) -> GraphSnapshot:
        """저장된 지도. 없거나 손상·내용 불일치면 SnapshotStoreError."""
        key = checked_id(key)
        path = self._snapshot_path(key)
        if not path.exists():
            raise SnapshotStoreError(f"저장된 지도 없음: {key}")
        try:
            snapshot = GraphSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError) as error:
            raise SnapshotStoreError(f"저장된 지도 파일 읽기 실패({key}): {unreadable(error)}") from None
        if snapshot.snapshot_id != key or snapshot_id(snapshot) != key:
            raise SnapshotStoreError(f"저장된 지도의 내용이 ID와 불일치(손상·변조): {key}")
        return snapshot

    def info(self, key: str) -> SnapshotInfo:
        key = checked_id(key)
        path = self._info_path(key)
        try:
            info = SnapshotInfo.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise SnapshotStoreError(f"저장된 지도 정보 없음: {key}") from None
        except (OSError, UnicodeError, ValidationError) as error:
            raise SnapshotStoreError(f"저장된 지도 정보 읽기 실패({key}): {unreadable(error)}") from None
        if info.snapshot_id != key:
            raise SnapshotStoreError(f"저장된 지도 정보의 ID가 파일 이름과 다름: {key}")
        return info

    def infos(self) -> tuple[SnapshotInfo, ...]:
        """정보를 읽을 수 있는 저장 지도(가져온 시각 → ID 순). 지도 내용 대조는 쓸 때(load) 한다."""
        if not self.folder.exists():
            return ()
        found = []
        for path in self.folder.glob("*.info.json"):
            key = path.name.removesuffix(".info.json")
            if not _ID.fullmatch(key):
                continue
            try:
                found.append(self.info(key))
            except SnapshotStoreError:
                continue  # 읽히지 않는 정보는 목록에서 뺀다(지도를 고를 수 없음)
        return tuple(sorted(found, key=lambda i: (i.imported_at is None, i.imported_at, i.snapshot_id)))

    # ---------- 활성 지도 ----------

    def active(self) -> str | None:
        """활성 지도 ID(None = 기본 지도). 기록이 없으면 None, 읽을 수 없으면 SnapshotStoreError."""
        path = self.root / "active.json"
        try:
            return ActivePointer.model_validate_json(path.read_text(encoding="utf-8")).snapshot_id
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError, ValidationError) as error:
            raise SnapshotStoreError(
                f"활성 지도 기록(active.json) 읽기 실패: {unreadable(error, ACTIVE_SHAPE)}"
            ) from None

    def set_active(self, key: str | None) -> None:
        pointer = ActivePointer(snapshot_id=None if key is None else checked_id(key))
        self.root.mkdir(parents=True, exist_ok=True)
        write_atomic(self.root / "active.json", pointer.model_dump_json())

    # ---------- 경로 ----------

    def _snapshot_path(self, key: str) -> Path:
        return self.folder / f"{key}.json"

    def _info_path(self, key: str) -> Path:
        return self.folder / f"{key}.info.json"


ACTIVE_SHAPE = '{"snapshot_id": "G-…"} 또는 기본 지도면 {"snapshot_id": null}'
"""active.json의 형식(문서 docs/operations.md(서비스) 6절과 같음)."""


def unreadable(error: Exception, shape: str | None = None) -> str:
    """저장 파일을 읽지 못한 이유(사람이 읽는 말 — 예외 클래스 이름을 화면에 내지 않는다). shape = 맞는 형식 안내."""
    if isinstance(error, UnicodeError):
        return "글자 인코딩이 UTF-8이 아님"
    if isinstance(error, ValidationError):
        return "내용 형식 오류" + (f" — {shape} 형식 필요" if shape else "")
    return "파일 열기 실패(권한·잠금 확인)"


def checked_id(key: str) -> str:
    if not _ID.fullmatch(key):
        raise SnapshotStoreError(f"지도 ID 형식 아님: {key[:40]!r}")
    return key
