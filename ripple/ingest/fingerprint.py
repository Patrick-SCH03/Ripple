"""확정 매핑을 다시 쓸 수 있는지 확인할 파일 모양 지문."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Literal

from ripple.contracts.ingest import ConfirmedMapping, SheetMapping

from .mapping import header_cells, header_units, is_guide, unit_notes
from .workbook import RawSheet

Kind = Literal["full", "status"]


def shape_of(raw: Mapping[str, RawSheet], mapping: ConfirmedMapping, kind: Kind) -> str:
    """데이터 값과 안내 시트를 제외하고 시트 이름·머리글·단위 안내를 해시한다."""
    names = sorted(name for name in raw if not is_guide(name))
    sheets = [
        _sheet_shape(raw, sheet)
        for sheet in sorted(mapping.sheets, key=lambda item: item.file_sheet)
        if not is_guide(sheet.file_sheet)
    ]
    body = {"kind": kind, "sheets": names, "mapping": sheets}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "F-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def reusable(raw: Mapping[str, RawSheet], mapping: ConfirmedMapping, kind: Kind, fingerprint: str) -> bool:
    """시트나 머리글 행이 없으면 재사용하지 않고, 있으면 현재 모양과 비교한다."""
    for sheet in mapping.sheets:
        source = raw.get(sheet.file_sheet)
        if source is None or not set(sheet.header_rows) <= {number for number, _ in source.rows}:
            return False
    return shape_of(raw, mapping, kind) == fingerprint


def _sheet_shape(raw: Mapping[str, RawSheet], sheet: SheetMapping) -> dict[str, object]:
    source = raw.get(sheet.file_sheet)
    if source is None:
        return {"file_sheet": sheet.file_sheet, "missing": True}
    available = {number for number, _ in source.rows}
    if not set(sheet.header_rows) <= available:
        return {"file_sheet": sheet.file_sheet, "missing_header_rows": sorted(set(sheet.header_rows) - available)}
    return {
        "file_sheet": sheet.file_sheet,
        "template": sheet.template,
        "header_rows": sheet.header_rows,
        "header_cells": header_cells(source, sheet.header_rows),
        "header_units": header_units(source, sheet.header_rows),
        "unit_notes": unit_notes(source, sheet.header_rows),
    }
