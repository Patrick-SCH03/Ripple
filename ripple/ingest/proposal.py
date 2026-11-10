"""엑셀 파일 하나의 매핑 제안(표 찾기 → 열 판단 → 경로)과 확정 매핑 만들기(docs/input.md(엑셀 양식) 4절).

열 확인 화면·API(ripple/api)와 보정 점검(scripts/calibrate_columns.py)·관문 검사가 같은 함수를 쓴다.
- 표 찾기(tables.guess_sheets)로 시트마다 양식 시트·머리글 행을 정하고(사람이 덮어쓸 수 있음),
- 그 위에서 열마다 정확 일치 또는 판단 계층 열 문(columns.judge_sheet + decide.router.decide_unit)을 거친다.
- 자동 진행(auto): 정확 일치 열은 자격(ready)만으로, 판단 열은 자격 + 문턱(τ) 이상일 때.
제안의 값은 plan_types.py, 계약(열 확인 화면)으로 바꾸기는 proposal_view.py에 있다(서버·검사가 쓰는 이름은 여기서도
import된다).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import replace

from ripple.contracts.decision import Route
from ripple.contracts.ingest import ColumnMapping, ColumnMethod, ConfirmedMapping, SheetMapping, UnitState
from ripple.decide.router import decide_unit

from .column_features import Featurizer
from .columns import ColumnJudgment, judge_sheet, reference_sets
from .fields import FieldDictionary
from .mapping import exact_sheet, is_guide
from .normalize import unit_factor
from .plan_types import ColumnModel, FilePlan, Override, RoutedColumn, SheetPlan, pending
from .proposal_view import mapping_of, to_contract
from .tables import HeaderGuess, HeaderIndex, SheetGuess, guess_header, guess_sheets
from .template import SHEET_BY_KEY
from .workbook import RawSheet

__all__ = [
    "ColumnModel",
    "FilePlan",
    "Override",
    "RoutedColumn",
    "confirmed_mapping",
    "mapping_of",
    "pending",
    "plain_template",
    "plan_file",
    "same_mapping",
    "to_contract",
]


def plan_file(
    raw: Mapping[str, RawSheet],
    model: ColumnModel,
    fields: FieldDictionary,
    overrides: Mapping[str, Override] | None = None,
) -> FilePlan:
    index = HeaderIndex(fields)
    featurizer = Featurizer(fields)
    chosen = overrides or {}
    guesses = [
        g if g.file_sheet not in chosen else _apply(g, chosen[g.file_sheet], raw[g.file_sheet], index)
        for g in guess_sheets(raw, index)
    ]
    twice = {t for t, n in Counter(g.template for g in guesses if g.template).items() if n > 1}
    guesses = [
        replace(g, certain=False, reasons=(*g.reasons, "같은 양식 시트로 고른 시트 둘 이상 · 하나만 남기기"))
        if g.template in twice
        else g
        for g in guesses
    ]
    references = reference_sets(raw, guesses, index)
    plans = []
    for guess in guesses:
        if guess.template is None or guess.header is None:
            plans.append(SheetPlan(guess, None, ()))
            continue
        judged = judge_sheet(
            SHEET_BY_KEY[guess.template],
            raw[guess.file_sheet],
            guess.header.rows,
            guess.certain,
            featurizer,
            model.weights,
            model.temperature,
            question_prefix=f"{guess.file_sheet}:",
            references=references,
        )
        plans.append(SheetPlan(guess, judged, tuple(_route(j, model) for j in judged.columns)))
    return FilePlan(tuple(plans), all(plain_template(plan, raw[plan.guess.file_sheet]) for plan in plans))


def plain_template(plan: SheetPlan, raw: RawSheet) -> bool:
    """지정 양식 그대로인 시트: '양식 안내'·빈 시트(읽지 않음, 확실)이거나, 시트 이름이 양식 시트 이름과 같고
    첫 행 한 줄 머리글이며 모든 열이 정확 일치·자동 진행이고 단위 배율이 1(같은 단위)이다. 하나라도 다르면 열 확인
    화면에서 확인한다."""
    guess = plan.guess
    if guess.template is None:
        return guess.certain and (is_guide(guess.file_sheet) or not raw.rows)
    if not plan.certain or guess.header is None or exact_sheet(guess.file_sheet) is not SHEET_BY_KEY[guess.template]:
        return False
    if not raw.rows or guess.header.rows != (raw.rows[0][0],):
        return False
    return all(
        c.judgment.method is ColumnMethod.EXACT and c.auto and c.judgment.factor in (None, 1.0) for c in plan.columns
    )


def _apply(guess: SheetGuess, override: Override, raw: RawSheet, index: HeaderIndex) -> SheetGuess:
    """사람이 정한 시트 상태. 양식 시트·머리글 행을 함께 정하면 확실하다. 양식 시트만 정하면 그 양식 시트로 머리글
    행을 다시 찾고, 그 결과가 확실하지 않으면 머리글 행을 골라 달라고 한다."""
    if override.template is None:
        return SheetGuess(guess.file_sheet, None, guess.candidates, True, None, ())
    if override.header_rows:
        header = HeaderGuess(rows=tuple(override.header_rows), matched=0, certain=True)
        return SheetGuess(guess.file_sheet, override.template, guess.candidates, True, header, ())
    found = guess_header(raw, SHEET_BY_KEY[override.template], index)
    if found is None:
        return SheetGuess(guess.file_sheet, override.template, guess.candidates, False, None, ("머리글 행 선택 필요",))
    reasons = () if found.certain else ("머리글 행 불확실 · 미리보기에서 머리글 행 선택",)
    return SheetGuess(guess.file_sheet, override.template, guess.candidates, found.certain, found, reasons)


def _route(judgment: ColumnJudgment, model: ColumnModel) -> RoutedColumn:
    case = judgment.case
    if judgment.method is ColumnMethod.EXACT or case is None or judgment.score_map is None:
        return RoutedColumn(judgment, None, judgment.ready and judgment.method is ColumnMethod.EXACT)
    (answer,) = decide_unit(
        [(case.question, judgment.score_map)],
        model.calibrations,
        model.gate,
        model.max_choices,
        model.version,
        ready=judgment.ready,
    )
    return RoutedColumn(judgment, answer, answer.route is Route.AUTO)


def confirmed_mapping(plan: FilePlan) -> ConfirmedMapping:
    """제안 그대로의 확정 매핑(개입 전). 단위가 미해결인 열은 원본 단위가 비어 있어 읽기에서 오류가 난다."""
    sheets: list[SheetMapping] = []
    for sheet in plan.sheets:
        guess = sheet.guess
        if guess.template is None or guess.header is None:
            sheets.append(SheetMapping(file_sheet=guess.file_sheet))
            continue
        columns = tuple(
            ColumnMapping(
                position=c.judgment.file_column.position,
                key=c.judgment.key,
                unit=c.judgment.unit if c.judgment.unit_state is UnitState.CONFIRMED else None,
            )
            for c in sheet.columns
        )
        sheets.append(
            SheetMapping(
                file_sheet=guess.file_sheet,
                template=guess.template,
                header_rows=guess.header.rows,
                columns=columns,
            )
        )
    return ConfirmedMapping(sheets=tuple(sheets))


def same_mapping(proposed: ConfirmedMapping, truth: ConfirmedMapping) -> list[str]:
    """두 매핑이 다른 곳(관문 검사·평가). 단위는 양식 단위로의 배율로 비교한다(표기 'KRW'·'원'은 같음)."""

    differences = []
    wanted = {s.file_sheet: s for s in truth.sheets}
    for sheet in proposed.sheets:
        other = wanted.get(sheet.file_sheet)
        if other is None or sheet.template != other.template:
            differences.append(f"{sheet.file_sheet}: 양식 시트 {sheet.template} ≠ {other.template if other else None}")
            continue
        if sheet.template is None:
            continue
        if sheet.header_rows != other.header_rows:
            differences.append(f"{sheet.file_sheet}: 머리글 행 {sheet.header_rows} ≠ {other.header_rows}")
        template = SHEET_BY_KEY[sheet.template]
        mine = {c.position: c for c in sheet.columns}
        for column in other.columns:
            got = mine.get(column.position)
            if got is None or got.key != column.key:
                differences.append(
                    f"{sheet.file_sheet}: {column.position}열 항목 {got.key if got else None} ≠ {column.key}"
                )
                continue
            unit = template.column(column.key).unit if column.key else ""
            if unit:
                factor = unit_factor(got.unit, unit) if got.unit else None
                expected = unit_factor(column.unit, unit) if column.unit else None
                if factor != expected:
                    differences.append(f"{sheet.file_sheet}: {column.position}열 단위 {got.unit} ≠ {column.unit}")
    return differences
