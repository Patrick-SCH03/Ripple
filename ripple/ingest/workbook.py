"""엑셀 파일 → 시트별 행(값만). 수식은 엑셀이 저장해 둔 계산값을 읽고, 계산값이 없는 수식은 Uncomputed로
표시해 빈칸과 구분한다(엑셀에서 열어 저장하지 않은 파일 — 조용히 빈칸으로 읽지 않게).

크기 상한: 압축은 작아도 쓰는 범위가 큰 파일이 서버를 오래 붙잡지 않게, 읽기 전에 압축을 푼 총량·항목 수를 보고,
읽는 동안 시트·행·칸 수를 세어 넘으면 그 상한을 말하고 멈춘다. 값이 있는 칸을 버리지는 않는다(넘으면 오류).

병합 범위: 읽기 전용 모드는 병합을 읽지 않아 시트 XML의 <mergeCells>만 따로 읽어 RawSheet.merges에 둔다(채우는 일은
머리글을 정한 뒤 mapping.data_rows — 데이터 영역만).
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries
from openpyxl.utils.datetime import CALENDAR_WINDOWS_1900

MAX_UNZIPPED_BYTES = 100 * 1024 * 1024
MAX_ZIP_ENTRIES = 1000
MAX_SHEETS = 64
MAX_ROWS = 100_000  # 시트마다(빈 행 포함, 엑셀이 저장한 범위)
MAX_COLUMNS = 256  # 이 뒤에 값이 있으면 오류, 빈칸이면 잘라 읽음
MAX_CELLS = 2_000_000  # 모든 시트의 읽은 칸 합


EXCEL_ERRORS = frozenset(
    {"#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A", "#GETTING_DATA", "#SPILL!", "#CALC!"}
    | {"#FIELD!", "#BLOCKED!", "#CONNECT!", "#BUSY!", "#UNKNOWN!"}
)
"""엑셀 오류 값. 날짜 서식 칸의 날짜 범위 밖 숫자도 openpyxl이 #VALUE!로 읽는다."""


@dataclass(frozen=True, slots=True)
class Uncomputed:
    """계산값이 저장되지 않은 수식 셀."""

    formula: str


@dataclass(frozen=True, slots=True)
class ExcelError:
    """엑셀 오류 값(#N/A·#REF! 등)이 든 셀. 글자나 빈칸으로 읽지 않고 그 칸을 짚는다."""

    code: str


Merge = tuple[int, int, int, int]
"""병합 범위(첫 행, 첫 열, 끝 행, 끝 열 — 1부터, 엑셀 번호)."""


@dataclass(frozen=True, slots=True)
class RawSheet:
    name: str  # 파일 안의 시트 이름 그대로
    rows: tuple[tuple[int, tuple[object, ...]], ...]  # (엑셀 행 번호, 셀 값) — 완전히 빈 행은 뺌
    epoch: datetime = CALENDAR_WINDOWS_1900  # 그 파일의 날짜 체계(엑셀 날짜 숫자를 읽을 때). 1904 체계 파일이면 다름
    # 병합 범위(값은 왼쪽 위 칸에만). 데이터 영역의 병합은 머리글을 정한 뒤 mapping.data_rows가 왼쪽 위 값으로 채운다
    merges: tuple[Merge, ...] = ()


def read_workbook(data: bytes) -> dict[str, RawSheet]:
    """시트 이름 → 행. 파일 형식이 xlsx가 아니거나 크기 상한을 넘으면 ValueError(명사형 문구)."""
    check_archive(data)
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        formulas = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    except Exception as error:  # openpyxl은 형식 오류를 여러 예외로 낸다
        raise ValueError(f"파일 형식 오류 · .xlsx만 가능({type(error).__name__})") from error
    try:
        if len(workbook.worksheets) > MAX_SHEETS:
            raise ValueError(
                f"시트 {len(workbook.worksheets)}개 · {MAX_SHEETS}개까지 읽기 가능(쓰지 않는 시트 삭제 필요)"
            )
        sheets = {}
        cells = 0
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for ws, raw in zip(workbook.worksheets, formulas.worksheets, strict=True):
                values, written = ws.iter_rows(values_only=True), raw.iter_rows(values_only=True)
                rows, cells = _sheet_rows(ws.title, values, written, cells)
                merges = merged_ranges(archive, getattr(ws, "_worksheet_path", None), ws.title)
                sheets[ws.title] = RawSheet(ws.title, rows, workbook.epoch, merges)
        return sheets
    except (ValueError, MemoryError):
        raise
    except Exception as error:  # 읽기 전용 모드는 시트를 돌 때 XML을 풀어서, 손상된 시트는 여기서 여러 예외로 난다
        raise ValueError(f"엑셀 시트 읽기 실패 · 파일 손상 가능({type(error).__name__})") from error
    finally:
        workbook.close()
        formulas.close()


def _sheet_rows(
    title: str, values_rows: Iterable[Sequence[object]], written_rows: Iterable[Sequence[object]], cells: int
) -> tuple[tuple[tuple[int, tuple[object, ...]], ...], int]:
    """시트 하나의 (엑셀 행 번호, 셀 값) — 완전히 빈 행은 뺌 — 와 지금까지 읽은 칸 수. 상한을 넘으면 ValueError."""
    rows = []
    for number, (values, written) in enumerate(zip(values_rows, written_rows, strict=False), start=1):
        if number > MAX_ROWS:
            raise ValueError(f"'{title}' 시트 {MAX_ROWS:,}행 초과 · 쓰는 범위만 남기고 다시 올리기")
        cells += max(len(values), len(written))
        if cells > MAX_CELLS:
            raise ValueError(f"읽을 칸 합계 {MAX_CELLS:,}개 초과 · 쓰는 범위만 남기고 다시 올리기")
        if len(values) > MAX_COLUMNS or len(written) > MAX_COLUMNS:
            if _has_value(values[MAX_COLUMNS:]) or _has_value(written[MAX_COLUMNS:]):
                raise ValueError(
                    f"'{title}' 시트 {number}행의 {MAX_COLUMNS}번째 열 뒤에 값 있음 · {MAX_COLUMNS}열까지 읽기 가능"
                )
            values, written = values[:MAX_COLUMNS], written[:MAX_COLUMNS]
        found = tuple(_cell(v, w) for v, w in zip(values, written, strict=False))
        if _has_value(found):
            rows.append((number, found))
    return tuple(rows), cells


MERGE_REF = re.compile(
    rb"<(?:[\w.-]+:)?mergeCell\b[^>]*?\bref\s*=\s*[\x22\x27]([A-Za-z]{1,3}[0-9]+(?::[A-Za-z]{1,3}[0-9]+)?)[\x22\x27]"
)
"""시트 XML의 병합 칸 하나(<mergeCell ref="A2:A9"/>, 이름공간 접두 허용)."""
CHUNK = 1 << 20


def merged_ranges(archive: zipfile.ZipFile, path: str | None, title: str) -> tuple[Merge, ...]:
    """시트 XML의 병합 범위. 읽기 전용 모드는 병합을 읽지 않아 시트 XML에서 <mergeCells> 묶음만 따로 찾는다(시트 데이터
    뒤에 온다 — 조각으로 읽으며 그 뒤만 모은다). 병합된 넓이(행 MAX_ROWS·열 MAX_COLUMNS 안)가 MAX_CELLS를 넘으면
    ValueError — 채워 읽을 때 서버를 오래 붙잡지 않게."""
    if not path:
        return ()
    try:
        stream = archive.open(path.lstrip("/"))
    except KeyError:
        return ()
    block, tail = bytearray(), b""
    with stream:
        while chunk := stream.read(CHUNK):
            if block:
                block += chunk
                continue
            text = tail + chunk
            at = text.find(b"mergeCells")
            if at >= 0:
                block += text[max(0, at - 16) :]
            tail = text[-32:]
    merges = []
    area = 0
    for ref in MERGE_REF.findall(bytes(block)):
        left, top, right, bottom = range_boundaries(ref.decode("ascii"))
        if left is None or top is None or right is None or bottom is None or (top, left) == (bottom, right):
            continue
        area += max(0, min(bottom, MAX_ROWS) - top + 1) * max(0, min(right, MAX_COLUMNS) - left + 1)
        if area > MAX_CELLS:
            raise ValueError(f"'{title}' 시트의 병합 범위 과다 · 병합을 풀고 다시 올리기")
        merges.append((top, left, bottom, right))
    return tuple(merges)


def check_archive(data: bytes) -> None:
    """xlsx(zip)의 항목 수·압축을 푼 총량(목록에 적힌 크기)을 읽기 전에 본다. zip이 아니면 ValueError."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile:
        raise ValueError("파일 형식 오류 · .xlsx만 가능(zip 형식 아님)") from None
    if len(entries) > MAX_ZIP_ENTRIES:
        raise ValueError(f"엑셀 파일 안 항목 {len(entries):,}개 · {MAX_ZIP_ENTRIES:,}개까지 읽기 가능")
    unzipped = sum(entry.file_size for entry in entries)
    if unzipped > MAX_UNZIPPED_BYTES:
        raise ValueError(
            f"엑셀 파일 압축 해제 크기 {unzipped / 1024 / 1024:,.0f}MB · "
            f"{MAX_UNZIPPED_BYTES // (1024 * 1024)}MB까지 읽기 가능(쓰는 범위만 남기기)"
        )


def _has_value(cells: Sequence[object]) -> bool:
    return any(c is not None and str(c).strip() != "" for c in cells)


def _cell(value: object, written: object) -> object:
    """저장된 값. 수식인데 계산값이 없으면 Uncomputed, 엑셀 오류 값이면 ExcelError."""
    if value is None and isinstance(written, str) and written.startswith("="):
        return Uncomputed(written)
    if isinstance(value, str) and value.strip().upper() in EXCEL_ERRORS:
        return ExcelError(value.strip().upper())
    return value
