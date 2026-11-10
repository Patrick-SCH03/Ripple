"""표 만들기(docs/input.md(엑셀 양식)): 확정 매핑대로 파일 시트를 양식 표로 만든다(머리글 행·열 위치·원본 단위
배율·상식 범위). 없는 시트·같은 양식 시트 둘·같은 항목에 두 열·단위 미해결·필수 열 없음은 문제로 남기고, 메모 행·
머리글 위 제목 행·고르지 않은 열은 읽지 않고 경고로 남긴다. 데이터 영역의 병합 칸은 왼쪽 위 값으로 채워 읽고 곳 수를
경고 한 줄로 남긴다(mapping.data_merges). 행 읽기는 rows.py, 표·문제 모음의 모양은 table_types.py.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from openpyxl.utils import get_column_letter

from ripple.contracts.ingest import ColumnMapping, ConfirmedMapping, IssueCode, IssueSeverity, SheetMapping

from .fields import FieldDictionary
from .mapping import data_merges, data_rows, header_cells, header_units, is_guide, unit_notes
from .normalize import header_key, split_unit, unit_factor
from .table_types import Issues, Row, Table
from .template import SHEETS, Column, Sheet
from .workbook import RawSheet


def tables(
    raw: Mapping[str, RawSheet],
    mapping: ConfirmedMapping,
    fields: FieldDictionary,
    issues: Issues,
    sheets: Sequence[Sheet] = SHEETS,
) -> dict[str, Table]:
    """확정 매핑대로 양식 시트마다 표를 만든다. 없는 파일 시트·같은 양식 시트 둘·같은 항목에 두 열·단위 미해결·
    필수 열 없음은 문제로 남긴다(조용히 하나를 고르지 않는다). sheets = 읽을 양식 시트(상태 올리기는 상태 시트만)."""
    by_template = _by_template(raw, mapping, {sheet.key: sheet for sheet in sheets}, issues)
    result: dict[str, Table] = {}
    for sheet in sheets:
        entries = by_template.get(sheet.key, [])
        if len(entries) > 1:
            names = ", ".join(f"'{e.file_sheet}'" for e in entries)
            issues.add(
                IssueSeverity.ERROR,
                IssueCode.DUPLICATE_SHEET,
                f"'{sheet.name}' 시트로 읽히는 시트 둘 이상({names}) · 하나만 남기기",
                sheet.name,
            )
            continue
        chosen = entries[0] if entries else None
        sheet_raw = raw[chosen.file_sheet] if chosen is not None else None
        if chosen is None or sheet_raw is None or not sheet_raw.rows:
            _missing(sheet, issues)
            continue
        result[sheet.key] = _table(sheet, chosen, sheet_raw, fields, issues)
    return result


def _by_template(
    raw: Mapping[str, RawSheet], mapping: ConfirmedMapping, known: Mapping[str, Sheet], issues: Issues
) -> dict[str, list[SheetMapping]]:
    """양식 시트 → 그 시트로 읽을 파일 시트들. 정하지 않은 시트·없는 시트·모르는 양식 시트는 문제로, 읽지 않기로 한
    시트는 경고로 남긴다."""
    by_template: dict[str, list[SheetMapping]] = defaultdict(list)
    listed = {entry.file_sheet for entry in mapping.sheets}
    for name in raw:
        if name not in listed:
            issues.add(
                IssueSeverity.ERROR,
                IssueCode.MISSING_SHEET,
                f"'{name}' 시트 읽을지 미정 · 열 확인에서 양식 시트나 '읽지 않음' 선택",
                name,
            )
    for entry in mapping.sheets:
        if entry.file_sheet not in raw:
            issues.add(
                IssueSeverity.ERROR,
                IssueCode.MISSING_SHEET,
                f"파일에 '{entry.file_sheet}' 시트 없음",
                entry.file_sheet,
            )
        elif entry.template is not None and entry.template not in known:
            issues.add(
                IssueSeverity.ERROR, IssueCode.BAD_VALUE, f"모르는 양식 시트({entry.template})", entry.file_sheet
            )
        elif entry.template is not None:
            by_template[entry.template].append(entry)
        elif not is_guide(entry.file_sheet) and raw[entry.file_sheet].rows:
            issues.add(
                IssueSeverity.WARNING,
                IssueCode.IGNORED_SHEET,
                f"'{entry.file_sheet}' 시트 읽기 제외",
                entry.file_sheet,
            )
    return by_template


def _missing(sheet: Sheet, issues: Issues) -> None:
    """읽을 행이 없는 양식 시트: 필수면 오류, 선택이면 '없을 때의 뜻'을 경고로(계산에 쓰지 않는 시트는 조용히)."""
    if sheet.required:
        issues.add(IssueSeverity.ERROR, IssueCode.MISSING_SHEET, f"필수 시트 '{sheet.name}' 없음", sheet.name)
    elif not sheet.quiet:
        issues.add(
            IssueSeverity.WARNING, IssueCode.MISSING_SHEET, f"'{sheet.name}' 시트 없음 · {sheet.absent}", sheet.name
        )


@dataclass(frozen=True, slots=True)
class _Layout:
    """파일 시트 하나를 확정 매핑대로 읽는 문맥: 양식 시트·시트 매핑·파일 시트와 그 머리글·데이터 행·메모 행."""

    sheet: Sheet
    entry: SheetMapping
    raw: RawSheet
    headers: tuple[str | None, ...]  # 위치마다 파일 머리글(mapping.header_cells)
    written_units: tuple[str | None, ...]  # 위치마다 머리글에 적힌 단위(mapping.header_units)
    data: tuple[Row, ...]
    memos: tuple[int, ...]  # 메모로 보고 뺀 행 번호
    width: int  # 머리글·데이터 행 중 가장 넓은 칸 수
    noted: bool  # 제목·메모 행에 단위 표기가 있음(mapping.unit_notes)

    @property
    def header_row(self) -> int:
        """문제를 다는 머리글 행(두 줄 머리글이면 아래 줄)."""
        return self.entry.header_rows[-1]


def _layout(sheet: Sheet, entry: SheetMapping, raw: RawSheet) -> _Layout:
    """확정 매핑의 머리글 행으로 파일 시트를 머리글·데이터 행·메모 행으로 나눈다."""
    headers = header_cells(raw, entry.header_rows)
    written_units = header_units(raw, entry.header_rows)
    noted = bool(unit_notes(raw, entry.header_rows))
    data, memos = data_rows(raw, entry.header_rows)
    width = max([len(headers), *(len(cells) for _, cells in data)])
    return _Layout(sheet, entry, raw, headers, written_units, data, memos, width, noted)


@dataclass(slots=True)
class _Mapped:
    """확정 매핑에서 읽을 열: 항목 → 위치(0부터)·배율·원본 단위, 단위 문제로 막은 항목, 항목에 쓴 위치."""

    positions: dict[str, int] = field(default_factory=dict)
    factors: dict[str, float] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)  # 배율이 1이 아닌 열의 원본 단위(문구용)
    flagged: set[str] = field(default_factory=set)
    taken: set[int] = field(default_factory=set)


def _table(sheet: Sheet, entry: SheetMapping, raw: RawSheet, fields: FieldDictionary, issues: Issues) -> Table:
    layout = _layout(sheet, entry, raw)
    headers, data = layout.headers, layout.data
    present = {number for number, _ in raw.rows}
    blank = [number for number in entry.header_rows if number not in present]
    if blank:
        issues.add(
            IssueSeverity.ERROR,
            IssueCode.MISSING_COLUMN,
            f"머리글로 고른 {', '.join(map(str, blank))}행이 빈 행 · 머리글 행 다시 선택",
            raw.name,
            blank[0],
        )
        return Table(sheet, raw, entry.header_rows, headers, data, {}, {}, {})
    _row_warnings(layout, issues)
    mapped = _mapped_columns(layout, issues)
    for column in sheet.columns:
        if column.required and column.key not in mapped.positions and column.key not in mapped.flagged:
            issues.add(
                IssueSeverity.ERROR,
                IssueCode.MISSING_COLUMN,
                f"필수 열 '{column.header}' 없음",
                raw.name,
                layout.header_row,
                column.header,
            )
    _unread_columns(layout, mapped.taken, issues)
    ranges = {key: bounds for key in mapped.positions if (bounds := fields.info(sheet.key, key).range) is not None}
    return Table(sheet, raw, entry.header_rows, headers, data, mapped.positions, mapped.factors, ranges, mapped.units)


def _row_warnings(layout: _Layout, issues: Issues) -> None:
    """머리글 위 제목·안내 행과 메모 행은 읽지 않았다고 알리고, 데이터 행이 꼭 있어야 하는 필수 시트가 비면 오류."""
    sheet, raw = layout.sheet, layout.raw
    above = [number for number, _ in raw.rows if number < layout.entry.header_rows[0]]
    if above:
        issues.add(
            IssueSeverity.WARNING,
            IssueCode.IGNORED_ROW,
            f"머리글 위 {_rows_text(above)}행은 제목·안내로 보고 읽기 제외",
            raw.name,
            above[0],
        )
    if sheet.required and sheet.needs_rows and not layout.data:
        issues.add(
            IssueSeverity.ERROR,
            IssueCode.MISSING_VALUE,
            f"필수 시트 '{sheet.name}'에 데이터 행 없음",
            raw.name,
            layout.header_row,
        )
    merged = data_merges(raw, layout.entry.header_rows, layout.memos)
    if merged:
        issues.add(
            IssueSeverity.WARNING,
            IssueCode.MISSING_VALUE,
            f"'{raw.name}' 시트의 병합된 칸 {len(merged):,}곳은 병합 범위의 왼쪽 위 값으로 채워 처리"
            "(엑셀에는 값이 보여도 파일에는 첫 칸에만 값 있음)",
            raw.name,
            merged[0][0],
        )
    lookup = dict(raw.rows) if layout.memos else {}
    for number in layout.memos:
        text = next(str(c).strip() for c in lookup[number] if _filled(c))
        issues.add(
            IssueSeverity.WARNING,
            IssueCode.IGNORED_ROW,
            f"메모로 보고 읽기 제외한 행('{_preview(text)}')",
            raw.name,
            number,
        )


def _unread_columns(layout: _Layout, taken: set[int], issues: Issues) -> None:
    """양식 항목으로 고르지 않은 열(머리글이 있거나 값이 있는 것)은 읽지 않았다고 알린다."""
    raw, headers, header_row = layout.raw, layout.headers, layout.header_row
    for position in range(layout.width):
        if position in taken:
            continue
        header = headers[position] if position < len(headers) else None
        letter = get_column_letter(position + 1)
        if header is not None:
            message = f"양식 항목으로 고르지 않은 열 '{header}'({letter}열) 읽기 제외"
        elif any(position < len(cells) and _filled(cells[position]) for _, cells in layout.data):
            message = f"머리글 없는 {letter}열의 값 읽기 제외 · 필요한 값이면 머리글 추가"
        else:
            continue
        issues.add(IssueSeverity.WARNING, IssueCode.IGNORED_COLUMN, message, raw.name, header_row, None, header)


def _mapped_columns(layout: _Layout, issues: Issues) -> _Mapped:
    by_key = {c.key: c for c in layout.sheet.columns}
    mapped = _Mapped()
    raw, headers, written_units, header_row = layout.raw, layout.headers, layout.written_units, layout.header_row
    for chosen in layout.entry.columns:
        header = headers[chosen.position] if chosen.position < len(headers) else None
        if chosen.key is None:
            continue
        mapped.taken.add(chosen.position)
        column = by_key.get(chosen.key)
        problem = _choice_problem(layout, chosen, column, header, mapped)
        if problem is not None:
            message, shown, file_column = problem
            issues.add(IssueSeverity.ERROR, IssueCode.BAD_VALUE, message, raw.name, header_row, shown, file_column)
            continue
        assert column is not None
        written = written_units[chosen.position] if chosen.position < len(written_units) else None
        factor, unit_problem = _unit(column, chosen.unit, header, written, chosen.ignore_unit, layout.noted)
        if unit_problem is not None:
            mapped.flagged.add(column.key)
            issues.add(
                IssueSeverity.ERROR, IssueCode.BAD_VALUE, unit_problem, raw.name, header_row, column.header, header
            )
            continue
        assert factor is not None
        mapped.positions[column.key] = chosen.position
        mapped.factors[column.key] = factor
        if factor != 1.0 and chosen.unit is not None:
            mapped.units[column.key] = chosen.unit
    return mapped


def _choice_problem(
    layout: _Layout, chosen: ColumnMapping, column: Column | None, header: str | None, mapped: _Mapped
) -> tuple[str, str | None, str | None] | None:
    """고른 열을 쓸 수 없는 이유와 문제를 달 (양식 열, 파일 열): 표 밖·시트에 없는 항목·한 항목에 두 열."""
    where = header or f"{get_column_letter(chosen.position + 1)}열"
    if chosen.position >= layout.width:
        return f"고른 열({where})이 표 밖 · 열 확인 다시 필요", None, None
    if column is None:
        return f"'{where}' 열에 고른 항목({chosen.key})이 '{layout.sheet.name}' 시트에 없음", None, header
    if column.key in mapped.positions or column.key in mapped.flagged:
        return f"'{column.header}' 항목에 두 열 선택됨 · 한 열만 남기기", column.header, header
    return None


def _filled(value: object) -> bool:
    return value is not None and bool(str(value).strip())


def _preview(text: str, limit: int = 30) -> str:
    return text if len(text) <= limit else f"{text[:limit]}…"


def _rows_text(numbers: list[int]) -> str:
    """행 번호 목록 → '1~3' · '1, 4'(이어진 구간은 물결표로)."""
    spans: list[list[int]] = []
    for number in numbers:
        if spans and number == spans[-1][-1] + 1:
            spans[-1].append(number)
        else:
            spans.append([number])
    return ", ".join(str(s[0]) if len(s) == 1 else f"{s[0]}~{s[-1]}" for s in spans)


def _unit(
    column: Column,
    unit: str | None,
    header: str | None,
    written: str | None,
    ignore_unit: bool = False,
    noted: bool = False,
) -> tuple[float | None, str | None]:
    """원본 단위 → (배율, 문제). 단위가 필요한 항목에서 원본 단위를 모르면 추측하지 않는다 — 예외는 지정 양식 관례
    하나(머리글 이름이 양식과 정확히 같고 단위 표기가 없음 → 양식 단위).

    written(머리글에 적힌 단위 — 두 줄 머리글이면 위 줄 묶음 단위 포함, mapping.header_units)가 있으면,
    확정 매핑이 그 단위와 다를 때(단위를 비운 것 포함) 사람이 열 확인에서 '머리글 단위를 쓰지 않음'
    (ignore_unit)을 고른 경우에만 받는다 — 화면이 단위를 비워 보내도 머리글의 % · inch · 묶음 단위를
    조용히 버리지 않게. noted(제목·메모 행에 단위 표기, mapping.unit_notes)면 관례를
    쓰지 않는다 — '(단위: 천원)' 아래 금액을 원 단위로 짐작하지 않게.
    """
    shown = header or column.header
    if not column.unit:
        if unit is not None:
            return None, (
                f"'{shown}' 열에 단위({unit}) 표기 · '{column.header}' 항목은 단위 없음(규격 단위 따름) — "
                "열 확인에서 '단위 없음' 선택 또는 머리글에서 단위 삭제"
            )
        if written is not None and not ignore_unit:
            return None, (
                f"'{shown}' 열 머리글에 단위({written}) 표기 · '{column.header}' 항목은 단위 없음 — "
                "값이 그 단위면 원본 엑셀 수정, 아니면 열 확인에서 '머리글 단위를 쓰지 않고 "
                "그대로 읽기' 선택"
            )
        return 1.0, None
    if unit is None:
        same_name = header is not None and header_key(split_unit(header)[0]) == header_key(column.header)
        if written is None and not noted and same_name:
            return 1.0, None
        if noted:
            return None, (
                f"'{shown}' 열의 원본 단위 미확인 · 시트의 제목·메모 행에 단위 표기가 있어 양식 단위"
                f"({column.unit}) 판단 불가 — 원본 단위 선택 필요"
            )
        return None, (
            f"'{shown}' 열의 원본 단위 미확인 · '{column.header}' 항목은 {column.unit} 단위 — 원본 단위 선택 필요"
        )
    factor = unit_factor(unit, column.unit)
    if factor is None:
        return None, f"'{shown}' 열의 단위({unit})를 '{column.header}' 항목의 단위({column.unit})로 변환 불가"
    if written is not None and not ignore_unit and unit_factor(written, column.unit) != factor:
        return None, (
            f"'{shown}' 열 머리글의 단위({written})와 고른 원본 단위({unit}) 불일치 · 열 확인에서 원본 단위 확인"
        )
    return factor, None
