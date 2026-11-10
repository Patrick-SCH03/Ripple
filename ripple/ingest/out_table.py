"""엑셀 내보내기 공통(분석 결과·결재 대장): 표 시트와 항목 시트를 쓴다.

머리글 굵게 · 첫 줄 고정 · 자동 거르기 · 열 폭 · 숫자(천 단위)·날짜 서식. 값은 받은 그대로 쓰고(계산하지 않음),
'='로 시작하는 글이 여는 사람의 엑셀에서 수식으로 돌지 않게 글자로 둔다(지도 내보내기 export.py와 같은 규칙).
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

MONEY = "#,##0"
"""원 단위 금액(천 단위 구분)."""
DAY = "yyyy-mm-dd"
DECIMAL = "#,##0.###"

Cell = str | int | float | date | None


@dataclass(frozen=True, slots=True)
class Column:
    title: str
    width: int = 12
    number_format: str | None = None
    wrap: bool = False


@dataclass(frozen=True, slots=True)
class Item:
    """항목 시트 한 줄: 이름 · 값 · (값 서식) · (비고)."""

    label: str
    value: Cell
    number_format: str | None = None
    note: str = ""


def _append(ws: Worksheet, values: Sequence[Cell]) -> None:
    ws.append(list(values))
    for cell in ws[ws.max_row]:
        if cell.data_type == "f":  # '='로 시작하는 이름·메모를 수식이 아닌 글자로
            cell.data_type = "s"


def _header(ws: Worksheet, titles: Sequence[str]) -> None:
    ws.append(list(titles))
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)


def table(ws: Worksheet, columns: Sequence[Column], rows: Iterable[Sequence[Cell]]) -> int:
    """머리글 + 줄. 쓴 줄 수(머리글 제외)를 돌려준다."""
    _header(ws, [c.title for c in columns])
    count = 0
    for row in rows:
        _append(ws, row)
        count += 1
    for index, column in enumerate(columns, start=1):
        letter = get_column_letter(index)
        ws.column_dimensions[letter].width = column.width
        for (cell,) in ws.iter_rows(min_row=2, max_row=count + 1, min_col=index, max_col=index):
            if column.number_format:
                cell.number_format = column.number_format
            if column.wrap:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    if count:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{count + 1}"
    return count


def items(ws: Worksheet, rows: Iterable[Item], *, widths: tuple[int, int, int] = (26, 44, 60)) -> None:
    """항목 · 값 · 비고 세 칸(요약 시트). 값 서식은 줄마다."""
    _header(ws, ["항목", "값", "비고"])
    for row in rows:
        _append(ws, [row.label, row.value, row.note or None])
        if row.number_format:
            ws.cell(row=ws.max_row, column=2).number_format = row.number_format
    for letter, width in zip("ABC", widths, strict=True):
        ws.column_dimensions[letter].width = width
    for (cell,) in ws.iter_rows(min_row=2, min_col=3, max_col=3):
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"


def note_rows(ws: Worksheet, lines: Iterable[str], *, gap: int = 1) -> None:
    """표 아래 안내 줄(한계·가정 문장 그대로). 앞에 빈 줄 gap개."""
    for _ in range(gap):
        ws.append([])
    for line in lines:
        _append(ws, [line])


def save(workbook: Workbook) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def sheet(workbook: Workbook, title: str, *, first: bool = False) -> Worksheet:
    """시트 하나: first면 통합 문서의 첫 시트 이름을 바꿔 쓴다."""
    ws = workbook.active if first else workbook.create_sheet(title)
    assert isinstance(ws, Worksheet)
    ws.title = title
    return ws
