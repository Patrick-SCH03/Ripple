"""엑셀 가져오기의 성질(docs/input.md(엑셀 양식)): 지정 양식이 계약 필드를 빠짐없이 담음, 왕복(지도 → 엑셀 → 지도)의
내용과 분석 수치가 같음, 품질 리포트가 시트·행·열을 짚음, 오류가 있으면 지도를 만들지 않음, 값 정규화(단위 배율·날짜·
코드 표기)가 정확함, 확정 매핑(시트·머리글 행·열·원본 단위)대로 읽고 어떤 행·열·시트도 조용히 빼지 않음."""

from __future__ import annotations

import ast
import io
import random
import zipfile
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any, get_args

from harness import Checker
from openpyxl import Workbook, load_workbook
from openpyxl.utils.datetime import CALENDAR_MAC_1904
from openpyxl.worksheet.worksheet import Worksheet

from ripple.config.loaders import load_params, load_rulebook, load_strength
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.change import ChangeIntent
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.domain import (
    Activity,
    ActivityKind,
    Block,
    BlockShape,
    Connection,
    ConnectionKind,
    Crew,
    DataMode,
    Drawing,
    GraphSnapshot,
    MaterialCategory,
    MaterialSpec,
    Part,
    PartKind,
    PipeSystem,
    POLine,
    POStatus,
    PurchaseOrder,
    Ship,
    SourceRef,
    StockLot,
    Supplier,
    SupplierKind,
    Zone,
    ZoneBoundary,
)
from ripple.contracts.ingest import ConfirmedMapping, ImportSummary, IssueCode, IssueSeverity, SheetMapping
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.ingest.build import build
from ripple.ingest.export import GUIDE_SHEET, to_workbook
from ripple.ingest.fields import default_fields
from ripple.ingest.mapping import exact_column, exact_mapping
from ripple.ingest.normalize import UNITS, code_key, convert, parse_date, split_unit, unit_factor, unit_token
from ripple.ingest.template import SHEET_BY_KEY, SHEETS, Column, Kind, code_value
from ripple.ingest.values import parse
from ripple.ingest.variants import GATE_STYLES, dev_style, gate_variants, load_vocabulary, make_variant
from ripple.ingest.workbook import read_workbook

FILE = "ripple-template.xlsx"
# 시트 → 계약 모델과 양식 열로 따로 담는 필드(다른 시트·열로 나눠 담음)
MODELS: dict[str, tuple[type[Any], set[str]]] = {
    "ships": (Ship, {"ld_terms"}),
    "zones": (Zone, set()),
    "boundaries": (ZoneBoundary, set()),
    "blocks": (Block, {"source"}),
    "specs": (MaterialSpec, set()),
    "parts": (Part, {"source"}),
    "suppliers": (Supplier, set()),
    "purchase_orders": (PurchaseOrder, {"entered_on", "observations", "source"}),
    "po_lines": (POLine, {"source"}),
    "activities": (Activity, {"predecessors", "confirmations"}),
    "connections": (Connection, set()),
    "stock": (StockLot, set()),
    "drawings": (Drawing, set()),
    "pipe_systems": (PipeSystem, set()),
    "crews": (Crew, set()),
}
ANALYSES_PER_RUN = 14  # 왕복 분석 비교에 쓰는 개발 설계변경 수(강도형은 대안까지)


def run(c: Checker) -> None:
    _template(c)
    _normalize(c)
    config = load_config()
    snapshot = generate(config).snapshot
    _round_trip(c, snapshot)
    _issues(c, snapshot)
    _untrusted(c, snapshot)
    _mapped(c, snapshot)
    _variants(c, snapshot)


def _template(c: Checker) -> None:
    c.section("엑셀: 지정 양식 정의")
    missing = {
        key: sorted(set(model.model_fields) - split - {col.key for col in SHEET_BY_KEY[key].columns})
        for key, (model, split) in MODELS.items()
    }
    c.check(
        "계약 필드가 모두 양식 열에 있음(엔진이 쓰는 값을 잃지 않음 — 발주 간격·진입일·관측·품목 단가·소비 공정 포함)",
        not any(missing.values())
        and {"entered_ordered", "entered_processed"} <= {col.key for col in SHEET_BY_KEY["purchase_orders"].columns}
        and {"unit_price_krw", "consumed_by_activity_id"} <= {col.key for col in SHEET_BY_KEY["po_lines"].columns},
        {k: v for k, v in missing.items() if v},
    )
    codes = {
        "부재 종류": ({k.value for k in PartKind}, SHEET_BY_KEY["parts"].column("kind")),
        "상태": ({k.value for k in POStatus}, SHEET_BY_KEY["observations"].column("status")),
        "공정 종류": ({k.value for k in ActivityKind}, SHEET_BY_KEY["activities"].column("kind")),
        "연결 종류": ({k.value for k in ConnectionKind}, SHEET_BY_KEY["connections"].column("kind")),
        "협력사 구분": ({k.value for k in SupplierKind}, SHEET_BY_KEY["suppliers"].column("kind")),
        "분류": (set(get_args(MaterialCategory)), SHEET_BY_KEY["specs"].column("category")),
        "블록 형상": ({k.value for k in BlockShape}, SHEET_BY_KEY["blocks"].column("shape")),
    }
    gaps = {name: sorted(values - set(col.codes)) for name, (values, col) in codes.items()}
    c.check("코드 열의 한글 라벨이 계약 값 전부를 덮음", not any(gaps.values()), gaps)
    names = [s.name for s in SHEETS]
    c.check(
        "시트 이름이 겹치지 않고 열 머리글도 시트 안에서 겹치지 않음",
        len(set(names)) == len(names) and all(len({col.header for col in s.columns}) == len(s.columns) for s in SHEETS),
    )
    c.check(
        "선택 시트마다 '없을 때의 뜻'이 있음(미제공과 빈 목록을 구분해 리포트에 적음)",
        all(s.absent for s in SHEETS if not s.required),
    )
    text = (PROJECT_ROOT / "docs" / "input.md").read_text(encoding="utf-8")
    doc = text[text.index("\n## 엑셀 양식\n") :]
    absent = [
        (s.name, col.title)
        for s in SHEETS
        for col in s.columns
        if f"\n#### {s.name} (`{s.key}`" not in doc or f"| {col.title} | {'필수' if col.required else ''} |" not in doc
    ]
    c.check("명세 문서(docs/input.md 엑셀 양식 편)의 시트·열 표가 양식 정의와 같음", not absent, absent[:5])
    clashes = []
    for s in SHEETS:
        for col in s.columns:
            owner: dict[str, str] = {}
            for value, label in col.codes.items():
                clashes += [
                    (s.name, col.header, t) for t in (value, label) if owner.setdefault(code_key(t), value) != value
                ]
    c.check("코드 열마다 라벨·계약 값의 비교 키(공백·하이픈·밑줄·점·대소문자 무시)가 겹치지 않음", not clashes, clashes)
    units = sorted({col.unit for s in SHEETS for col in s.columns if col.unit and unit_token(col.unit) not in UNITS})
    c.check("양식 단위가 모두 단위 표에 있음(원본 단위 → 양식 단위 배율을 정할 수 있음)", not units, units)
    unsplit = [
        (s.name, col.title)
        for s in SHEETS
        for col in s.columns
        if split_unit(col.title) != (col.header, unit_token(col.unit) if col.unit else None)
        or exact_column(s, col.title) is not col
    ]
    c.check(
        "양식 머리글은 모두 (이름, 단위)로 나뉘고 그 열로 정확히 찾아짐('발주일(확인)'의 '확인'은 단위 아님)",
        not unsplit,
        unsplit,
    )
    fields = default_fields()
    stray = [
        (s.key, col.key)
        for s in SHEETS
        for col in s.columns
        if fields.info(s.key, col.key).range is not None and col.kind not in (Kind.INT, Kind.FLOAT)
    ]
    c.check(
        "필드 사전이 양식의 모든 열을 덮고, 상식 범위는 숫자 열에만",
        len(fields.columns) == sum(len(s.columns) for s in SHEETS) and not stray,
        stray,
    )


def _normalize(c: Checker) -> None:
    c.section("엑셀: 값 정규화(단위·날짜·코드)")
    factors = {
        ("mm", "m"): 0.001,
        ("cm", "mm"): 10.0,
        ("m", "mm"): 1000.0,
        ("kg", "t"): 0.001,
        ("톤", "t"): 1.0,
        ("Ton", "t"): 1.0,
        ("천원", "원"): 1000.0,
        ("만원", "원"): 10000.0,
        ("백만원", "원"): 1e6,
        ("KRW", "원"): 1.0,
        ("days", "일"): 1.0,
        ("DN", "DN"): 1.0,
    }
    got = {pair: unit_factor(*pair) for pair in factors}
    c.check("단위 배율은 같은 차원끼리, 10의 거듭제곱 그대로(cm → mm = 10, 잡음 없음)", got == factors, got)
    refused = {
        pair: unit_factor(*pair)
        for pair in (("kg", "mm"), ("ea", "t"), ("inch", "mm"), ("주", "일"), ("%", "원"), ("mm", ""), (None, "mm"))
    }
    c.check(
        "차원이 다르거나 바꾸지 않는 단위(EA·inch·주·%), 단위 없는 항목에 온 단위, 필요한데 없는 단위는 배율 없음",
        all(v is None for v in refused.values()) and unit_factor(None, "") == 1.0,
        refused,
    )
    flag = Column("processed", "가공 여부", Kind.BOOL)
    flags = [parse(flag, v) for v in (1.0, 0.0, 1, 0, "1.0", "예", 2.0, 0.5)]  # 1.0 == 1이라 dict 키로 쓰지 않음
    c.check(
        "예/아니오 칸: 숫자로 저장된 1.0·0.0도 1·0과 같이 읽고, 다른 숫자(2·0.5)는 문제",
        flags
        == [(True, None), (False, None), (True, None), (False, None), (True, None), (True, None)]
        + [(None, "예/아니오")] * 2,
        flags,
    )
    known = {(0.0135, 1000.0): 13.5, (13.5, 0.001): 0.0135, (12345678901.234, 1000.0): 12345678901234.0}
    known |= {(2085.3, 0.001): 2.0853, (0.0021, 1000.0): 2.1, (7.0, 1.0): 7.0}
    wrong = {pair: convert(*pair) for pair, want in known.items() if convert(*pair) != want}
    c.check(
        "배율 곱이 정확함(0.0135 m = 13.5 mm, 12,345,678,901.234천원 = 12,345,678,901,234원 — 원 단위를 잃지 않음)",
        not wrong,
        wrong,
    )
    rng = random.Random(20261008)
    misses = []
    for _ in range(2000):
        value = float(Decimal(rng.randint(1, 10 ** rng.randint(1, 14) - 1)).scaleb(-rng.randint(0, 6)))
        for factor in (1000.0, 0.001, 10.0, 0.01, 1e4, 1e6):
            there = convert(value, factor)
            back = convert(there, float(Decimal(1) / Decimal(repr(factor))))
            if there != float(Decimal(repr(value)) * Decimal(repr(factor))) or back != value:
                misses.append((value, factor, there, back))
    c.check(
        "무작위 십진수 2,000개 × 배율 6개: 셀 값 × 배율을 한 번만 반올림하고 되돌리면 원래 값", not misses, misses[:3]
    )
    splits = {
        "두께(mm)": ("두께", "mm"),
        "두께 [mm]": ("두께", "mm"),
        "두께_mm": ("두께", "mm"),
        "중량 kg": ("중량", "kg"),
        "Weight (KG)": ("Weight", "kg"),
        "계약가(천원)": ("계약가", "천원"),
        "수량(EA)": ("수량", "ea"),
        "발주일(확인)": ("발주일(확인)", None),
        "PL_T": ("PL_T", None),
        "두께 m": ("두께 m", None),
        "STIFF_SP(m)": ("STIFF_SP", "m"),  # 밑줄이 든 이름 + 괄호 단위(밑줄 꼬리 'SP(m)'로 읽지 않음)
        "SPAN_L [m]": ("SPAN_L", "m"),
    }
    split_wrong = {h: split_unit(h) for h, want in splits.items() if split_unit(h) != want}
    c.check(
        "머리글 단위는 괄호·대괄호·밑줄·띄어 쓴 꼬리의 아는 단위만(한 글자 단위는 괄호 안만: 'PL_T'의 T는 약어)",
        not split_wrong,
        split_wrong,
    )
    day = date(2026, 10, 20)
    forms: list[object] = ["2026-10-20", "2026.10.20", "2026. 10. 20.", "2026/10/20", "20261020", 20261020]
    forms += [_serial(day), datetime(2026, 10, 20, 9, 30), "2026-10-20 09:30", "2026년 10월 20일"]
    misread = [f for f in forms if parse_date(f) != (day, None)]
    c.check(
        "날짜 10표기(점·빗금·띄어 쓴 점·8자리 글자·숫자·엑셀 날짜 숫자·날짜시각·한국식)가 같은 날", not misread, misread
    )
    ambiguous = ["26.10.20", "10/20/2026", "20/10/26"]
    refused_dates = ["2026-02-30", "2026.10/20", 100, True, "내일"]
    c.check(
        "두 자리 연도·월/일 순서가 모호한 표기는 읽지 않고 그렇다고 말함, 없는 날·섞인 구분자·작은 숫자·참거짓은 오류",
        all(parse_date(v)[0] is None and "모호" in str(parse_date(v)[1]) for v in ambiguous)
        and all(parse_date(v)[0] is None and parse_date(v)[1] for v in refused_dates)
        and parse_date(46315, CALENDAR_MAC_1904)[0] is None,
    )
    kind = SHEET_BY_KEY["parts"].column("kind")
    spool = ["pipe_spool", "PIPE-SPOOL", "Pipe Spool", "pipe.spool", "배관 스풀", "배관스풀", " 배관_스풀 "]
    c.check(
        "코드는 공백·하이픈·밑줄·점·대소문자만 무시하고 라벨·계약 값으로 읽음, 다른 말은 읽지 않음",
        all(code_value(kind, f) == "pipe_spool" for f in spool) and code_value(kind, "파이프") is None,
        [f for f in spool if code_value(kind, f) != "pipe_spool"],
    )


def _bytes(workbook: Workbook) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _unsourced(value: object) -> object:
    """출처 표시(원본 파일·시트·행)를 뺀 값. 왕복은 출처만 엑셀 행으로 바뀐다."""
    if isinstance(value, dict):
        return {k: _unsourced(v) for k, v in value.items() if k not in ("source", "sources")}
    if isinstance(value, list):
        return [_unsourced(v) for v in value]
    return value


def _domain(snapshot: GraphSnapshot) -> object:
    """출처 표시·지도 ID·출처 종류·데이터 모드를 뺀 내용."""
    return _unsourced(snapshot.model_dump(mode="json", exclude={"snapshot_id", "origin", "data_mode"}))


def _round_trip(c: Checker, snapshot: GraphSnapshot) -> None:
    c.section("엑셀: 지정 양식 왕복")
    data = _bytes(to_workbook(snapshot))
    raw = read_workbook(data)
    got, summary = build(raw, FILE)
    c.check(
        "생성기 지도 → 지정 양식 → 가져오기: 문제 0건, 지도 생성(excel_import·real)",
        got is not None and not summary.issues and got.origin == "excel_import" and got.data_mode is DataMode.REAL,
        [str(i.message) for i in summary.issues[:3]],
    )
    assert got is not None
    c.check("왕복한 지도의 내용이 같음(출처 표시·지도 ID·출처 종류 제외)", _domain(got) == _domain(snapshot))
    c.check(
        "가져온 값마다 원본 시트·행을 담음(부재 첫 행 = '부재' 2행, 발주 품목도 행 번호)",
        got.parts[0].source == SourceRef(file=FILE, sheet="부재", row=2)
        and all(li.source is not None and li.source.sheet == "발주 품목" for li in got.po_lines),
    )
    again, _ = build(read_workbook(data), FILE)
    renamed, _ = build(read_workbook(data), "다른 이름.xlsx")
    c.check(
        "같은 파일·같은 이름이면 같은 지도 ID, 이름이 다르면 다른 ID(출처가 다름)",
        again is not None
        and again.snapshot_id == got.snapshot_id
        and renamed is not None
        and renamed.snapshot_id != got.snapshot_id,
    )
    c.check("'양식 안내' 시트는 읽지 않음(문제로 세지 않음)", GUIDE_SHEET in raw and not summary.issues)

    settings = Settings.from_env({})
    book, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    strength = load_strength(settings.strength_path)
    original, imported = GraphIndex(snapshot), GraphIndex(got)
    config = load_config()
    fields = {"impacts", "cost_lines", "total", "schedule", "timing", "verdict", "unresolved"}
    fields |= {"alternatives", "recommendation", "cheapest_by_date"}
    compared, different, sourced = 0, [], 0
    for ecn in [e for e in generate(config).ecns if e.split is EcnSplit.DEV]:
        if compared >= ANALYSES_PER_RUN:
            break
        alternatives = ecn.change.intent is ChangeIntent.STRENGTH
        request = AnalysisRequest(change=ecn.change, as_of=config.scenario_date, include_alternatives=alternatives)
        try:
            before = analyze(original, request, book, params, strength)
        except RequestError:
            continue
        after = analyze(imported, request, book, params, strength)
        compared += 1
        if _unsourced(before.model_dump(mode="json", include=fields)) != _unsourced(
            after.model_dump(mode="json", include=fields)
        ):
            different.append(ecn.change.ecn_id)
        sourced += sum(1 for line in after.cost_lines if any(src.file == FILE for src in line.sources))
    c.check(
        f"왕복한 지도로 분석한 수치가 같음(개발 설계변경 {compared}건: 영향·비용 줄·일정·곡선·판정·대안)",
        compared == ANALYSES_PER_RUN and not different,
        different[:3],
    )
    c.check("가져온 지도로 분석하면 비용 줄 근거에 원본 엑셀 시트·행이 붙음(금액마다 원본 행)", sourced > 0, sourced)


def _column(ws: Worksheet, title: str) -> int:
    return next(i for i, cell in enumerate(ws[1], start=1) if cell.value == title)


def _issues(c: Checker, snapshot: GraphSnapshot) -> None:
    c.section("엑셀: 품질 리포트")

    def tampered(change: Callable[[Workbook], None]) -> tuple[GraphSnapshot | None, ImportSummary]:
        workbook = to_workbook(snapshot)
        change(workbook)
        return build(read_workbook(_bytes(workbook)), FILE)

    has = _has

    got, summary = tampered(lambda wb: wb.remove(wb["재고"]))
    stock_note = SHEET_BY_KEY["stock"].absent
    c.check(
        "선택 시트(재고)가 없으면 지도는 만들고 경고에 그 뜻을 적음(재고 없음과 구분)",
        got is not None
        and got.stock == ()
        and any(
            i.code is IssueCode.MISSING_SHEET and i.severity is IssueSeverity.WARNING and stock_note in i.message
            for i in summary.issues
        )
        and "재고" in summary.missing_sheets,
    )
    got, summary = tampered(lambda wb: wb.remove(wb["공정"]))
    c.check("필수 시트(공정)가 없으면 오류, 지도 없음", got is None and has(summary, IssueCode.MISSING_SHEET, "공정"))

    def drop_column(wb: Workbook) -> None:
        wb["부재"].delete_cols(_column(wb["부재"], "규격ID"))

    got, summary = tampered(drop_column)
    c.check(
        "필수 열(부재 규격ID)이 없으면 오류, 지도 없음",
        got is None and has(summary, IssueCode.MISSING_COLUMN, "부재", 1, "규격ID"),
    )

    def blank(wb: Workbook) -> None:
        ws = wb["블록"]
        ws.cell(row=3, column=_column(ws, "블록명")).value = None

    got, summary = tampered(blank)
    c.check(
        "필수 값 빈칸은 그 시트·행·열을 짚음(블록 3행 블록명)",
        got is None and has(summary, IssueCode.MISSING_VALUE, "블록", 3, "블록명"),
    )

    def bad_number(wb: Workbook) -> None:
        ws = wb["블록"]
        ws.cell(row=2, column=_column(ws, "강재 중량(t)")).value = "무거움"

    got, summary = tampered(bad_number)
    c.check(
        "숫자 열에 글자가 있으면 형식 오류(블록 2행 강재 중량)",
        got is None and has(summary, IssueCode.BAD_VALUE, "블록", 2, "강재 중량"),
    )

    def bad_code(wb: Workbook) -> None:
        ws = wb["부재"]
        ws.cell(row=2, column=_column(ws, "부재 종류")).value = "철판"

    got, summary = tampered(bad_code)
    c.check(
        "코드 열에 없는 값이면 허용 값과 함께 오류",
        got is None and any(i.code is IssueCode.BAD_VALUE and "판 / 보강재" in i.message for i in summary.issues),
    )

    def english_code(wb: Workbook) -> None:
        ws = wb["부재"]
        ws.cell(row=2, column=_column(ws, "부재 종류")).value = " Plate "
        ws.cell(row=2, column=_column(ws, "두께(mm)")).value = str(ws.cell(row=2, column=_column(ws, "두께(mm)")).value)

    got, summary = tampered(english_code)
    c.check(
        "코드는 한글 라벨·계약 값 모두 받고(공백·대소문자 무시), 숫자는 글자로 적혀도 읽음",
        got is not None
        and got.parts[0].kind is PartKind.PLATE
        and got.parts[0].thickness_mm == snapshot.parts[0].thickness_mm,
    )

    def unknown_block(wb: Workbook) -> None:
        ws = wb["부재"]
        ws.cell(row=2, column=_column(ws, "블록ID")).value = "S-001:XXXX"

    got, summary = tampered(unknown_block)
    c.check(
        "다른 시트에 없는 ID를 가리키면 오류(부재 2행 블록ID)",
        got is None and has(summary, IssueCode.UNKNOWN_REFERENCE, "부재", 2, "블록ID"),
    )

    def duplicate(wb: Workbook) -> None:
        ws = wb["블록"]
        col = _column(ws, "블록ID")
        ws.cell(row=3, column=col).value = ws.cell(row=2, column=col).value

    got, summary = tampered(duplicate)
    c.check("같은 ID가 두 번이면 오류(블록 3행)", got is None and has(summary, IssueCode.DUPLICATE_ID, "블록", 3))

    def no_consumer(wb: Workbook) -> None:
        ws = wb["발주 품목"]
        col = _column(ws, "소비 공정ID")
        for row in (2, 4):
            ws.cell(row=row, column=col).value = None

    got, summary = tampered(no_consumer)
    warned = [i for i in summary.issues if i.code is IssueCode.MISSING_VALUE and i.column == "소비 공정ID"]
    c.check(
        "소비 공정ID가 빈 품목은 지도는 만들고 경고 한 줄(건수·첫 행, 일정 영향은 '연결 확인 필요')",
        got is not None
        and len(warned) == 1
        and warned[0].severity is IssueSeverity.WARNING
        and warned[0].sheet == "발주 품목"
        and warned[0].row == 2
        and "2건" in warned[0].message,
        warned,
    )
    _, clean = tampered(lambda wb: None)
    c.check(
        "소비 공정ID가 모두 있으면 그 경고 없음",
        not any(i.column == "소비 공정ID" for i in clean.issues),
    )

    def cycle(wb: Workbook) -> None:
        ws = wb["선후행"]
        first = [cell.value for cell in ws[2]]
        ws.append([first[1], first[0], 0])

    got, summary = tampered(cycle)
    c.check(
        "선후행이 순환하면 기준 일정을 못 세운다는 오류",
        got is None and any("순환" in i.message for i in summary.issues),
    )

    def partial_ld(wb: Workbook) -> None:
        ws = wb["호선"]
        ws.cell(row=2, column=_column(ws, "지체상금 유예일(일)")).value = 30  # 일률·최대일은 빈칸

    got, summary = tampered(partial_ld)
    c.check("지체상금 세 값 중 일부만 있으면 오류", got is None and has(summary, IssueCode.INVALID_ROW, "호선", 2))

    def plain_header(wb: Workbook) -> None:
        ws = wb["부재"]
        ws.cell(row=1, column=_column(ws, "두께(mm)")).value = "두께"

    got, summary = tampered(plain_header)
    baseline, _ = tampered(lambda wb: None)
    c.check(
        "머리글의 단위 표기는 빼도 읽음('두께(mm)' → '두께')",
        got is not None and baseline is not None and got.parts == baseline.parts,
    )

    def other_unit(wb: Workbook) -> None:
        ws = wb["부재"]
        ws.cell(row=1, column=_column(ws, "두께(mm)")).value = "두께(m)"

    got, summary = tampered(other_unit)
    c.check(
        "단위만 다르고 값은 그대로면(mm 값에 '두께(m)') 1000배로 바꿔 상식 범위 밖 → 그 칸을 짚고 파일 값·단위를 보임",
        got is None
        and any(
            i.code is IssueCode.BAD_VALUE
            and i.sheet == "부재"
            and i.row == 2
            and i.column == "두께"
            and i.file_column == "두께(m)"
            and "상식 범위" in i.message
            and "m →" in i.message
            for i in summary.issues
        ),
        [i.message for i in summary.issues[:1]],
    )

    def auto_dated(wb: Workbook) -> None:
        ws = wb["부재"]
        ws.cell(row=2, column=_column(ws, "개정")).value = datetime(2026, 1, 2)

    got, summary = tampered(auto_dated)
    c.check(
        "글자 칸(개정)에 날짜 값(엑셀 자동 변환)이 있으면 날짜 글로 바꿔 저장하지 않고 그 칸을 짚어 오류",
        got is None and _has(summary, IssueCode.BAD_VALUE, "부재", 2, "개정"),
        [i.message for i in summary.issues[:1]],
    )

    def meters(wb: Workbook) -> None:
        ws = wb["부재"]
        col = _column(ws, "두께(mm)")
        ws.cell(row=1, column=col).value = "두께(m)"
        for row in range(2, ws.max_row + 1):
            cell = ws.cell(row=row, column=col)
            if cell.value is not None:
                cell.value = float(Decimal(repr(cell.value)) / 1000)

    got, summary = tampered(meters)
    c.check(
        "'두께(m)'에 m 값이면 mm로 바꿔 원래 부재와 같음(같은 차원 단위는 배율로 읽음)",
        got is not None and baseline is not None and got.parts == baseline.parts and not summary.issues,
        [i.message for i in summary.issues[:2]],
    )

    def kilograms(wb: Workbook) -> None:
        ws = wb["블록"]
        col = _column(ws, "강재 중량(t)")
        ws.cell(row=1, column=col).value = "강재 중량 [kg]"
        for row in range(2, ws.max_row + 1):
            cell = ws.cell(row=row, column=col)
            cell.value = float(Decimal(repr(cell.value)) * 1000)

    def thousands(wb: Workbook) -> None:
        for name, title in (("호선", "계약가(원)"), ("규격", "단가(원)"), ("발주 품목", "단가(원)")):
            ws = wb[name]
            col = _column(ws, title)
            ws.cell(row=1, column=col).value = title.replace("(원)", "(천원)")
            for row in range(2, ws.max_row + 1):
                cell = ws.cell(row=row, column=col)
                cell.value = float(Decimal(str(cell.value)) / 1000)

    converted = {name: tampered(change) for name, change in (("kg", kilograms), ("천원", thousands))}
    c.check(
        "t → kg, 원 → 천원으로 적은 엑셀도 원래 지도와 같음(돈은 원 단위까지 정확)",
        all(g is not None and baseline is not None and _domain(g) == _domain(baseline) for g, _ in converted.values()),
        {k: [i.message for i in s.issues[:2]] for k, (g, s) in converted.items() if g is None},
    )

    def fractional_won(wb: Workbook) -> None:
        thousands(wb)
        ws = wb["규격"]
        ws.cell(row=2, column=_column(ws, "단가(천원)")).value = 1.2345

    got, summary = tampered(fractional_won)
    c.check(
        "정수 항목(단가 원)이 단위를 바꾸면 정수가 아니면 반올림하지 않고 오류(1.2345천원 = 1,234.5원)",
        got is None and any("1,234.5" in i.message and i.row == 2 and i.sheet == "규격" for i in summary.issues),
        [i.message for i in summary.issues[:2]],
    )
    for title, header, problem in (
        ("부재", "두께(inch)", "변환 불가"),
        ("부재", "수량(EA)", "단위 없음(규격 단위 따름)"),
        ("블록", "강재 중량(m)", "변환 불가"),
    ):

        def unit_header(wb: Workbook, title: str = title, header: str = header) -> None:
            ws = wb[title]
            base = split_unit(header)[0]
            col = next(i for i, cell in enumerate(ws[1], start=1) if split_unit(cell.value)[0] == base)
            ws.cell(row=1, column=col).value = header

        got, summary = tampered(unit_header)
        c.check(
            f"'{header}': 단위를 추측하지 않고 머리글 행을 짚어 오류({problem})",
            got is None
            and any(i.file_column == header and i.row == 1 and problem in i.message for i in summary.issues),
            [i.message for i in summary.issues[:2]],
        )

    def twin_column(wb: Workbook) -> None:
        ws = wb["부재"]
        source = _column(ws, "두께(mm)")
        target = ws.max_column + 1
        for row in range(1, ws.max_row + 1):
            ws.cell(row=row, column=target).value = ws.cell(row=row, column=source).value
        ws.cell(row=1, column=target).value = "두께"

    got, summary = tampered(twin_column)
    c.check(
        "같은 항목으로 읽히는 열이 둘이면('두께(mm)'·'두께') 하나를 조용히 고르지 않고 오류",
        got is None and any("두 열" in i.message and i.column == "두께" for i in summary.issues),
    )

    def extra(wb: Workbook) -> None:
        ws = wb["부재"]
        ws.cell(row=1, column=ws.max_column + 1).value = "비고"

    got, summary = tampered(extra)
    c.check(
        "양식에 없는 열은 읽지 않았다고 경고만(지도는 만듦, 파일 머리글과 열 문자를 적음)",
        got is not None
        and has(summary, IssueCode.IGNORED_COLUMN, "부재", 1, file_column="비고")
        and any("비고" in i.message and "열)" in i.message for i in summary.issues),
    )

    def headless(wb: Workbook) -> None:
        ws = wb["부재"]
        ws.cell(row=3, column=ws.max_column + 2).value = "확인 필요"

    got, summary = tampered(headless)
    c.check(
        "머리글 없는 열에 값이 있으면 조용히 버리지 않고 그 열 문자를 짚어 경고",
        got is not None
        and any(i.code is IssueCode.IGNORED_COLUMN and "머리글 없는" in i.message for i in summary.issues),
    )

    def memo(wb: Workbook) -> None:
        ws = wb["블록"]
        ws.append(["※ 중량은 t 기준이에요"])
        ws.append([None, None, "비고: 2026-10-08 수정"])
        ws.append(["S-001:B999"])

    got, summary = tampered(memo)
    last = to_workbook(snapshot)["블록"].max_row
    c.check(
        "메모 행(칸 하나, ※·비고로 시작)만 빼고 행 번호와 글 앞부분을 경고, 칸 하나짜리 다른 행은 데이터로 읽어 오류",
        got is None
        and has(summary, IssueCode.IGNORED_ROW, "블록", last + 1)
        and has(summary, IssueCode.IGNORED_ROW, "블록", last + 2)
        and any("※ 중량은" in i.message for i in summary.issues)
        and has(summary, IssueCode.MISSING_VALUE, "블록", last + 3),
    )

    def stray_sheet(wb: Workbook) -> None:
        wb.create_sheet("작업 메모").append(["다음 주 확인", "홍길동"])

    got, summary = tampered(stray_sheet)
    c.check(
        "양식에 없는 시트는 읽지 않았다고 경고(지도는 만듦), '양식 안내' 시트는 경고 없음",
        got is not None
        and has(summary, IssueCode.IGNORED_SHEET, "작업 메모")
        and not any(i.sheet == GUIDE_SHEET for i in summary.issues),
    )
    c.check("엑셀이 아닌 파일은 읽기 전에 거부", c.raises(lambda: read_workbook(b"not an xlsx")))

    # 재발 방지: 조용히 값을 잃거나 바꾸는 경로
    def twin_sheet(wb: Workbook) -> None:
        twin = wb.create_sheet("재 고")
        twin.append([cell.value for cell in wb["재고"][1]])

    got, summary = tampered(twin_sheet)
    c.check(
        "이름이 공백·대소문자만 다른 시트가 둘이면 하나를 조용히 고르지 않고 오류('재고'·'재 고')",
        got is None and has(summary, IssueCode.DUPLICATE_SHEET, "재고"),
    )

    def cross_type(wb: Workbook) -> None:
        ws, parts = wb["재고"], wb["부재"]
        ws.cell(row=2, column=_column(ws, "로트ID")).value = parts.cell(row=2, column=_column(parts, "부재ID")).value

    got, summary = tampered(cross_type)
    c.check(
        "종류가 다른 항목의 ID가 같으면 오류(재고 로트 = 부재 ID — 그래프 색인에서 한쪽이 덮임)",
        got is None and has(summary, IssueCode.DUPLICATE_ID, "재고", 2, "로트ID"),
    )

    def formula(wb: Workbook) -> None:
        ws = wb["부재"]
        ws.cell(row=2, column=_column(ws, "두께(mm)")).value = "=10+2"

    got, summary = tampered(formula)
    c.check(
        "계산값이 저장되지 않은 수식은 빈칸으로 읽지 않고 그 칸을 짚어 오류(부재 2행 두께)",
        got is None and has(summary, IssueCode.BAD_VALUE, "부재", 2, "두께"),
    )
    for text, ok in (("1,5", False), ("1,,000", False), ("1,234.5", True), ("15.5", True)):

        def number(wb: Workbook, text: str = text) -> None:
            ws = wb["블록"]
            ws.cell(row=2, column=_column(ws, "강재 중량(t)")).value = text

        got, summary = tampered(number)
        c.check(
            f"숫자 '{text}': {'천 단위 쉼표·소수는 읽음' if ok else '애매한 쉼표는 형식 오류(1,5를 15로 읽지 않음)'}",
            (got is not None and got.blocks[0].steel_weight_t == float(text.replace(",", "")))
            if ok
            else (got is None and has(summary, IssueCode.BAD_VALUE, "블록", 2, "강재 중량")),
        )

    def clash(wb: Workbook) -> None:
        ws = wb["발주 관측"]
        po, status, day = (cell.value for cell in ws[2])
        ws.append([po, "가공" if status != "가공" else "입고", day])

    got, summary = tampered(clash)
    last = to_workbook(snapshot)["발주 관측"].max_row + 1
    c.check(
        "같은 날 서로 다른 관측은 '발주 관측'의 두 행을 짚음(발주 행이 아니라)",
        got is None
        and has(summary, IssueCode.INVALID_ROW, "발주 관측", 2, "상태")
        and has(summary, IssueCode.INVALID_ROW, "발주 관측", last, "상태")
        and not has(summary, IssueCode.INVALID_ROW, "발주"),
    )

    def empty_required(wb: Workbook) -> None:
        ws = wb["공정"]
        ws.delete_rows(2, ws.max_row)

    got, summary = tampered(empty_required)
    c.check(
        "데이터 행이 꼭 있어야 하는 필수 시트(공정)에 행이 없으면 바로 그 시트를 짚어 오류",
        got is None and any(i.code is IssueCode.MISSING_VALUE and i.sheet == "공정" for i in summary.issues),
    )


def _untrusted(c: Checker, snapshot: GraphSnapshot) -> None:
    """올린 파일의 값을 그대로 내려받기에 쓰거나, 손상된 파일을 읽을 때(서버 오류 대신 명사형 안내)."""
    c.section("엑셀: 믿을 수 없는 값·손상된 파일")
    first = snapshot.parts[0]
    formula = '=HYPERLINK("http://evil.example","x")'
    named = snapshot.model_copy(update={"parts": (first.model_copy(update={"name": formula}), *snapshot.parts[1:])})
    data = _bytes(to_workbook(named))
    ws = load_workbook(io.BytesIO(data))["부재"]
    written = [cell for row in ws.iter_rows(min_row=2) for cell in row if cell.value == formula]
    back = read_workbook(data)["부재"]
    c.check(
        "'='로 시작하는 이름은 내려받은 엑셀에서 수식이 아니라 글자로 저장되고, 다시 읽어도 같은 글자",
        len(written) == 1
        and written[0].data_type == "s"
        and any(value == formula for _, values in back.rows for value in values),
        [(cell.coordinate, cell.data_type) for cell in written],
    )
    source = zipfile.ZipFile(io.BytesIO(_bytes(to_workbook(snapshot))))
    broken = io.BytesIO()
    with zipfile.ZipFile(broken, "w") as target:
        for info in source.infolist():
            body = source.read(info.filename)
            target.writestr(info, body[: len(body) // 2] if info.filename.endswith("sheet2.xml") else body)
    c.check(
        "시트 XML이 깨진 파일은 서버 오류가 아니라 '파일 손상 가능' ValueError(422)",
        c.raises(lambda: read_workbook(broken.getvalue()))
        and _message(lambda: read_workbook(broken.getvalue())).startswith("엑셀 시트 읽기 실패 · 파일 손상 가능"),
    )


def _message(fn: Callable[[], object]) -> str:
    try:
        fn()
    except ValueError as error:
        return str(error)
    return ""


def _serial(day: date) -> float:
    """엑셀 날짜 숫자(1900 체계, 1900-03-01 이후): 1899-12-30부터 센 날 수. openpyxl과 따로 계산한 기준."""
    return float((day - date(1899, 12, 30)).days)


def _has(
    summary: ImportSummary,
    code: IssueCode,
    sheet: str,
    row: int | None = None,
    column: str | None = None,
    file_column: str | None = None,
) -> bool:
    return any(
        i.code is code
        and i.sheet == sheet
        and (row is None or i.row == row)
        and (column is None or i.column == column)
        and (file_column is None or i.file_column == file_column)
        for i in summary.issues
    )


def _with_sheet(mapping: ConfirmedMapping, name: str, /, **update: object) -> ConfirmedMapping:
    """매핑에서 파일 시트 하나(name)의 항목만 바꾼다(검증을 거쳐)."""
    sheets = [
        SheetMapping.model_validate({**entry.model_dump(), **update}) if entry.file_sheet == name else entry
        for entry in mapping.sheets
    ]
    return ConfirmedMapping(sheets=tuple(sheets))


def _with_unit(entry: SheetMapping, key: str, unit: str | None) -> list[dict[str, object]]:
    return [{**col.model_dump(), "unit": unit} if col.key == key else col.model_dump() for col in entry.columns]


def _mapped(c: Checker, snapshot: GraphSnapshot) -> None:
    c.section("엑셀: 확정 매핑대로 읽기(시트·머리글 행·열·원본 단위)")
    base_raw = read_workbook(_bytes(to_workbook(snapshot)))
    base = exact_mapping(base_raw)
    c.check(
        "지정 양식 그대로면 매핑이 저절로 정해짐: 양식 시트마다 첫 행 머리글·모든 열, '양식 안내'는 읽지 않음",
        all(
            (entry.template is None) == (entry.file_sheet == GUIDE_SHEET)
            and (entry.template is None or len(entry.columns) == len(SHEET_BY_KEY[entry.template].columns))
            for entry in base.sheets
        ),
    )
    entries = {entry.file_sheet: entry for entry in base.sheets}

    def read(
        change: Callable[[Workbook], None], mapping: ConfirmedMapping
    ) -> tuple[GraphSnapshot | None, ImportSummary]:
        workbook = to_workbook(snapshot)
        change(workbook)
        return build(read_workbook(_bytes(workbook)), FILE, mapping)

    def bom(wb: Workbook) -> None:
        ws = wb["부재"]
        ws.title = "BOM"
        col = _column(ws, "두께(mm)")
        ws.cell(row=1, column=col).value = "THK"
        for row in range(2, ws.max_row + 1):
            cell = ws.cell(row=row, column=col)
            if cell.value is not None:
                cell.value = float(Decimal(repr(cell.value)) / 1000)
        ws.cell(row=1, column=_column(ws, "부재명")).value = "품명"

    mapping = _with_sheet(base, "부재", file_sheet="BOM", columns=_with_unit(entries["부재"], "thickness_mm", "m"))
    got, summary = read(bom, mapping)
    c.check(
        "시트 이름·머리글이 달라도(BOM·THK·품명) 확정 매핑과 원본 단위(m)로 읽으면 원래 지도와 같고 출처는 파일 시트",
        got is not None
        and _domain(got) == _domain(snapshot)
        and not summary.issues
        and got.parts[0].source == SourceRef(file=FILE, sheet="BOM", row=2),
        [i.message for i in summary.issues[:3]],
    )
    unknown_unit = _with_sheet(
        base, "부재", file_sheet="BOM", columns=_with_unit(entries["부재"], "thickness_mm", None)
    )
    got, summary = read(bom, unknown_unit)
    c.check(
        "양식과 이름이 다른 머리글(THK)에 원본 단위가 없으면 양식 단위로 짐작하지 않고 오류(단위를 골라 달라고)",
        got is None and _has(summary, IssueCode.BAD_VALUE, "BOM", 1, "두께", "THK"),
        [i.message for i in summary.issues[:2]],
    )
    got, summary = read(bom, base)
    c.check(
        "매핑에 없는 파일 시트(BOM)는 조용히 건너뛰지 않고 오류, 매핑에만 있는 시트(부재)도 오류",
        got is None
        and _has(summary, IssueCode.MISSING_SHEET, "BOM")
        and any(i.code is IssueCode.MISSING_SHEET and "'부재' 시트 없음" in i.message for i in summary.issues),
    )

    def framed(wb: Workbook) -> None:
        ws = wb["블록"]
        col = _column(ws, "강재 중량(t)")
        ws.cell(row=1, column=col).value = "강재 중량(kg)"
        for row in range(2, ws.max_row + 1):
            cell = ws.cell(row=row, column=col)
            cell.value = float(Decimal(repr(cell.value)) * 1000)
        ws.insert_rows(1, 3)
        ws.cell(row=1, column=1).value = "블록 목록 (2026-10-08 기준)"
        ws.cell(row=3, column=1).value = "기본 정보"
        ws.cell(row=3, column=col).value = "물량"
        ws.append(["※ 중량은 kg 기준"])

    framed_mapping = _with_sheet(
        base, "블록", header_rows=(3, 4), columns=_with_unit(entries["블록"], "steel_weight_t", "kg")
    )
    got, summary = read(framed, framed_mapping)
    c.check(
        "제목·빈 행 아래 두 줄 머리글, 끝 메모 행, kg 값: 확정 매핑대로 읽으면 원래 지도와 같고 제목·메모 행은 경고만",
        got is not None
        and _domain(got) == _domain(snapshot)
        and {(i.code, i.row) for i in summary.issues}
        == {(IssueCode.IGNORED_ROW, 1), (IssueCode.IGNORED_ROW, 5 + len(snapshot.blocks))}
        and got.blocks[0].source == SourceRef(file=FILE, sheet="블록", row=5),
        [(i.row, i.message) for i in summary.issues[:4]],
    )
    got, summary = read(framed, _with_sheet(framed_mapping, "블록", header_rows=(2,)))
    c.check(
        "빈 행을 머리글로 고르면 지도를 만들지 않고 머리글 행을 다시 고르라고 함",
        got is None and _has(summary, IssueCode.MISSING_COLUMN, "블록", 2),
    )
    c.check(
        "떨어진 두 행은 두 줄 머리글로 받지 않음(사이 행을 조용히 빼지 않게)",
        c.raises(lambda: _with_sheet(base, "블록", header_rows=(1, 3))),
    )
    moved = [
        {**col.model_dump(), "position": 99} if col.key == "fabricator_id" else col.model_dump()
        for col in entries["블록"].columns
    ]
    got, summary = read(lambda wb: None, _with_sheet(base, "블록", columns=moved))
    c.check(
        "표 밖 열 위치를 고르면 오류(빈 열을 조용히 읽지 않음)",
        got is None and any("표 밖" in i.message for i in summary.issues),
        [i.message for i in summary.issues[:2]],
    )

    # 머리글에 적힌 단위를 확정 매핑이 조용히 무시하지 않음
    def ld_percent(wb: Workbook) -> None:
        ws = wb["호선"]
        ws.cell(row=1, column=_column(ws, "지체상금 일률")).value = "지체상금 일률(%)"
        ws.cell(row=2, column=_column(ws, "지체상금 유예일(일)")).value = 30
        ws.cell(row=2, column=_column(ws, "지체상금 일률(%)")).value = 0.005
        ws.cell(row=2, column=_column(ws, "지체상금 최대일(일)")).value = 120

    rate = SHEET_BY_KEY["ships"].columns.index(SHEET_BY_KEY["ships"].column("ld_rate_per_day_of_price"))
    silent = read(ld_percent, base)
    acknowledged = read(
        ld_percent,
        _with_sheet(
            base,
            "호선",
            columns=[
                {**col.model_dump(), "unit": None, "ignore_unit": True} if col.position == rate else col.model_dump()
                for col in entries["호선"].columns
            ],
        ),
    )
    c.check(
        "단위 없는 항목(지체상금 일률)에 머리글 단위(%)가 있으면, 사람이 '머리글 단위를 쓰지 않음'을 고르기 전엔 오류"
        " — 화면이 단위를 비워 보내도 100배로 읽지 않음",
        silent[0] is None
        and any(i.column == "지체상금 일률" and "%" in i.message for i in silent[1].issues)
        and acknowledged[0] is not None
        and acknowledged[0].ships[0].ld_terms is not None
        and acknowledged[0].ships[0].ld_terms.rate_per_day_of_price == 0.005,
        ([i.message for i in silent[1].issues][:2], [i.message for i in acknowledged[1].issues][:2]),
    )

    def inch(wb: Workbook) -> None:
        ws = wb["부재"]
        ws.cell(row=1, column=_column(ws, "두께(mm)")).value = "두께(inch)"

    blank_unit = read(inch, _with_sheet(base, "부재", columns=_with_unit(entries["부재"], "thickness_mm", None)))
    c.check(
        "머리글에 단위(inch)가 있는데 확정 매핑 단위가 비면 지정 양식 관례(양식 단위)로 읽지 않고 오류",
        blank_unit[0] is None and _has(blank_unit[1], IssueCode.BAD_VALUE, "부재", 1, "두께", "두께(inch)"),
        [i.message for i in blank_unit[1].issues][:2],
    )

    def meter_header(wb: Workbook) -> None:
        ws = wb["부재"]
        ws.cell(row=1, column=_column(ws, "두께(mm)")).value = "두께(m)"

    differs = read(meter_header, _with_sheet(base, "부재", columns=_with_unit(entries["부재"], "thickness_mm", "mm")))
    overridden = read(
        meter_header,
        _with_sheet(
            base,
            "부재",
            columns=[
                {**col.model_dump(), "unit": "mm", "ignore_unit": True}
                if col.key == "thickness_mm"
                else col.model_dump()
                for col in entries["부재"].columns
            ],
        ),
    )
    c.check(
        "머리글 단위(m)와 다른 원본 단위(mm)로 확정하면 사람이 명시(머리글 단위 쓰지 않음)하지 않는 한 오류,"
        " 명시하면 그 단위로",
        differs[0] is None
        and _has(differs[1], IssueCode.BAD_VALUE, "부재", 1, "두께", "두께(m)")
        and overridden[0] is not None
        and _domain(overridden[0]) == _domain(snapshot),
        ([i.message for i in differs[1].issues][:2], [i.message for i in overridden[1].issues][:2]),
    )
    skipped = _with_sheet(base, "재고", template=None, header_rows=(), columns=[])
    got, summary = read(lambda wb: None, skipped)
    c.check(
        "'읽지 않음'으로 고른 시트는 경고하고 선택 시트가 없는 것으로 읽음(재고 없음과 구분)",
        got is not None
        and got.stock == ()
        and _has(summary, IssueCode.IGNORED_SHEET, "재고")
        and "재고" in summary.missing_sheets,
    )

    def formats(wb: Workbook) -> None:
        ws = wb["발주"]
        col = _column(ws, "계획 발주일")
        styles: list[Callable[[date], str | int | float]] = [
            lambda d: f"{d:%Y.%m.%d}",
            lambda d: f"{d:%Y/%m/%d}",
            lambda d: f"{d.year}. {d.month}. {d.day}.",
            lambda d: f"{d:%Y%m%d}",
            lambda d: int(f"{d:%Y%m%d}"),
            _serial,
            lambda d: f"{d.year}년 {d.month}월 {d.day}일",
        ]
        filled = [row for row in range(2, ws.max_row + 1) if ws.cell(row=row, column=col).value is not None]
        for row, style in zip(filled, styles, strict=False):
            cell = ws.cell(row=row, column=col)
            value = cell.value
            day = value.date() if isinstance(value, datetime) else value
            assert isinstance(day, date)
            cell.value = style(day)
            cell.number_format = "General"  # 날짜 서식 칸에 8자리 숫자를 넣으면 엑셀도 날짜 범위 밖(#VALUE!)으로 본다
        kinds = wb["부재"]
        kind = _column(kinds, "부재 종류")
        for row in range(2, kinds.max_row + 1):
            cell = kinds.cell(row=row, column=kind)
            value = next(k for k, label in SHEET_BY_KEY["parts"].column("kind").codes.items() if label == cell.value)
            cell.value = f" {value.upper().replace('_', '-')} "

    got, summary = _tampered(snapshot, formats)
    c.check(
        "날짜 7표기·코드 표기(대문자·하이픈·공백)로 적은 엑셀도 원래 지도와 같음",
        got is not None and _domain(got) == _domain(snapshot) and not summary.issues,
        [i.message for i in summary.issues[:3]],
    )

    def two_digit(wb: Workbook) -> None:
        ws = wb["발주"]
        col = _column(ws, "계획 발주일")
        row = next(r for r in range(2, ws.max_row + 1) if ws.cell(row=r, column=col).value is not None)
        ws.cell(row=row, column=col).value = "26.10.20"

    got, summary = _tampered(snapshot, two_digit)
    c.check(
        "두 자리 연도 날짜는 짐작하지 않고 그 칸을 짚어 오류",
        got is None and any(i.column == "계획 발주일" and "네 자리 연도" in i.message for i in summary.issues),
    )

    def excel_errors(wb: Workbook) -> None:
        ws = wb["부재"]
        ws.cell(row=2, column=_column(ws, "강종")).value = "#N/A"
        orders = wb["발주"]
        col = _column(orders, "계획 발주일")
        row = next(r for r in range(2, orders.max_row + 1) if orders.cell(row=r, column=col).value is not None)
        orders.cell(row=row, column=col).value = 20261020  # 날짜 서식은 그대로 → 엑셀·openpyxl 모두 날짜 범위 밖
        orders.cell(row=row, column=col).number_format = "yyyy-mm-dd"

    got, summary = _tampered(snapshot, excel_errors)
    c.check(
        "엑셀 오류 값(#N/A, 날짜 서식 칸의 범위 밖 숫자 → #VALUE!)은 선택 열이어도 글자·빈칸으로 읽지 않고 오류",
        got is None
        and _has(summary, IssueCode.BAD_VALUE, "부재", 2, "강종")
        and any(i.column == "계획 발주일" and "#VALUE!" in i.message for i in summary.issues),
        [i.message for i in summary.issues[:3]],
    )


def _tampered(
    snapshot: GraphSnapshot, change: Callable[[Workbook], None]
) -> tuple[GraphSnapshot | None, ImportSummary]:
    workbook = to_workbook(snapshot)
    change(workbook)
    return build(read_workbook(_bytes(workbook)), FILE)


GATE_ECNS = 4  # 관문 변형마다 분석 수치를 비교할 개발 설계변경 수
DEV_FULL = 10  # 전체 행으로 정답 매핑을 확인할 개발 변형 수
JUDGMENT_MODULES = {"mapping", "fields", "normalize", "build", "columns", "proposal"}


def _variants(c: Checker, snapshot: GraphSnapshot) -> None:
    c.section("엑셀: 흔한 변형 생성기(관문 3종·개발 변형)")
    variants = gate_variants(snapshot)
    c.check("관문 변형은 V1·V2·V3 세 가지", [v.name for v in variants] == list(GATE_STYLES))
    settings = Settings.from_env({})
    book, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    strength = load_strength(settings.strength_path)
    config = load_config()
    ecns = [e for e in generate(config).ecns if e.split is EcnSplit.DEV]
    original = GraphIndex(snapshot)
    for variant in variants:
        raw = read_workbook(variant.data)
        got, summary = build(raw, f"{variant.name}.xlsx", variant.truth)
        warnings = {i.code for i in summary.issues}
        c.check(
            f"관문 {variant.name}: 정답 매핑으로 읽으면 원래 지도와 같고 오류 0(경고는 덧붙인 열·제목·메모 행·시트뿐)",
            got is not None
            and _domain(got) == _domain(snapshot)
            and warnings <= {IssueCode.IGNORED_COLUMN, IssueCode.IGNORED_ROW, IssueCode.IGNORED_SHEET},
            [i.message for i in summary.issues if i.severity is IssueSeverity.ERROR][:3],
        )
        if got is None:
            continue
        imported, compared, different = GraphIndex(got), 0, []
        for ecn in ecns:
            if compared >= GATE_ECNS:
                break
            request = AnalysisRequest(change=ecn.change, as_of=config.scenario_date)
            try:
                before = analyze(original, request, book, params, strength)
            except RequestError:
                continue
            after = analyze(imported, request, book, params, strength)
            compared += 1
            keys = {"impacts", "cost_lines", "total", "schedule", "timing", "verdict"}
            if _unsourced(before.model_dump(mode="json", include=keys)) != _unsourced(
                after.model_dump(mode="json", include=keys)
            ):
                different.append(ecn.change.ecn_id)
        c.check(
            f"관문 {variant.name}: 그 지도로 분석한 수치가 같음(개발 설계변경 {compared}건)",
            compared == GATE_ECNS and not different,
            different,
        )
    _gate_elements(c, variants)

    rng = random.Random(20261008)
    broken = []
    for index in range(DEV_FULL):
        style = dev_style(rng, max_rows=None)
        variant = make_variant(snapshot, f"D{index}", style, 5000 + index)
        got, summary = build(read_workbook(variant.data), "dev.xlsx", variant.truth)
        if got is None or _domain(got) != _domain(snapshot):
            broken.append((index, [i.message for i in summary.issues if i.severity is IssueSeverity.ERROR][:2]))
    c.check(
        f"개발 변형 {DEV_FULL}개(요소를 시드마다 섞음, 전체 행): 정답 매핑으로 읽으면 모두 원래 지도와 같음",
        not broken,
        broken[:2],
    )

    style = dev_style(random.Random(7))
    first, second = make_variant(snapshot, "A", style, 77), make_variant(snapshot, "B", style, 77)
    c.check(
        "같은 시드·요소면 같은 시트 내용과 정답(파일 시각 정보만 다를 수 있음)",
        read_workbook(first.data) == read_workbook(second.data) and first.truth == second.truth,
    )
    c.check(
        "개발 변형은 시트마다 앞 40행만(보정 자료의 파일 단위 독립·크기)",
        all(len(sheet.rows) <= 40 + 6 for sheet in read_workbook(first.data).values()),
    )

    tree = ast.parse((PROJECT_ROOT / "ripple" / "ingest" / "variants.py").read_text(encoding="utf-8"))
    imported_modules = {
        (node.module or "").split(".")[-1] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {alias.name.split(".")[-1] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    c.check(
        "생성기는 가져오기 판단 코드(표 찾기·필드 사전·정규화·읽기·열 매핑)를 쓰지 않음(정답이 판단을 따라가지 않게)",
        not imported_modules & JUDGMENT_MODULES,
        sorted(imported_modules & JUDGMENT_MODULES),
    )
    vocab = load_vocabulary()
    thin = [
        (s.key, col.key)
        for s in SHEETS
        for col in s.columns
        if len({_plain(h) for h in vocab.columns.get((s.key, col.key), ())}) < 3
    ]
    clashes = []
    for s in SHEETS:
        seen: dict[str, str] = {}
        for col in s.columns:
            for header in vocab.columns.get((s.key, col.key), ()):
                if seen.setdefault(_plain(header), col.key) != col.key:
                    clashes.append((s.key, header))
    c.check(
        "어휘: 모든 양식 열에 머리글 후보 3개 이상, 한 시트 안에서 두 열에 겹치는 후보 없음",
        not thin and not clashes,
        (thin[:3], clashes[:3]),
    )
    inverse = [
        (unit, alt)
        for unit, alts in vocab.units.items()
        for alt, factor in alts.items()
        if alt in vocab.units and unit in vocab.units[alt] and factor * vocab.units[alt][unit] != 1
    ]
    c.check(
        "어휘: 단위 배율이 서로 역수(t → kg 1000, kg → t 0.001)이고 양식 단위마다 항목이 있음",
        not inverse and all(col.unit in vocab.units for s in SHEETS for col in s.columns if col.unit),
        inverse,
    )
    fields = default_fields()
    known = {(sheet, key): {_plain(h) for h in info.synonyms} for (sheet, key), info in fields.columns.items()}
    pairs_all = [(k, h) for k, headers in vocab.columns.items() for h in headers]
    unseen = [(k, h) for k, h in pairs_all if _plain(h) not in known.get(k, set())]
    c.check(
        f"생성기 머리글 중 필드 사전에 없는 것 {len(unseen)}/{len(pairs_all)}개({len(unseen) / len(pairs_all):.0%}) — "
        "처음 보는 머리글의 정확도를 따로 잰다",
        0 < len(unseen) < len(pairs_all),
    )


def _gate_elements(c: Checker, variants: list[Any]) -> None:
    """관문 변형마다 그 요소가 실제로 들어갔는지(정답 매핑 기준)."""
    by_name = {v.name: v for v in variants}
    v1, v2, v3 = by_name["V1"], by_name["V2"], by_name["V3"]
    raw1 = read_workbook(v1.data)
    renamed = total = extra = 0
    for entry in v1.truth.sheets:
        if entry.template is None:
            continue
        headers = [cell for cell in dict(raw1[entry.file_sheet].rows)[entry.header_rows[0]]]
        sheet = SHEET_BY_KEY[entry.template]
        for col in entry.columns:
            if col.key is None:
                extra += 1
                continue
            total += 1
            renamed += split_unit(headers[col.position])[0] != sheet.column(col.key).header
    keys_in_order = [
        [col.key for col in entry.columns if col.key] for entry in v1.truth.sheets if entry.template is not None
    ]
    template_order = [[col.key for col in SHEET_BY_KEY[e.template].columns] for e in v1.truth.sheets if e.template]
    c.check(
        f"V1: 머리글 {renamed}/{total}개를 동의어로, 덧붙인 열 {extra}개, 열 순서가 양식과 다름",
        renamed / total > 0.8 and extra >= len(template_order) and keys_in_order != template_order,
    )
    raw2 = read_workbook(v2.data)
    vocab = load_vocabulary()
    two_row = [e for e in v2.truth.sheets if e.template and e.template in vocab.groups]
    dimensions = {
        unit
        for e in v2.truth.sheets
        if e.template
        for col in e.columns
        if col.key
        and (template_unit := SHEET_BY_KEY[e.template].column(col.key).unit)
        and col.unit != _plain(template_unit)
        for unit in [template_unit]
    }
    memo_rows = sum(
        1
        for e in v2.truth.sheets
        if e.file_sheet in raw2
        for _, cells in raw2[e.file_sheet].rows
        if len([x for x in cells if x is not None]) == 1 and isinstance(cells[0], str) and cells[0][:1] in "※*비"
    )
    c.check(
        f"V2: 묶음 시트는 두 줄 머리글·제목 행, 원본 단위를 바꾼 양식 단위 {sorted(dimensions)}, 메모 {memo_rows}행",
        all(len(e.header_rows) == 2 and e.header_rows[0] > 1 for e in two_row)
        and {"mm", "m", "t", "kg", "원", "일"} <= dimensions
        and memo_rows >= len(two_row),
    )
    raw3 = read_workbook(v3.data)
    renamed_sheets = sum(1 for e in v3.truth.sheets if e.template and e.file_sheet != SHEET_BY_KEY[e.template].name)
    dated = [
        cells[col.position]
        for e in v3.truth.sheets
        if e.template
        for col in e.columns
        if col.key and SHEET_BY_KEY[e.template].column(col.key).kind is Kind.DATE
        for number, cells in raw3[e.file_sheet].rows
        if number > e.header_rows[-1] and col.position < len(cells) and cells[col.position] is not None
    ]
    c.check(
        f"V3: 시트 이름 {renamed_sheets}개 바꿈·양식과 상관없는 시트, 날짜 칸이 날짜 서식이 아닌 표기({len(dated)}칸)",
        renamed_sheets >= len([e for e in v3.truth.sheets if e.template]) * 0.8
        and any(e.template is None for e in v3.truth.sheets)
        and bool(dated)
        and not any(isinstance(value, datetime) for value in dated),
    )


def _plain(text: str) -> str:
    return "".join(str(text).split()).casefold()
