"""표 찾기(결정적, 제안만 함): 파일 시트마다 양식 시트(또는 읽지 않음)와 머리글 행을 제안하고 확실한지 적는다.

확실하지 않으면 열 확인 화면에서 사람이 명시적으로 고른다(docs/input.md(엑셀 양식) 4절). 열 매핑의 자동 진행
자격(ready)은 시트·머리글이 확실할 때만 있다.

- 머리글 칸이 양식 열과 맞는다: 단위를 뺀 이름이 양식 머리글이나 필드 사전 동의어와 같다(공백·문장부호·대소문자 무시).
- 머리글 행: 앞 10행(빈 행 제외)에서 맞는 칸이 가장 많은 행(두 줄 후보 포함). 두 줄 후보는 두 행이 모두 글자뿐이고
  위 칸이 빈 자리에 아래 칸 글자가 있을 때(묶음 아래 칸)만 세고(위 행이 한 칸뿐이면 표 제목이라 세지 않음), 위 행에서
  맞지 않던 자리의 아래 칸 일치를 더한다.
  확실하려면 겹치지 않는 다른 후보보다 맞는 칸이 2개 이상 많아야 하고(다른 후보가 하나도 안 맞으면 1개), 한 줄로
  골랐는데 바로 아래 행과 두 줄 머리글 모양이면 확실하지 않다.
- 양식 시트: 머리글 일치(정밀도·재현율의 조화 평균) + 시트 이름(양식 이름·사전 동의어와 같으면 0.5, 그 이름을 품으면
  0.3)으로 점수를 매겨, 양식 시트마다 파일 시트 하나만 배정한다. '양식 안내' 시트와 빈 시트는 읽지 않음(확실).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .fields import FieldDictionary
from .mapping import header_cells, is_guide
from .normalize import header_key, split_unit
from .template import SHEETS, Sheet
from .workbook import RawSheet

HEADER_SCAN = 10  # 머리글을 찾을 앞 행 수(빈 행 제외)
HEADER_MARGIN = 2  # 머리글 후보와 겹치지 않는 다음 후보의 맞는 칸 수 차가 이보다 작으면 확실하지 않음
NAME_BONUS = 0.5  # 시트 이름이 양식 이름·사전 동의어와 같을 때 더하는 점수
NAME_PART_BONUS = 0.3  # 시트 이름이 양식 이름·사전 동의어(두 글자 이상)를 품을 때(예: '업체 목록' ⊃ '업체')
SHEET_CERTAIN = 0.6  # 이 점수 이상이고 2위와 SHEET_MARGIN 이상 차이 나면 확실
SHEET_MARGIN = 0.25
SHEET_FLOOR = 0.3  # 이 점수 미만이면 '읽지 않음'을 제안(확실하지 않음)


@dataclass(frozen=True, slots=True)
class HeaderGuess:
    rows: tuple[int, ...]  # 머리글 행(엑셀 행 번호)
    matched: int  # 양식 열과 맞는 칸 수
    certain: bool


@dataclass(frozen=True, slots=True)
class SheetGuess:
    file_sheet: str
    template: str | None  # 제안한 양식 시트 키(None = 읽지 않음)
    candidates: tuple[str, ...]  # 양식 시트 후보(점수 순)
    certain: bool
    header: HeaderGuess | None
    reasons: tuple[str, ...]  # 확실하지 않은 이유(화면 문구)


class HeaderIndex:
    """양식 시트마다 '정규화한 이름(양식 머리글·사전 동의어) → 열 키'."""

    def __init__(self, fields: FieldDictionary) -> None:
        self.fields = fields
        self._by_sheet = {
            sheet.key: {
                header_key(name): column.key
                for column in sheet.columns
                for name in fields.info(sheet.key, column.key).synonyms
            }
            for sheet in SHEETS
        }
        self._names = {
            sheet.key: {header_key(n) for n in fields.sheet_names.get(sheet.key, (sheet.name,))} for sheet in SHEETS
        }

    def key(self, sheet: Sheet, text: object) -> str | None:
        """머리글 칸이 맞는 양식 열 키(단위를 뺀 이름이 양식 머리글·사전 동의어와 같을 때). 없으면 None."""
        if text is None or not str(text).strip():
            return None
        return self._by_sheet[sheet.key].get(header_key(split_unit(text)[0]))

    def name_bonus(self, sheet: Sheet, name: str) -> float:
        wanted = header_key(name)
        if wanted in self._names[sheet.key]:
            return NAME_BONUS
        if any(len(n) >= 2 and n in wanted for n in self._names[sheet.key]):
            return NAME_PART_BONUS
        return 0.0


def guess_header(raw: RawSheet, sheet: Sheet, index: HeaderIndex) -> HeaderGuess | None:
    """머리글 행 제안. 맞는 칸이 하나도 없으면 None."""
    following = {number: cells for number, cells in raw.rows}
    scored: list[tuple[int, int, tuple[int, ...]]] = []  # (맞는 칸 수, 두 줄이 새 일치를 더하면 1·아니면 -1, 행들)
    for number, cells in raw.rows[:HEADER_SCAN]:
        top = [index.key(sheet, c) for c in cells]
        found = {k for k in top if k}
        scored.append((len(found), 0, (number,)))
        below = following.get(number + 1)
        if below is None or not stacked(cells, below):
            continue
        extra = {key for i, c in enumerate(below) if (i >= len(top) or top[i] is None) and (key := index.key(sheet, c))}
        scored.append((len(found | extra), 1 if extra - found else -1, (number, number + 1)))
    scored.sort(key=lambda s: (-s[0], -s[1], s[2]))
    if not scored or scored[0][0] == 0:
        return None
    best = scored[0]
    rivals = [s for s in scored[1:] if not set(s[2]) & set(best[2])]
    runner_up = rivals[0][0] if rivals else 0
    certain = best[0] - runner_up >= (HEADER_MARGIN if runner_up else 1)
    if len(best[2]) == 1:
        below = following.get(best[2][0] + 1)
        certain = certain and not (below is not None and stacked(following[best[2][0]], below))
    return HeaderGuess(rows=best[2], matched=best[0], certain=certain)


def stacked(top: Sequence[object], bottom: Sequence[object]) -> bool:
    """두 행이 두 줄 머리글 모양인가: 채운 칸이 모두 글자이고, 위 칸이 빈 자리에 아래 칸 글자가 있다(묶음 아래 칸).

    위 행에 칸이 하나뿐이면 표 제목('블록 목록', '발주 품목 (단위: 천원)')으로 보고 두 줄 머리글이 아니다 —
    위 줄로 잡으면 모든 열 이름 앞에 제목이 붙는다. 제목 행은 머리글 위 '읽지 않은 행'이 되고 그 속 단위 안내는
    그대로 본다(unit_notes)."""
    filled = [c for c in (*top, *bottom) if c is not None and str(c).strip()]
    if not filled or not all(isinstance(c, str) for c in filled):
        return False
    if sum(1 for c in top if c is not None and str(c).strip()) < 2:
        return False
    return any(
        (i >= len(top) or top[i] is None or not str(top[i]).strip()) and value is not None and str(value).strip()
        for i, value in enumerate(bottom)
    )


def guess_sheets(raw: Mapping[str, RawSheet], index: HeaderIndex) -> list[SheetGuess]:
    """파일 시트마다 양식 시트·머리글 행 제안. 양식 시트 하나에 파일 시트 하나만 배정한다(점수 높은 시트 먼저)."""
    scores = _sheet_scores(raw, index)
    taken: dict[str, str] = {}
    for name, options in sorted(scores.items(), key=lambda item: (-item[1][0][0], item[0])):
        for score, key, _ in options:
            if score < SHEET_FLOOR:
                break
            if key not in taken.values():
                taken[name] = key
                break
    guesses = []
    for name in raw:
        if name not in scores:
            guesses.append(SheetGuess(name, None, (), True, None, ()))  # 양식 안내·빈 시트
            continue
        options = scores[name]
        chosen = taken.get(name)
        candidates = tuple(key for score, key, _ in options[:3] if score >= SHEET_FLOOR)
        header = next((h for _, key, h in options if key == chosen), None) if chosen else None
        top_score = options[0][0]
        second = options[1][0] if len(options) > 1 else 0.0
        reasons: list[str] = []
        if chosen is None:
            certain = False
            reasons.append("양식 시트와 맞는 머리글 적음 · 읽을 시트면 양식 시트 선택")
        elif options[0][1] != chosen:
            certain = False
            reasons.append("같은 양식 시트로 보이는 시트 둘 이상 · 맞는 양식 시트 선택")
        else:
            certain = top_score >= SHEET_CERTAIN and top_score - second >= SHEET_MARGIN
            if not certain:
                reasons.append("어느 양식 시트인지 불확실 · 맞는 양식 시트 선택")
        if chosen is not None and (header is None or not header.certain):
            certain = False
            reasons.append("머리글 행 불확실 · 미리보기에서 머리글 행 선택")
        guesses.append(SheetGuess(name, chosen, candidates, certain, header, tuple(reasons)))
    return guesses


def _sheet_scores(
    raw: Mapping[str, RawSheet], index: HeaderIndex
) -> dict[str, list[tuple[float, str, HeaderGuess | None]]]:
    scores: dict[str, list[tuple[float, str, HeaderGuess | None]]] = {}
    for name, sheet_raw in raw.items():
        if is_guide(name) or not sheet_raw.rows:
            continue
        options = []
        for sheet in SHEETS:
            header = guess_header(sheet_raw, sheet, index)
            score = _header_score(sheet_raw, sheet, header) + index.name_bonus(sheet, name)
            options.append((round(score, 6), sheet.key, header))
        options.sort(key=lambda o: (-o[0], o[1]))
        scores[name] = options
    return scores


def _header_score(raw: RawSheet, sheet: Sheet, header: HeaderGuess | None) -> float:
    """머리글 일치의 조화 평균: 정밀도(머리글 칸 중 맞는 칸) · 재현율(양식 열 중 찾은 열)."""
    if header is None:
        return 0.0
    cells = [c for c in header_cells(raw, header.rows) if c is not None]
    if not cells:
        return 0.0
    precision = min(1.0, header.matched / len(cells))
    recall = header.matched / len(sheet.columns)
    return 2 * precision * recall / (precision + recall)


def column_texts(raw: RawSheet, rows: Sequence[int]) -> tuple[tuple[str | None, ...], tuple[str | None, ...]]:
    """(합친 머리글, 자기 칸 머리글) — 두 줄 머리글이면 묶음 이름을 붙인 이름과 그 열 칸의 이름을 따로 본다."""
    merged = header_cells(raw, rows)
    if len(rows) == 1:
        return merged, merged
    found = {number: cells for number, cells in raw.rows}
    top, bottom = found.get(rows[0], ()), found.get(rows[1], ())
    own: list[str | None] = []
    for i in range(len(merged)):
        lower = bottom[i] if i < len(bottom) else None
        upper = top[i] if i < len(top) else None
        value = lower if lower is not None and str(lower).strip() else upper
        own.append(" ".join(str(value).split()) if value is not None and str(value).strip() else None)
    return merged, tuple(own)
