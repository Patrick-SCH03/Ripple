"""고정 용어집으로 한국어 이름 바꾸기(현장 통보문 번역 초안, docs/records.md(통보) 6절). 외부 AI 없음, 결정적.

엔터티 이름('No.3 COT 횡격벽 판 7', 'T31C 판넬조립', '한빛 작업반')의 한국어 말을 용어집 번역으로 바꾼다.
- 한글 덩어리(붙어 쓴 한글)를 용어 연쇄로 끝까지 빈틈없이 덮을 때만 바꾼다. 긴 용어 먼저(판넬조립 > 판).
  용어 뒤에 한글이 이어지면 다음 용어를 또 찾는다(판넬+조립 같은 합성어).
- 끝까지 못 덮으면 그 덩어리 전체를 한국어 그대로 두고 '번역 안 한 말'로 돌려준다(지어내지 않는다).
  앞머리만 맞는 용어로 더 긴 낱말을 쪼개지 않는다('배관재' ≠ '배관'+'재', '판정' ≠ '판'+'정').
- 한글이 아닌 글자(블록 번호·숫자·영문·기호)는 그대로 둔다 — 숫자·블록 번호가 원문과 같다.
낱말 순서는 한국어 그대로다(용어 대역이지 문장 번역이 아니다).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

HANGUL = re.compile(r"[가-힣]")


@dataclass(frozen=True, slots=True)
class Termed:
    text: str  # 바꾼 글(맞는 용어가 없으면 원문 그대로)
    missing: tuple[str, ...]  # 용어집에 없어 한국어로 남긴 덩어리(나온 순서)
    changed: bool  # 용어를 하나라도 바꿨는가


class TermTable:
    """한 언어의 용어표: 한국어 용어 → 번역. 길게 맞는 용어부터 찾는다."""

    def __init__(self, terms: Mapping[str, str]) -> None:
        self._terms = dict(terms)
        self._longest = max((len(t) for t in self._terms), default=0)

    def convert(self, text: str) -> Termed:
        out: list[str] = []
        missing: list[str] = []
        changed = False
        i = 0
        while i < len(text):
            if not HANGUL.match(text[i]):
                out.append(text[i])
                i += 1
                continue
            chain = self._cover(text, i, {})
            if chain is None:
                end = _run_end(text, i)
                out.append(text[i:end])
                missing.append(text[i:end])
                i = end
                continue
            out.append(" ".join(self._terms[term] for term in chain))
            changed = True
            i += sum(len(term) for term in chain)
        return Termed(text="".join(out), missing=tuple(dict.fromkeys(missing)), changed=changed)

    def _cover(self, text: str, start: int, memo: dict[int, list[str] | None]) -> list[str] | None:
        """start부터 한글 덩어리 끝까지를 빈틈없이 덮는 용어 연쇄(긴 용어 먼저, 안 되면 짧은 용어로 되짚음).

        덩어리 끝 = 뒤에 한글이 없는 자리. 연쇄로 다 못 덮으면 None — 덩어리 앞머리만 맞는 한 낱말 용어로
        더 긴 낱말을 쪼개지 않는다('배관재'를 '배관'+'재'로, '판정'을 '판'+'정'으로 바꾸지 않게).
        """
        if start in memo:
            return memo[start]
        memo[start] = None
        for size in range(min(self._longest, len(text) - start), 0, -1):
            piece = text[start : start + size]
            if piece not in self._terms or not _ends_cleanly(text, start + size, piece):
                continue
            end = start + size
            rest = [] if end >= len(text) or not HANGUL.match(text[end]) else self._cover(text, end, memo)
            if rest is not None:
                memo[start] = [piece, *rest]
                break
        return memo[start]

    def name(self, text: str) -> Termed:
        """엔터티 이름 표시: 바꾼 말이 있으면 '번역 (원문)' — 현장 서류의 한국어 이름과 맞춰 보게. 없으면 원문."""
        termed = self.convert(text)
        if not termed.changed:
            return Termed(text=text, missing=termed.missing, changed=False)
        return Termed(text=f"{termed.text} ({text})", missing=termed.missing, changed=True)


def _run_end(text: str, start: int) -> int:
    end = start
    while end < len(text) and HANGUL.match(text[end]):
        end += 1
    return end


def _ends_cleanly(text: str, end: int, piece: str) -> bool:
    """띄어 쓴 여러 낱말 용어('판 두께')는 낱말 경계에서 끝나야 한다('판 두께감' 같은 말 중간에서 끊지 않게)."""
    if " " not in piece:
        return True
    return end >= len(text) or not HANGUL.match(text[end])


def key_terms(texts: list[str], terms: Mapping[str, str], limit: int) -> list[tuple[str, str]]:
    """원문에 나온 용어집 용어(두 글자 이상, 더 긴 다른 용어에 들어 있는 것은 뺌), 용어집 순서로 limit개까지."""
    joined = "\n".join(texts)
    found = [t for t in terms if len(t.replace(" ", "")) >= 2 and t in joined]
    kept = [t for t in found if not any(t != other and t in other for other in found)]
    return [(t, terms[t]) for t in kept[:limit]]
