"""사례 양식 엑셀(docs/backtest.md 2절): 빈 양식(+ 설명 시트) 쓰기와 사례 읽기.

'사례' 시트의 한 행 = 한 사례. 1행은 머리글(COLUMNS의 이름 그대로), 2행부터 사례. 선택 칸은 드롭다운, 숫자 칸은
0 이상 숫자만 받게 데이터 유효성 검사를 건다. 읽을 때 원문 칸(변경 내용·블록·구역)은 행이 비었는지 볼 때만 쓴다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from .case import COLUMNS, Case, Column, parse_case

CASE_SHEET = "사례"
GUIDE_SHEET = "설명"
INPUT_ROWS = 200  # 유효성 검사를 거는 행 수(2행부터)
PRIVATE_FILL = PatternFill("solid", fgColor="FFF2CC")  # 원문 칸 머리글: 결과로 옮기지 않음

GUIDE: tuple[tuple[str, str], ...] = (
    ("이 파일", "과거 설계변경 사례를 한 행에 하나씩 적는 양식 · Ripple 예측과 실제 결과 비교용"),
    (
        "실데이터 취급",
        "회사·호선·사람 이름 기입 금지 · 채운 파일은 저장소·팀 공유 문서·외부 AI·발표 자료에 올리기 금지",
    ),
    ("원문 칸", "노란 머리글(변경 내용·블록·구역)은 확인용 · 결과 파일(엑셀·마크다운)에는 미포함"),
    ("모르는 칸", "빈칸으로 두기(지어내기 금지) — 빈칸은 기본값으로 계산, 결과의 '가정' 시트에 기록"),
    ("숫자 칸", "숫자만 기입(단위는 머리글) · 범위는 최소·최대 두 칸, 한 값만 알면 두 칸에 같은 값"),
    (
        "발견 단계",
        "엔진의 블록 단계에서 선택 · 예: 선행도장 뒤 → 선행도장, PE(탑재 전 블록 합치기) → PE, 탑재 뒤 → 탑재",
    ),
    ("블록 종류", "재작업 난이도(평·곡·선수미 형상 계수)에 사용 · 블록 무게가 비면 종류별 기본 무게 선택에도 사용"),
    ("변경 원인", "선주 코멘트는 '선주 요청'으로 계산(늘어난 인도 지연은 지체상금 대신 인도일 조정 대상)"),
    (
        "재제작 방식",
        "사내 재제작·사외 재발주는 옛 스풀을 빼고 새로 제작(새 스풀 리드타임만 차이) · "
        "치수 변경은 같은 자재를 다시 가공",
    ),
    ("추가 공수", "변경 전체 공수(재작업·도면 개정 등) · 예측의 모든 공수 합과 비교"),
    ("비용", "이 변경에 든 비용 · 예측 총액과 비교(지연 파급 비용은 결과에 따로 표시)"),
    (
        "지연 일수·지연 기준",
        "이 변경으로 늦어진 날과 그 기준(탑재·구역 출구·인도) · 기준이 비면 구역 출구와 비교",
    ),
    ("결정까지 걸린 일수", "확정일 = 발견한 날 + 이 일수 · 비면 발견한 날 확정으로 간주"),
    (
        "수행 주체",
        "사내 협력사는 탑재를 뺀 블록 공정을 작업반이 맡은 것으로 계산(작업반 단가는 지금 직영과 동일)",
    ),
    ("계산하는 법", "uv run python scripts/backtest.py run <이 파일> <저장소 밖 출력 폴더>"),
)


def write_template(path: Path, rows: Sequence[Mapping[str, object]] = ()) -> Path:
    """빈 양식(rows가 있으면 그 행을 채운 양식). 열 키 → 값."""
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = CASE_SHEET
    sheet.append([column.header for column in COLUMNS])
    for row in rows:
        sheet.append([row.get(column.key) for column in COLUMNS])
    _decorate(sheet)
    _guide(workbook.create_sheet(GUIDE_SHEET))
    workbook.save(path)
    return path


def _decorate(sheet: Worksheet) -> None:
    for index, column in enumerate(COLUMNS, start=1):
        letter = get_column_letter(index)
        header = sheet.cell(row=1, column=index)
        header.font = Font(bold=True)
        header.alignment = Alignment(wrap_text=True, vertical="top")
        if column.private:
            header.fill = PRIVATE_FILL
        sheet.column_dimensions[letter].width = 36 if column.kind == "text" else max(12, len(column.header) * 2)
        validation = _validation(column)
        if validation is not None:
            sheet.add_data_validation(validation)
            validation.add(f"{letter}2:{letter}{INPUT_ROWS + 1}")
    sheet.freeze_panes = "B2"


def _validation(column: Column) -> DataValidation | None:
    if column.kind == "choice":
        return DataValidation(
            type="list",
            formula1='"' + ",".join(column.options) + '"',
            allow_blank=True,
            showErrorMessage=True,
            error="목록에 있는 값만 선택 가능",
        )
    if column.kind in ("number", "count"):
        return DataValidation(
            type="whole" if column.kind == "count" else "decimal",
            operator="greaterThanOrEqual",
            formula1="0",
            allow_blank=True,
            showErrorMessage=True,
            error="0 이상의 숫자만 가능" if column.kind == "number" else "0 이상의 정수만 가능",
        )
    return None


def _guide(sheet: Worksheet) -> None:
    sheet.append(["항목", "쓰는 법"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for item, text in GUIDE:
        sheet.append([item, text])
    sheet.append([])
    sheet.append(["열", "설명", "선택지"])
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True)
    for column in COLUMNS:
        sheet.append([column.header, column.note, " · ".join(column.options)])
    sheet.column_dimensions["A"].width = 24
    sheet.column_dimensions["B"].width = 90
    sheet.column_dimensions["C"].width = 60
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")


class InputError(ValueError):
    """양식이 아니라 읽을 수 없는 파일(사람이 읽는 이유)."""


def read_cases(path: Path) -> tuple[Case, ...]:
    """'사례' 시트의 행 → 사례(빈 행은 건너뜀). 머리글이 양식과 다르면 InputError."""
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if CASE_SHEET not in workbook.sheetnames:
            raise InputError(f"'{CASE_SHEET}' 시트 없음 · scripts/backtest.py template으로 만든 양식 필요")
        rows = workbook[CASE_SHEET].iter_rows(values_only=True)
        header = [str(value).strip() if value is not None else "" for value in next(rows, ())]
        missing = [column.header for column in COLUMNS if column.header not in header]
        if missing:
            raise InputError(f"양식 열 누락: {', '.join(missing)}")
        positions = {column.key: header.index(column.header) for column in COLUMNS}
        cases: list[Case] = []
        for number, values in enumerate(rows, start=2):
            cells = {key: values[i] if i < len(values) else None for key, i in positions.items()}
            if all(value is None or (isinstance(value, str) and not value.strip()) for value in cells.values()):
                continue
            cases.append(parse_case(cells, row=number, ordinal=len(cases) + 1))
        return tuple(cases)
    finally:
        workbook.close()
