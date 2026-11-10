"""확정을 기다리는 엑셀 가져오기(docs/input.md(엑셀 양식) 4·5절): 열 확인 중인 것과 확정한 것을 30분 기억하고
상태 버전 대조·시트 덮어쓰기 검증·정리·개수 상한을 맡는다.

전체 가져오기(Workspaces)와 상태 올리기(StatusImports)가 같은 규칙(PendingImports)을 쓰고 안내 문장(Wording)만 다르다.
상태는 PendingImports의 잠금 안에서만 바꾼다.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from ripple.contracts.domain import GraphSnapshot
from ripple.contracts.ingest import ConfirmedMapping, MappingOverrides
from ripple.contracts.workspace import SnapshotInfo
from ripple.ingest.proposal import Override
from ripple.ingest.template import SHEET_BY_KEY
from ripple.ingest.workbook import RawSheet

from .workspace_errors import ImportChanged, NotFound

PENDING_TTL_S = 30 * 60.0
MAX_PENDING = 5  # 확정을 기다리는 가져오기(오래된 것부터 버림)
MAX_CONFIRMED = 20  # 다시 확정해도 같은 결과가 되게 기억하는 확정한 가져오기


class Built(Protocol):
    """그 상태 버전에서 오류 없이 읽은 결과(그 버전에서만 확정할 수 있다)."""

    @property
    def version(self) -> int: ...


@dataclass(frozen=True, slots=True)
class BuiltImport:
    """확정 매핑으로 오류 없이 만든 지도(그 버전에서만 확정할 수 있다)."""

    version: int
    snapshot: GraphSnapshot
    info: SnapshotInfo
    mapping: ConfirmedMapping | None = None  # 확정하면 기억할 매핑(열 매핑 기억)


@dataclass(slots=True)
class PendingImport[B]:
    """열 확인 중인 가져오기: 읽은 시트, 사람의 시트 덮어쓰기, 상태 버전, 그 버전의 성공한 읽기 결과."""

    file_name: str
    raw: dict[str, RawSheet]
    created: float  # time.monotonic()
    version: int = 1
    overrides: dict[str, Override] = field(default_factory=dict)
    built: B | None = None


@dataclass(frozen=True, slots=True)
class Confirmed[T]:
    """확정을 마친 가져오기(응답을 잃은 화면이 다시 확정해도 같은 결과가 되게 30분 기억): 그 버전과 확정 결과."""

    version: int
    result: T
    created: float  # time.monotonic()


@dataclass(frozen=True, slots=True)
class Draft[B]:
    """잠금 안에서 상태 버전을 올린 대기 항목과 그때의 버전·읽은 시트·파일 이름·덮어쓰기(읽기는 잠금 밖에서)."""

    import_id: str
    pending: PendingImport[B]
    version: int
    raw: dict[str, RawSheet]
    file_name: str
    overrides: dict[str, Override]


@dataclass(frozen=True, slots=True)
class Claim[B]:
    """확정할 대기 항목과 그 버전에서 오류 없이 읽은 결과."""

    pending: PendingImport[B]
    built: B


@dataclass(frozen=True, slots=True)
class Wording:
    """흐름(가져오기·상태 올리기)마다 다른 안내 문장."""

    missing: str  # 열 확인 중인 것이 없음(404)
    missing_confirm: str  # 확정할 것이 없음(404)
    not_ready: str  # 그 버전에 확정할 읽기 결과가 없음(409)
    confirmed_other: str  # 이미 다른 버전으로 확정함(409)


IMPORT_WORDING = Wording(
    missing="가져오기 없음(30분 지남 또는 서버 재시작) · 파일 다시 올리기",
    missing_confirm="확정할 가져오기 없음(30분 지남 또는 서버 재시작) · 파일 다시 올리기",
    not_ready="이 읽기 결과 뒤 열 확인 변경 또는 오류 없이 읽은 결과 없음 · 다시 읽은 결과 확인",
    confirmed_other="이미 다른 읽기 결과로 확정된 가져오기",
)
STATUS_WORDING = Wording(
    missing="상태 올리기 없음(30분 지남 또는 서버 재시작) · 파일 다시 올리기",
    missing_confirm="확정할 상태 올리기 없음(30분 지남 또는 서버 재시작) · 다시 올리기",
    not_ready="이 읽기 결과 뒤 열 확인 변경 또는 적용 가능한 결과 없음",
    confirmed_other="이미 다른 읽기 결과로 확정된 상태 올리기",
)


class PendingImports[B: Built, T]:
    """확정을 기다리는 가져오기(B = 그 버전의 읽기 결과)와 확정한 가져오기의 기억(T = 확정 결과).

    시계는 부를 때마다 clock()을 쓰고, 상한·만료(MAX_PENDING·MAX_CONFIRMED·PENDING_TTL_S)는 쓸 때 이 모듈에서 읽는다.
    """

    def __init__(self, wording: Wording, clock: Callable[[], float]) -> None:
        self._wording = wording
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: OrderedDict[str, PendingImport[B]] = OrderedDict()
        self._confirmed: OrderedDict[str, Confirmed[T]] = OrderedDict()

    def add(self, file_name: str, raw: dict[str, RawSheet]) -> str:
        """새 가져오기(상태 버전 1)의 ID. 오래된 것부터 버려 MAX_PENDING개까지 둔다."""
        import_id = uuid.uuid4().hex
        with self._lock:
            self._prune()
            self._pending[import_id] = PendingImport(file_name=file_name, raw=raw, created=self._clock())
            while len(self._pending) > MAX_PENDING:
                self._pending.popitem(last=False)
        return import_id

    def override(self, import_id: str, overrides: MappingOverrides) -> Draft[B]:
        """사람이 정한 시트 상태·머리글 행을 더하고 상태 버전 +1(이전 읽기 결과 무효).

        모르는 시트·양식 시트, 비었거나 떨어진 머리글 행이면 ValueError(아무것도 바꾸지 않음).
        """
        with self._lock:
            pending = self._live(import_id, overrides.version)
            merged = dict(pending.overrides)
            for item in overrides.sheets:
                validate_override(pending.raw, item.file_sheet, item.template, item.header_rows)
                merged[item.file_sheet] = Override(item.template, item.header_rows)
            pending.overrides = merged
            return self._advance(import_id, pending)

    def advance(self, import_id: str, version: int) -> Draft[B]:
        """확정 매핑으로 다시 읽기 전에 상태 버전 +1(이전 읽기 결과 무효)."""
        with self._lock:
            return self._advance(import_id, self._live(import_id, version))

    def keep(self, draft: Draft[B], built: B) -> None:
        """그 버전의 성공한 읽기 결과를 둔다. 읽는 사이 상태 버전이 바뀌었으면(덮어쓰기·다른 제출) 버린다
        — 늦게 끝난 읽기가 새 상태를 덮지 않게."""
        with self._lock:
            if self._pending.get(draft.import_id) is draft.pending and draft.pending.version == draft.version:
                draft.pending.built = built

    def confirm[R](
        self,
        import_id: str,
        version: int,
        *,
        again: Callable[[Confirmed[T]], R],
        apply: Callable[[Claim[B]], tuple[R, T]],
    ) -> R:
        """찾기 → apply(확정) → 대기에서 빼고 기억하기(최근 MAX_CONFIRMED개)를 잠금 하나 안에서 한다.

        그 사이 덮어쓰기·제출이 버전을 올려도 옛 버전 결과가 새 수정을 지우지 않게(끼어든 요청은 확정이 끝난 뒤
        '없는 가져오기'), 같은 확정이 동시에 와도 apply는 한 번. 이미 확정했으면 again.
        확정은 늘 이 길로만 한다(찾기·기억을 따로 열지 않음)."""
        with self._lock:
            found = self._claim(import_id, version)
            if isinstance(found, Confirmed):
                return again(found)
            outcome, result = apply(found)
            self._finish(import_id, version, result)
            return outcome

    # ---------- 잠금 안에서 ----------

    def _live(self, import_id: str, version: int) -> PendingImport[B]:
        """열 확인 중인 가져오기. 없거나 만료면 NotFound, 상태 버전이 다르면 ImportChanged."""
        self._prune()
        pending = self._pending.get(import_id)
        if pending is None:
            raise NotFound(self._wording.missing)
        if version != pending.version:
            raise ImportChanged(
                "다른 곳에서 열 확인 변경됨 · 지금 상태로 다시 불러온 뒤 진행",
                pending.version,
            )
        return pending

    @staticmethod
    def _advance(import_id: str, pending: PendingImport[B]) -> Draft[B]:
        pending.version += 1
        pending.built = None
        return Draft(import_id, pending, pending.version, pending.raw, pending.file_name, pending.overrides)

    def _claim(self, import_id: str, version: int) -> Claim[B] | Confirmed[T]:
        """확정할 수 있는 것: 지금 버전이고 그 버전에서 오류 없이 읽은 결과(아니면 ImportChanged), 또는 같은 버전으로
        확정한 기억. 없으면 NotFound."""
        self._prune()
        pending = self._pending.get(import_id)
        confirmed = self._confirmed.get(import_id)
        if pending is None and confirmed is not None:
            if confirmed.version != version:
                raise ImportChanged(self._wording.confirmed_other, confirmed.version)
            return confirmed
        if pending is None:
            raise NotFound(self._wording.missing_confirm)
        built = pending.built
        if version != pending.version or built is None or built.version != version:
            raise ImportChanged(self._wording.not_ready, pending.version)
        return Claim(pending, built)

    def _finish(self, import_id: str, version: int, result: T) -> None:
        self._pending.pop(import_id, None)
        self._confirmed[import_id] = Confirmed(version, result, self._clock())
        while len(self._confirmed) > MAX_CONFIRMED:
            self._confirmed.popitem(last=False)

    def _prune(self) -> None:
        """30분이 지난 대기·확정 기억을 지운다."""
        now = self._clock()
        for key in [k for k, p in self._pending.items() if now - p.created > PENDING_TTL_S]:
            del self._pending[key]
        for key in [k for k, c in self._confirmed.items() if now - c.created > PENDING_TTL_S]:
            del self._confirmed[key]


def validate_override(
    raw: dict[str, RawSheet], file_sheet: str, template: str | None, header_rows: tuple[int, ...] | None
) -> None:
    """덮어쓰기 검증: 파일에 있는 시트, 양식에 있는 시트, 비지 않은 머리글 행(두 줄이면 붙은 두 행)."""
    sheet = raw.get(file_sheet)
    if sheet is None:
        raise ValueError(f"파일에 '{file_sheet}' 시트 없음")
    if template is not None and template not in SHEET_BY_KEY:
        raise ValueError(f"모르는 양식 시트: {template}")
    if header_rows:
        present = {number for number, _ in sheet.rows}
        if any(number not in present for number in header_rows):
            raise ValueError("머리글로 고른 행이 빈 행 · 값이 있는 행 선택")
        if len(header_rows) == 2 and header_rows[1] != header_rows[0] + 1:
            raise ValueError("두 줄 머리글은 붙어 있는 두 행만 가능")
