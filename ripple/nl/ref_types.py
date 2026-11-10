"""참조 추출이 내는 값: 블록 단서(Cue)·문맥(Context)·부재 표현(Mention)·바꿀 규격 설명(TargetDescription)·
참조 묶음(References). 만드는 규칙은 refs.py."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ripple.contracts.domain import PartKind

from .aliases import Hit
from .specs import SpecToken
from .text import Span

CueKind = Literal["block", "cot", "word", "side", "system", "valve_type"]
Role = Literal["crosses", "attach", "remove", "add", "at"]


@dataclass(frozen=True, slots=True)
class Cue:
    start: int
    end: int
    kind: CueKind
    value: str  # 블록 ID·화물탱크 번호·이름 단어·'P'/'S'·계통·밸브 종류
    fuzzy: bool = False


@dataclass(frozen=True, slots=True)
class Context:
    block: str | None = None  # 블록 코드로 정한 블록 ID
    cot: int | None = None
    words: frozenset[str] = frozenset()
    side: str | None = None
    system: str | None = None
    valve_type: str | None = None
    start: int | None = None  # 문맥이 시작된 위치(표현 전체 범위용)
    fuzzy: bool = False  # 오타 허용으로 찾은 단서가 있음

    @property
    def has_block_cue(self) -> bool:
        return self.block is not None or self.cot is not None or bool(self.words) or self.side is not None


@dataclass(frozen=True, slots=True)
class Mention:
    """부재 표현 하나."""

    start: int
    end: int
    text: str
    kind: PartKind | None
    number: int | None
    code: str | None  # 문장에 쓴 부재 코드(정규화, 예: T31C-PL-007)
    part_id: str | None  # 코드로 바로 정해진 지도 부재
    context: Context
    block_ids: frozenset[str]  # 문맥 단서와 맞는 블록(단서가 없으면 빈 집합)
    phrase: Span  # 문맥을 포함한 표현 전체
    listed: bool = False  # 목록·범위의 한 항목
    role: Role | None = None  # 역할 단서
    fuzzy: bool = False  # 종류 단어나 문맥 단서를 오타 허용으로 찾음(결정적 일치로 치지 않는다)

    @property
    def span(self) -> Span:
        return (self.start, self.end)


@dataclass(frozen=True, slots=True)
class TargetDescription:
    """'볼 밸브로'처럼 바꿀 규격을 설명하는 종류 단어(앞의 밸브 종류·계통 단서 포함)."""

    kind: PartKind
    valve_type: str | None
    span: Span


@dataclass(frozen=True, slots=True)
class References:
    mentions: tuple[Mention, ...]
    cues: tuple[Cue, ...]
    occupied: tuple[Span, ...]  # 값 추출에서 뺄 자리
    kind_words: tuple[Hit, ...]  # 찾은 부재 종류 단어 전부
    targets: tuple[TargetDescription, ...]  # '~로'가 붙은 종류 단어
    specs: tuple[SpecToken, ...]  # 규격 ID·부분 표기
    unread: tuple[tuple[Span, str], ...] = ()  # 읽었지만 쓸 수 없는 표현과 이유(확인받는다)
