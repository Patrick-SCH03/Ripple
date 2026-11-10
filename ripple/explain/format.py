"""설명 문장의 숫자·날짜 표기와 조사(화면 web/src/lib/money.ts와 같은 규칙, DESIGN.md 8절)."""

from __future__ import annotations

from datetime import date

MAN = 10_000


def grouped(n: int) -> str:
    return f"{n:,}"


def won(value: int) -> str:
    """원 단위: 2984205 → '2,984,205원'."""
    return f"{'−' if value < 0 else ''}{grouped(abs(value))}원"


def man_units(value: int) -> int:
    """0 이상 금액의 만원 사사오입(화면 Math.round와 같게 — round()의 짝수 쪽 반올림이 아님): 125,000 → 13.
    문장 검사(explain·brief audit)도 이 값으로 대조한다."""
    return (value + MAN // 2) // MAN


def _manwon(value: int) -> str:
    man = man_units(value)
    eok, rest = divmod(man, MAN)
    if eok == 0:
        return f"{grouped(rest)}만"
    return f"{grouped(eok)}억" if rest == 0 else f"{grouped(eok)}억 {grouped(rest)}만"


def money(value: int) -> str:
    """첫 화면 금액: 1만원 미만은 원 그대로, 그 위는 만원 반올림('2억 2,421만원'), 음수는 '절감 …'."""
    if value < 0:
        return f"절감 {money(-value)}"
    if value < MAN:
        return won(value)
    return f"{_manwon(value)}원"


def money_range(low: int, high: int) -> str:
    """'66만~789만원'. 끝이 1만원 미만이거나 음수면 끝마다 단위를 붙인다."""
    if low >= MAN and high >= MAN:
        return f"{_manwon(low)}~{_manwon(high)}원"

    def end(value: int) -> str:
        return f"−{money(-value)}" if value < 0 else money(value)

    return f"{end(low)}~{end(high)}"


def day(value: date) -> str:
    return f"{value.year}년 {value.month}월 {value.day}일"


_DIGIT_BATCHIM = {digit: digit in "013678" for digit in "0123456789"}
"""숫자를 한자어로 읽을 때 받침이 있는가(영·일·삼·육·칠·팔)."""


def _batchim(word: str) -> bool | None:
    """마지막 글자(따옴표·괄호 밖 빼고)에 받침이 있는가. 한글·숫자가 아니면 모름(None)."""
    last = word.rstrip().rstrip("'\"”’)]")[-1:]
    if "가" <= last <= "힣":
        return bool((ord(last) - 0xAC00) % 28)
    return _DIGIT_BATCHIM.get(last)


def _particle(word: str, with_batchim: str, without: str) -> str:
    batchim = _batchim(word)
    if batchim is None:
        return f"{with_batchim}({without})"
    return with_batchim if batchim else without


def topic_particle(word: str) -> str:
    """은/는: 마지막 글자에 받침이 있으면 '은'. 한글·숫자가 아니면 '은(는)'."""
    return _particle(word, "은", "는")


def object_particle(word: str) -> str:
    """을/를: 마지막 글자에 받침이 있으면 '을'. 한글·숫자가 아니면 '을(를)'."""
    return _particle(word, "을", "를")


def subject_particle(word: str) -> str:
    """이/가: 마지막 글자에 받침이 있으면 '이'. 한글·숫자가 아니면 '이(가)'."""
    return _particle(word, "이", "가")
