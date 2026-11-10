"""열 자동 매핑(판단 계층 열 문, docs/input.md(엑셀 양식) 4절): 파일 열 하나 → 양식 시트의 열 또는 해당 없음.

- 정확 일치(단위를 뺀 머리글이 양식 머리글과 같음 — 두 줄 머리글이면 합친 이름 먼저, 그다음 그 열 칸 이름)는 판단 밖에서
  바로 정한다(ColumnMethod.EXACT, 보정 밖). 정확 일치로 정해진 항목은 다른 열의 선택지에서 뺀다.
- 그 밖의 열은 질문 하나(선택지 = 남은 양식 열 + 해당 없음)로 점수기 → 온도 → 자동 진행 문턱·되묻기 집합을 거친다.
- 특징: 머리글(필드 사전 동의어 일치·글자 유사도·2글자 조각·낱말·포함·ID 낱말), 단위(같은 차원·충돌·빠짐), 값(앞
  40행이 그 종류로 읽히는/안 읽히는 비율·상식 범위·정수·숫자 비율, 주 ID 열의 고유값, 다른 시트 ID를 가리키는 열이면 그
  시트 ID에 들어 있는 비율, 필드 사전 값 모양 힌트에 맞는 비율), 해당 없음(편향·메모성 머리글·빈 열·순번·머리글 없음·
  가장 비슷한 항목의 유사도).
- 다른 시트의 ID 목록(reference_sets)은 그 시트 ID 열의 머리글이 양식 머리글·사전 동의어와 같을 때만 모은다(짐작 없음).
- 단위 상태(unit_state)와 자동 진행 자격(ready, 정답을 보지 않음)은 보정·라우터·평가가 같은 함수를 쓴다.

파일 열 읽기·단위 상태·값 검사는 file_columns.py, 특징은 column_features.py에 있다(검사·보정 스크립트가 쓰는 이름은
여기서도 import된다).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ripple.contracts.decision import NONE_OPTION, ChoiceQuestion, DecisionTopic, Option
from ripple.contracts.ingest import ColumnMethod, UnitState
from ripple.decide.calibration import softmax
from ripple.decide.scorer import Features, scores

from .column_features import Featurizer
from .fields import FieldDictionary
from .file_columns import (
    FileColumn,
    References,
    check_values,
    exact_key,
    read_columns,
    unit_state,
)
from .mapping import data_rows, unit_notes
from .tables import HeaderIndex, SheetGuess
from .template import ID_COLUMNS, SHEET_BY_KEY, Column, Sheet
from .workbook import RawSheet

__all__ = [
    "ColumnCase",
    "ColumnJudgment",
    "Featurizer",
    "FileColumn",
    "References",
    "SheetJudgment",
    "column_case",
    "exact_key",
    "judge_sheet",
    "read_columns",
    "ready_values",
    "reference_sets",
    "unit_state",
]


def reference_sets(
    raw: Mapping[str, RawSheet], guesses: Sequence[SheetGuess], index: HeaderIndex
) -> dict[str, frozenset[str]]:
    """양식 시트마다 그 시트 ID 열의 값(모든 데이터 행). ID 열은 머리글이 양식 머리글·사전 동의어와 같을 때만 찾는다."""
    found: dict[str, frozenset[str]] = {}
    for guess in guesses:
        if guess.template is None or guess.header is None or guess.template not in ID_COLUMNS:
            continue
        sheet, id_key = SHEET_BY_KEY[guess.template], ID_COLUMNS[guess.template]
        sheet_raw = raw[guess.file_sheet]
        column = next(
            (
                fc
                for fc in read_columns(sheet_raw, guess.header.rows)
                if exact_key(sheet, fc) == id_key or any(index.key(sheet, n) == id_key for n in fc.names)
            ),
            None,
        )
        if column is None:
            continue
        data, _ = data_rows(sheet_raw, guess.header.rows)
        values = (cells[column.position] for _, cells in data if column.position < len(cells))
        found[guess.template] = frozenset(str(v).strip() for v in values if v is not None and str(v).strip())
    return found


# ---------- 시트 하나의 판단 ----------


@dataclass(frozen=True, slots=True)
class ColumnCase:
    """판단 대상 열 하나: 질문과 선택지별 특징(question.options와 같은 순서)."""

    file_column: FileColumn
    question: ChoiceQuestion
    features: tuple[Features, ...]

    def scores(self, weights: Mapping[str, float]) -> dict[str, float]:
        return scores(weights, self.question.option_ids, self.features)


@dataclass(slots=True)
class ColumnJudgment:
    """열 하나의 판단(정확 일치 또는 판단 계층)과 제안."""

    file_column: FileColumn
    method: ColumnMethod
    top: str | None  # 정확 일치 항목 또는 점수 최상위(None = 해당 없음)
    case: ColumnCase | None = None
    score_map: Mapping[str, float] | None = None
    key: str | None = None  # 제안(시트 안 배타 배정 뒤)
    conflict: bool = False  # 최상위 항목이 같은 시트 다른 열의 최상위와 겹침
    unit_state: UnitState = UnitState.NOT_NEEDED
    unit: str | None = None
    factor: float | None = None
    problems: list[str] = field(default_factory=list)
    ready: bool = False


@dataclass(frozen=True, slots=True)
class SheetJudgment:
    sheet: Sheet
    columns: tuple[ColumnJudgment, ...]


def judge_sheet(
    sheet: Sheet,
    raw: RawSheet,
    header_rows: Sequence[int],
    certain: bool,
    featurizer: Featurizer,
    weights: Mapping[str, float],
    temperature: float = 1.0,
    question_prefix: str = "",
    references: References | None = None,
) -> SheetJudgment:
    """시트 하나의 모든 열: 정확 일치 → 나머지 열 질문·점수 → 시트 안 배타 배정 → 단위 상태 → 자격.

    certain: 시트·머리글 행이 확실한가(표 찾기). 아니면 어떤 열도 자동 진행 자격이 없다.
    references: 다른 시트 ID 목록(reference_sets). 없으면 참조 특징을 쓰지 않는다.
    """
    file_columns = read_columns(raw, header_rows)
    noted = bool(unit_notes(raw, header_rows))  # 제목·메모 행의 단위 표기 → 지정 양식 관례를 쓰지 않음
    judgments, exact_keys = _tops(sheet, file_columns, featurizer, weights, question_prefix, references)
    judgments.sort(key=lambda j: j.file_column.position)
    _assign(judgments, temperature)
    decided_tops = [j.top for j in judgments if j.method is ColumnMethod.DECIDED and j.top]
    by_key = {c.key: c for c in sheet.columns}
    for j in judgments:
        if j.method is ColumnMethod.EXACT:
            j.conflict = exact_keys[j.top or ""] > 1
            if j.conflict:
                j.problems.append("같은 항목으로 읽히는 열 둘 이상")
        else:
            j.conflict = j.top is not None and decided_tops.count(j.top) > 1
            if j.conflict:
                j.problems.append("다른 열과 같은 항목으로 보임")
        if j.key is None:
            j.unit_state, j.unit, j.factor = UnitState.NOT_NEEDED, None, None
            j.ready = certain and not j.conflict
            continue
        column = by_key[j.key]
        j.unit_state, j.unit, j.factor, problem = unit_state(
            column, j.file_column, j.method is ColumnMethod.EXACT, noted
        )
        if problem:
            j.problems.append(problem)
        j.ready = certain and not j.conflict and ready_values(sheet, column, j, featurizer)
        if j.method is ColumnMethod.DECIDED:
            _guard(sheet, j, featurizer.fields)
    return SheetJudgment(sheet, tuple(judgments))


def _tops(
    sheet: Sheet,
    file_columns: Sequence[FileColumn],
    featurizer: Featurizer,
    weights: Mapping[str, float],
    question_prefix: str,
    references: References | None,
) -> tuple[list[ColumnJudgment], dict[str, int]]:
    """정확 일치 열(항목마다 몇 열인지 함께)과, 남은 항목을 선택지로 점수 낸 판단 열(정확 일치 열 뒤에)."""
    judgments: list[ColumnJudgment] = []
    exact_keys: dict[str, int] = {}
    rest: list[FileColumn] = []
    for fc in file_columns:
        key = exact_key(sheet, fc)
        if key is None:
            rest.append(fc)
            continue
        exact_keys[key] = exact_keys.get(key, 0) + 1
        judgments.append(ColumnJudgment(fc, ColumnMethod.EXACT, key, key=key))
    taken = set(exact_keys)
    for fc in rest:
        if taken >= {c.key for c in sheet.columns}:
            judgments.append(ColumnJudgment(fc, ColumnMethod.DECIDED, None))  # 남은 양식 항목이 없음 → 해당 없음
            continue
        case = column_case(sheet, fc, taken, featurizer, f"{question_prefix}{sheet.key}:{fc.position}", references)
        score_map = case.scores(weights)
        top = max(sorted(score_map), key=lambda k: score_map[k])
        judgments.append(ColumnJudgment(fc, ColumnMethod.DECIDED, None if top == NONE_OPTION else top, case, score_map))
    return judgments, exact_keys


def _guard(sheet: Sheet, j: ColumnJudgment, fields: FieldDictionary) -> None:
    """점수가 높아도 사람이 확인할 판단 열: 다른 시트 항목 이름(발주 시트의 '자재코드')과
    양식에 없는 흔한 머리글이 어떤 항목으로 제안된 경우(수량 열이 없는 시트의 '미납수량')."""
    names = j.file_column.names
    foreign = fields.foreign_sheet(sheet.key, names, j.key)
    if foreign is not None:
        j.problems.append(f"'{SHEET_BY_KEY[foreign].name}' 시트 항목 이름 · 이 시트에 맞는지 확인")
        j.ready = False
    elif fields.common_other(names):
        j.problems.append("양식에 없는 흔한 머리글(납기·미납·금액 등) · 이 항목이 맞는지 확인")
        j.ready = False


def column_case(
    sheet: Sheet,
    fc: FileColumn,
    taken: set[str],
    featurizer: Featurizer,
    question_id: str,
    references: References | None = None,
) -> ColumnCase:
    columns = [c for c in sheet.columns if c.key not in taken]
    features: list[Features] = [featurizer.option(sheet, c, fc, references) for c in columns]
    best = max((f.get("ratio", 0.0) for f in features), default=0.0)
    features.append(featurizer.none(fc, best))
    question = ChoiceQuestion(
        question_id=question_id,
        topic=DecisionTopic.EXCEL_COLUMN,
        mention=fc.header or f"{fc.position + 1}번째 열",
        options=(
            *(Option(option_id=c.key, label=c.title) for c in columns),
            Option(option_id=NONE_OPTION, label="해당 없음(읽지 않음)"),
        ),
    )
    return ColumnCase(fc, question, tuple(features))


def ready_values(sheet: Sheet, column: Column, judgment: ColumnJudgment, featurizer: Featurizer) -> bool:
    """값 쪽 자격: 단위가 정해졌고(필요 없음·확인됨), 앞 40행이 모두 그 종류로 읽히고, 상식 범위 밖 값이 없다."""
    if judgment.unit_state is UnitState.UNRESOLVED or judgment.factor is None:
        return False
    check = check_values(column, judgment.file_column, judgment.factor, featurizer.bounds(sheet, column.key))
    return check.all_parsed and check.all_in_range


def _assign(judgments: list[ColumnJudgment], temperature: float) -> None:
    """시트 안 배타 배정. 정확 일치 항목과, 최상위가 다른 판단 열과 겹치지 않는 판단 열은 그 항목으로 정한다.
    최상위가 겹치는 판단 열끼리만 남은 항목에서 확률이 큰 (열, 항목) 쌍부터 겹치지 않게 고르고, 남으면 해당 없음.
    겹치는 열은 자격이 없으므로(충돌) 이 배정은 화면에 미리 채울 제안일 뿐이다."""
    tops = Counter(j.top for j in judgments if j.method is ColumnMethod.DECIDED and j.top)
    used = {j.top for j in judgments if j.method is ColumnMethod.EXACT and j.top}
    contested: list[int] = []
    for index, j in enumerate(judgments):
        if j.method is not ColumnMethod.DECIDED:
            continue
        if j.top is None or tops[j.top] == 1:
            j.key = j.top
            if j.top is not None:
                used.add(j.top)
        else:
            contested.append(index)
    pairs: list[tuple[float, int, str]] = []
    for index in contested:
        score_map = judgments[index].score_map or {}
        ids = sorted(score_map)
        for option, p in zip(ids, softmax([score_map[i] for i in ids], temperature), strict=True):
            pairs.append((p, index, option))
    done: set[int] = set()
    for _p, index, option in sorted(pairs, key=lambda x: (-x[0], x[1], x[2])):
        if index in done or (option != NONE_OPTION and option in used):
            continue
        done.add(index)
        judgments[index].key = None if option == NONE_OPTION else option
        if option != NONE_OPTION:
            used.add(option)
