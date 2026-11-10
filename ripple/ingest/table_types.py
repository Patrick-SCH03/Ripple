"""가져오기 표의 값(docs/input.md(엑셀 양식)): 데이터 행(Row)·양식 표(Table)·읽은 행(Record)·문제 모음(Issues).

표 만들기(sheet_tables.py)·행 읽기(rows.py)·시트 정합(integrity.py)·조립(build.py)·상태 올리기(status.py)가 함께 쓴다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ripple.contracts.domain import SourceRef
from ripple.contracts.ingest import ImportIssue, IssueCode, IssueSeverity

from .template import Sheet
from .workbook import RawSheet

Row = tuple[int, tuple[object, ...]]


@dataclass(frozen=True, slots=True)
class Table:
    """양식 시트 하나를 파일에서 어떻게 읽는지: 파일 시트, 머리글 행, 데이터 행, 열 키 → 위치(0부터)·배율·상식 범위."""

    sheet: Sheet
    raw: RawSheet
    header_rows: tuple[int, ...]
    headers: tuple[str | None, ...]  # 위치마다 파일 머리글(두 줄이면 합친 것)
    data: tuple[Row, ...]  # 머리글 아래 행(메모 행 뺌)
    positions: Mapping[str, int]
    factors: Mapping[str, float]  # 원본 단위 → 양식 단위 배율(숫자 열)
    ranges: Mapping[str, tuple[float, float]]  # 양식 단위 기준 상식 범위(필드 사전)
    units: Mapping[str, str] = field(default_factory=dict)  # 배율이 1이 아닌 열의 원본 단위(문구용)

    def file_column(self, key: str) -> str | None:
        position = self.positions.get(key)
        return self.headers[position] if position is not None and position < len(self.headers) else None


@dataclass(frozen=True, slots=True)
class Record:
    """읽은 데이터 행 하나."""

    table: Table
    row: int
    values: Mapping[str, object]

    def source(self, file: str) -> SourceRef:
        return SourceRef(file=file, sheet=self.table.raw.name, row=self.row)


@dataclass(slots=True)
class Issues:
    items: list[ImportIssue] = field(default_factory=list)

    def add(
        self,
        severity: IssueSeverity,
        code: IssueCode,
        message: str,
        sheet: str | None = None,
        row: int | None = None,
        column: str | None = None,
        file_column: str | None = None,
    ) -> None:
        self.items.append(
            ImportIssue(
                severity=severity,
                code=code,
                message=message,
                sheet=sheet,
                row=row,
                column=column,
                file_column=file_column if file_column != column else None,
            )
        )

    def error(self, code: IssueCode, message: str, record: Record | None = None, column: str | None = None) -> None:
        sheet = record.table.raw.name if record else None
        self.add(IssueSeverity.ERROR, code, message, sheet, record.row if record else None, column)

    @property
    def has_errors(self) -> bool:
        return any(i.severity is IssueSeverity.ERROR for i in self.items)
