"""열 판단 특징(docs/input.md(엑셀 양식) 4절): 파일 열 하나와 양식 열 선택지 하나 → 특징 값.

머리글(필드 사전 동의어 일치·글자 유사도·2글자 조각·낱말·포함·ID 낱말), 단위(같은 차원·충돌·빠짐), 값(그 종류로
읽히는/안 읽히는 비율·상식 범위·정수·숫자 비율, 주 ID 열의 고유값, 다른 시트 ID에 들어 있는 비율, 값 모양 힌트에 맞는
비율), 해당 없음(편향·메모성 머리글·빈 열·순번·머리글 없음·가장 비슷한 항목의 유사도).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from .fields import FieldDictionary
from .file_columns import FileColumn, References, check_values
from .normalize import header_key, unit_factor
from .template import ID_COLUMNS, REFERENCES, Column, Kind, Sheet
from .values import LIST_SPLIT

SEQUENCE_MIN = 3  # 순번 열로 보려면 이만큼의 값이 1, 2, 3, … 이어야 함
ID_WORDS = ("id", "no", "번호", "코드", "code", "cd", "num", "number")  # 머리글이 이 말로 끝나면 식별자 열로 보임
CODE_LENGTH = 12  # 값 모양 code의 최대 글자 수


def _grams(text: str) -> frozenset[str]:
    return frozenset(text[i : i + 2] for i in range(len(text) - 1)) or frozenset({text})


def _tokens(text: str) -> frozenset[str]:
    return frozenset(t for t in re.split(r"[^0-9a-z가-힣]+", text.casefold()) if t)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


@dataclass(frozen=True, slots=True)
class _Name:
    key: str  # header_key
    tokens: frozenset[str]
    grams: frozenset[str]

    @staticmethod
    def of(text: str) -> _Name:
        key = header_key(text)
        return _Name(key, _tokens(text), _grams(key))


class Featurizer:
    """필드 사전(동의어·메모성 머리글·상식 범위)으로 선택지별 특징을 만든다."""

    def __init__(self, fields: FieldDictionary) -> None:
        self.fields = fields
        self._synonyms: dict[tuple[str, str], tuple[_Name, ...]] = {
            key: tuple(_Name.of(s) for s in info.synonyms) for key, info in fields.columns.items()
        }

    def bounds(self, sheet: Sheet, key: str) -> tuple[float, float] | None:
        return self.fields.info(sheet.key, key).range

    def option(
        self, sheet: Sheet, column: Column, file_column: FileColumn, references: References | None = None
    ) -> dict[str, float]:
        features = self._header(sheet, column, file_column)
        if _id_word(file_column):
            features["id_word" if _id_like(sheet, column) else "id_word_other"] = 1.0
        unit = file_column.unit
        if unit is not None:
            same = bool(column.unit) and unit_factor(unit, column.unit) is not None
            features["unit_same" if same else "unit_conflict"] = 1.0
        elif column.unit:
            features["unit_absent"] = 1.0
        factor = (unit_factor(unit, column.unit) if unit is not None and column.unit else None) or 1.0
        check = check_values(column, file_column, factor, self.bounds(sheet, column.key))
        if not check.filled:
            features["empty"] = 1.0
            return features
        features[f"parse:{column.kind.value}"] = check.parsed / check.filled
        features["parse_fail"] = 1 - check.parsed / check.filled
        features["parse_all"] = float(check.all_parsed)
        if column.kind in (Kind.INT, Kind.FLOAT) and check.parsed:
            features["range_out"] = float(not check.all_in_range)
            if column.kind is Kind.INT:
                features["integral"] = check.integral / check.parsed
        if column.kind is Kind.TEXT:
            features["text_numeric"] = check.numeric / check.filled
        texts = [str(v).strip() for v in file_column.filled]
        if ID_COLUMNS.get(sheet.key) == column.key:
            features["pk_unique"] = len(set(texts)) / len(texts)
        target = REFERENCES.get(column.key)
        if target is not None and target != sheet.key and references and target in references:
            items = [i.strip() for t in texts for i in (LIST_SPLIT.split(t) if column.kind is Kind.LIST else [t])]
            items = [i for i in items if i]
            cover = sum(i in references[target] for i in items) / len(items) if items else 0.0
            features["ref_cover"] = cover
            features["ref_miss"] = 1 - cover
        shape = self.fields.info(sheet.key, column.key).shape
        if shape is not None:
            fit = sum(_fits(shape, t) for t in texts) / len(texts)
            features["shape_fit"] = fit
            features["shape_miss"] = 1 - fit
        return features

    def _header(self, sheet: Sheet, column: Column, file_column: FileColumn) -> dict[str, float]:
        names = [_Name.of(n) for n in file_column.names]
        if not names:
            return {"no_header": 1.0}
        synonyms = self._synonyms[(sheet.key, column.key)]
        ratio = bigram = token = 0.0
        matched = contains = False
        for name in names:
            for synonym in synonyms:
                matched = matched or name.key == synonym.key
                ratio = max(ratio, SequenceMatcher(None, name.key, synonym.key).ratio())
                bigram = max(bigram, _jaccard(name.grams, synonym.grams))
                token = max(token, _jaccard(name.tokens, synonym.tokens))
                shorter, longer = sorted((name.key, synonym.key), key=len)
                contains = contains or (len(shorter) >= 2 and shorter in longer)
        features = {"ratio": ratio, "bigram": bigram, "token": token}
        if matched:
            features["dict"] = 1.0
        if contains:
            features["contains"] = 1.0
        return features

    def none(self, file_column: FileColumn, best_ratio: float) -> dict[str, float]:
        features = {"none": 1.0, "none_best": best_ratio}
        if not file_column.names:
            features["none_no_header"] = 1.0
        elif any(
            header_key(n) in self.fields.memo_headers or header_key(n) in self.fields.other_headers
            for n in file_column.names
        ):
            features["none_memo"] = 1.0  # 메모성 머리글과 양식에 없는 흔한 머리글은 같은 특징(해당 없음 쪽)
        filled = file_column.filled
        if not filled:
            features["none_empty"] = 1.0
        elif _sequence(filled):
            features["none_seq"] = 1.0
        return features


def _id_word(file_column: FileColumn) -> bool:
    return any(header_key(n).endswith(ID_WORDS) for n in file_column.names)


def _id_like(sheet: Sheet, column: Column) -> bool:
    """식별자 항목: 시트의 ID 열, 다른 시트 ID를 가리키는 열, 번호(_no)·ID(_id) 항목."""
    key = column.key
    return ID_COLUMNS.get(sheet.key) == key or key in REFERENCES or key.endswith(("_id", "_no"))


_ID_MARK = re.compile(r"[0-9\-:_/.]")
_HANGUL = re.compile(r"[가-힣]")


def _fits(shape: str, text: str) -> bool:
    """값 모양 힌트(fields.SHAPES)에 맞는가."""
    spaced = any(ch.isspace() for ch in text)
    if shape == "id":
        return not spaced and len(text) >= 2 and bool(_ID_MARK.search(text))
    if shape == "code":
        return not spaced and len(text) <= CODE_LENGTH
    return spaced or bool(_HANGUL.search(text))


def _sequence(values: Sequence[object]) -> bool:
    """1, 2, 3, … 순번(행 번호 열)."""
    numbers = [v for v in values if isinstance(v, int) and not isinstance(v, bool)]
    return len(numbers) == len(values) >= SEQUENCE_MIN and numbers == list(range(numbers[0], numbers[0] + len(numbers)))
