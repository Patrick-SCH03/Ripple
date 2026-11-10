"""엑셀 열 매핑 지문과 최근 기록의 성질 검사."""

from __future__ import annotations

import io
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from harness import Checker
from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook

from ripple.contracts.ingest import ConfirmedMapping, SheetMapping
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.ingest.export import to_bytes
from ripple.ingest.fingerprint import reusable, shape_of
from ripple.ingest.mapping import exact_mapping, header_units, is_guide
from ripple.ingest.workbook import RawSheet, read_workbook
from ripple.store.mappings import MappingStore


def run(c: Checker) -> None:
    c.section("엑셀 열 매핑 기억")
    original = to_bytes(generate(load_config()).snapshot)
    raw = read_workbook(original)
    mapping = exact_mapping(raw)
    selected = next(sheet for sheet in mapping.sheets if sheet.template is not None and sheet.columns)
    name = selected.file_sheet
    first = shape_of(raw, mapping, "full")
    again = read_workbook(original)
    c.check(
        "같은 파일을 두 번 읽으면 같은 지문이며 재사용 가능",
        first == shape_of(again, mapping, "full") and reusable(again, mapping, "full", first),
    )
    c.check("종류가 다르면 지문도 다름", first != shape_of(raw, mapping, "status"))

    changed_header = _read_edited(original, lambda book: _change_header(book, name))
    c.check(
        "머리글 한 글자 변경 시 다른 지문",
        first != shape_of(changed_header, mapping, "full") and not reusable(changed_header, mapping, "full", first),
    )
    unit_sheet = next(
        sheet
        for sheet in mapping.sheets
        if sheet.header_rows and any(header_units(raw[sheet.file_sheet], sheet.header_rows))
    )
    unit_index = next(
        index
        for index, unit in enumerate(header_units(raw[unit_sheet.file_sheet], unit_sheet.header_rows), start=1)
        if unit is not None
    )
    old_unit = header_units(raw[unit_sheet.file_sheet], unit_sheet.header_rows)[unit_index - 1]
    new_unit = "원" if old_unit == "천원" else "천원"
    changed_unit = _read_edited(
        original, lambda book: _change_unit_header(book, unit_sheet.file_sheet, unit_index, new_unit)
    )
    c.check(
        "머리글 단위 변경 시 다른 지문",
        header_units(raw[unit_sheet.file_sheet], unit_sheet.header_rows)
        != header_units(changed_unit[unit_sheet.file_sheet], unit_sheet.header_rows)
        and first != shape_of(changed_unit, mapping, "full"),
    )

    won = _read_edited(original, lambda book: _insert_title(book, name, "(단위: 원)"))
    thousand = _read_edited(original, lambda book: _insert_title(book, name, "(단위: 천원)"))
    title_mapping = ConfirmedMapping(
        sheets=tuple(
            sheet.model_copy(update={"header_rows": (2,)}) if sheet.file_sheet == name else sheet
            for sheet in mapping.sheets
        )
    )
    won_shape = shape_of(won, title_mapping, "full")
    c.check(
        "제목 행 단위만 원에서 천원으로 바뀌면 재사용 거부",
        won_shape != shape_of(thousand, title_mapping, "full")
        and not reusable(thousand, title_mapping, "full", won_shape),
    )

    data_marker = "데이터값-비저장-8723"
    changed_data = _read_edited(original, lambda book: _change_data(book, name, data_marker))
    c.check(
        "데이터 행 값만 바뀌면 같은 지문",
        first == shape_of(changed_data, mapping, "full") and reusable(changed_data, mapping, "full", first),
    )

    minimal = ConfirmedMapping(sheets=(selected,))
    minimal_shape = shape_of(raw, minimal, "full")
    extra = _read_edited(original, lambda book: book.create_sheet("새 자료 시트"))
    removable = next(sheet_name for sheet_name in raw if sheet_name != name and not is_guide(sheet_name))
    fewer = _read_edited(original, lambda book: book.remove(book[removable]))
    c.check(
        "시트 추가와 삭제 모두 지문을 바꿈",
        minimal_shape != shape_of(extra, minimal, "full") and minimal_shape != shape_of(fewer, minimal, "full"),
    )
    missing = _read_edited(original, lambda book: book.remove(book[name]))
    c.check(
        "매핑 시트가 없으면 지문이 다르고 재사용 거부",
        first != shape_of(missing, mapping, "full") and not reusable(missing, mapping, "full", first),
    )
    without_guide = {sheet_name: sheet_raw for sheet_name, sheet_raw in raw.items() if not is_guide(sheet_name)}
    c.check(
        "안내 시트는 지문에서 빼되 매핑에 있던 시트가 없으면 재사용 거부",
        shape_of(without_guide, mapping, "full") == first and not reusable(without_guide, mapping, "full", first),
    )
    out_of_range = ConfirmedMapping(
        sheets=(
            SheetMapping(file_sheet=name, template=selected.template, header_rows=(99999,), columns=selected.columns),
        )
    )
    c.check("머리글 행이 범위를 벗어나면 재사용 거부", not reusable(raw, out_of_range, "full", first))

    _store_checks(c, mapping, data_marker)


def _read_edited(data: bytes, edit: Callable[[Workbook], object]) -> dict[str, RawSheet]:
    book = load_workbook(io.BytesIO(data))
    edit(book)
    output = io.BytesIO()
    book.save(output)
    book.close()
    return read_workbook(output.getvalue())


def _change_header(book: Workbook, name: str) -> None:
    cell = book[name].cell(1, 1)
    cell.value = f"{cell.value}가"


def _change_unit_header(book: Workbook, name: str, index: int, unit: str) -> None:
    book[name].cell(1, index, f"금액({unit})")


def _insert_title(book: Workbook, name: str, title: str) -> None:
    sheet = book[name]
    sheet.insert_rows(1)
    sheet.cell(1, 1, title)


def _change_data(book: Workbook, name: str, marker: str) -> None:
    book[name].cell(2, 1, marker)


def _store_checks(c: Checker, mapping: ConfirmedMapping, marker: str) -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "mappings.json"
        store = MappingStore(path)
        now = datetime(2026, 10, 11, tzinfo=UTC)
        for number in range(21):
            store.remember(f"F-{number:016x}", "full", mapping, "합성.xlsx", now + timedelta(minutes=number))
        recent = store.candidates("full")
        c.check(
            "21개 저장하면 최근 20개만 남음",
            len(recent) == 20
            and recent[0].fingerprint == "F-0000000000000014"
            and recent[-1].fingerprint == "F-0000000000000001",
        )
        store.remember("F-0000000000000001", "status", mapping, "새 합성.xlsx", now + timedelta(hours=1))
        c.check(
            "같은 지문은 덮어쓰고 앞으로 이동",
            len(store.candidates("full")) == 19
            and store.candidates("status")[0].file_name == "새 합성.xlsx"
            and store.candidates("status")[0].fingerprint == "F-0000000000000001",
        )
        c.check("저장 파일에는 데이터 행 값이 없음", marker not in path.read_text(encoding="utf-8"))
        c.check(
            "forget은 실제 삭제 여부를 반환",
            store.forget("F-0000000000000001")
            and not store.forget("F-0000000000000001")
            and store.candidates("status") == [],
        )
        store.clear()
        c.check("clear 후에는 두 종류 모두 비어 있음", not store.candidates("full") and not store.candidates("status"))
        path.write_text("{ 깨진 파일", encoding="utf-8")
        empty = store.candidates("full")
        broken = list(path.parent.glob("mappings.json.broken-*"))
        store.remember("F-000000000000000a", "full", mapping, "합성.xlsx", now)
        c.check(
            "깨진 JSON은 백업하고 빈 저장소로 읽은 뒤 새로 저장",
            empty == []
            and len(broken) == 1
            and broken[0].read_text(encoding="utf-8") == "{ 깨진 파일"
            and len(store.candidates("full")) == 1,
        )
        path.write_text('{"mappings":[{"unknown":true}]}', encoding="utf-8")
        c.check(
            "계약에 맞지 않는 JSON도 빈 저장소",
            store.candidates("full") == [] and len(list(path.parent.glob("mappings.json.broken-*"))) == 2,
        )
        _concurrent_remember(c, MappingStore(Path(directory) / "race.json"), mapping, now)


def _concurrent_remember(c: Checker, store: MappingStore, mapping: ConfirmedMapping, now: datetime) -> None:
    """두 확정이 동시에 기억하면(읽기 → 쓰기 사이가 겹침) 둘 다 남는다 — 나중에 쓴 쪽이 먼저 쓴 것을 지우지 않게."""
    real_read = store._read

    def slow_read() -> object:
        found = real_read()
        time.sleep(0.2)  # 다른 요청이 그사이 읽게
        return found

    setattr(store, "_read", slow_read)  # noqa: B010
    threads = [
        threading.Thread(target=store.remember, args=(f"F-{n:016x}", "full", mapping, "동시.xlsx", now)) for n in (1, 2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10.0)
    delattr(store, "_read")
    kept = sorted(m.fingerprint for m in store.candidates("full"))
    c.check("동시에 기억한 두 매핑이 모두 남음(읽고 쓰는 사이 잠금)", kept == [f"F-{n:016x}" for n in (1, 2)], kept)
