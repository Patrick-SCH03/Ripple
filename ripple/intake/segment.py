"""규칙 분할과 문서 머리글 읽기(순수 계산).

문서를 줄·글머리표·번호·문장 끝·', 그리고'로 나눈다. '라벨: 값' 꼴의 머리 줄(ECN 번호·제목·개정·요청자·요청일·사유)과
설계변경 번호만 담은 안내 줄('설계변경 2026-034 건 아래 내용 반영 부탁드립니다')은 머리 정보로 읽고 항목에서 뺀다.
표 행('1 | 변경 내용 | 비고')은 칸마다 나누고 숫자 없는 머리 행은 건너뛴다. 번호·글머리표 목록 안에서 표시 없이 이어지는
줄은 앞 항목이 문장으로 끝나지 않았으면 그 항목의 이어지는 줄로 본다(줄바꿈으로 갈린 한 항목).
위치는 정규화한 원문 기준이다(줄바꿈만 \\n으로 맞춘다 — 글자 수가 같은 변환만 한다).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ripple.contracts.intake import IntakeHeader

_BULLET = re.compile(r"^\s*(?:[-•·*▶▷○●◦■□▪]|\(?\d{1,3}[.)](?!\d)|[①-⑳]|[가-하][.)]|\d{1,3}\s*\))\s*")
"""줄 머리 글머리표·번호('1.'·'(2)'·'가)'). 소수('12.5mm')의 '12.'는 번호가 아니다."""
_SENTENCE_END = re.compile(r"(?<=[다요음함됨임])\.\s+|;\s*|(?<=[다요])\s{2,}|,?\s*그리고\s+")
_LABEL_VALUE = re.compile(r"^\s*(?P<label>[^:：\n]{1,24}?)\s*[:：]\s*(?P<value>\S.*?)\s*$")

_HEADER_LABELS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ecn_ref",
        re.compile(r"^(?:ECN|EC|DCN|ECO)\s*(?:No\.?|NO\.?|번호|#)?$|^(?:설계\s*변경|설변|문서|변경)\s*번호$", re.I),
    ),
    ("title", re.compile(r"^(?:제목|건명|Subject|Title)$", re.I)),
    ("revision", re.compile(r"^(?:Rev(?:ision)?\.?|개정(?:\s*번호)?)$", re.I)),
    ("requested_by", re.compile(r"^(?:요청자|작성자|발신|발신자|From|담당|담당자)$", re.I)),
    ("requested_on", re.compile(r"^(?:요청일|작성일|발행일|일자|날짜|Date)$", re.I)),
    ("reason", re.compile(r"^(?:(?:변경\s*)?사유|이유|Reason)$", re.I)),
)
_IGNORED_LABELS = re.compile(r"^(?:수신|참조|CC|To|첨부|호선|Hull|프로젝트|Project)$", re.I)
_ECN_INLINE = re.compile(r"\b(?:ECN|DCN|ECO)\s*(?:No\.?|번호|#)?\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_/.]{1,40})", re.I)
_REV_INLINE = re.compile(r"\bRev(?:ision)?(?:\.\s*|\s+)([A-Z0-9]{1,3})\b", re.I)
"""본문 속 개정 표시('Rev.B'·'Rev B'·'Revision 2'). 표시와 값 사이에 점이나 공백이 있어야 한다 — 'Review'의 'iew'를
개정으로 읽지 않게."""
_ECN_LINE = re.compile(
    r"(?:\b(?:ECN|DCN|ECO)|설계\s*변경|설변)\s*(?:No\.?|번호|#)?\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_/.]*\d[A-Za-z0-9\-_/.]*)",
    re.I,
)
"""설계변경 번호가 든 줄. 번호를 빼면 숫자도 변경 단서 말도 없는 짧은 줄은 안내 줄(머리)이다."""
_COUNT_AFTER = re.compile(r"\s*(?:건|개|가지|항목)")
"""'설계변경 12건'의 12는 번호가 아니라 개수다(숫자 세 자리 이하 뒤에 이 말이 오면)."""
_REV_TAIL = re.compile(r"[\s,·(]*\bRev(?:ision)?(?:\.\s*|\s+)[A-Z0-9]{1,3}\)?\s*$", re.I)
"""번호만 있는 줄 끝의 개정 표시('ECN No. 2026-034 Rev.B')."""
_CHANGE_WORDS = re.compile(
    r"두께|강종|재질|치수|길이|폭|높이|지름|사양|규격|추가|삭제|철거|신설|설치|교체|이동|경로|관통|증후|감후|보강|배관|밸브|펌프"
)
"""안내 줄로 보지 않을 변경 단서 말('설계변경 2026-034 건으로 펌프 P-A 사양 변경 부탁드립니다'는 항목)."""
_OPEN_END = re.compile(r"(?:[다요음함됨임청람것]|변경|추가|삭제|교체|이동|철거|검토|반영|수정|적용|[.!?。)])\s*$")
"""문장이나 항목이 끝난 줄(그 뒤 표시 없는 줄은 새 줄이다)."""
_NOTE = re.compile(r"^\s*(?:※|\*|참고|비고|감사|첨부|이상|끝|以上)")
_DATE = re.compile(r"(20\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})")


@dataclass(frozen=True, slots=True)
class Segment:
    """규칙 조각: 문서 위치 [start, end)와 글."""

    start: int
    end: int
    text: str


_TARGET_WORDS = re.compile(
    r"판|보강재|브라켓|브래킷|밸브|펌프|배관|스풀|장비|부재|관통|(?<![A-Za-z0-9])[A-Z]\d{2}[A-Z](?![A-Za-z0-9])"
)
"""변경 대상 말(부재 종류·블록 코드 'B31P'). 값 절('15mm에서 17mm로 증후')에는 보통 없다."""


def has_change_words(text: str) -> bool:
    """변경 단서 말(두께·삭제·교체 …)이 있는가."""
    return _CHANGE_WORDS.search(text) is not None


def names_target(text: str) -> bool:
    """대상 말(판·밸브·블록 코드 …)이 있는가 — 따로 변경일 수 있는 조각."""
    return _TARGET_WORDS.search(text) is not None


def normalize_document(text: str) -> str:
    """줄바꿈만 맞춘다(\\r\\n·\\r → \\n). 위치 계산의 기준 문서."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_header(document: str) -> tuple[IntakeHeader, frozenset[int]]:
    """머리 정보와 머리로 쓴 줄의 시작 위치. 라벨 줄이 없으면 안내 줄의 번호, 그다음 본문 속 'ECN No. …'(숫자가 든
    것)·'Rev.B'를 찾는다."""
    found: dict[str, str] = {}
    header_lines: set[int] = set()
    noticed: str | None = None  # 안내 줄 속 번호는 번호만 있는 줄·라벨 줄이 없을 때만 쓴다
    for start, line in _lines(document):
        ref, is_header, alone = _ecn_line(line)
        if ref and alone:
            found.setdefault("ecn_ref", ref)
        elif ref:
            noticed = noticed or ref
        if is_header or _label_line(line, found):
            header_lines.add(start)
    if "ecn_ref" not in found and noticed:
        found["ecn_ref"] = noticed
    if "ecn_ref" not in found:
        inline = next((m for m in _ECN_INLINE.finditer(document) if re.search(r"\d", m.group(1))), None)
        if inline:
            found["ecn_ref"] = inline.group(1).rstrip(".")
    if "revision" not in found:
        rev = _REV_INLINE.search(document)
        if rev:
            found["revision"] = rev.group(1).upper()
    requested_on = _date(found.get("requested_on"))
    header = IntakeHeader(
        ecn_ref=clip(found.get("ecn_ref"), 120),
        title=clip(found.get("title"), 200),
        revision=clip(found.get("revision"), 40),
        requested_by=clip(found.get("requested_by"), 80),
        requested_on=requested_on,
        reason=clip(found.get("reason"), 300),
    )
    return header, frozenset(header_lines)


def _label_line(line: str, found: dict[str, str]) -> bool:
    """'라벨: 값' 머리 줄이면 값을 found에 넣고(먼저 나온 값 우선) True. 무시하는 라벨(수신·참조 …)도 머리 줄이다."""
    match = _LABEL_VALUE.match(line)
    if not match:
        return False
    label = match.group("label").strip()
    if _IGNORED_LABELS.match(label):
        return True
    for key, pattern in _HEADER_LABELS:
        if pattern.match(label):
            found.setdefault(key, match.group("value").strip())
            return True
    return False


def _ecn_line(line: str) -> tuple[str | None, bool, bool]:
    """줄에 적힌 설계변경 번호, 그 줄이 머리인지, 번호만 있는 줄인지. 머리 = 번호만 있는 줄('ECN No. 2026-034'·
    '설계변경 번호: 2026-034')이나, 번호를 빼면 숫자도 변경 단서 말도 없는 80자 이하 안내 줄
    ('변경 리스트 (ECN 2026-755)').
    안내 줄의 번호는 번호만 있는 줄·라벨 줄보다 뒤로 미룬다(앞의 안내 줄이 진짜 번호를 가리지 않게)."""
    alone = _ECN_INLINE.fullmatch(_REV_TAIL.sub("", line.strip()))
    if alone:
        return alone.group(1).rstrip("."), True, True
    notice = _ECN_LINE.search(line)
    if notice is None:
        return None, False, False
    rest = line[: notice.start()] + line[notice.end() :]
    header = len(line.strip()) <= 80 and not re.search(r"\d", rest) and not _CHANGE_WORDS.search(rest)
    if re.fullmatch(r"\d{1,3}", notice.group(1)) and _COUNT_AFTER.match(line, notice.end()):
        return (
            None,
            header,
            False,
        )  # '설계변경 12건 정리해서 보냅니다': 12는 개수(안내 줄이지만 번호 없음)
    return notice.group(1).rstrip("."), header, not rest.strip(" \t:：")


def segments(document: str, header_lines: frozenset[int] = frozenset()) -> list[Segment]:
    """머리 줄을 뺀 나머지를 단위(줄 · 표 칸 · 이어지는 줄을 합친 항목)로 묶고, 문장 끝·세미콜론·', 그리고'로 나눈
    조각(빈 조각 없음)."""
    out: list[Segment] = []
    for start, body in _units(document, header_lines):
        cursor = 0
        for match in _SENTENCE_END.finditer(body):
            _add(out, start + cursor, body[cursor : match.start()])
            cursor = match.end()
        _add(out, start + cursor, body[cursor:])
    return out


def _units(document: str, header_lines: frozenset[int]) -> list[tuple[int, str]]:
    """(문서 위치, 글) 단위. 이어지는 줄을 합친 단위의 글은 원문 그대로(줄바꿈 포함)라 위치가 어긋나지 않는다."""
    units: list[tuple[int, str]] = []
    marked = False  # 직전 단위가 번호·글머리표 항목(또는 그 이어지는 줄)
    table = False  # 직전 줄이 표 행
    for start, line in _lines(document):
        if start in header_lines or not line.strip():
            marked = table = False
            continue
        if line.count("|") >= 2:  # 표 행: 표의 첫 행이 숫자 없으면 머리 행
            first, table, marked = not table, True, False
            if not (first and not re.search(r"\d", line)):
                units.extend(_cells(start, line))
            continue
        table = False
        bullet = _BULLET.match(line)
        if bullet is None and marked and units and not _OPEN_END.search(units[-1][1]) and not _NOTE.match(line):
            begin = units[-1][0]
            units[-1] = (begin, document[begin : start + len(line)])
            continue
        offset = bullet.end() if bullet else 0
        units.append((start + offset, line[offset:]))
        marked = bullet is not None
    return units


def _cells(start: int, line: str) -> list[tuple[int, str]]:
    """표 행. 변경 글 칸(12자 이상)이 있으면 칸마다, 없으면(열마다 대상·속성·전·후를 나눈 표) 행 전체를 한 단위로 —
    값 칸('15'·'17')을 번호로 버리지 않게. 맨 앞 번호 칸(숫자 3자리 이하)과 빈 칸만 뺀다."""
    parts: list[tuple[int, str]] = []
    cursor = 0
    for part in line.split("|"):
        parts.append((start + cursor, part))
        cursor += len(part) + 1
    cells = [(s, p) for s, p in parts if p.strip()]
    if cells and re.fullmatch(r"\s*\d{1,3}\s*", cells[0][1]):
        cells = cells[1:]
    if not cells or any(len(p.strip()) >= 12 for _, p in cells):
        return cells
    begin, end = cells[0][0], cells[-1][0] + len(cells[-1][1])
    return [(begin, line[begin - start : end - start])]


def _add(out: list[Segment], start: int, text: str) -> None:
    stripped = text.strip()
    if not stripped:
        return
    lead = len(text) - len(text.lstrip())
    begin = start + lead
    out.append(Segment(begin, begin + len(stripped), stripped))


def _lines(document: str) -> list[tuple[int, str]]:
    lines = []
    position = 0
    for line in document.split("\n"):
        lines.append((position, line))
        position += len(line) + 1
    return lines


def _date(value: str | None) -> date | None:
    if not value:
        return None
    match = _DATE.search(value)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def clip(value: str | None, limit: int) -> str | None:
    """앞뒤 공백을 떼고 limit자까지. 비면 None."""
    if value is None:
        return None
    value = value.strip()
    return value[:limit] or None
