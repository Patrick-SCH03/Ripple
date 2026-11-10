"""엑셀 흔한 변형 생성기(합성): 지도를 회사마다 다른 모양의 엑셀로 쓰고 정답 매핑(ConfirmedMapping)을 낸다.

열 자동 매핑의 보정·평가 자료와 관문 변형 3종(V1~V3)을 만든다. 어휘는 generator/excel_variants.yaml.
정답이 판단 코드를 따라가지 않도록 가져오기 판단(mapping.py · fields.py · normalize.py · 열 매핑)과 코드·어휘를 나누지
않는다 — 함께 쓰는 것은 양식 정의(template.py)와 행 내보내기(export.rows_of)뿐이고, 단위 배율도 어휘에 따로 적은
십진수로 계산한다.

변형 요소(Style)
- 머리글: 어휘 동의어(한영·약어), 단위 꼬리 모양, 원본 단위 바꾸기(값도 함께), 단위 꼬리 빼기(개발 변형만 —
  정답 단위는 값의 실제 단위라 판단은 '미해결'이어야 맞다)
- 표: 열 순서 섞기, 덧붙인 열, 두 줄 머리글(묶음), 제목·빈 행, 메모 행, 양식과 상관없는 시트
- 값: 날짜 표기(점·빗금·띄어 쓴 점·8자리 글자·8자리 숫자·엑셀 날짜 숫자·한국식), 코드 표기(붙여 쓴 라벨·대문자 계약
  값·하이픈), 예/아니오 표기(O/X·Y/N), 목록 구분자
- 시트 이름

정답 단위: 단위가 있는 항목은 값이 실제로 적힌 단위(머리글에 단위가 없어도), 단위 없는 항목은 None.
"""

from __future__ import annotations

import io
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.domain import GraphSnapshot
from ripple.contracts.ingest import ColumnMapping, ConfirmedMapping, SheetMapping

from .export import OPTIONAL_EMPTY, rows_of
from .template import SHEETS, Column, Kind, Sheet

VOCAB_PATH = PROJECT_ROOT / "generator" / "excel_variants.yaml"
DATE_STYLES = ("dot", "slash", "dot_space", "compact_text", "compact_number", "serial", "korean")
CODE_STYLES = ("label_nospace", "value_upper", "value_hyphen")
BOOL_STYLES = ("ox", "yn")
EXCEL_EPOCH = date(1899, 12, 30)  # 1900 체계 날짜 숫자 0(1900-03-01 이후 날짜에 맞음)


@dataclass(frozen=True, slots=True)
class Style:
    """변형 요소의 확률(시트·열마다 따로 뽑는다). 0이면 그 요소를 쓰지 않는다."""

    synonyms: float = 0.0  # 열 머리글을 어휘 동의어로
    units: float = 0.0  # 단위 있는 열의 원본 단위를 다른 단위로(값도 바꿈)
    unitless: float = 0.0  # 동의어 머리글의 단위 꼬리를 뺌(값은 양식 단위 그대로)
    plain_exact: float = 0.0  # 양식 이름 그대로인 단위 열의 단위 꼬리를 뺌(지정 양식 관례)
    shuffle: bool = False  # 열 순서 섞기(두 줄 머리글이면 묶음째)
    extra_columns: int = 0  # 시트마다 덧붙일 열 수 상한
    two_row: float = 0.0  # 묶음이 있는 시트의 두 줄 머리글
    framing: float = 0.0  # 제목·빈 행
    memos: float = 0.0  # 메모 행
    dates: float = 0.0  # 날짜 열의 다른 표기
    codes: float = 0.0  # 코드·예/아니오 열의 다른 표기
    sheet_names: float = 0.0  # 시트 이름 바꾸기
    extra_sheets: float = 0.0  # 양식과 상관없는 시트 하나
    gate_units: bool = False  # 단위 꼬리를 괄호류로만(관문 변형)
    max_rows: int | None = None  # 시트마다 앞 n행(None = 전부)


GATE_STYLES: Mapping[str, Style] = {
    # V1 머리글 동의어·한영·약어 + 열 순서 섞기 + 덧붙인 열
    "V1": Style(synonyms=1.0, shuffle=True, extra_columns=2, gate_units=True),
    # V2 두 줄 머리글 + 단위 혼재 + 제목·빈·메모 행
    "V2": Style(units=1.0, two_row=1.0, framing=1.0, memos=1.0, gate_units=True),
    # V3 날짜 표기 + 코드 표기 + 시트 이름
    "V3": Style(dates=1.0, codes=1.0, sheet_names=1.0, extra_sheets=1.0, gate_units=True),
}
GATE_SEEDS: Mapping[str, int] = {"V1": 101, "V2": 202, "V3": 303}


@dataclass(frozen=True, slots=True)
class Variant:
    name: str
    seed: int
    style: Style
    data: bytes  # xlsx
    truth: ConfirmedMapping  # 정답: 파일 시트 → 양식 시트·머리글 행·열 → 항목·원본 단위


@dataclass(frozen=True, slots=True)
class Vocabulary:
    version: str
    sheets: Mapping[str, tuple[str, ...]]
    columns: Mapping[tuple[str, str], tuple[str, ...]]
    units: Mapping[str, Mapping[str, Decimal]]
    unit_styles: tuple[str, ...]
    gate_unit_styles: tuple[str, ...]
    extra_columns: Mapping[str, str]
    extra_text: tuple[str, ...]
    people: tuple[str, ...]
    groups: Mapping[str, Mapping[str, tuple[str, ...]]]
    extra_sheets: tuple[str, ...]
    titles: tuple[str, ...]
    memos: tuple[str, ...]


def load_vocabulary(path: Path = VOCAB_PATH) -> Vocabulary:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    columns = {
        (sheet, key): tuple(str(h) for h in headers)
        for sheet, entries in data["columns"].items()
        for key, headers in entries.items()
    }
    return Vocabulary(
        version=str(data["version"]),
        sheets={k: tuple(v) for k, v in data["sheets"].items()},
        columns=columns,
        units={unit: {k: Decimal(str(v)) for k, v in (alts or {}).items()} for unit, alts in data["units"].items()},
        unit_styles=tuple(data["unit_styles"]),
        gate_unit_styles=tuple(data["gate_unit_styles"]),
        extra_columns=dict(data["extra_columns"]),
        extra_text=tuple(data["extra_text"]),
        people=tuple(data["people"]),
        groups={s: {g: tuple(keys) for g, keys in groups.items()} for s, groups in data["groups"].items()},
        extra_sheets=tuple(data["extra_sheets"]),
        titles=tuple(data["titles"]),
        memos=tuple(data["memos"]),
    )


@lru_cache(maxsize=1)
def default_vocabulary() -> Vocabulary:
    return load_vocabulary(VOCAB_PATH)


def gate_variants(snapshot: GraphSnapshot) -> list[Variant]:
    """관문 변형 3종(고정 시드·전체 행)."""
    return [make_variant(snapshot, name, GATE_STYLES[name], GATE_SEEDS[name]) for name in GATE_STYLES]


def dev_style(rng: random.Random, max_rows: int | None = 40) -> Style:
    """개발(보정·평가) 변형: 요소를 시드마다 섞는다."""
    return Style(
        synonyms=rng.choice((0.0, 0.3, 0.7, 1.0)),
        units=rng.choice((0.0, 0.3, 0.7)),
        unitless=rng.choice((0.0, 0.0, 0.3)),
        plain_exact=rng.choice((0.0, 0.5)),
        shuffle=rng.random() < 0.5,
        extra_columns=rng.choice((0, 1, 2, 3)),
        two_row=rng.choice((0.0, 0.5)),
        framing=rng.choice((0.0, 0.5, 1.0)),
        memos=rng.choice((0.0, 0.3)),
        dates=rng.choice((0.0, 0.5, 1.0)),
        codes=rng.choice((0.0, 0.5, 1.0)),
        sheet_names=rng.choice((0.0, 0.5, 1.0)),
        extra_sheets=rng.choice((0.0, 0.3)),
        max_rows=max_rows,
    )


def make_variant(
    snapshot: GraphSnapshot, name: str, style: Style, seed: int, vocabulary: Vocabulary | None = None
) -> Variant:
    vocab = vocabulary or default_vocabulary()
    rng = random.Random(seed)
    workbook = Workbook()
    first = workbook.active
    assert first is not None
    workbook.remove(first)
    rows = rows_of(snapshot)
    truths: list[SheetMapping] = []
    used_names: set[str] = set()
    for sheet in SHEETS:
        sheet_rows = rows[sheet.key]
        if sheet.key in OPTIONAL_EMPTY and not sheet_rows:
            continue
        if style.max_rows is not None:
            sheet_rows = sheet_rows[: style.max_rows]
        title = _sheet_name(sheet, style, vocab, rng, used_names)
        ws = workbook.create_sheet(title)
        truths.append(_write_sheet(ws, sheet, sheet_rows, style, vocab, rng))
    if style.extra_sheets and rng.random() < style.extra_sheets:
        extra = rng.choice([n for n in vocab.extra_sheets if n not in used_names])
        ws = workbook.create_sheet(extra, index=0)
        ws.append([f"{snapshot.ships[0].ship_id if snapshot.ships else ''} 자료"])
        ws.append(["작성", rng.choice(vocab.people)])
        truths.insert(0, SheetMapping(file_sheet=extra))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return Variant(name, seed, style, buffer.getvalue(), ConfirmedMapping(sheets=tuple(truths)))


# ---------- 시트 ----------


@dataclass(slots=True)
class _Plan:
    """파일 열 하나: 양식 열(덧붙인 열이면 None), 머리글, 원본 단위(정답), 배율, 값 표기."""

    column: Column | None
    header: str
    unit: str | None = None
    factor: Decimal = Decimal(1)
    style: str | None = None
    extra: str | None = None  # 덧붙인 열의 값 모양
    group: str | None = None
    values: list[object] = field(default_factory=list)


def _sheet_name(sheet: Sheet, style: Style, vocab: Vocabulary, rng: random.Random, used: set[str]) -> str:
    name = sheet.name
    if style.sheet_names and rng.random() < style.sheet_names:
        choices = [n for n in vocab.sheets.get(sheet.key, ()) if n not in used]
        if choices:
            name = rng.choice(choices)
    used.add(name)
    return name


def _write_sheet(
    ws: Worksheet,
    sheet: Sheet,
    rows: Sequence[Mapping[str, object]],
    style: Style,
    vocab: Vocabulary,
    rng: random.Random,
) -> SheetMapping:
    groups = vocab.groups.get(sheet.key, {})
    two_row = bool(groups) and bool(style.two_row) and rng.random() < style.two_row
    plans = [_column_plan(sheet, column, style, vocab, rng) for column in sheet.columns]
    if two_row:
        owner = {key: group for group, keys in groups.items() for key in keys}
        for plan in plans:
            plan.group = owner.get(plan.column.key) if plan.column else None
    extras = _extra_plans(style, vocab, rng, {p.header for p in plans})
    plans = _order(plans, extras, two_row, style.shuffle, rng)

    framing = bool(style.framing) and rng.random() < style.framing
    if framing:
        ws.append([rng.choice(vocab.titles).format(sheet=sheet.name, date="2026-10-20")])
        ws.append([])
    if two_row:
        _two_row_header(ws, plans)
    else:
        ws.append([p.header for p in plans])
    header_rows = tuple(range(ws.max_row - (1 if two_row else 0), ws.max_row + 1))
    for number in header_rows:
        for cell in ws[number]:
            cell.font = Font(bold=True)

    memo_after = (
        rng.randrange(len(rows)) if rows and style.memos and rng.random() < style.memos else None
    )  # 데이터 사이 메모 한 줄
    for index, row in enumerate(rows):
        ws.append([_value(plan, row, index, vocab, rng) for plan in plans])
        for position, plan in enumerate(plans, start=1):
            if plan.column is not None and plan.column.kind is Kind.DATE and plan.style is None:
                ws.cell(row=ws.max_row, column=position).number_format = "yyyy-mm-dd"
        if memo_after == index:
            ws.append([rng.choice(vocab.memos)])
    if memo_after is not None:
        ws.append([rng.choice(vocab.memos)])  # 끝 메모

    columns = tuple(
        ColumnMapping(position=i, key=p.column.key if p.column else None, unit=p.unit) for i, p in enumerate(plans)
    )
    return SheetMapping(file_sheet=ws.title, template=sheet.key, header_rows=header_rows, columns=columns)


def _column_plan(sheet: Sheet, column: Column, style: Style, vocab: Vocabulary, rng: random.Random) -> _Plan:
    synonyms = vocab.columns.get((sheet.key, column.key), ())
    renamed = bool(synonyms) and bool(style.synonyms) and rng.random() < style.synonyms
    name = rng.choice(synonyms) if renamed else column.header
    plan = _Plan(column, name)
    if column.unit:
        plan.unit = _token(column.unit)
        alternatives = vocab.units.get(column.unit, {})
        if alternatives and style.units and rng.random() < style.units:
            unit = rng.choice(sorted(alternatives))
            plan.unit, plan.factor = _token(unit), alternatives[unit]
            plan.header = _with_unit(name, unit, style, vocab, rng)
        elif renamed and style.unitless and rng.random() < style.unitless:
            plan.header = name  # 값은 양식 단위, 머리글엔 단위 없음(판단은 미해결이어야)
        elif not renamed and style.plain_exact and rng.random() < style.plain_exact:
            plan.header = name  # 양식 이름 그대로 + 단위 생략 = 지정 양식 관례(양식 단위)
        else:
            plan.header = _with_unit(name, column.unit, style, vocab, rng)
    if column.kind is Kind.DATE and style.dates and rng.random() < style.dates:
        plan.style = rng.choice(DATE_STYLES)
    elif column.kind is Kind.CODE and style.codes and rng.random() < style.codes:
        plan.style = rng.choice(CODE_STYLES)
    elif column.kind is Kind.BOOL and style.codes and rng.random() < style.codes:
        plan.style = rng.choice(BOOL_STYLES)
    elif column.kind is Kind.LIST and style.codes and rng.random() < style.codes:
        plan.style = "semicolon"
    return plan


def _with_unit(name: str, unit: str, style: Style, vocab: Vocabulary, rng: random.Random) -> str:
    shapes = vocab.gate_unit_styles if style.gate_units else vocab.unit_styles
    return rng.choice(shapes).format(name=name, unit=unit)


def _extra_plans(style: Style, vocab: Vocabulary, rng: random.Random, taken: set[str]) -> list[_Plan]:
    if not style.extra_columns:
        return []
    count = rng.randint(1, style.extra_columns)
    names = [n for n in vocab.extra_columns if n not in taken]
    return [_Plan(None, n, extra=vocab.extra_columns[n]) for n in rng.sample(names, min(count, len(names)))]


def _order(plans: list[_Plan], extras: list[_Plan], two_row: bool, shuffle: bool, rng: random.Random) -> list[_Plan]:
    """열 순서. 두 줄 머리글이면 묶음 열을 첫 열 자리에 모아 붙인다(섞을 때도 묶음째). 덧붙인 열은 섞으면 사이에,
    아니면 끝에."""
    units: list[list[_Plan]] = []
    by_group: dict[str, list[_Plan]] = {}
    for plan in plans:
        if two_row and plan.group:
            if plan.group in by_group:
                by_group[plan.group].append(plan)
                continue
            by_group[plan.group] = [plan]
            units.append(by_group[plan.group])
        else:
            units.append([plan])
    units += [[e] for e in extras]
    if shuffle:
        rng.shuffle(units)
    return [plan for unit in units for plan in unit]


def _two_row_header(ws: Worksheet, plans: list[_Plan]) -> None:
    top: list[str | None] = []
    bottom: list[str | None] = []
    for i, plan in enumerate(plans):
        if plan.group is None:
            top.append(plan.header)
            bottom.append(None)
        else:
            starts = i == 0 or plans[i - 1].group != plan.group
            top.append(plan.group if starts else None)
            bottom.append(plan.header)
    ws.append(top)
    ws.append(bottom)
    upper = ws.max_row - 1
    start = 0
    while start < len(plans):
        end = start
        if plans[start].group is None:
            ws.merge_cells(start_row=upper, start_column=start + 1, end_row=upper + 1, end_column=start + 1)
        else:
            while end + 1 < len(plans) and plans[end + 1].group == plans[start].group:
                end += 1
            if end > start:
                ws.merge_cells(start_row=upper, start_column=start + 1, end_row=upper, end_column=end + 1)
        start = end + 1


# ---------- 값 ----------


def _value(plan: _Plan, row: Mapping[str, object], index: int, vocab: Vocabulary, rng: random.Random) -> object:
    if plan.column is None:
        return _extra_value(plan.extra or "text", index, vocab, rng)
    value = row.get(plan.column.key)
    if value is None:
        return None
    kind = plan.column.kind
    if kind in (Kind.INT, Kind.FLOAT) and plan.factor != 1:
        scaled = Decimal(repr(value) if isinstance(value, float) else str(value)) * plan.factor
        return int(scaled) if scaled == scaled.to_integral_value() else float(scaled)
    if kind is Kind.DATE and isinstance(value, date):
        return _date_text(value, plan.style)
    if kind is Kind.CODE:
        return _code_text(plan.column, str(value), plan.style)
    if kind is Kind.BOOL and isinstance(value, bool):
        return {"ox": "O" if value else "X", "yn": "Y" if value else "N"}.get(plan.style or "", value)
    if kind is Kind.LIST:
        items = [str(v) for v in value] if isinstance(value, (list, tuple)) else [str(value)]
        return ("; " if plan.style == "semicolon" else ", ").join(items)
    return value


def _date_text(day: date, style: str | None) -> object:
    match style:
        case "dot":
            return f"{day:%Y.%m.%d}"
        case "slash":
            return f"{day:%Y/%m/%d}"
        case "dot_space":
            return f"{day.year}. {day.month}. {day.day}."
        case "compact_text":
            return f"{day:%Y%m%d}"
        case "compact_number":
            return int(f"{day:%Y%m%d}")
        case "serial":
            return (day - EXCEL_EPOCH).days
        case "korean":
            return f"{day.year}년 {day.month}월 {day.day}일"
        case _:
            return day


def _code_text(column: Column, value: str, style: str | None) -> str:
    label = column.codes.get(value, value)
    match style:
        case "label_nospace":
            return label.replace(" ", "")
        case "value_upper":
            return value.upper()
        case "value_hyphen":
            return value.upper().replace("_", "-")
        case _:
            return label


def _extra_value(kind: str, index: int, vocab: Vocabulary, rng: random.Random) -> object:
    match kind:
        case "seq":
            return index + 1
        case "date":
            return date(2026, 9, 1 + index % 28) if rng.random() < 0.5 else None
        case "mark":
            return "O" if rng.random() < 0.6 else None
        case "person":
            return rng.choice(vocab.people)
        case _:
            return rng.choice(vocab.extra_text) if rng.random() < 0.3 else None


def _token(unit: str) -> str:
    return "".join(unit.split()).casefold()
