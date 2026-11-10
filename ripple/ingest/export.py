"""지도 → Ripple 지정 양식 엑셀(docs/input.md(엑셀 양식)).

시연용 양식 파일과 가져오기 왕복 검사에 쓴다. 맨 앞에 '양식 안내' 시트(시트·열·필수·단위·허용 값)를 두고,
코드 열은 한글 라벨로 쓴다. 가져오기는 안내 시트를 읽지 않는다.
"""

from __future__ import annotations

import io
from collections.abc import Mapping

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from ripple.contracts.domain import DIRECT_PERFORMER, Activity, GraphSnapshot

from .template import ACTIVITY_KINDS, DIRECT_LABEL, ENTERED_COLUMNS, GUIDE_SHEET, SHEETS, Kind, Sheet

__all__ = ["GUIDE_SHEET", "OPTIONAL_EMPTY", "rows_of", "to_bytes", "to_workbook"]
Row = Mapping[str, object]
OPTIONAL_EMPTY = ("pipe_systems", "boundaries", "observations", "activity_checks", "stock", "connections", "crews")
"""지도에 행이 없으면 만들지 않는 선택 시트(빈 시트 = '없음 확인'과 구분)."""


def _activity_row(activity: Activity) -> dict[str, object]:
    """공정 행: 수행 주체의 직영은 한글 표기로(작업반ID는 그대로)."""
    row = activity.model_dump(exclude={"predecessors", "confirmations"})
    if activity.performer == DIRECT_PERFORMER:
        row["performer"] = DIRECT_LABEL
    return row


def rows_of(snapshot: GraphSnapshot) -> dict[str, list[Row]]:
    """시트 키 → 행(열 키 → 계약 값). 코드 열은 계약 값 그대로(쓸 때 한글 라벨로 바꾼다)."""
    return {
        "ships": [
            {
                **s.model_dump(include={"ship_id", "ship_type", "dwt", "contract_price_krw", "delivery_date"}),
                "ld_grace_days": s.ld_terms.grace_days if s.ld_terms else None,
                "ld_rate_per_day_of_price": s.ld_terms.rate_per_day_of_price if s.ld_terms else None,
                "ld_max_days": s.ld_terms.max_days if s.ld_terms else None,
            }
            for s in snapshot.ships
        ],
        "zones": [z.model_dump() for z in snapshot.zones],
        "boundaries": [b.model_dump() for b in snapshot.boundaries],
        "blocks": [b.model_dump(exclude={"source"}) for b in snapshot.blocks],
        "specs": [s.model_dump() for s in snapshot.specs],
        "parts": [p.model_dump(exclude={"source"}) for p in snapshot.parts],
        "suppliers": [s.model_dump() for s in snapshot.suppliers],
        "purchase_orders": [
            {
                **po.model_dump(exclude={"entered_on", "observations", "source"}),
                **{key: po.entered_on.get(status) for status, key in ENTERED_COLUMNS.items()},
            }
            for po in snapshot.purchase_orders
        ],
        "po_lines": [li.model_dump(exclude={"source"}) for li in snapshot.po_lines],
        "observations": [
            {"po_id": po.po_id, "status": o.status, "observed_on": o.observed_on}
            for po in snapshot.purchase_orders
            for o in po.observations
        ],
        "activities": [_activity_row(a) for a in snapshot.activities],
        "activity_checks": [
            {"activity_id": a.activity_id, "state": check.state, "confirmed_on": check.confirmed_on}
            for a in snapshot.activities
            for check in a.confirmations
        ],
        "precedences": [
            {"activity_id": a.activity_id, "predecessor_id": p.activity_id, "lag_days": p.lag_days}
            for a in snapshot.activities
            for p in a.predecessors
        ],
        "connections": [c.model_dump() for c in snapshot.connections],
        "stock": [s.model_dump() for s in snapshot.stock],
        "drawings": [d.model_dump() for d in snapshot.drawings],
        "pipe_systems": [s.model_dump() for s in snapshot.pipe_systems],
        "crews": [
            {**c.model_dump(exclude={"processes"}), "processes": [ACTIVITY_KINDS[k.value] for k in c.processes]}
            for c in snapshot.crews
        ],
    }


def to_workbook(snapshot: GraphSnapshot, sheets: tuple[Sheet, ...] = SHEETS) -> Workbook:
    workbook = Workbook()
    guide = workbook.active
    assert guide is not None
    guide.title = GUIDE_SHEET
    _guide(guide, sheets)
    rows = rows_of(snapshot)
    for sheet in sheets:
        if sheet.key in OPTIONAL_EMPTY and not rows[sheet.key]:
            continue
        _write(workbook.create_sheet(sheet.name), sheet, rows[sheet.key])
    return workbook


def to_bytes(snapshot: GraphSnapshot) -> bytes:
    buffer = io.BytesIO()
    to_workbook(snapshot).save(buffer)
    return buffer.getvalue()


def _write(ws: Worksheet, sheet: Sheet, rows: list[Row]) -> None:
    ws.append([c.title for c in sheet.columns])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append([_cell(c.kind, c.codes, row.get(c.key)) for c in sheet.columns])
        for cell in ws[ws.max_row]:
            if cell.data_type == "f":  # '='로 시작하는 이름·메모가 여는 사람의 엑셀에서 수식으로 돌지 않게 글자로
                cell.data_type = "s"
    for index, column in enumerate(sheet.columns, start=1):
        if column.kind is Kind.DATE:
            for (cell,) in ws.iter_rows(min_row=2, min_col=index, max_col=index):
                cell.number_format = "yyyy-mm-dd"
        ws.column_dimensions[get_column_letter(index)].width = max(10, len(column.title) * 2 + 4)
    ws.freeze_panes = "A2"


def _cell(kind: Kind, codes: Mapping[str, str], value: object) -> object:
    if value is None:
        return None
    if kind is Kind.CODE:
        return codes.get(str(value), str(value))
    if kind is Kind.LIST:
        return ", ".join(str(v) for v in value) if isinstance(value, (list, tuple)) else str(value)
    return value


def _guide(ws: Worksheet, sheets: tuple[Sheet, ...]) -> None:
    ws.append(["시트", "열", "필수", "단위", "허용 값", "시트가 없을 때"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for sheet in sheets:
        for index, column in enumerate(sheet.columns):
            ws.append(
                [
                    sheet.name if index == 0 else "",
                    column.header,
                    "필수" if column.required else "",
                    column.unit,
                    " / ".join(column.codes.values()),
                    (sheet.absent if not sheet.required else "필수 시트") if index == 0 else "",
                ]
            )
    for letter, width in zip("ABCDEF", (12, 18, 6, 6, 40, 60), strict=True):
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = "A2"
