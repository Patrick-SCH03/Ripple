"""과거 설계변경 백테스트 도구(ripple/eval/backtest/, docs/backtest.md): 양식 → 실행 → 출력 · 결정성 · 빈 칸 처리 ·
발견 단계 단조성 · 출력에 원문 없음 · 변환 규칙(도면·발주 수) · 저장소 안 출력 거부. 서버·키 없이 가상 예시만 쓴다.
"""

from __future__ import annotations

import io
import tempfile
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

from harness import Checker
from openpyxl import load_workbook

from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.domain import BLOCK_STAGE_ORDER, DIRECT_PERFORMER, ActivityKind, BlockStage
from ripple.contracts.result import AnalysisResult
from ripple.engine.analyze import analyze
from ripple.engine.cost.rework_block import AFTER_PAINT_ITEM
from ripple.engine.describe import BLOCK_STAGE_NAMES
from ripple.engine.index import GraphIndex
from ripple.eval.backtest.build import Built, build_case
from ripple.eval.backtest.case import COLUMNS, Case, parse_case
from ripple.eval.backtest.compare import REWORK_RULE, CaseResult, line_hours, predict, run_case, run_cases
from ripple.eval.backtest.crew import CREW_ID
from ripple.eval.backtest.engine import Engine
from ripple.eval.backtest.examples import EXAMPLE_MARK, EXAMPLE_ROWS
from ripple.eval.backtest.summary import summarize
from ripple.eval.backtest.workbook import CASE_SHEET, GUIDE_SHEET, read_cases, write_template
from scripts.backtest import run as run_script

SHEETS = ["요약", "사례별", "가정", "고정 가정값"]


def _example(index: int, **override: object) -> Case:
    return parse_case({**EXAMPLE_ROWS[index], **override}, row=index + 2, ordinal=index + 1)


def _cells(path: Path) -> dict[str, list[tuple[object, ...]]]:
    workbook = load_workbook(path, read_only=True)
    try:
        return {name: list(workbook[name].iter_rows(values_only=True)) for name in workbook.sheetnames}
    finally:
        workbook.close()


def _template(c: Checker, folder: Path) -> Path:
    blank = _cells(write_template(folder / "blank.xlsx"))
    workbook = load_workbook(folder / "blank.xlsx")
    sheet = workbook[CASE_SHEET]
    lists = [v.formula1 for v in sheet.data_validations.dataValidation if v.type == "list"]
    stages = '"' + ",".join(BLOCK_STAGE_NAMES[s] for s in BLOCK_STAGE_ORDER) + '"'
    c.check(
        "빈 양식: 사례 시트 머리글 = 양식 열(사례 0건)·설명 시트·드롭다운(발견 단계 = 엔진 블록 단계 이름 순서)",
        list(blank) == [CASE_SHEET, GUIDE_SHEET]
        and blank[CASE_SHEET] == [tuple(column.header for column in COLUMNS)]
        and stages in lists
        and read_cases(folder / "blank.xlsx") == (),
        (list(blank), lists[:2]),
    )
    filled = write_template(folder / "cases.xlsx", EXAMPLE_ROWS)
    cases = read_cases(filled)
    c.check(
        "가상 예시 3건: 서로 다른 발견 단계, 사례 번호에 '예시(가상)', 입력 문제 없음, 원문 칸은 사례에 없음",
        len(cases) == 3
        and len({case.stage for case in cases}) == 3
        and all(EXAMPLE_MARK in case.number and not case.problems for case in cases)
        and not any(hasattr(case, "content") or hasattr(case, "area") for case in cases),
        cases,
    )
    return filled


def _quiet(source: Path, out_dir: Path) -> int:
    """스크립트 run을 출력 없이(검사 화면에 요약 줄이 섞이지 않게)."""
    with redirect_stdout(io.StringIO()):
        return run_script(source, out_dir)


def _outputs(c: Checker, folder: Path, filled: Path) -> None:
    codes = (_quiet(filled, folder / "out1"), _quiet(filled, folder / "out2"))
    first, second = folder / "out1", folder / "out2"
    sheets = _cells(first / "backtest_result.xlsx")
    md = (first / "backtest_result.md").read_text(encoding="utf-8")
    c.check(
        "실행 → 출력: 종료 코드 0, 시트 요약·사례별·가정·고정 가정값, 사례별 3행, 요약에 엔진·규칙·비용·생성기 판",
        codes == (0, 0)
        and list(sheets) == SHEETS
        and len(sheets["사례별"]) == 4
        and {f"판 · {name}" for name in ("엔진", "전파 규칙", "비용 파라미터", "생성기 설정")}
        <= {row[0] for row in sheets["요약"]},
        (codes, list(sheets)),
    )
    c.check(
        "결정성: 두 번 실행한 마크다운 바이트와 엑셀 칸 값이 같음",
        md == (second / "backtest_result.md").read_text(encoding="utf-8")
        and sheets == _cells(second / "backtest_result.xlsx"),
    )
    originals = [str(row[key]) for row in EXAMPLE_ROWS for key in ("content", "area")]
    flat = " ".join(str(value) for rows in sheets.values() for row in rows for value in row)
    c.check(
        "출력 마크다운·엑셀에 원문 칸(변경 내용·블록·구역) 글이 없음 — 사례 번호만",
        not any(text in md or text in flat for text in originals)
        and all(str(r["case_no"]) in md for r in EXAMPLE_ROWS),
        [text for text in originals if text in md or text in flat],
    )
    refused = _quiet(filled, PROJECT_ROOT / "backtest_out_check")
    c.check(
        "결과 폴더가 저장소 안이면 거부(종료 코드 2, 폴더를 만들지 않음)",
        refused == 2 and not (PROJECT_ROOT / "backtest_out_check").exists(),
    )


def _blanks(c: Checker, engine: Engine) -> None:
    third = run_case(_example(2), engine)
    blank_items = {a.item for a in third.built.assumptions if a.blank} if third.built else set()
    c.check(
        "빈 칸: 실제 공수가 없으면 '비교 불가'(값을 만들지 않음), 블록 무게·결정 일수·지연 기준은 기본값 + '가정'",
        third.mh is not None
        and third.mh.actual is None
        and third.mh.ratio is None
        and "비교 불가" in third.mh.note
        and blank_items == {"블록 무게(t)", "결정까지 걸린 일수", "지연 기준"},
        (third.mh, blank_items),
    )
    empty = {key: None for key in ("mh_min", "mh_max", "cost_min", "cost_max", "delay_days")}
    bare = run_case(_example(0, **empty, cause=None, drawings=None), engine)
    summary = summarize(run_cases([_example(0, **empty), _example(1)], engine))
    c.check(
        "실제 값이 모두 비면 비용·공수·지연 모두 비교 불가, 요약은 비교한 사례만 셈",
        bare.prediction is not None
        and bare.cost is not None
        and bare.cost.actual is None
        and bare.delay_diff is None
        and "비교 불가" in bare.delay_note
        and summary.cost.compared == 1
        and summary.mh.compared == 1
        and summary.delay_compared == 1,
        summary,
    )
    c.check(
        "발견 단계는 옛 이름도 읽음(판계·판넬조립 = 같은 단계, 조립·대조립 = 같은 단계)",
        all(_example(1, stage=name).stage is BlockStage.PANEL for name in ("판계", "판넬조립"))
        and all(_example(1, stage=name).stage is BlockStage.ASSEMBLY for name in ("조립", "대조립")),
    )
    bad = run_cases(
        [_example(0, mh_min="약 100"), _example(1, stage=None), _example(1, members=0, spools=0)],
        engine,
    )
    c.check(
        "잘못 적은 칸·빈 발견 단계·바뀐 것 없음은 '계산 불가'와 이유(지어내지 않음)",
        all(r.prediction is None and r.problem for r in bad)
        and "추가 공수 최소" in (bad[0].problem or "")
        and "발견 단계" in (bad[1].problem or ""),
        [r.problem for r in bad],
    )


def _monotone(c: Checker, engine: Engine) -> None:
    broken: list[str] = []
    for index in range(len(EXAMPLE_ROWS)):
        results = [run_case(replace(_example(index), stage=stage), engine) for stage in BLOCK_STAGE_ORDER]
        rework = [r.prediction.rework_mh.value for r in results if r.prediction]
        total = [r.prediction.all_mh.value for r in results if r.prediction]
        days = [r.prediction.as_of for r in results if r.prediction]
        steady = len(rework) == len(BLOCK_STAGE_ORDER) and days == sorted(set(days))
        if not (steady and rework == sorted(rework) and total == sorted(total) and rework[-1] > 0):
            broken.append(f"{EXAMPLE_ROWS[index]['case_no']}: {rework}")
    c.check(
        "단조성: 같은 사례에서 발견 단계만 늦추면 기준일이 늦어지고 예측 공수(재작업·전체)가 줄지 않음(미착수~탑재)",
        not broken,
        broken,
    )


def _conversion(c: Checker, engine: Engine) -> None:
    first = run_case(_example(0), engine)
    p = first.prediction
    c.check(
        "변환: 예시 1(부재 3·스풀 4·도면 2·발주 변경 1) → 엔진의 도면 개정 2건·발주 변경 1건, 가정 없음",
        p is not None
        and (p.drawing_revisions, p.po_changes) == (2, 1)
        and first.built is not None
        and not first.built.assumptions,
        p,
    )
    over = run_case(_example(0, drawings=9, po_changes=6), engine)
    notes = {a.item for a in over.built.assumptions if not a.blank} if over.built else set()
    q = over.prediction
    c.check(
        "변환: 도면 수·발주 변경이 부재·스풀보다 많으면 넣을 수 있는 만큼(7장·4건)만 넣고 변환 메모로 남김",
        q is not None and (q.drawing_revisions, q.po_changes) == (7, 4) and {"개정 도면 수", "발주 변경 건수"} <= notes,
        (q, notes),
    )


def _blank_items(result: CaseResult) -> set[str]:
    return {a.item for a in result.built.assumptions if a.blank} if result.built else set()


def _columns(c: Checker, engine: Engine) -> None:
    """양식 열 재제작 방식·지연 기준·결정 일수·수행 주체: 빈 칸 → 기본값 + '가정', 값 있음 → 그 값."""
    base = run_case(_example(0), engine)
    blank = run_case(_example(0, spool_method=None), engine)
    outside = run_case(_example(0, spool_method="사외 재발주"), engine)
    dimension = run_case(_example(0, spool_method="치수 변경"), engine)
    p, q, o, d = base.prediction, blank.prediction, outside.prediction, dimension.prediction
    c.check(
        "재제작 방식: 비면 사내 재제작 + '가정'(결과 같음), 사외 재발주는 새 스풀이 늦게 와 구역 출구가 더 늦음, "
        "치수 변경은 발주 변경 0건",
        p is not None
        and q is not None
        and o is not None
        and d is not None
        and _blank_items(blank) == {"재제작 방식"}
        and not _blank_items(base)
        and q == p
        and o.exit_delay > p.exit_delay
        and (p.po_changes, d.po_changes) == (1, 0),
        (p, o, d),
    )
    bases = {name: run_case(_example(0, delay_basis=name), engine) for name in ("탑재", "구역 출구", "인도", None)}
    quiet = run_case(_example(0, delay_basis=None, delay_days=None), engine)
    actual = 5  # 예시 1의 실제 지연
    c.check(
        "지연 기준: 탑재·구역 출구·인도는 그 예측과 견주고, 비면 구역 출구 + '가정'(실제 지연이 없으면 세지 않음)",
        p is not None
        and p.delivery_delay is not None
        and bases["탑재"].delay_diff == p.erection_delay - actual
        and bases["구역 출구"].delay_diff == p.exit_delay - actual
        and bases["인도"].delay_diff == p.delivery_delay - actual
        and bases[None].delay_diff == p.exit_delay - actual
        and _blank_items(bases[None]) == {"지연 기준"}
        and not _blank_items(quiet),
        {name: r.delay_diff for name, r in bases.items()},
    )
    undecided = run_case(_example(0, decision_days=None), engine)
    direct = run_case(_example(0, performer="직영"), engine)
    u, w = undecided.prediction, direct.prediction
    c.check(
        "결정 일수: 있으면 확정일 = 기준일 + 일수(예시 1은 7일), 비면 0일 + '가정'. 수행 주체는 둘 다 같은 금액",
        p is not None
        and u is not None
        and w is not None
        and (p.confirm_on - p.as_of).days == 7
        and u.confirm_on == u.as_of
        and _blank_items(undecided) == {"결정까지 걸린 일수"}
        and w.total == p.total,
        (p, u),
    )


def _compared_cost(result: CaseResult) -> object:
    """실제 비용과 견준 예측(총액이어야 함 — 지연 파급 비용을 더하지 않음)."""
    return None if result.cost is None else result.cost.predicted


def _analyzed(case: Case, engine: Engine) -> tuple[Built, AnalysisResult]:
    built = build_case(case, engine.defaults, engine.generator)
    return built, analyze(GraphIndex(built.snapshot), built.request, engine.rulebook, engine.params)


def _engine_v2(c: Checker, engine: Engine) -> None:
    """엔진 0.10.0 · 계약 1.32.0: 블록 형상(난이도)·작업반·도장 뒤 고정 항목·지연 파급 비용·PE."""
    params = engine.params
    shapes = {name: run_case(_example(1, block_type=name), engine) for name in ("평", "곡", "선수미", None)}
    mh = {name: r.prediction.rework_mh.value for name, r in shapes.items() if r.prediction}
    flat = mh.get("평", 0.0)
    c.check(
        "블록 종류 → 형상 난이도: 곡·선수미 재작업 공수 = 평 × 형상 계수(파라미터), 비면 계수 1 + '가정'",
        len(mh) == 4
        and flat > 0
        and abs(mh["곡"] - flat * params.value("difficulty.shape.curved")) < 1e-6
        and abs(mh["선수미"] - flat * params.value("difficulty.shape.bow_stern")) < 1e-6
        and abs(mh[None] - flat) < 1e-6
        and _blank_items(shapes[None]) == {"블록 종류"},
        mh,
    )
    crew_built, crew_result = _analyzed(_example(0), engine)
    direct_built, direct_result = _analyzed(_example(0, performer="직영"), engine)
    performers = {a.kind: a.performer for a in crew_built.snapshot.activities if a.block_id is not None}
    split = [line.line_id for line in crew_result.cost_lines if line.rule_id == REWORK_RULE]
    c.check(
        "사내 협력사 → 작업반(탑재 뺀 블록 공정, 탑재 직영): 재작업 줄이 작업반 몫으로 나뉘고 금액·공수는 직영과 같음",
        len(crew_built.snapshot.crews) == 1
        and not direct_built.snapshot.crews
        and performers[ActivityKind.ERECTION] == DIRECT_PERFORMER
        and all(who == CREW_ID for kind, who in performers.items() if kind is not ActivityKind.ERECTION)
        and any("@" in line_id for line_id in split)
        and crew_result.total == direct_result.total
        and abs(
            predict(crew_result, crew_built, params).all_mh.value
            - predict(direct_result, direct_built, params).all_mh.value
        )
        < 1e-6,
        split,
    )
    built, result = _analyzed(_example(2), engine)
    got = predict(result, built, params)
    after = [line for line in result.cost_lines if line.rule_id == AFTER_PAINT_ITEM]
    readable = [h for line in result.cost_lines if (h := line_hours(line, params)) is not None]
    after_hours = sum(params.value(f"after_paint.{k}_hours") for k in ("repaint", "scaffold", "hot_work"))
    ripple = result.delay_ripple
    c.check(
        "탑재 단계: 도장 뒤 고정 항목(C-04)도 전체 공수에 들어감, 지연 파급 비용은 엔진 값 그대로 따로(비교는 총액)",
        len(after) == 1
        and abs(got.all_mh.value - sum(h.value for h in readable)) < 1e-6
        and got.all_mh.value - got.rework_mh.value >= after_hours - 1e-6
        and ripple is not None
        and got.delay_ripple is not None
        and (got.delay_ripple.value, got.delay_ripple.low, got.delay_ripple.high)
        == (ripple.amount.value, ripple.amount.low, ripple.amount.high)
        and _compared_cost(run_case(_example(2), engine)) == got.total,
        (got, ripple),
    )
    c.check("발견 단계 'PE'는 PE 단계(엔진 1.32.0)", _example(1, stage="PE").stage is BlockStage.PRE_ERECTION)


def _outfit_only(c: Checker, engine: Engine) -> None:
    """엔진 0.12.0(현업 사례): 의장품 재작업은 선행의장부터 · 배관도 개정 공수 · 진행 중 선행의장의 후행 설치 후보."""
    params = engine.params
    _, early = _analyzed(_example(0, members=0, stage="대조립", decision_days=0), engine)
    early_rework = [line for line in early.cost_lines if line.rule_id == REWORK_RULE]
    c.check(
        "배관만 바뀌고 대조립: 재작업 줄 0원 하나 · '아직 블록에 달기 전' · 톤당 공수 가정값 없음 · 경고 아님",
        len(early_rework) == 1
        and early_rework[0].amount.high == 0
        and "아직 블록에 달기 전" in (early_rework[0].reason or "")
        and not any(key.startswith("base_work_hours_per_t.") for key in early_rework[0].param_keys)
        and "대조립 이후 블록 재작업 필요" not in early.verdict.reasons,
        [(line.line_id, line.amount, line.reason) for line in early_rework],
    )
    _, outfit = _analyzed(_example(0, members=0, stage="선행의장", decision_days=0), engine)
    rework = [line for line in outfit.cost_lines if line.rule_id == REWORK_RULE]
    weight = float(rework[0].inputs["outfit_weight_t"]) if rework else 0.0
    difficulty = float(rework[0].inputs["difficulty"]) if rework else 0.0
    expected = (
        weight
        * params.value("base_work_hours_per_t.pre_outfitting")
        * params.value("rework_multiplier.pre_outfitting")
        * difficulty
    )
    hours = sum(float(line.inputs["hours"]) for line in rework)
    c.check(
        "배관만 바뀌고 선행의장: 재작업 공수 = 의장품 중량 × 선행의장 톤당 공수 × 배수 × 난이도 · 검토 필요",
        bool(rework)
        and weight > 0
        and float(rework[0].inputs["hull_weight_t"]) == 0
        and abs(hours - expected) < 0.01
        and outfit.verdict.level.value == "review",
        (hours, expected, outfit.verdict),
    )
    keys: dict[str | None, set[str]] = {}
    for case in (_example(0, members=0), _example(0, spools=0, spool_method=None)):
        built, result = _analyzed(case, engine)
        discipline = {d.drawing_id: d.discipline for d in built.snapshot.drawings}
        for line in result.cost_lines:
            if line.rule_id == "R-D01":
                keys.setdefault(discipline.get(line.entity_id), set()).update(
                    k for k in line.param_keys if k.startswith("minor_work_hours.")
                )
    c.check(
        "도면 개정 공수: 배관도는 drawing_revision_piping, 선체 구조도는 drawing_revision_per_drawing",
        keys.get("piping") == {"minor_work_hours.drawing_revision_piping"}
        and keys.get("hull") == {"minor_work_hours.drawing_revision_per_drawing"},
        keys,
    )
    _, late = _analyzed(_example(0, members=0, stage="선행의장", decision_days=0, spool_method="사외 재발주"), engine)
    option = late.onboard
    c.check(
        "선행의장 진행 중 + 늦게 오는 새 배관: 후행 설치 선택지가 나오고 그 방식이면 탑재 지연이 줄어듦",
        option is not None
        and option.direction.value == "to_on_board"
        and option.erection_delay_then_days < option.erection_delay_now_days,
        option,
    )


def _hours(c: Checker, engine: Engine) -> None:
    """공수 다시 읽기: 재작업 줄의 금액 ÷ 인건비 = 엔진이 줄에 적은 대표 공수, 범위는 최소 ≤ 대표 ≤ 최대."""
    problems: list[str] = []
    for index in range(len(EXAMPLE_ROWS)):
        built = build_case(_example(index), engine.defaults, engine.generator)
        result = analyze(GraphIndex(built.snapshot), built.request, engine.rulebook, engine.params)
        got = predict(result, built, engine.params)
        written = sum(float(line.inputs["hours"]) for line in result.cost_lines if line.rule_id == REWORK_RULE)
        bands = (got.rework_mh, got.all_mh)
        if abs(got.rework_mh.value - written) > 0.01 or not all(b.low <= b.value <= b.high for b in bands):
            problems.append(f"{index}: {got.rework_mh} vs {written}")
        if got.rework_mh.value > got.all_mh.value:
            problems.append(f"{index}: 재작업 > 전체")
    c.check(
        "예측 공수: 재작업 줄 금액 ÷ 인건비 = 줄에 적힌 공수, 최소 ≤ 대표 ≤ 최대, 재작업 ≤ 전체 공수",
        not problems,
        problems,
    )


def run(c: Checker) -> None:
    c.section("과거 설계변경 백테스트(양식 → 실행 → 출력 · 결정성 · 빈 칸 · 단조성 · 원문 없음 · 변환)")
    engine = Engine.load()
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        filled = _template(c, folder)
        _outputs(c, folder, filled)
    _blanks(c, engine)
    _monotone(c, engine)
    _conversion(c, engine)
    _columns(c, engine)
    _engine_v2(c, engine)
    _outfit_only(c, engine)
    _hours(c, engine)
