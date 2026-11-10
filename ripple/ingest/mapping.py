"""엑셀 표 찾기(결정적 부분): 머리글 행 합치기(한 줄·두 줄), 데이터 행과 메모 행, 머리글 이름의 정확 일치,
지정 양식 그대로인 파일의 매핑(docs/input.md(엑셀 양식) 2절).

열이 어느 항목인지 고르는 판단(흔한 변형)은 ripple/ingest/columns.py가 하고, 사용자가 열 확인 화면에서 확정한
매핑(ConfirmedMapping)으로 build.py가 읽는다. 여기 함수는 제안·읽기 양쪽이 같은 정의로 쓴다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from ripple.contracts.ingest import ColumnMapping, ConfirmedMapping, SheetMapping

from .normalize import header_key, split_unit
from .table_types import Row
from .template import GUIDE_SHEET, SHEETS, Column, Sheet
from .workbook import MAX_COLUMNS, ExcelError, Merge, RawSheet, Uncomputed

UNIT_NOTE = re.compile(r"단위\s*[:：]|[\(\[]\s*단위")
"""제목·메모 행의 단위 안내('부재 목록 (단위: cm)', '※ 금액 단위: 천원'). '단위는 머리글을 따릅니다'처럼 단위를
정하지 않는 글은 아니다."""
MEMO_PREFIXES = ("※", "*", "주)", "주:", "비고", "메모", "note")
"""메모 행: 칸 하나만 차 있고 이 말로 시작하는 글. 그 밖의 행은 모두 데이터로 읽는다(조용히 빼지 않는다)."""


def header_cells(raw: RawSheet, rows: Sequence[int]) -> tuple[str | None, ...]:
    """머리글 행의 칸을 위치마다 합친다. 두 줄이면 위 줄 이름(묶음)을 오른쪽 빈칸까지 이어 아래 줄 이름 앞에 붙인다
    (묶음은 아래 칸에 이름이 있거나 가로 병합된 위 칸만 — _starts_group).

    예: 위 줄 ['부재ID', '치수', None], 아래 줄 [None, '두께(mm)', '폭(mm)']
    → ['부재ID', '치수 두께(mm)', '치수 폭(mm)'].
    """
    found = {number: cells for number, cells in raw.rows}
    lines = [found.get(number, ()) for number in rows]
    width = max((len(line) for line in lines), default=0)
    if len(lines) == 1:
        return tuple(_text(lines[0][i]) if i < len(lines[0]) else None for i in range(width))
    top, bottom = lines[0], lines[1]
    merged: list[str | None] = []
    group: str | None = None
    for i in range(width):
        upper = _text(top[i]) if i < len(top) else None
        lower = _text(bottom[i]) if i < len(bottom) else None
        if upper is not None:
            group = upper if _starts_group(raw, rows[0], i, lower) else None
        elif lower is None:
            group = None  # 위·아래 모두 빈 열이 나오면 묶음이 끝난다
        if lower is None:
            merged.append(upper)
        elif upper is None and group is not None:
            merged.append(f"{group} {lower}")
        elif upper is not None:
            merged.append(f"{upper} {lower}")
        else:
            merged.append(lower)
    return tuple(merged)


def header_units(raw: RawSheet, rows: Sequence[int]) -> tuple[str | None, ...]:
    """위치마다 머리글에 적힌 단위 표기. 두 줄 머리글이면 그 열 칸 이름의 단위, 없으면 위 줄 묶음 이름의
    단위를 물려받는다(예: 위 '치수(cm)' 아래 '두께'·'스팬' → 둘 다 cm). 합친 이름의 끝만 보면 묶음 단위가
    사라진다. 묶음을 이어 가는 규칙은 header_cells와 같다.
    """
    found = {number: cells for number, cells in raw.rows}
    lines = [found.get(number, ()) for number in rows]
    width = max((len(line) for line in lines), default=0)
    if len(lines) == 1:
        line = lines[0]
        return tuple(_unit_of(line[i]) if i < len(line) else None for i in range(width))
    top, bottom = lines[0], lines[1]
    units: list[str | None] = []
    group: str | None = None
    for i in range(width):
        upper = _text(top[i]) if i < len(top) else None
        lower = _text(bottom[i]) if i < len(bottom) else None
        if upper is not None:
            group = split_unit(upper)[1] if _starts_group(raw, rows[0], i, lower) else None
        elif lower is None:
            group = None
        if lower is None:
            units.append(split_unit(upper)[1] if upper is not None else None)  # 위·아래를 합친 칸: 위 칸이 그 열 이름
        else:
            units.append(split_unit(lower)[1] or group)
    return tuple(units)


def _starts_group(raw: RawSheet, top_row: int, column: int, lower: str | None) -> bool:
    """위 줄 칸(0부터 column번째 열)이 오른쪽 빈칸까지 이어지는 묶음 이름인가: 그 아래 칸에 이름이 있거나(묶음의 첫
    하위 열), 위 줄에서 오른쪽으로 가로 병합된 칸. 아래 칸이 빈 한 칸짜리 열('부재ID'·'비고')은 묶음이 아니다 —
    그 오른쪽의 위가 빈 열에 이름·단위를 물려주지 않는다."""
    if lower is not None:
        return True
    first = column + 1  # 병합 범위는 엑셀 번호(1부터)
    return any(r1 <= top_row <= r2 and c1 == first and c2 > c1 for r1, c1, r2, c2 in raw.merges)


def unit_notes(raw: RawSheet, rows: Sequence[int]) -> tuple[str, ...]:
    """열 머리글 밖에 적힌 단위 표기: 머리글 위 행·메모 행의 단위 글('(단위: 천원)', 괄호 단위), 그리고 머리글 행
    안의 단위 안내 글('(단위: cm)' — 제목 행이 두 줄 머리글 위 줄로 잡혀도). 그 단위가 어느 열에 걸리는지 파일만으로는
    알 수 없으니, 있으면 지정 양식 관례(이름이 양식과 같고 단위가 빠짐 → 양식 단위)를 쓰지 않는다 — 단위가 필요한
    열은 사람이 고른다. 예: 제목 '발주 목록 (단위: 천원)' 아래 '발주 금액' 열을 원 단위로 짐작하면 1,000배 틀린다.
    머리글 행의 괄호 단위('강도 계산(cm)')는 묶음 단위(header_units)로 따로 본다.
    """
    if not rows:
        return ()
    first = min(rows)
    header = set(rows)
    _, memos = data_rows(raw, rows)
    outside = set(memos)
    notes: list[str] = []
    for number, cells in raw.rows:
        if first <= number and number not in outside and number not in header:
            continue  # 데이터 행
        for cell in cells:
            text = _text(cell)
            if text is None or text in notes:
                continue
            if UNIT_NOTE.search(text) or (number not in header and split_unit(text)[1]):
                notes.append(text)
    return tuple(notes)


def _unit_of(value: object) -> str | None:
    text = _text(value)
    return split_unit(text)[1] if text is not None else None


def is_memo(cells: Sequence[object]) -> bool:
    filled = [c for c in cells if c is not None and str(c).strip()]
    if len(filled) != 1 or not isinstance(filled[0], str):
        return False
    return filled[0].strip().casefold().startswith(MEMO_PREFIXES)


def data_rows(raw: RawSheet, header_rows: Sequence[int]) -> tuple[tuple[Row, ...], tuple[int, ...]]:
    """머리글 아래의 (데이터 행, 메모로 보고 뺀 행 번호). 데이터 영역의 병합 칸은 왼쪽 위 값으로 채운다(data_merges)."""
    after = max(header_rows)
    data: list[Row] = []
    memos: list[int] = []
    for number, cells in raw.rows:
        if number <= after:
            continue
        if is_memo(cells):
            memos.append(number)
        else:
            data.append((number, cells))
    fills = _merge_fills(raw, data_merges(raw, header_rows, memos))
    if fills:
        data = [(number, _filled(cells, fills.get(number))) for number, cells in data]
    return tuple(data), tuple(memos)


def data_merges(raw: RawSheet, header_rows: Sequence[int], memos: Sequence[int] | None = None) -> tuple[Merge, ...]:
    """데이터 영역의 병합 범위: 머리글 아래에서 시작하고 왼쪽 위 칸에 값이 있으며 메모 행에서 시작하지 않는 것.

    현장 엑셀은 같은 값이 이어지는 호선·블록 칸을 세로로 병합하는데 파일에는 첫 칸에만 값이 있다. 병합을 읽지 않으면
    나머지 행이 모두 '값 비어 있음'이 된다(점검 D-2). 머리글 행의 병합(두 줄 머리글 묶음)과 머리글 위 제목 병합은
    여기 들지 않는다 — 머리글 처리는 header_cells 그대로다."""
    if not raw.merges:
        return ()
    after = max(header_rows)
    skipped = set(memos) if memos is not None else set(data_rows(raw, header_rows)[1])
    found = dict(raw.rows)
    return tuple(
        m for m in raw.merges if m[0] > after and m[0] not in skipped and _filled_value(found.get(m[0], ()), m[1] - 1)
    )


def _filled_value(cells: Sequence[object], position: int) -> bool:
    return position < len(cells) and cells[position] is not None and str(cells[position]).strip() != ""


def _merge_fills(raw: RawSheet, merges: Sequence[Merge]) -> dict[int, dict[int, object]]:
    """행 번호 → (위치(0부터) → 채울 값): 병합 범위의 왼쪽 위 값을 나머지 칸에."""
    found = dict(raw.rows)
    fills: dict[int, dict[int, object]] = {}
    for top, left, bottom, right in merges:
        value = found[top][left - 1]
        for number in range(top, bottom + 1):
            if number not in found:
                continue  # 완전히 빈 행은 데이터 행이 아니다(채워서 새 행을 만들지 않음)
            row = fills.setdefault(number, {})
            for position in range(left - 1, min(right, MAX_COLUMNS)):
                if (number, position) != (top, left - 1):
                    row[position] = value
    return fills


def _filled(cells: tuple[object, ...], fills: dict[int, object] | None) -> tuple[object, ...]:
    """빈 칸만 채운다(행 너비 안 — 엑셀이 저장한 범위 밖으로 넓히지 않음)."""
    if not fills:
        return cells
    return tuple(fills[i] if i in fills and not _filled_value(cells, i) else value for i, value in enumerate(cells))


def exact_column(sheet: Sheet, header: str | None) -> Column | None:
    """단위를 뺀 머리글 이름이 양식 열 머리글과 정확히 같은 열(공백·대소문자·문장부호 무시)."""
    if header is None:
        return None
    base, _ = split_unit(header)
    wanted = header_key(base)
    return next((c for c in sheet.columns if header_key(c.header) == wanted), None)


def is_guide(name: str) -> bool:
    return header_key(name) == header_key(GUIDE_SHEET)


def exact_sheet(name: str) -> Sheet | None:
    wanted = header_key(name)
    return next((s for s in SHEETS if header_key(s.name) == wanted), None)


def exact_mapping(raw: Mapping[str, RawSheet]) -> ConfirmedMapping:
    """지정 양식 그대로인 파일의 매핑: 시트 이름이 양식과 같은 시트만, 첫 행이 머리글, 머리글 이름이 양식과 같은 열.

    단위는 머리글에 적힌 대로(없으면 None — 이름이 양식과 정확히 같으면 양식 단위로 읽는 지정 양식 관례).
    """
    sheets: list[SheetMapping] = []
    for name, sheet_raw in raw.items():
        template = exact_sheet(name)
        if template is None or is_guide(name) or not sheet_raw.rows:
            sheets.append(SheetMapping(file_sheet=name))
            continue
        header_row = sheet_raw.rows[0][0]
        columns = []
        for position, header in enumerate(header_cells(sheet_raw, (header_row,))):
            column = exact_column(template, header)
            if column is not None and header is not None:
                columns.append(ColumnMapping(position=position, key=column.key, unit=split_unit(header)[1]))
        sheets.append(
            SheetMapping(file_sheet=name, template=template.key, header_rows=(header_row,), columns=tuple(columns))
        )
    return ConfirmedMapping(sheets=tuple(sheets))


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, ExcelError):
        value = value.code
    elif isinstance(value, Uncomputed):
        value = value.formula
    text = " ".join(str(value).split())
    return text or None
