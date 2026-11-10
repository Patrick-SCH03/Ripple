"""엑셀 필드 사전(rules/excel_fields.yaml): 시트·열 동의어, 메모성 머리글, 양식에 없는 흔한 머리글, 항목별 상식 범위.

열 자동 매핑의 '사전 일치' 특징과 시트 찾기에 쓰고, 상식 범위는 값 읽기의 이상값 검출(단위 착오)에 쓴다.
읽을 때 확인한다: 시트·열 키가 양식에 있음, 한 시트 안에서 동의어가 두 열에 겹치지 않음(양식 머리글 포함),
양식에 없는 흔한 머리글이 어느 시트의 동의어와도 겹치지 않음, 범위 하한 < 상한.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

import yaml

from ripple.config.settings import PROJECT_ROOT

from .normalize import header_key
from .template import SHEET_BY_KEY

DEFAULT_PATH = PROJECT_ROOT / "rules" / "excel_fields.yaml"


SHAPES = ("id", "code", "text")
"""글자 항목의 값 모양: id(공백 없는 식별자, 숫자나 - : _ / . 를 품음) · code(공백 없는 짧은 표기, 12자 이하) ·
text(공백이나 한글이 있는 글)."""


@dataclass(frozen=True, slots=True)
class FieldInfo:
    synonyms: tuple[str, ...]  # 양식 머리글 + 사전 동의어(원문 표기)
    range: tuple[float, float] | None  # 양식 단위 기준 상식 범위
    shape: str | None = None  # 글자 항목의 값 모양(SHAPES)


@dataclass(frozen=True, slots=True)
class FieldDictionary:
    version: str
    memo_headers: frozenset[str]  # header_key로 정규화
    other_headers: frozenset[str]  # 양식에 없는 흔한 머리글(header_key로 정규화) — 메모성 머리글처럼 '해당 없음' 쪽
    sheet_names: Mapping[str, tuple[str, ...]]  # 양식 시트 키 → 이름들(양식 이름 + 사전 동의어)
    columns: Mapping[tuple[str, str], FieldInfo]  # (양식 시트 키, 열 키) → 정보
    owners: Mapping[str, frozenset[tuple[str, str]]]  # header_key(머리글·동의어) → 그 이름을 쓰는 (시트 키, 열 키)들

    def info(self, sheet: str, key: str) -> FieldInfo:
        return self.columns[(sheet, key)]

    def foreign_sheet(self, sheet: str, names: tuple[str, ...], key: str | None = None) -> str | None:
        """머리글이 이 시트에는 없고 다른 양식 시트 항목의 이름(머리글·동의어)이면 그 시트 키(여럿이면 키 순 첫째).
        제안한 항목 키(key)와 같은 키로 쓰는 시트가 있으면 같은 개념(예: 호선 시트의 '호선' = 다른 시트의
        호선ID)이라 아니다."""
        for name in names:
            owners = self.owners.get(header_key(name), frozenset())
            if owners and all(s != sheet for s, _ in owners) and all(k != key for _, k in owners):
                return min(owners)[0]
        return None

    def common_other(self, names: tuple[str, ...]) -> bool:
        """양식에 없는 흔한 머리글(other_headers)인가."""
        return any(header_key(name) in self.other_headers for name in names)


def load_fields(path: Path = DEFAULT_PATH) -> FieldDictionary:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    sheets_data = data.get("sheets") or {}
    sheet_names: dict[str, tuple[str, ...]] = {}
    columns: dict[tuple[str, str], FieldInfo] = {}
    for key, template in SHEET_BY_KEY.items():
        entry = sheets_data.get(key) or {}
        sheet_names[key] = _unique((template.name, *entry.get("names", ())))
        given = entry.get("columns") or {}
        unknown = set(given) - {c.key for c in template.columns}
        if unknown:
            raise ValueError(f"필드 사전 '{key}' 시트에 양식에 없는 열 있음: {sorted(unknown)}")
        owner: dict[str, str] = {}
        for column in template.columns:
            spec = given.get(column.key) or {}
            synonyms = _unique((column.header, *spec.get("synonyms", ())))
            for synonym in synonyms:
                normalized = header_key(synonym)
                if owner.setdefault(normalized, column.key) != column.key:
                    pair = f"{owner[normalized]}, {column.key}"
                    raise ValueError(f"필드 사전 '{key}' 시트에서 '{synonym}'이(가) 두 열({pair})에 중복")
            bounds = spec.get("range")
            if bounds is not None and (len(bounds) != 2 or not float(bounds[0]) < float(bounds[1])):
                raise ValueError(f"필드 사전 '{key}.{column.key}'의 범위는 [하한, 상한] · 하한 < 상한 필요")
            shape = spec.get("shape")
            if shape is not None and shape not in SHAPES:
                raise ValueError(f"필드 사전 '{key}.{column.key}'의 값 모양은 {', '.join(SHAPES)} 중 하나만 가능")
            columns[(key, column.key)] = FieldInfo(
                synonyms=synonyms,
                range=(float(bounds[0]), float(bounds[1])) if bounds is not None else None,
                shape=shape,
            )
    unknown_sheets = set(sheets_data) - set(SHEET_BY_KEY)
    if unknown_sheets:
        raise ValueError(f"필드 사전에 양식에 없는 시트 있음: {sorted(unknown_sheets)}")
    owners: dict[str, set[tuple[str, str]]] = {}
    for (sheet_key, column_key), info in columns.items():
        for synonym in info.synonyms:
            owners.setdefault(header_key(synonym), set()).add((sheet_key, column_key))
    others = frozenset(header_key(h) for h in data.get("other_headers", ()))
    clash = sorted(f"{h}({'.'.join(min(owners[h]))})" for h in others if h in owners)
    if clash:
        raise ValueError(f"양식에 없는 흔한 머리글이 동의어와 중복: {', '.join(clash)}")
    return FieldDictionary(
        version=str(data["version"]),
        memo_headers=frozenset(header_key(h) for h in data.get("memo_headers", ())),
        other_headers=others,
        sheet_names=MappingProxyType(sheet_names),
        columns=MappingProxyType(columns),
        owners=MappingProxyType({k: frozenset(v) for k, v in owners.items()}),
    )


@lru_cache(maxsize=1)
def default_fields() -> FieldDictionary:
    return load_fields(DEFAULT_PATH)


def _unique(items: tuple[str, ...]) -> tuple[str, ...]:
    seen: dict[str, str] = {}
    for item in items:
        seen.setdefault(header_key(item), str(item))
    return tuple(seen.values())
