"""상태 올리기(바뀌는 시트만, docs/input.md(엑셀 양식) 5절): 발주·발주 관측·공정·공정 확인 시트에서 상태·날짜만 읽는다.

가져오기와 같은 읽기(매핑 제안·열 확인·확정 매핑)를 쓰되 양식은 상태 시트(STATUS_SHEETS)만 고른다 —
ID와 관측·확인 값만 필수. 다른 시트는 읽지 않고, 빈 칸은 '바꾸지 않음'이다.
읽기 오류가 하나라도 있으면 갱신을 만들지 않는다(가져오기와 같은 원칙).
갱신을 지금 지도에 적용할 수 있는지(없는 ID·역행 등)는 engine.updates가 따로 본다.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from ripple.contracts.domain import ActivityCheck, POStatus
from ripple.contracts.ingest import (
    ColumnProposal,
    ConfirmedMapping,
    ImportSummary,
    IssueCode,
    IssueSeverity,
    MappingProposal,
    SheetProposal,
)
from ripple.contracts.updates import (
    ActivityActualItem,
    ActivityCheckItem,
    POEntryItem,
    POPlanItem,
    POStatusItem,
    StatusUpdate,
    UpdateItem,
    UpdateOrigin,
)

from .fields import FieldDictionary, default_fields
from .proposal_view import template_sheets
from .rows import read
from .sheet_tables import tables
from .table_types import Issues, Record
from .template import ENTERED_COLUMNS, STATUS_COLUMNS, STATUS_SHEETS, TEMPLATE_VERSION
from .workbook import RawSheet

PLAN_KEYS = ("planned_order_date", "material_secured_days", "fabrication_start_days", "lead_time_days")
NOT_READ = "상태 올리기에서는 이 시트 읽기 제외(발주·발주 관측·공정·공정 확인만)"


def status_proposal(proposal: MappingProposal) -> MappingProposal:
    """전체 가져오기 제안 → 상태 올리기 제안: 상태 시트만 고를 수 있고, 그 시트에서도 상태 열만 읽는다."""
    template = template_sheets("status")
    required = {sheet.key: {c.key for c in sheet.columns if c.required} for sheet in template}
    sheets = tuple(_status_sheet(sheet, required) for sheet in proposal.sheets)
    pending = sum(not s.certain for s in sheets if s.template) + sum(
        1 for s in sheets for c in s.columns if c.key and not c.auto
    )
    exact = proposal.exact and all(s.template is None or s.template in STATUS_COLUMNS for s in proposal.sheets)
    return proposal.model_copy(update={"sheets": sheets, "template": template, "pending": pending, "exact": exact})


def _status_sheet(sheet: SheetProposal, required: Mapping[str, set[str]]) -> SheetProposal:
    if sheet.template is None or sheet.template not in STATUS_COLUMNS:
        reasons = (NOT_READ,) if sheet.template else sheet.reasons
        return sheet.model_copy(
            update={"template": None, "certain": True, "columns": (), "missing_required": (), "reasons": reasons}
        )
    keep = STATUS_COLUMNS[sheet.template]
    columns = tuple(_status_column(column, keep) for column in sheet.columns)
    chosen = {c.key for c in columns if c.key}
    missing = tuple(key for key in sorted(required[sheet.template]) if key not in chosen)
    return sheet.model_copy(update={"columns": columns, "missing_required": missing})


def _status_column(column: ColumnProposal, keep: tuple[str, ...]) -> ColumnProposal:
    if column.key is None or column.key in keep:
        return column
    return column.model_copy(update={"key": None, "auto": True, "problems": ()})  # 구조 열은 읽지 않음


def build_update(
    raw: Mapping[str, RawSheet], file: str, mapping: ConfirmedMapping, fields: FieldDictionary | None = None
) -> tuple[StatusUpdate | None, ImportSummary]:
    """엑셀(읽은 시트) + 확정 매핑 → (상태 갱신, 요약). 읽기 오류가 있거나 읽은 항목이 없으면 갱신은 None."""
    issues = Issues()
    found = tables(raw, mapping, fields or default_fields(), issues, STATUS_SHEETS)
    records = {key: read(table, issues) for key, table in found.items()}
    items: list[UpdateItem] = []
    if not issues.has_errors:
        items = _items(records, file)
        if not items:
            issues.add(
                IssueSeverity.ERROR,
                IssueCode.MISSING_SHEET,
                "읽은 상태 없음 · 발주·발주 관측·공정 시트 확인",
            )
    summary = ImportSummary(
        template_version=TEMPLATE_VERSION,
        file=file,
        counts={key: len(rows) for key, rows in records.items()},
        issues=tuple(issues.items),
    )
    if issues.has_errors:
        return None, summary
    return StatusUpdate(origin=UpdateOrigin.EXCEL, file_name=file[:200], items=tuple(items)), summary


def _items(records: Mapping[str, list[Record]], file: str) -> list[UpdateItem]:
    items: list[UpdateItem] = []
    for record in records.get("purchase_orders", []):
        items += _order_items(record, file)
    for record in records.get("observations", []):
        v = record.values
        items.append(
            POStatusItem(
                po_id=str(v["po_id"]),
                status=POStatus(str(v["status"])),
                observed_on=_day(v["observed_on"]),
                source=record.source(file),
            )
        )
    for record in records.get("activities", []):
        v = record.values
        if v.get("actual_start") is None and v.get("actual_finish") is None:
            continue
        items.append(
            ActivityActualItem(
                activity_id=str(v["activity_id"]),
                actual_start=_maybe_day(v.get("actual_start")),
                actual_finish=_maybe_day(v.get("actual_finish")),
                source=record.source(file),
            )
        )
    for record in records.get("activity_checks", []):
        v = record.values
        items.append(
            ActivityCheckItem(
                activity_id=str(v["activity_id"]),
                state=ActivityCheck(str(v["state"])),
                confirmed_on=_day(v["confirmed_on"]),
                source=record.source(file),
            )
        )
    return items


def _order_items(record: Record, file: str) -> list[UpdateItem]:
    v = record.values
    po_id = str(v["po_id"])
    source = record.source(file)
    items: list[UpdateItem] = []
    for key in PLAN_KEYS:
        value = v.get(key)
        if isinstance(value, date) or (isinstance(value, int) and not isinstance(value, bool)):
            items.append(POPlanItem(po_id=po_id, field=key, value=value, source=source))
    for status, key in ENTERED_COLUMNS.items():
        entered = v.get(key)
        if isinstance(entered, date):
            items.append(POEntryItem(po_id=po_id, status=status, entered_on=entered, source=source))
    return items


def _day(value: object) -> date:
    if not isinstance(value, date):
        raise ValueError(f"날짜 아님: {value!r}")
    return value


def _maybe_day(value: object) -> date | None:
    return value if isinstance(value, date) else None
