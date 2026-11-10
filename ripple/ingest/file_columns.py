"""파일 열 읽기와 값·단위 검사(열 자동 매핑의 재료, docs/input.md(엑셀 양식) 4절).

표 찾기 결과 위의 파일 열(머리글·앞 40행 값·머리글 단위), 정확 일치 항목, 단위 상태(짐작하지 않음), 앞 40행 값을 그
항목으로 읽어 본 결과. 단위 상태와 값 검사는 특징·자격·보정·평가가 같은 함수를 쓴다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from ripple.contracts.ingest import UnitState

from .mapping import data_rows, exact_column, header_units
from .normalize import split_unit, unit_factor, unit_token
from .tables import column_texts
from .template import Column, Sheet
from .values import parse
from .workbook import RawSheet

SAMPLE_ROWS = 40  # 값 모양을 볼 앞 데이터 행 수
References = Mapping[str, frozenset[str]]
"""양식 시트 키 → 그 시트 ID 열의 값(파일 안)."""


@dataclass(frozen=True, slots=True)
class FileColumn:
    """표 찾기 결과 위의 파일 열 하나."""

    position: int
    header: str | None  # 합친 머리글(두 줄이면 묶음 이름 + 칸 이름)
    own: str | None  # 그 열 칸의 머리글(한 줄 머리글이면 header와 같음)
    values: tuple[object, ...]  # 앞 40 데이터 행의 값(빈칸 포함)
    epoch: datetime
    written: str | None = None  # 머리글에 적힌 단위(두 줄이면 위 줄 묶음 단위까지 — mapping.header_units, 서버와 같음)

    @property
    def names(self) -> tuple[str, ...]:
        """단위를 뺀 머리글 이름(합친 이름 먼저, 겹치면 하나)."""
        found: list[str] = []
        for text in (self.header, self.own):
            if text is not None and (name := split_unit(text)[0]) and name not in found:
                found.append(name)
        return tuple(found)

    @property
    def unit(self) -> str | None:
        """그 열 머리글의 단위 표기(그 열 칸 이름 먼저). 위 줄 묶음에서 물려받은 단위는 넣지 않는다(inherited)."""
        for text in (self.own, self.header):
            if text is not None and (unit := split_unit(text)[1]) is not None:
                return unit
        return None

    @property
    def inherited(self) -> bool:
        """단위가 위 줄 묶음 이름에만 적힘. 묶음이 이 열까지 걸치는지는 값만으로 알 수 없다(병합 범위를 읽지 않음)."""
        return self.unit is None and self.written is not None

    @property
    def filled(self) -> tuple[object, ...]:
        return tuple(v for v in self.values if v is not None and str(v).strip())


def read_columns(raw: RawSheet, header_rows: Sequence[int]) -> list[FileColumn]:
    """머리글이나 값이 있는 파일 열(위치 순)."""
    merged, own = column_texts(raw, header_rows)
    units = header_units(raw, header_rows)
    data, _ = data_rows(raw, header_rows)
    sample = data[:SAMPLE_ROWS]
    width = max([len(merged), *(len(cells) for _, cells in sample)])
    columns = []
    for i in range(width):
        values = tuple(cells[i] if i < len(cells) else None for _, cells in sample)
        header = merged[i] if i < len(merged) else None
        written = units[i] if i < len(units) else None
        column = FileColumn(i, header, own[i] if i < len(own) else None, values, raw.epoch, written)
        if header is not None or column.filled:
            columns.append(column)
    return columns


def exact_key(sheet: Sheet, column: FileColumn) -> str | None:
    """정확 일치 항목: 합친 이름 먼저('선행 공정ID'), 없으면 그 열 칸 이름."""
    for text in (column.header, column.own):
        if text is not None and (found := exact_column(sheet, text)) is not None:
            return found.key
    return None


def unit_state(
    column: Column, file_column: FileColumn, exact: bool, noted: bool = False
) -> tuple[UnitState, str | None, float | None, str | None]:
    """(상태, 원본 단위 표기, 배율, 문제). 단위가 필요한데 모르면 짐작하지 않는다 — 예외는 지정 양식 관례 하나
    (이름이 양식과 정확히 같고 단위만 빠짐 → 양식 단위). 단위가 그 열 머리글이 아니라 위 줄 묶음(inherited)이나
    제목·메모 행(noted, mapping.unit_notes)에만 적혀 있으면 그 단위가 이 열 것인지 알 수 없어 관례를 쓰지 않고
    자동으로 정하지도 않는다."""
    unit = file_column.unit
    if file_column.inherited:
        group = file_column.written
        if not column.unit:
            return (
                UnitState.UNRESOLVED,
                group,
                None,
                f"위 줄 묶음 머리글의 단위({group})가 이 열에도 걸리는지 미확인('{column.header}' 항목은 단위 없음)",
            )
        return (
            UnitState.UNRESOLVED,
            None,
            None,
            f"단위가 위 줄 묶음 머리글({group})에만 있음 — 이 열에도 맞는지 보고 원본 단위 선택",
        )
    if not column.unit:
        if unit is None:
            return UnitState.NOT_NEEDED, None, 1.0, None
        return (
            UnitState.UNRESOLVED,
            unit,
            None,
            f"'{column.header}' 항목은 단위 없음 · 머리글에 단위({unit}) 표기",
        )
    if unit is None:
        if exact and not noted:
            return UnitState.CONFIRMED, unit_token(column.unit), 1.0, None
        if noted:
            return (
                UnitState.UNRESOLVED,
                None,
                None,
                f"제목·메모 행에 단위 표기가 있어 양식 단위({column.unit}) 판단 불가 — 원본 단위 선택",
            )
        return UnitState.UNRESOLVED, None, None, f"원본 단위 미확인('{column.header}' 항목은 {column.unit} 단위)"
    factor = unit_factor(unit, column.unit)
    if factor is None:
        return (
            UnitState.UNRESOLVED,
            unit,
            None,
            f"단위({unit})를 '{column.header}' 항목의 단위({column.unit})로 변환 불가",
        )
    return UnitState.CONFIRMED, unit, factor, None


@dataclass(frozen=True, slots=True)
class ValueCheck:
    """앞 40행 값을 그 항목으로 읽어 본 결과."""

    filled: int
    parsed: int
    in_range: int  # 상식 범위가 있는 숫자 항목에서 범위 안(없으면 parsed와 같음)
    integral: int
    numeric: int  # 숫자로 읽히는 값

    @property
    def all_parsed(self) -> bool:
        return self.parsed == self.filled

    @property
    def all_in_range(self) -> bool:
        return self.in_range == self.parsed


def check_values(
    column: Column, file_column: FileColumn, factor: float, bounds: tuple[float, float] | None
) -> ValueCheck:
    filled = file_column.filled
    parsed = in_range = integral = numeric = 0
    for value in filled:
        result, problem = parse(column, value, factor, file_column.epoch)
        if (isinstance(value, (int, float)) and not isinstance(value, bool)) or _numeric_text(value):
            numeric += 1
        if problem is not None:
            continue
        parsed += 1
        if isinstance(result, (int, float)) and not isinstance(result, bool):
            integral += float(result).is_integer()
            in_range += bounds is None or bounds[0] <= result <= bounds[1]
        else:
            in_range += 1
    return ValueCheck(len(filled), parsed, in_range, integral, numeric)


_NUMERIC = re.compile(r"^[+-]?\d[\d,]*(\.\d+)?$")


def _numeric_text(value: object) -> bool:
    return isinstance(value, str) and bool(_NUMERIC.match(value.strip()))
