"""결과 파일 쓰기(docs/backtest.md 5절): backtest_result.xlsx(요약·사례별·가정·고정 가정값)와 같은 내용의
backtest_result.md.

두 파일 모두 원문 칸(변경 내용·블록·구역)이 없다 — 사례(Case)에 처음부터 담지 않는다.
마크다운은 다른 문서로 옮길 때 쓴다.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .compare import CaseResult
from .engine import Engine
from .summary import Summary
from .tables import Cell, Pct, Table, assumption_tables, case_tables, summary_table

XLSX_NAME = "backtest_result.xlsx"
MD_NAME = "backtest_result.md"
NO_VALUE = "—"


def write_results(results: Sequence[CaseResult], summary: Summary, engine: Engine, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_tab = summary_table(summary, engine)
    cases = case_tables(results)
    assumed, fixed = assumption_tables(results, engine)
    xlsx = _write_xlsx(out_dir / XLSX_NAME, summary_tab, _joined(cases), assumed, fixed)
    md = out_dir / MD_NAME
    md.write_text(markdown(summary, engine, (summary_tab, *cases, assumed, fixed)), encoding="utf-8", newline="\n")
    return xlsx, md


def _joined(tables: Sequence[Table]) -> Table:
    """사례별 시트: 네 표를 사례 번호 하나로 이어 붙인 넓은 표(머리글에 표 이름을 붙임)."""
    first, *rest = tables
    headers = list(first.headers)
    rows = [list(row) for row in first.rows]
    for table in rest:
        headers.extend(f"{table.title} · {h}" for h in table.headers[1:])
        for row, extra in zip(rows, table.rows, strict=True):
            row.extend(extra[1:])
    return Table("사례별", tuple(headers), tuple(tuple(row) for row in rows))


def _write_xlsx(path: Path, *tables: Table) -> Path:
    workbook = Workbook()
    default = workbook.active
    if default is not None:
        workbook.remove(default)
    for table in tables:
        sheet = workbook.create_sheet(table.title.split("(")[0])
        _fill(sheet, table)
    workbook.save(path)
    return path


def _fill(sheet: Worksheet, table: Table) -> None:
    sheet.append(list(table.headers))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for row in table.rows:
        sheet.append([_xlsx_value(value) for value in row])
        for cell, value in zip(sheet[sheet.max_row], row, strict=True):
            cell.number_format = _xlsx_format(value)
    sheet.freeze_panes = "B2"
    for index, header in enumerate(table.headers, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = max(10, min(48, len(header) * 2 + 2))


def _xlsx_value(value: Cell) -> object:
    return value.value if isinstance(value, Pct) else value


def _xlsx_format(value: Cell) -> str:
    if isinstance(value, Pct):
        return "+0.0%;-0.0%;0.0%" if value.signed else "0.0%"
    if isinstance(value, float):
        return "#,##0.0##"
    if isinstance(value, int):
        return "#,##0"
    return "General"


def md_value(value: Cell) -> str:
    if value is None:
        return NO_VALUE
    if isinstance(value, Pct):
        return f"{value.value:+.1%}" if value.signed else f"{value.value:.1%}"
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return value.replace("|", "\\|").replace("\n", " ")


def md_table(table: Table) -> str:
    lines = [f"## {table.title}", "", "| " + " | ".join(table.headers) + " |"]
    lines.append("|" + "|".join("---" for _ in table.headers) + "|")
    lines.extend("| " + " | ".join(md_value(value) for value in row) + " |" for row in table.rows)
    if not table.rows:
        lines.append("| " + " | ".join(NO_VALUE for _ in table.headers) + " |")
    return "\n".join(lines)


def markdown(summary: Summary, engine: Engine, tables: Sequence[Table]) -> str:
    versions = " · ".join(f"{name} {version}" for name, version in engine.versions())
    head = [
        "# 백테스트 결과 — 예측 대 실제",
        "",
        f"- 사례 {summary.cases}건(계산 {summary.computed} · 계산 불가 {summary.failed}) · "
        "원문 칸(변경 내용·블록·구역)은 이 파일에 미포함 — 사례 번호로만 표시",
        f"- 판: {versions}",
        "- 실제 값은 양식의 최소·최대 가운데를 대표값으로 사용 · 실제 값이 없는 칸은 '비교 불가'",
        "- 작은 지도(배 1척·블록 1개)로 계산한 값 · 이웃 블록·공정 파급은 사례가 준 범위만 반영(docs/backtest.md 6절)",
    ]
    return "\n\n".join(["\n".join(head), *(md_table(table) for table in tables)]) + "\n"
