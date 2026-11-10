"""엑셀 열 매핑의 성질(docs/input.md(엑셀 양식) 4절): 표 찾기(시트·머리글 행 제안과 확실성), 열 판단(정확 일치·선택지·
특징·단위 상태·자격·시트 안 배타 배정), 보정 산출물(params/column_v1.yaml)로 만든 파일 제안(지정 양식 = 모두 정확 일치,
관문 변형 3종 = 제안이 정답과 같고 그 매핑으로 읽은 지도가 원래 지도와 같음), 덮어쓰기."""

from __future__ import annotations

import io
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from harness import Checker
from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from ripple.config.loaders import load_decision_config
from ripple.config.settings import Settings
from ripple.contracts.decision import NONE_OPTION, DecisionTopic, GateKind, Route
from ripple.contracts.domain import GraphSnapshot
from ripple.contracts.ingest import ColumnMethod, ConfirmedMapping, IssueSeverity, SheetMapping, UnitState
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.ingest.build import build
from ripple.ingest.columns import (
    ColumnJudgment,
    Featurizer,
    FileColumn,
    _assign,
    judge_sheet,
    reference_sets,
    unit_state,
)
from ripple.ingest.export import GUIDE_SHEET, to_bytes, to_workbook
from ripple.ingest.fields import DEFAULT_PATH as DEFAULT_FIELDS_PATH
from ripple.ingest.fields import default_fields, load_fields
from ripple.ingest.mapping import exact_column, exact_mapping, header_cells, header_units, unit_notes
from ripple.ingest.normalize import split_unit
from ripple.ingest.proposal import (
    ColumnModel,
    FilePlan,
    Override,
    RoutedColumn,
    confirmed_mapping,
    pending,
    plan_file,
    same_mapping,
)
from ripple.ingest.tables import NAME_BONUS, NAME_PART_BONUS, HeaderIndex, guess_header, guess_sheets, stacked
from ripple.ingest.template import SHEET_BY_KEY
from ripple.ingest.variants import gate_variants, load_vocabulary
from ripple.ingest.workbook import RawSheet, read_workbook

EPOCH = datetime(1899, 12, 30)


def run(c: Checker) -> None:
    snapshot = generate(load_config()).snapshot
    _tables(c, snapshot)
    _columns(c)
    _proposals(c, snapshot)
    _unit_hints(c, snapshot)
    _title_rows(c, snapshot)
    _merged_data(c, snapshot)


def _bytes(workbook: Workbook) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _domain(snapshot: GraphSnapshot) -> object:
    def unsourced(value: object) -> object:
        if isinstance(value, dict):
            return {k: unsourced(v) for k, v in value.items() if k not in ("source", "sources")}
        if isinstance(value, list):
            return [unsourced(v) for v in value]
        return value

    return unsourced(snapshot.model_dump(mode="json", exclude={"snapshot_id", "origin", "data_mode"}))


def _tables(c: Checker, snapshot: GraphSnapshot) -> None:
    c.section("엑셀 열 매핑: 표 찾기")
    index = HeaderIndex(default_fields())
    raw = read_workbook(to_bytes(snapshot))
    guesses = {g.file_sheet: g for g in guess_sheets(raw, index)}
    truth = {s.file_sheet: s for s in exact_mapping(raw).sheets}
    c.check(
        "지정 양식: 모든 시트를 그 양식 시트·1행 머리글로 확실하게 찾고 '양식 안내'는 읽지 않음(확실)",
        all(
            g.certain and g.template == truth[name].template and (g.header is None or g.header.rows == (1,))
            for name, g in guesses.items()
        )
        and guesses[GUIDE_SHEET].template is None,
    )
    for variant in gate_variants(snapshot):
        proposed = guess_sheets(read_workbook(variant.data), index)
        wanted = {s.file_sheet: s for s in variant.truth.sheets}
        wrong = [
            g.file_sheet
            for g in proposed
            if g.template != wanted[g.file_sheet].template
            or (g.template is not None and (g.header is None or g.header.rows != wanted[g.file_sheet].header_rows))
        ]
        unsure = [g.file_sheet for g in proposed if not g.certain]
        expected_unsure = [s.file_sheet for s in variant.truth.sheets if s.template is None]
        c.check(
            f"관문 {variant.name}: 시트·머리글 행(두 줄·제목 아래 포함)을 모두 맞히고, "
            "확실하지 않은 시트는 양식과 상관없는 "
            "시트뿐",
            not wrong and unsure == expected_unsure,
            (wrong, unsure),
        )
    c.check(
        "두 줄 머리글 모양: 위 칸이 빈 자리에 아래 칸 글자가 있고 둘 다 글자일 때만"
        "(데이터 행·꽉 찬 한 줄 머리글은 아님)",
        stacked(["부재ID", "자재", None], [None, "두께(mm)", "강종"])
        and not stacked(["부재ID", "두께(mm)"], ["S-001:B01-PL-001", 12.0])
        and not stacked(["구역ID", "호선번호", "구역명"], ["S-001:ZCT", "S-001", "화물탱크 구역"]),
    )
    standalone = ((1, ("부재ID", "치수", None, "비고(mm)", None)), (2, (None, "두께", "폭", None, "메모")))
    joined = RawSheet("부재", standalone, merges=((1, 4, 1, 5),))  # 위 줄 '비고(mm)'를 오른쪽 칸까지 가로 병합
    c.check(
        "두 줄 머리글: 아래 칸이 빈 한 칸짜리 열('부재ID'·'비고(mm)')은 묶음이 아님 — 오른쪽 열에 이름·단위가 이어지지"
        " 않음(가로 병합이면 묶음)",
        header_cells(RawSheet("부재", standalone), (1, 2)) == ("부재ID", "치수 두께", "치수 폭", "비고(mm)", "메모")
        and header_units(RawSheet("부재", standalone), (1, 2)) == (None, None, None, "mm", None)
        and header_cells(joined, (1, 2))[4] == "비고(mm) 메모"
        and header_units(joined, (1, 2))[4] == "mm",
        (header_cells(RawSheet("부재", standalone), (1, 2)), header_units(RawSheet("부재", standalone), (1, 2))),
    )
    hidden = RawSheet(
        "부재",
        (
            (1, ("부재ID", "자재", None)),
            (2, (None, "THK_X", "GRD_X")),
            (3, ("S-001:B01-PL-001", 12, "AH36")),
        ),
    )
    header = guess_header(hidden, SHEET_BY_KEY["parts"], index)
    c.check(
        "아래 줄 이름이 사전에 없는 두 줄 머리글은 한 줄로 골라도 확실하지 않음(아래 행이 두 줄 머리글 모양)",
        header is not None and header.rows == (1,) and not header.certain,
        header,
    )
    workbook = to_workbook(snapshot)
    twin = workbook.copy_worksheet(workbook["부재"])
    twin.title = "부재 사본"
    twins = {g.file_sheet: g for g in guess_sheets(read_workbook(_bytes(workbook)), index)}
    c.check(
        "같은 양식 시트로 보이는 시트가 둘이면 하나만 배정하고 다른 하나는 확실하지 않다고 이유를 적음",
        twins["부재"].template == "parts"
        and twins["부재 사본"].template != "parts"
        and not twins["부재 사본"].certain
        and bool(twins["부재 사본"].reasons),
    )
    workbook = to_workbook(snapshot)
    workbook["협력사"].title = "업체 목록"
    renamed = {g.file_sheet: g for g in guess_sheets(read_workbook(_bytes(workbook)), index)}
    suppliers, parts = SHEET_BY_KEY["suppliers"], SHEET_BY_KEY["parts"]
    c.check(
        "시트 이름 점수: 양식 이름·사전 동의어와 같으면 0.5, 그 이름을 품으면('업체 목록' ⊃ '업체') 0.3, 아니면 0 — "
        "이름을 바꾼 지정 양식 시트도 그 양식 시트로 제안",
        index.name_bonus(suppliers, "협력사") == NAME_BONUS
        and index.name_bonus(suppliers, "업체 목록") == NAME_PART_BONUS
        and index.name_bonus(parts, "업체 목록") == 0.0
        and renamed["업체 목록"].template == "suppliers",
    )


def _column(header: str | None, values: tuple[object, ...], position: int = 0) -> FileColumn:
    return FileColumn(position, header, header, values, EPOCH)


def _columns(c: Checker) -> None:
    c.section("엑셀 열 매핑: 열 판단(정확 일치·특징·단위·자격·배정)")
    fields = default_fields()
    featurizer = Featurizer(fields)
    parts = SHEET_BY_KEY["parts"]
    thickness = parts.column("thickness_mm")
    states = {
        "두께(mm) 정확": unit_state(thickness, _column("두께(mm)", (12,)), True),
        "THK [m] 같은 차원": unit_state(thickness, _column("THK [m]", (0.012,)), False),
        "두께 단위 생략(지정 양식 관례)": unit_state(thickness, _column("두께", (12,)), True),
        "THK 단위 없음": unit_state(thickness, _column("THK", (12,)), False),
        "THK(kg) 다른 차원": unit_state(thickness, _column("THK(kg)", (12,)), False),
        "수량(EA) 단위 없는 항목": unit_state(parts.column("qty"), _column("수량(EA)", (1,)), True),
        "수량": unit_state(parts.column("qty"), _column("수량", (1,)), True),
    }
    expected = {
        "두께(mm) 정확": (UnitState.CONFIRMED, 1.0),
        "THK [m] 같은 차원": (UnitState.CONFIRMED, 1000.0),
        "두께 단위 생략(지정 양식 관례)": (UnitState.CONFIRMED, 1.0),
        "THK 단위 없음": (UnitState.UNRESOLVED, None),
        "THK(kg) 다른 차원": (UnitState.UNRESOLVED, None),
        "수량(EA) 단위 없는 항목": (UnitState.UNRESOLVED, None),
        "수량": (UnitState.NOT_NEEDED, 1.0),
    }
    got = {name: (state[0], state[2]) for name, state in states.items()}
    c.check(
        "단위 상태: 같은 차원 머리글 단위·지정 양식 관례만 확인됨, 모르는·다른 차원·단위 없는 항목의 단위는 미해결",
        got == expected,
        {k: v for k, v in got.items() if v != expected[k]},
    )
    revision = parts.column("revision")
    failing = featurizer.option(parts, revision, _column("확인", ("O", "O")))
    date_option = featurizer.option(
        SHEET_BY_KEY["purchase_orders"],
        SHEET_BY_KEY["purchase_orders"].column("entered_received"),
        _column("확인", ("O", "O", "O")),
    )
    c.check(
        "값이 그 종류로 하나도 안 읽히면 읽기 실패 특징이 1(날짜 항목에 'O' 표시) — 비율 0이 벌점 없이 지나가지 않게",
        date_option.get("parse_fail") == 1.0 and failing.get("parse_fail") == 0.0,
        (date_option, failing),
    )
    spec = parts.column("spec_id")
    covered = featurizer.option(
        parts, spec, _column("MAT_CD", ("PL-1", "PL-2")), {"specs": frozenset({"PL-1", "PL-2"})}
    )
    unknown = featurizer.option(parts, spec, _column("MAT_CD", ("PL-1", "PL-9")), {"specs": frozenset({"PL-1"})})
    no_refs = featurizer.option(parts, spec, _column("MAT_CD", ("PL-1",)))
    c.check(
        "다른 시트 ID를 가리키는 항목: 그 시트 ID 목록에 든 비율(참조 포함률), 목록이 없으면 참조 특징 없음",
        covered.get("ref_cover") == 1.0
        and unknown.get("ref_cover") == 0.5
        and "ref_cover" not in no_refs
        and covered.get("id_word") == 1.0,
        (covered, unknown),
    )
    name = parts.column("name")
    text_fit = featurizer.option(parts, name, _column("DESCRIPTION", ("기관실 이중저 판 1", "선측 판 2")))
    code_fit = featurizer.option(parts, revision, _column("DESCRIPTION", ("기관실 이중저 판 1", "선측 판 2")))
    c.check(
        "값 모양 힌트: 글 항목(부재명)엔 공백·한글 글이 맞고 짧은 코드 항목(개정)엔 맞지 않음",
        text_fit.get("shape_fit") == 1.0 and code_fit.get("shape_fit") == 0.0,
        (text_fit.get("shape_fit"), code_fit.get("shape_fit")),
    )
    none = featurizer.none(_column("No.", (1, 2, 3, 4)), 0.2)
    memo = featurizer.none(_column("비고", ("확인 필요",)), 0.1)
    c.check(
        "해당 없음 특징: 순번 열(1, 2, 3, …)·메모성 머리글·빈 열·머리글 없음",
        none.get("none_seq") == 1.0
        and memo.get("none_memo") == 1.0
        and featurizer.none(_column("비고", ()), 0.0).get("none_empty") == 1.0
        and featurizer.none(_column(None, ("x",)), 0.0).get("none_no_header") == 1.0,
    )
    others = [featurizer.none(_column(h, (3,)), 0.5).get("none_memo") for h in ("납기일", "미입고 수량", "W/O 확정일")]
    c.check(
        "양식에 없는 흔한 머리글(납기일·미입고수량·W/O확정일, 공백·빗금 무시)도 메모성 머리글과 같은 '해당 없음' 특징",
        others == [1.0, 1.0, 1.0] and "none_memo" not in featurizer.none(_column("THK", (12,)), 0.5),
        others,
    )
    with tempfile.TemporaryDirectory() as folder:
        clashing = Path(folder) / "fields.yaml"
        clashing.write_text(
            DEFAULT_FIELDS_PATH.read_text(encoding="utf-8") + "\nother_headers: [납기일, 자재 코드]\n", encoding="utf-8"
        )
        clash = c.raises(lambda: load_fields(clashing), ValueError)
    c.check("필드 사전 읽기: 양식에 없는 흔한 머리글이 어느 시트의 동의어(자재코드)와 겹치면 오류", clash)
    c.check(
        "다른 시트 항목 이름: 이 시트엔 없고 다른 양식 시트의 머리글·동의어인 이름만(발주 시트의 '자재코드'는 해당, "
        "부재 시트의 '자재코드'·발주 시트의 '발주번호'·사전에 없는 이름은 아님)",
        fields.foreign_sheet("purchase_orders", ("자재코드",), "supplier_id") is not None
        and fields.foreign_sheet("parts", ("자재코드",)) is None
        and fields.foreign_sheet("purchase_orders", ("발주번호",)) is None
        and fields.foreign_sheet("purchase_orders", ("LCNO",)) is None,
    )
    own = {
        ("ships", "호선", "ship_id"),
        ("blocks", "블록", "block_id"),
        ("blocks", "Block", "block_id"),
        ("zones", "구역", "zone_id"),
        ("specs", "규격", "spec_id"),
        ("po_lines", "Spec", "spec_id"),
        ("stock", "규격", "spec_id"),
    }
    flagged = [(s, h) for s, h, k in sorted(own) if fields.foreign_sheet(s, (h,), k) is not None]
    c.check(
        "제안한 항목 키를 다른 시트도 같은 키로 쓰면 같은 개념이라 다른 시트 이름이 아님"
        "(호선 시트 '호선' = 다른 시트의 호선ID, 블록·구역·규격도)",
        not flagged,
        flagged,
    )
    po_rows = RawSheet(
        "발주",
        (
            (1, ("발주번호", "자재코드", "발주일")),
            (2, ("PO-1", "SUP-01", datetime(2026, 9, 1))),
            (3, ("PO-2", "SUP-02", datetime(2026, 9, 2))),
        ),
    )
    eager = {"ratio": 6.0, "bigram": 6.0, "dict": 5.0, "none": 0.1}
    po_judged = {
        j.file_column.header: j
        for j in judge_sheet(SHEET_BY_KEY["purchase_orders"], po_rows, (1,), True, featurizer, eager).columns
    }
    material = po_judged["자재코드"]
    c.check(
        "다른 시트 항목 이름 열은 점수가 높아 항목을 제안해도 자동 진행 자격이 없고 이유를 적음"
        "(같은 시트 이름 열은 그대로)",
        material.key is not None
        and not material.ready
        and any("시트 항목 이름" in p for p in material.problems)
        and po_judged["발주일"].ready,
        (material.key, material.ready, material.problems, po_judged["발주일"].ready),
    )
    owing = RawSheet(
        "발주 품목",
        (
            (1, ("발주번호", "품목번호", "미납수량")),
            (2, ("PO-1", 1, 3)),
            (3, ("PO-2", 1, 5)),
        ),
    )
    line_judged = {
        j.file_column.header: j
        for j in judge_sheet(SHEET_BY_KEY["po_lines"], owing, (1,), True, featurizer, eager).columns
    }
    remaining = line_judged["미납수량"]
    c.check(
        "양식에 없는 흔한 머리글이 어떤 항목으로 제안되면 자동 진행 자격이 없고 이유를 적음(수량 열이 없는 시트의 "
        "'미납수량'이 수량으로 읽히지 않게)",
        remaining.key == "qty" and not remaining.ready and any("흔한 머리글" in p for p in remaining.problems),
        (remaining.key, remaining.ready, remaining.problems),
    )

    weights = {"dict": 5.0, "ratio": 2.0, "none": 1.0, "parse_fail": -3.0}
    rows = (
        (1, ("부재ID", "THK", "품명", "두께(mm)", "비고")),
        (2, ("S-001:B01-PL-001", 12, "판 1", 12, None)),
        (3, ("S-001:B01-PL-002", 13, "판 2", 13, "확인")),
    )
    sheet_raw = RawSheet("부재", rows)
    judged = judge_sheet(parts, sheet_raw, (1,), True, featurizer, weights)
    by_header = {j.file_column.header: j for j in judged.columns}
    thk = by_header["THK"]
    c.check(
        "정확 일치 열은 판단 밖(그 항목은 다른 열 선택지에서 빠짐), 나머지는 '해당 없음'이 있는 질문",
        by_header["부재ID"].method is ColumnMethod.EXACT
        and by_header["두께(mm)"].method is ColumnMethod.EXACT
        and thk.method is ColumnMethod.DECIDED
        and thk.case is not None
        and "thickness_mm" not in thk.case.question.option_ids
        and "part_id" not in thk.case.question.option_ids
        and NONE_OPTION in thk.case.question.option_ids,
    )
    unsure = judge_sheet(parts, sheet_raw, (1,), False, featurizer, weights)
    c.check(
        "시트·머리글이 확실하지 않으면 어떤 열도 자동 진행 자격이 없음(정확 일치 열 포함)",
        not any(j.ready for j in unsure.columns) and any(j.ready for j in judged.columns),
    )
    full = RawSheet(
        "발주 관측", ((1, ("발주번호", "상태", "관측일", "메모")), (2, ("PO-1", "발주", datetime(2026, 10, 1), "x")))
    )
    observed = judge_sheet(SHEET_BY_KEY["observations"], full, (1,), True, featurizer, weights)
    leftover = next(j for j in observed.columns if j.file_column.header == "메모")
    c.check(
        "양식 항목이 정확 일치로 모두 정해졌으면 남은 열은 질문 없이 해당 없음",
        leftover.method is ColumnMethod.DECIDED and leftover.case is None and leftover.key is None,
    )
    bad_range = RawSheet(
        "부재", ((1, ("부재ID", "두께")), (2, ("S-001:B01-PL-001", 12000)), (3, ("S-001:B01-PL-002", 13)))
    )
    ranged = judge_sheet(parts, bad_range, (1,), True, featurizer, weights)
    unread = RawSheet("부재", ((1, ("부재ID", "두께")), (2, ("S-001:B01-PL-001", "두꺼움"))))
    unparsed = judge_sheet(parts, unread, (1,), True, featurizer, weights)
    c.check(
        "상식 범위 밖 값이 있거나 앞 40행이 그 종류로 다 읽히지 않으면 자격 없음(정확 일치 열도)",
        not next(j for j in ranged.columns if j.key == "thickness_mm").ready
        and not next(j for j in unparsed.columns if j.key == "thickness_mm").ready,
    )
    judgments = [
        ColumnJudgment(
            _column("A", (), 0), ColumnMethod.DECIDED, "grade", score_map={"grade": 3.0, "name": 1.0, NONE_OPTION: 0.0}
        ),
        ColumnJudgment(
            _column("B", (), 1), ColumnMethod.DECIDED, "grade", score_map={"grade": 2.0, "name": 1.5, NONE_OPTION: 0.0}
        ),
        ColumnJudgment(_column("C", (), 2), ColumnMethod.DECIDED, "kind", score_map={"kind": 2.0, NONE_OPTION: 0.0}),
    ]
    _assign(judgments, 1.0)
    c.check(
        "시트 안 배타 배정: 최상위가 겹치지 않는 열은 그 항목, 겹치는 열끼리는 확률 순으로 다른 항목"
        "(같은 항목 두 번 없음)",
        [j.key for j in judgments] == ["grade", "name", "kind"],
        [j.key for j in judgments],
    )
    vocab = load_vocabulary()
    misleading = [
        (sheet, key, header)
        for (sheet, key), headers in vocab.columns.items()
        for header in headers
        if (found := exact_column(SHEET_BY_KEY[sheet], header)) is not None and found.key != key
    ]
    c.check(
        "생성기 머리글 후보 중 다른 양식 열 이름과 정확히 같은 것은 없음(정답이 정확 일치 규칙과 어긋나지 않음)",
        not misleading,
        misleading,
    )
    raw = read_workbook(to_bytes(generate(load_config()).snapshot))
    index = HeaderIndex(fields)
    refs = reference_sets(raw, guess_sheets(raw, index), index)
    c.check(
        "다른 시트 ID 목록은 ID 열 머리글이 양식·사전과 같은 시트에서 모든 행으로 모음",
        refs.keys() >= {"ships", "blocks", "specs", "parts", "purchase_orders", "activities"}
        and "S-001" in refs["ships"],
        sorted(refs),
    )


def _proposals(c: Checker, snapshot: GraphSnapshot) -> None:
    c.section("엑셀 열 매핑: 보정 산출물과 파일 제안")
    settings = Settings.from_env({})
    config = load_decision_config(settings.column_path)
    gate = config.gate(GateKind.COLUMN)
    c.check(
        "보정 산출물(params/column_v1.yaml): 열 문 문턱·엑셀 열 온도·되묻기 q̂·점수기 가중치가 있음",
        config.version == "column-v2"
        and gate is not None
        and gate.auto_threshold is not None
        and config.topic(DecisionTopic.EXCEL_COLUMN) is not None
        and bool(config.scorer(DecisionTopic.EXCEL_COLUMN) and config.scorer(DecisionTopic.EXCEL_COLUMN).weights),  # type: ignore[union-attr]
    )
    model = ColumnModel.of(config)
    fields = default_fields()
    raw = read_workbook(to_bytes(snapshot))
    plan = plan_file(raw, model, fields)
    c.check(
        "지정 양식: 모든 시트·열이 정확 일치·자동 진행, 확인할 것 0, 제안 = 지정 양식 매핑",
        plan.exact and not pending(plan) and not same_mapping(confirmed_mapping(plan), exact_mapping(raw)),
    )
    for variant in gate_variants(snapshot):
        raw = read_workbook(variant.data)
        plan = plan_file(raw, model, fields)
        proposed = confirmed_mapping(plan)
        differences = same_mapping(proposed, variant.truth)
        got, summary = build(raw, f"{variant.name}.xlsx", proposed)
        c.check(
            f"관문 {variant.name}: 사람이 고치기 전 제안 = 정답 매핑(시트·머리글 행·항목·원본 단위), "
            "그 매핑으로 읽은 지도 = "
            "원래 지도",
            not differences and got is not None and _domain(got) == _domain(snapshot),
            (differences[:3], [i.message for i in summary.issues if i.severity.value == "error"][:2]),
        )
        again = confirmed_mapping(plan_file(raw, model, fields))
        c.check(f"관문 {variant.name}: 같은 파일이면 같은 제안(결정적)", again == proposed)
        c.check(
            f"관문 {variant.name}: '지정 양식 그대로'가 아님"
            "(시트 이름·머리글 행·단위 중 하나라도 다르면 열 확인 화면에서 확인)",
            not plan.exact,
        )
    v1 = next(v for v in gate_variants(snapshot) if v.name == "V1")
    raw = read_workbook(v1.data)
    plan = plan_file(raw, model, fields)
    routed = [col for sheet in plan.sheets for col in sheet.columns if col.answer is not None]
    c.check(
        "판단 열의 경로는 판단 계층 답 그대로(자동 진행은 자격이 있을 때만), 정확 일치 열은 자격으로만 자동 진행",
        all((col.answer.route is Route.AUTO) == col.auto for col in routed if col.answer)
        and all(col.judgment.ready for col in routed if col.auto)
        and any(not col.auto for col in routed),
    )
    target = next(s for s in plan.sheets if s.guess.template == "parts")
    skipped = plan_file(raw, model, fields, {target.guess.file_sheet: Override(None)})
    moved = plan_file(raw, model, fields, {target.guess.file_sheet: Override("parts", (1,))})
    c.check(
        "덮어쓰기: '읽지 않음'이면 그 시트 열을 판단하지 않고, 양식 시트·머리글 행을 정하면 확실한 것으로 다시 판단",
        next(s for s in skipped.sheets if s.guess.file_sheet == target.guess.file_sheet).judged is None
        and next(s for s in moved.sheets if s.guess.file_sheet == target.guess.file_sheet).certain,
    )


def _unit_hints(c: Checker, snapshot: GraphSnapshot) -> None:
    c.section("엑셀 열 매핑: 머리글 밖 단위(위 줄 묶음·제목·메모 행)는 짐작해 확정하지 않음")
    model = ColumnModel.of(load_decision_config(Settings.from_env({}).column_path))
    fields = default_fields()
    parts = SHEET_BY_KEY["parts"]
    grouped = ("stiffener_spacing_m", "span_m", "head_m")

    def positions(ws: Worksheet, row: int) -> dict[str, int]:
        """단위를 뺀 머리글 이름 → 열 번호."""
        return {split_unit(ws.cell(row=row, column=col).value)[0]: col for col in range(1, ws.max_column + 1)}

    def scale(ws: Worksheet, col: int, factor: str, first: int) -> None:
        for row in range(first, ws.max_row + 1):
            cell = ws.cell(row=row, column=col)
            if isinstance(cell.value, int | float):
                cell.value = float(Decimal(repr(cell.value)) * Decimal(factor))

    def parts_plan(raw_sheets: dict[str, RawSheet]) -> tuple[FilePlan, dict[str, RoutedColumn]]:
        plan = plan_file(raw_sheets, model, fields)
        sheet = next(s for s in plan.sheets if s.guess.file_sheet == "부재")
        return plan, {col.judgment.key: col for col in sheet.columns if col.judgment.key}

    def with_units(mapping: ConfirmedMapping, keys: tuple[str, ...], unit: str | None) -> ConfirmedMapping:
        sheets = []
        for entry in mapping.sheets:
            if entry.file_sheet == "부재":
                columns = [
                    {**col.model_dump(), "unit": unit} if col.key in keys else col.model_dump() for col in entry.columns
                ]
                entry = SheetMapping.model_validate({**entry.model_dump(), "columns": columns})
            sheets.append(entry)
        return ConfirmedMapping(sheets=tuple(sheets))

    # ① 두 줄 머리글: 위 줄 '강도 계산(cm)' 묶음 아래 '보강재 간격·스팬·설계 수두'(단위 없음, 값은 cm),
    #    나머지 열은 위·아래를 합친 칸(위 줄에 이름) — 묶음이 어디까지 걸치는지는 값만으로 알 수 없다
    workbook = to_workbook(snapshot)
    ws = workbook["부재"]
    at = positions(ws, 1)
    ws.insert_rows(2)
    for key in grouped:
        col = at[parts.column(key).header]
        ws.cell(row=1, column=col).value = None
        ws.cell(row=2, column=col).value = parts.column(key).header
        scale(ws, col, "100", 3)
    ws.cell(row=1, column=at[parts.column(grouped[0]).header]).value = "강도 계산(cm)"
    raw = read_workbook(_bytes(workbook))
    plan, judged = parts_plan(raw)
    sheet = next(s for s in plan.sheets if s.guess.file_sheet == "부재")
    c.check(
        "위 줄 묶음에만 단위가 있는 열(보강재 간격·스팬·설계 수두)은 묶음 단위(cm)를 확정하지도, 양식 단위(m)로"
        " 짐작하지도 않고 사람이 고름(자동 아님) — 자기 칸에 단위가 있는 두께(mm)는 그대로 확정",
        sheet.guess.header is not None
        and sheet.guess.header.rows == (1, 2)
        and all(judged[k].judgment.unit_state is UnitState.UNRESOLVED and not judged[k].auto for k in grouped)
        and judged["thickness_mm"].judgment.unit_state is UnitState.CONFIRMED,
        {k: judged[k].judgment.unit_state.value for k in (*grouped, "thickness_mm")},
    )
    proposed = confirmed_mapping(plan)
    as_proposed = build(raw, "hint.xlsx", proposed)
    in_meter = build(raw, "hint.xlsx", with_units(proposed, grouped, "m"))
    in_cm = build(raw, "hint.xlsx", with_units(proposed, grouped, "cm"))
    c.check(
        "서버도 같은 정의: 단위를 비우거나(제안 그대로) 묶음과 다른 단위(m)로 보내면 지도를 만들지 않고, 사람이"
        " cm를 고르면 원래 지도와 같음",
        as_proposed[0] is None
        and in_meter[0] is None
        and any("머리글의 단위(cm)와 고른 원본 단위(m)" in i.message for i in in_meter[1].issues)
        and in_cm[0] is not None
        and _domain(in_cm[0]) == _domain(snapshot),
        ([i.message for i in in_meter[1].issues][:2], [i.message for i in in_cm[1].issues][:2]),
    )

    # ② 제목 행의 단위 안내: '부재 목록 (단위: cm)' 아래 한 줄 머리글 '두께'(단위 꼬리 없음, 값은 cm)
    workbook = to_workbook(snapshot)
    ws = workbook["부재"]
    thickness = positions(ws, 1)["두께"]
    ws.cell(row=1, column=thickness).value = "두께"
    scale(ws, thickness, "0.1", 2)
    ws.insert_rows(1)
    ws.cell(row=1, column=1).value = "부재 목록 (단위: cm)"
    raw = read_workbook(_bytes(workbook))
    plan, judged = parts_plan(raw)
    proposed = confirmed_mapping(plan)
    blank = build(raw, "note.xlsx", proposed)
    in_cm = build(raw, "note.xlsx", with_units(proposed, ("thickness_mm",), "cm"))
    c.check(
        "제목 행에 '(단위: cm)'가 있으면 이름이 양식과 같아도(두께) 양식 단위(mm)로 짐작하지 않음:"
        " 제안은 사람이 고르기, 서버는 단위 없이 오면 오류, cm를 고르면 원래 지도",
        judged["thickness_mm"].judgment.unit_state is UnitState.UNRESOLVED
        and not judged["thickness_mm"].auto
        and blank[0] is None
        and any("제목·메모 행" in i.message for i in blank[1].issues)
        and in_cm[0] is not None
        and _domain(in_cm[0]) == _domain(snapshot),
        ([i.message for i in blank[1].issues][:2], [i.message for i in in_cm[1].issues][:2]),
    )

    def notes(above: tuple[str, ...], below: tuple[str, ...] = ()) -> tuple[str, ...]:
        rows: list[tuple[int, tuple[object, ...]]] = [(i + 1, (text,)) for i, text in enumerate(above)]
        header = len(rows) + 1
        rows += [(header, ("부재ID", "두께")), (header + 1, ("P-1", 12))]
        rows += [(header + 2 + i, (text,)) for i, text in enumerate(below)]
        return unit_notes(RawSheet("부재", tuple(rows)), (header,))

    c.check(
        "단위 안내로 보는 글: '(단위: 천원)'·'단위: mm'·괄호 단위 '강도 계산(cm)'·메모 '※ 금액 단위: 천원'. 아닌 글:"
        " 날짜 제목·'■ 부재'·생성기 메모 '※ 단위는 머리글을 따릅니다'",
        notes(("발주 목록 (단위: 천원)",)) == ("발주 목록 (단위: 천원)",)
        and notes(("단위: mm",)) == ("단위: mm",)
        and notes(("강도 계산(cm)",)) == ("강도 계산(cm)",)
        and notes((), ("※ 금액 단위: 천원",)) == ("※ 금액 단위: 천원",)
        and notes(("부재 현황 (2026-10-08 기준)", "■ 부재"), ("※ 단위는 머리글을 따릅니다",)) == (),
    )


def _cell_of(ws: Worksheet, title: str, row: int = 1) -> int:
    """머리글 이름(단위 포함 그대로) → 열 번호."""
    return next(col for col in range(1, ws.max_column + 1) if ws.cell(row=row, column=col).value == title)


def _title_rows(c: Checker, snapshot: GraphSnapshot) -> None:
    c.section("엑셀: 머리글 위 한 칸짜리 제목 행은 두 줄 머리글의 위 줄이 아님(점검 D-8, v1_common·v5_unitnote 모양)")
    model = ColumnModel.of(load_decision_config(Settings.from_env({}).column_path))
    fields = default_fields()
    workbook = to_workbook(snapshot)
    blocks = workbook["블록"]
    blocks.insert_rows(1)
    blocks["A1"] = "블록 목록"
    blocks.merge_cells("A1:D1")
    lines = workbook["발주 품목"]
    price = _cell_of(lines, "단가(원)")
    lines.cell(row=1, column=price).value = "단가"
    for row in range(2, lines.max_row + 1):
        cell = lines.cell(row=row, column=price)
        if isinstance(cell.value, int | float):
            cell.value = float(Decimal(repr(cell.value)) * Decimal("0.001"))
    lines.insert_rows(1)
    lines["A1"] = "발주 품목 (단위: 천원)"
    raw = read_workbook(_bytes(workbook))
    guesses = {g.file_sheet: g for g in guess_sheets(raw, HeaderIndex(fields))}
    heads = {name: header_cells(raw[name], (2,)) for name in ("블록", "발주 품목")}
    rows = {name: (g.header.rows if g.header else None) for name, g in guesses.items() if name in heads}
    plan = plan_file(raw, model, fields)
    sheet = next(s for s in plan.sheets if s.guess.file_sheet == "발주 품목")
    unit_price = next(col for col in sheet.columns if col.judgment.key == "unit_price_krw")
    c.check(
        "제목 행('블록 목록'·'발주 품목 (단위: 천원)') 아래 한 줄 머리글을 2행 한 줄로 찾고 "
        "열 이름에 제목이 붙지 않음, 제목 속 단위 안내로 단가 단위는 그대로 사람이 고름",
        all(rows[name] == (2,) for name in heads)
        and heads["블록"][0] == "블록ID"
        and not any(h and ("블록 목록" in h or "발주 품목" in h) for head in heads.values() for h in head)
        and unit_price.judgment.unit_state is UnitState.UNRESOLVED
        and not unit_price.auto,
        (rows, heads["블록"][:3], unit_price.judgment.unit_state),
    )
    _, summary = build(raw, "title.xlsx", confirmed_mapping(plan))
    ignored = [i for i in summary.issues if i.sheet == "블록" and i.row == 1]
    c.check(
        "제목 행은 '머리글 위 1행은 제목·안내로 보고 읽기 제외' 경고(읽지 않은 행)",
        len(ignored) == 1 and ignored[0].severity is IssueSeverity.WARNING and "읽기 제외" in ignored[0].message,
        [i.message for i in ignored],
    )
    c.check(
        "두 줄 머리글 모양 판단: 위 행에 칸이 하나뿐이면(제목 행) 두 줄 머리글이 아님, 둘 이상이면 그대로",
        not stacked(["블록 목록"], ["블록ID", "호선번호", "구역ID"])
        and stacked(["부재ID", "치수", None], [None, "두께(mm)", "폭(mm)"]),
    )


def _merge_runs(ws: Worksheet, column: int) -> int:
    """같은 값이 이어지는 구간을 세로로 병합(첫 칸에만 값, 현장 엑셀에서 흔한 꼴). 병합한 곳 수."""
    count, row = 0, 2
    while row <= ws.max_row:
        value, end = ws.cell(row=row, column=column).value, row
        while end + 1 <= ws.max_row and ws.cell(row=end + 1, column=column).value == value:
            end += 1
        if end > row:
            for below in range(row + 1, end + 1):
                ws.cell(row=below, column=column).value = None
            ws.merge_cells(start_row=row, start_column=column, end_row=end, end_column=column)
            count += 1
        row = end + 1
    return count


def _merged_data(c: Checker, snapshot: GraphSnapshot) -> None:
    c.section("엑셀: 데이터 영역의 병합 범위는 왼쪽 위 값으로 채워 읽고 경고 한 줄(점검 D-2, v4_merged 모양)")
    workbook = to_workbook(snapshot)
    parts = workbook["부재"]
    merged = sum(_merge_runs(parts, _cell_of(parts, title)) for title in ("호선번호", "블록ID"))
    memo = parts.max_row + 1
    parts.cell(row=memo, column=1).value = "※ 2026-10 기준 자료"
    parts.merge_cells(start_row=memo, start_column=1, end_row=memo, end_column=4)
    got, summary = build(read_workbook(_bytes(workbook)), "merged.xlsx")
    plain, _ = build(read_workbook(to_bytes(snapshot)), "merged.xlsx")
    errors = [i for i in summary.issues if i.severity is IssueSeverity.ERROR]
    filled = [i for i in summary.issues if i.sheet == "부재" and "병합" in i.message]
    memos = [i for i in summary.issues if i.sheet == "부재" and i.row == memo]
    c.check(
        f"호선번호·블록ID를 같은 값마다 세로 병합({merged:,}곳)해도 오류 없이 원래 지도와 같고, "
        "'부재' 시트에 병합 곳 수 경고 한 줄 · 가로로 병합한 메모 행은 채우지 않고 메모로 읽지 않음",
        merged > 0
        and got is not None
        and plain is not None
        and got == plain
        and not errors
        and len(filled) == 1
        and filled[0].severity is IssueSeverity.WARNING
        and f"{merged:,}곳" in filled[0].message
        and len(memos) == 1
        and "메모" in memos[0].message,
        ([i.message for i in errors][:2], [i.message for i in filled], [i.message for i in memos]),
    )
