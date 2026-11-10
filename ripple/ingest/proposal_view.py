"""매핑 제안 → 계약(열 확인 화면, docs/input.md(엑셀 양식) 4절): 고를 수 있는 양식 시트·열, 시트·열 제안과 미리보기,
제안 그대로의 확정 매핑(mapping_of)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from functools import lru_cache
from typing import Literal

from openpyxl.utils import get_column_letter

from ripple.contracts.ingest import (
    ColumnMapping,
    ColumnProposal,
    ConfirmedMapping,
    MappingProposal,
    PreviewRow,
    SheetMapping,
    SheetProposal,
    TemplateField,
    TemplateSheet,
    UnitOption,
    UnitState,
)

from .mapping import unit_notes
from .normalize import UNITS, unit_factor
from .plan_types import ColumnModel, FilePlan, RoutedColumn, pending
from .template import SHEET_BY_KEY, SHEETS, STATUS_SHEETS
from .workbook import ExcelError, RawSheet, Uncomputed

PREVIEW_ROWS = 12  # 머리글 고르기 미리보기 행 수
PREVIEW_COLUMNS = 40
TEXT_LIMIT = 40  # 미리보기·예시 값 글자 수
CALIBRATION_NOTE = "합성 변형 엑셀 기준 보정(실제 회사 엑셀로는 확인 전)"


@lru_cache(maxsize=2)
def template_sheets(kind: Literal["full", "status"] = "full") -> tuple[TemplateSheet, ...]:
    """고를 수 있는 양식 시트·열과 열마다 고를 수 있는 원본 단위(같은 차원, 배율 포함)."""
    return tuple(
        TemplateSheet(
            key=sheet.key,
            name=sheet.name,
            required=sheet.required,
            columns=tuple(
                TemplateField(
                    key=column.key,
                    header=column.header,
                    title=column.title,
                    required=column.required,
                    kind=column.kind.value,
                    unit=column.unit,
                    units=_unit_options(column.unit),
                )
                for column in sheet.columns
            ),
        )
        for sheet in (STATUS_SHEETS if kind == "status" else SHEETS)
    )


def _unit_options(unit: str) -> tuple[UnitOption, ...]:
    if not unit:
        return ()
    options = []
    for name in UNITS:
        factor = unit_factor(name, unit)
        if factor is not None:
            options.append(UnitOption(unit=name, factor=factor))
    return tuple(options)


def to_contract(
    plan: FilePlan, raw: Mapping[str, RawSheet], import_id: str, file: str, version: int, model: ColumnModel
) -> MappingProposal:
    sheets = []
    for sheet in plan.sheets:
        guess = sheet.guess
        columns = tuple(_column(c) for c in sheet.columns)
        keys = {c.key for c in columns if c.key}
        template = SHEET_BY_KEY[guess.template] if guess.template else None
        missing = tuple(c.key for c in template.columns if c.required and c.key not in keys) if template else ()
        sheets.append(
            SheetProposal(
                file_sheet=guess.file_sheet,
                template=guess.template,
                candidates=guess.candidates,
                certain=guess.certain,
                header_rows=guess.header.rows if guess.header else (),
                reasons=guess.reasons,
                preview=_preview(raw[guess.file_sheet]),
                columns=columns,
                missing_required=missing,
                unit_notes=unit_notes(raw[guess.file_sheet], guess.header.rows)
                if guess.template and guess.header
                else (),
            )
        )
    return MappingProposal(
        import_id=import_id,
        file=file,
        version=version,
        exact=plan.exact,
        pending=len(pending(plan)),
        sheets=tuple(sheets),
        template=template_sheets(),
        policy_version=model.version,
        calibration=CALIBRATION_NOTE,
    )


def _column(routed: RoutedColumn) -> ColumnProposal:
    j = routed.judgment
    fc = j.file_column
    confirmed = j.unit_state is UnitState.CONFIRMED
    return ColumnProposal(
        position=fc.position,
        letter=get_column_letter(fc.position + 1),
        header=fc.header,
        samples=tuple(_text(v) for v in fc.filled[:3]),
        key=j.key,
        method=j.method,
        answer=routed.answer,
        unit=j.unit if confirmed else fc.unit,
        header_unit=fc.written,  # 위 줄 묶음 단위까지(서버가 확정 매핑과 대조하는 것과 같은 값)
        unit_state=j.unit_state,
        factor=j.factor if confirmed else None,
        auto=routed.auto,
        problems=tuple(j.problems),
    )


def _preview(raw: RawSheet) -> tuple[PreviewRow, ...]:
    return tuple(
        PreviewRow(row=number, cells=tuple(_text(v) if v is not None else None for v in cells[:PREVIEW_COLUMNS]))
        for number, cells in raw.rows[:PREVIEW_ROWS]
    )


def _text(value: object) -> str:
    if isinstance(value, ExcelError):
        text = value.code
    elif isinstance(value, Uncomputed):
        text = value.formula
    elif isinstance(value, datetime):
        text = value.date().isoformat() if value.time() == datetime.min.time() else value.isoformat(sep=" ")
    elif isinstance(value, date):
        text = value.isoformat()
    elif isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = " ".join(str(value).split())
    return text if len(text) <= TEXT_LIMIT else f"{text[:TEXT_LIMIT]}…"


def mapping_of(proposal: MappingProposal) -> ConfirmedMapping:
    """제안 그대로의 확정 매핑(사람이 고치기 전). 단위가 미해결인 열은 원본 단위가 비어 읽기에서 오류가 난다."""
    sheets = []
    for sheet in proposal.sheets:
        if sheet.template is None or not sheet.header_rows:
            sheets.append(SheetMapping(file_sheet=sheet.file_sheet))
            continue
        sheets.append(
            SheetMapping(
                file_sheet=sheet.file_sheet,
                template=sheet.template,
                header_rows=sheet.header_rows,
                columns=tuple(
                    ColumnMapping(
                        position=c.position,
                        key=c.key,
                        unit=c.unit if c.unit_state is UnitState.CONFIRMED else None,
                    )
                    for c in sheet.columns
                ),
            )
        )
    return ConfirmedMapping(sheets=tuple(sheets))
