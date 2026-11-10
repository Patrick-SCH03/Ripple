"""사전 별칭 찾기: 정확 일치(긴 별칭 먼저, 겹치지 않게, 경계 규칙)와 오타 허용 일치(Hit.fuzzy)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .text import Span, free

_PARTICLE_START = "을를이가은는의에도만과와으로들랑"
_HANGUL = re.compile(r"[가-힣]")
_HANGUL_RUN = re.compile(r"[가-힣]+")


@dataclass(frozen=True, slots=True)
class Hit:
    start: int
    end: int
    value: str  # 사전의 표준 이름(부재 종류·블록 단어·계통·밸브 종류)
    fuzzy: bool = False  # 오타 허용 일치(결정적 일치가 아님)


def fuzzy_aliases(text: str, table: Mapping[str, Iterable[str]], occupied: Sequence[Span] = ()) -> list[Hit]:
    """오타 허용 일치: 남은 한글 덩어리의 앞부분이 한글 별칭과 거의 같으면(3자 이상은 편집 거리 1 — 빠짐·
    겹침·바뀜·뒤바뀜, 2자는 두 글자 뒤바뀜만) 그 별칭으로 본다. 2자 별칭은 뒤에 조사만 올 수 있다.
    결정적 일치가 아니므로 Hit.fuzzy로 표시한다.
    """
    aliases = [(a, n) for n, group in table.items() for a in group if len(a) >= 2 and re.fullmatch(r"[가-힣]+", a)]
    hits: list[Hit] = []
    for run in _HANGUL_RUN.finditer(text):
        if not free(run.span(), occupied):
            continue
        word = run.group(0)
        best: tuple[int, int, str, int] | None = None  # (거리, -별칭 길이, 이름, 조각 길이)
        for alias, name in aliases:
            for size in sorted({len(alias) - 1, len(alias), len(alias) + 1}):
                if size < 2 or size > len(word):
                    continue
                piece, rest = word[:size], word[size:]
                if len(alias) == 2 and (rest and rest[0] not in _PARTICLE_START):
                    continue
                distance = _distance(piece, alias)
                if piece == alias or distance > 1 or (len(alias) == 2 and piece != alias[::-1]):
                    continue
                candidate = (distance, -len(alias), name, size)
                if best is None or candidate < best:
                    best = candidate
        if best is not None:
            hits.append(Hit(run.start(), run.start() + best[3], best[2], fuzzy=True))
    return hits


def _distance(a: str, b: str) -> int:
    """제한된 다메라우-레벤슈타인 거리(인접 두 글자 뒤바뀜을 1로 센다)."""
    rows = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        rows[i][0] = i
    for j in range(len(b) + 1):
        rows[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            rows[i][j] = min(rows[i - 1][j] + 1, rows[i][j - 1] + 1, rows[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                rows[i][j] = min(rows[i][j], rows[i - 2][j - 2] + 1)
    return rows[len(a)][len(b)]


def find_aliases(
    text: str, table: Mapping[str, Iterable[str]], occupied: Sequence[Span] = (), *, kind_words: bool = False
) -> list[Hit]:
    """사전 별칭 찾기(긴 별칭 먼저, 겹치지 않게, 대소문자 무시).

    영문·숫자 별칭은 앞뒤가 영문·숫자가 아니어야 한다(종류 단어는 뒤에 번호가 바로 붙어도 됨: 'PL7').
    한 글자 한글 별칭은 뒤에 한글이 오면 조사일 때만 받고, 종류 단어가 아니면 앞에도 한글이 없어야
    한다('좌굴'의 '좌'는 좌현이 아님, '판단'의 '판'은 판이 아님).
    """
    pairs = sorted(((alias, name) for name, aliases in table.items() for alias in aliases), key=lambda p: -len(p[0]))
    hits: list[Hit] = []
    taken = list(occupied)
    for alias, name in pairs:
        for match in re.finditer(_alias_pattern(alias, kind_words), text, flags=re.IGNORECASE):
            span = match.span()
            if free(span, taken):
                hits.append(Hit(span[0], span[1], name))
                taken.append(span)
    return sorted(hits, key=lambda h: h.start)


def find_tagged[Tag: str](
    text: str,
    tables: Sequence[tuple[Tag, Mapping[str, Iterable[str]], bool]],
    occupied: Sequence[Span],
) -> list[tuple[Hit, Tag]]:
    """여러 표의 별칭을 한 번에 찾는다: 긴 별칭이 먼저 자리를 잡고(같은 길이면 표 순서),
    경계 규칙은 표마다(종류 단어 여부) 따른다. 값은 (별칭 이름, 표 종류).
    find_aliases의 규칙을 표 사이에도 적용한 것이다.
    """
    entries = [
        (alias, name, tag, kind_words)
        for tag, table, kind_words in tables
        for name, aliases in table.items()
        for alias in aliases
    ]
    entries.sort(key=lambda e: -len(e[0]))  # 안정 정렬: 같은 길이는 표 순서
    hits: list[tuple[Hit, Tag]] = []
    taken = list(occupied)
    for alias, name, tag, kind_words in entries:
        for match in re.finditer(_alias_pattern(alias, kind_words), text, flags=re.IGNORECASE):
            span = match.span()
            if free(span, taken):
                hits.append((Hit(span[0], span[1], name), tag))
                taken.append(span)
    return sorted(hits, key=lambda h: h[0].start)


def _alias_pattern(alias: str, kind_words: bool) -> str:
    body = r"\s?".join(re.escape(part) for part in alias.split())
    if not _HANGUL.search(alias):
        tail = r"(?![A-Za-z])" if kind_words else r"(?![A-Za-z0-9])"
        return rf"(?<![A-Za-z0-9]){body}{tail}"
    if len(alias) == 1:
        left = "" if kind_words else r"(?<![가-힣])"
        return rf"{left}{body}(?:(?![가-힣])|(?=[{_PARTICLE_START}]))"
    return body
