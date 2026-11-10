"""확정한 엑셀 열 매핑의 최근 기록을 한 JSON 파일에 보관한다."""

from __future__ import annotations

import contextlib
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, ValidationError

from ripple.contracts.base import Frozen
from ripple.contracts.ingest import ConfirmedMapping

from .snapshots import write_atomic

Kind = Literal["full", "status"]
LIMIT = 20


class SavedMapping(Frozen):
    """데이터 행 없이 매핑 선택과 출처만 저장한다."""

    fingerprint: str = Field(pattern=r"^F-[0-9a-f]{16}$")
    kind: Kind
    mapping: ConfirmedMapping
    saved_at: AwareDatetime
    file_name: str


class _MappingFile(Frozen):
    mappings: tuple[SavedMapping, ...] = Field(max_length=LIMIT)


class MappingStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()  # 읽고 고쳐 쓰는 사이에 다른 요청의 쓰기가 끼어 지워지지 않게

    def remember(
        self, fingerprint: str, kind: Kind, mapping: ConfirmedMapping, file_name: str, now: datetime
    ) -> SavedMapping:
        """같은 지문을 새 선택으로 대체하고 가장 앞에 둔다."""
        saved = SavedMapping(fingerprint=fingerprint, kind=kind, mapping=mapping, saved_at=now, file_name=file_name)
        with self._lock:
            older = [item for item in self._read().mappings if item.fingerprint != fingerprint]
            self._write(_MappingFile(mappings=(saved, *older[: LIMIT - 1])))
        return saved

    def candidates(self, kind: Kind) -> list[SavedMapping]:
        """요청한 종류의 매핑을 저장된 최근 순서로 돌려준다."""
        with self._lock:
            return [item for item in self._read().mappings if item.kind == kind]

    def forget(self, fingerprint: str) -> bool:
        """지문 하나를 지운다. 없으면 파일을 다시 쓰지 않는다."""
        with self._lock:
            stored = self._read().mappings
            remaining = tuple(item for item in stored if item.fingerprint != fingerprint)
            if len(remaining) == len(stored):
                return False
            self._write(_MappingFile(mappings=remaining))
            return True

    def clear(self) -> None:
        """기존 파일을 확인한 뒤 빈 기록으로 원자적으로 교체한다."""
        with self._lock:
            self._read()
            self._write(_MappingFile(mappings=()))

    def _read(self) -> _MappingFile:
        try:
            return _MappingFile.model_validate_json(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return _MappingFile(mappings=())
        except (OSError, UnicodeError, ValidationError):
            self._quarantine()
            return _MappingFile(mappings=())

    def _quarantine(self) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        broken = self.path.with_name(f"{self.path.name}.broken-{stamp}")
        suffix = 1
        while broken.exists():
            broken = self.path.with_name(f"{self.path.name}.broken-{stamp}-{suffix}")
            suffix += 1
        with contextlib.suppress(OSError):  # 이동할 수 없어도 읽기는 빈 저장소로 계속한다
            self.path.replace(broken)

    def _write(self, body: _MappingFile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(self.path, body.model_dump_json(indent=2) + "\n")
