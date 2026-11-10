"""행 읽기(docs/input.md(엑셀 양식)): 양식 표(Table)의 데이터 행을 값으로 읽으며 빈 필수 값·형식·단위 착오(상식
범위 밖)·수식·엑셀 오류를 시트·행·열과 함께 문제로 모은다. 표 만들기(확정 매핑 → 표)는 sheet_tables.py, 표·행·문제
모음의 모양은 table_types.py.
"""

from __future__ import annotations

from ripple.contracts.ingest import IssueCode, IssueSeverity

from .table_types import Issues, Record, Table
from .template import Column
from .values import amount_text, parse
from .workbook import ExcelError, Uncomputed


def read(table: Table, issues: Issues) -> list[Record]:
    records = []
    for number, cells in table.data:
        values: dict[str, object] = {}
        for column in table.sheet.columns:
            position = table.positions.get(column.key)
            cell = cells[position] if position is not None and position < len(cells) else None
            value, problem = parse(column, cell, table.factors.get(column.key, 1.0), table.raw.epoch)
            shown = table.file_column(column.key)
            found = _cell_problem(table, column, cell, value, problem, position is not None)
            if found is not None:
                code, message = found
                issues.add(IssueSeverity.ERROR, code, message, table.raw.name, number, column.header, shown)
            values[column.key] = value
        records.append(Record(table, number, values))
    return records


def _cell_problem(
    table: Table, column: Column, cell: object, value: object, problem: str | None, mapped: bool
) -> tuple[IssueCode, str] | None:
    """칸 하나를 읽은 결과의 문제(없으면 None): 계산값 없는 수식 · 엑셀 오류 · 형식 · 빈 필수 값 · 상식 범위 밖."""
    if isinstance(cell, Uncomputed):
        return IssueCode.BAD_VALUE, (
            f"'{column.header}' 칸이 수식({cell.formula})이고 저장된 계산값 없음 · 엑셀에서 열어 저장한 뒤 다시 올리기"
        )
    if isinstance(cell, ExcelError):
        return IssueCode.BAD_VALUE, (
            f"'{column.header}' 칸이 엑셀 오류 값({cell.code}) · 빈칸으로 읽지 않음 — 원본 엑셀에서 "
            "수정 필요(날짜 서식 칸에 날짜가 아닌 큰 숫자가 있어도 #VALUE!로 보임)"
        )
    if problem:
        return IssueCode.BAD_VALUE, f"'{column.header}' 값({cell})을 {problem}(으)로 읽기 실패"
    if value is None and column.required and mapped:
        return IssueCode.MISSING_VALUE, f"'{column.header}' 값 비어 있음"
    bounds = table.ranges.get(column.key)
    if bounds is not None and isinstance(value, (int, float)) and not bounds[0] <= value <= bounds[1]:
        unit = column.unit
        source = table.units.get(column.key)
        given = f"파일 {cell}{source} → {amount_text(value)}{unit}" if source else f"{amount_text(value)}{unit}"
        return IssueCode.BAD_VALUE, (
            f"'{column.header}' 값({given})이 이 항목의 상식 범위"
            f"({amount_text(bounds[0])}~{amount_text(bounds[1])}{unit}) 밖 · 원본 단위 확인"
        )
    return None
