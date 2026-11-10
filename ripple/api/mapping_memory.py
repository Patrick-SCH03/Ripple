"""열 매핑 기억(docs/input.md(엑셀 양식) 4절): 같은 모양의 파일로 전에 확정한 매핑을 제안에 싣고, 확정한 매핑을
파일 모양 지문과 함께 남긴다(값은 남기지 않음). 기억 저장소가 없으면 아무것도 하지 않는다."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from datetime import datetime

from ripple.contracts.ingest import ConfirmedMapping, MappingProposal
from ripple.ingest.fingerprint import reusable, shape_of
from ripple.ingest.workbook import RawSheet
from ripple.store.mappings import Kind, MappingStore


class MappingMemory:
    """작업 공간 세대와 무관하게 이어지는 열 매핑 기억(기억 저장소가 없으면 None)."""

    def __init__(self, mappings: MappingStore | None, wall: Callable[[], datetime]) -> None:
        self._mappings = mappings
        self._wall = wall

    def with_remembered(self, proposal: MappingProposal, raw: dict[str, RawSheet], kind: Kind) -> MappingProposal:
        """같은 모양(시트·머리글·단위 안내)의 파일로 전에 확정한 매핑이 지금 파일에도 그대로 맞으면 제안에 싣는다."""
        if self._mappings is None:
            return proposal
        for saved in self._mappings.candidates(kind):
            if reusable(raw, saved.mapping, kind, saved.fingerprint):
                return proposal.model_copy(update={"remembered": saved.mapping, "remembered_from": saved.file_name})
        return proposal

    def remember(self, raw: dict[str, RawSheet], mapping: ConfirmedMapping | None, kind: Kind, file_name: str) -> None:
        """확정한 매핑을 파일 모양 지문과 함께 기억한다(값은 남기지 않음). 실패해도 확정은 그대로."""
        if self._mappings is None or mapping is None:
            return
        with contextlib.suppress(OSError):
            self._mappings.remember(shape_of(raw, mapping, kind), kind, mapping, file_name, self._wall())

    def forget(self) -> None:
        if self._mappings is not None:
            self._mappings.clear()
