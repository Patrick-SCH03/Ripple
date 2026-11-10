"""문서 → 확인표 항목(순수 계산): 규칙 조각과 AI 항목을 합치고, AI 값을 원문 조각으로 검증하고, 항목을 만든다.

규칙 분할은 AI가 있어도 늘 돈다. AI 항목이 덮지 않은 규칙 조각(변경 단서가 있는 것)은 'AI가 뽑지 않은 줄'로
보인다 — AI가 항목을 조용히 빠뜨려도 사람이 볼 수 있게. AI 항목의 원문 인용은 문서의 실제 부분 문자열이어야 하고,
AI가 읽은 숫자는 그 인용 안에 있어야 한다(문서 전체가 아니라 — 다른 항목의 값을 붙이는 오류를 막는다).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ripple.contracts.corrections import DecisionTrace
from ripple.contracts.intake import (
    MAX_ITEMS,
    AiReading,
    Extractor,
    IntakeIssue,
    IntakeIssueCode,
    IntakeItem,
)

from .ai_values import NUMBER
from .assemble import Piece, ReadContext, read_piece
from .checks import with_cross_issues
from .segment import Segment, clip, has_change_words, names_target


@dataclass(frozen=True, slots=True)
class RawAiItem:
    """AI가 낸 항목 하나(스키마 검증 뒤, 원문 대조 전)."""

    source_span: str
    op: str | None = None
    target: str | None = None
    before: str | None = None
    after: str | None = None
    reason: str | None = None


def locate(document: str, quote: str, taken: Sequence[tuple[int, int]] = ()) -> tuple[int, int] | None:
    """인용의 문서 위치. 그대로 없으면 공백 차이만 무시하고 찾는다. 이미 쓴 위치와 겹치지 않는 첫 자리."""
    quote = quote.strip()
    if not quote:
        return None
    pattern = re.compile(r"\s+".join(re.escape(token) for token in quote.split()))
    for match in pattern.finditer(document):
        span = (match.start(), match.end())
        if not any(span[0] < end and start < span[1] for start, end in taken):
            return span
    return None


def ai_pieces(
    document: str, raw: Sequence[RawAiItem], rule: Sequence[Segment] = ()
) -> tuple[list[Piece], list[IntakeIssue]]:
    """AI 항목 → 조각. 원문에서 못 찾은 인용은 버리고 문서 문제로 알린다(그 줄은 규칙 조각으로 보인다).
    이미 뽑은 인용과 똑같은 인용은 한 항목으로 합친다(겹치기만 하는 인용은 따로 둔다 — 둘째 변경일 수 있다).
    규칙 조각을 주면 인용을 그 조각 끝까지 넓힌 뒤(_widened) AI 값의 숫자를 넓힌 조각에서 확인한다 — 인용 밖 바로 옆의
    값('10.5mm에서 …, 13.5mm로 + 판 두께 변경')을 '없는 값'으로 버리지 않게."""
    located: list[tuple[int, int, RawAiItem]] = []
    taken: list[tuple[int, int]] = []
    lost = 0
    for item in raw:
        span = locate(document, item.source_span, taken) or locate(document, item.source_span)
        if span is None:
            lost += 1
            continue
        if span in taken:  # 같은 인용을 대상마다 따로 낸 것('판 2, 5, 7번' → 3개): 해석기가 인용 하나로 다 읽는다
            continue
        taken.append(span)
        located.append((span[0], span[1], item))
    pieces = [Piece(s, e, document[s:e], Extractor.LLM, _reading(item), ()) for s, e, item in located]
    if rule:
        pieces = _widened(rule, pieces, document)
    verified = [_verified(piece, item) for piece, (_, _, item) in zip(pieces, located, strict=True)]
    problems: list[IntakeIssue] = []
    if lost:
        problems.append(
            IntakeIssue(
                code=IntakeIssueCode.EXTRACT_UNVERIFIED,
                message=f"AI 추출 항목 {lost}개 — 원문에서 찾지 못해 제외 · 그 줄은 규칙으로 읽은 결과",
            )
        )
    return verified, problems


def _reading(item: RawAiItem) -> AiReading:
    return AiReading(
        op=item.op,
        target=clip(item.target, 200),
        before=clip(item.before, 60),
        after=clip(item.after, 60),
        reason=clip(item.reason, 200),
    )


def _verified(piece: Piece, item: RawAiItem) -> Piece:
    """AI가 읽은 값의 숫자가 조각 안에 없으면 값을 버리고 'AI 값 확인 안 됨'을 붙인다."""
    foreign = [v for v in (item.before, item.after) if v and not _numbers_in(v, piece.text)]
    if not foreign or piece.ai is None:
        return piece
    value = foreign[0][:60]
    message = f"AI가 읽은 값 '{value}' — 이 조각에 없음 · 원문 보고 값 수정 필요"
    reading = piece.ai.model_copy(update={"before": None, "after": None})
    issue = IntakeIssue(code=IntakeIssueCode.EXTRACT_UNVERIFIED, message=message)
    return Piece(piece.start, piece.end, piece.text, piece.extractor, reading, (*piece.issues, issue))


def merge(rule: Sequence[Segment], ai: Sequence[Piece], document: str = "") -> list[Piece]:
    """AI 조각 + AI 조각과 겹치지 않는 규칙 조각(AI 경로였으면 'AI가 뽑지 않은 줄' 표시), 문서 순서.

    AI 인용이 문장 중간에서 시작하거나 꼬리를 잘라 내면('…좌현 판 2, 5, 7번 …'에서 '판 2, 5, 7번 …'만) 대상 맥락·개정
    표시가 빠진다. 같은 규칙 조각 안에 다른 AI 조각이 없는 쪽으로 인용을 그 조각 끝까지 넓힌다(_widened).
    """
    ai = _widened(rule, ai, document) if document else list(ai)
    out = list(ai)
    for segment in rule:
        if any(segment.start < p.end and p.start < segment.end for p in ai):
            continue
        issues: tuple[IntakeIssue, ...] = ()
        if ai:
            issues = (
                IntakeIssue(
                    code=IntakeIssueCode.NOT_EXTRACTED,
                    message="AI가 항목으로 뽑지 않은 줄 — 설계변경이면 확인, 아니면 빼기",
                ),
            )
        out.append(Piece(segment.start, segment.end, segment.text, Extractor.RULE, None, issues))
    return sorted(out, key=lambda p: (p.start, p.end))


def build_items(
    pieces: Sequence[Piece], ctx: ReadContext
) -> tuple[tuple[IntakeItem, ...], list[IntakeIssue], dict[str, tuple[DecisionTrace, ...]]]:
    """조각마다 항목을 만들고(변경 단서 없는 규칙 조각은 뺌) 항목 사이 문제를 붙인다. 상한을 넘으면 문서 문제.
    세 번째 값은 항목 ID → 재보정 자료(서버에만 둔다)."""
    items: list[IntakeItem] = []
    traces: dict[str, tuple[DecisionTrace, ...]] = {}
    problems: list[IntakeIssue] = []
    for piece in pieces:
        if len(items) >= MAX_ITEMS:
            problems.append(
                IntakeIssue(
                    code=IntakeIssueCode.TRUNCATED,
                    message=f"항목 {MAX_ITEMS}개 초과 · 뒷부분 미표시 — 문서 나눠서 입력",
                )
            )
            break
        outcome = read_piece(piece, f"I{len(items) + 1}", ctx)
        if outcome is not None:
            items.append(outcome.item)
            traces[outcome.item.item_id] = outcome.traces
    return with_cross_issues(items), problems, traces


def _widened(rule: Sequence[Segment], ai: Sequence[Piece], document: str) -> list[Piece]:
    """AI 인용을 그 규칙 조각의 앞·뒤 끝까지 넓힌다(같은 조각 안에 다른 AI 조각이 없는 쪽만). 앞은 대상 맥락('…좌현'),
    뒤는 꼬리('(도면 … Rev.C)'·'변경 바랍니다') — AI가 잘라 낸 꼬리의 개정 표시를 놓치지 않게.

    인용이 제 조각을 넘어 대상 말과 변경 단서 말이 있는 다음 조각('T31C 밸브 V-1 삭제')까지 덮으면 제 조각 끝에서
    자른다. 그 조각은 따로 변경일 수 있어 'AI가 뽑지 않은 줄'로 남긴다 — 두 변경을 AI 항목 하나로 합쳐 둘째 변경이
    조용히 사라지지 않게. 대상 말 없는 다음 조각(표의 값 칸 '10mm → 12mm', 값 절 '15mm에서 17mm로
    증후')은 그대로 덮는다."""
    out = []
    for piece in ai:
        home = next((s for s in rule if s.start <= piece.start < s.end), None)
        if home is None:
            out.append(piece)
            continue
        others = [o for o in ai if o is not piece]
        start, end = piece.start, piece.end
        if not any(home.start <= o.start < piece.start or home.start < o.end <= piece.start for o in others):
            start = min(start, home.start)
        if not any(piece.end <= o.start < home.end for o in others):
            end = max(end, home.end)
        if any(home.end <= s.start < end and names_target(s.text) and has_change_words(s.text) for s in rule):
            end = home.end
        if (start, end) == (piece.start, piece.end):
            out.append(piece)
            continue
        out.append(Piece(start, end, document[start:end], piece.extractor, piece.ai, piece.issues))
    return out


def _numbers_in(value: str, text: str) -> bool:
    """값의 숫자가 모두 조각에 있는가(천 단위 쉼표는 무시)."""
    plain = text.replace(",", "")
    found = set(NUMBER.findall(plain))
    wanted = NUMBER.findall(value.replace(",", ""))
    return all(_same_number(w, found) for w in wanted)


def _same_number(wanted: str, found: set[str]) -> bool:
    return any(float(wanted) == float(f) for f in found)
