"""감사 사슬: 덧붙이기만 하는 감사 줄을 앞 줄 해시로 잇는다(docs/records.md(기록·결재) 4절).

줄 해시 = SHA-256(정규 JSON {"prev": 앞 줄 해시, "entry": 줄 내용}). 첫 줄의 앞 해시는 GENESIS다.
검증은 순번이 1부터 빠짐없이 이어지는지, 앞 해시가 바로 앞 줄의 해시인지, 줄 해시를 다시 계산해 같은지를 보고
처음 어긋난 순번을 돌려준다. 끝 줄을 지운 것은 사슬만으로 알 수 없어, 저장소가 같은 트랜잭션에서 따로 적어 둔
머리(마지막 순번·해시)와 대조한다. 파일 전체를 다시 쓰는 사람은 막지 못한다(변조 확인용이지 접근 통제가 아니다).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ripple.contracts.identity import canonical_json

GENESIS = "0" * 64


def entry_hash(prev: str, entry: Mapping[str, object]) -> str:
    """앞 줄 해시와 줄 내용(정규 JSON으로 쓸 수 있는 값만)으로 이 줄의 해시를 만든다."""
    return hashlib.sha256(canonical_json({"prev": prev, "entry": dict(entry)})).hexdigest()


@dataclass(frozen=True, slots=True)
class ChainLink:
    """저장된 감사 줄 하나: 순번 · 앞 줄 해시 · 이 줄 해시 · 줄 내용."""

    seq: int
    prev: str
    digest: str
    entry: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ChainHead:
    """저장소가 따로 적어 둔 마지막 줄(없으면 순번 0 · GENESIS)."""

    seq: int
    digest: str


@dataclass(frozen=True, slots=True)
class ChainCheck:
    ok: bool
    entries: int  # 읽은 줄 수
    broken_at: int | None  # 처음 어긋난 순번(머리와 다르면 머리 순번 + 1 또는 마지막 순번)
    head: str  # 마지막으로 이어진 줄의 해시


def verify(links: Iterable[ChainLink], head: ChainHead) -> ChainCheck:
    """순번 순서로 받은 줄을 처음부터 다시 잇는다. 어긋나면 그 자리에서 멈춘다."""
    prev = GENESIS
    count = 0
    for expected_seq, link in enumerate(links, start=1):
        count = expected_seq
        if link.seq != expected_seq or link.prev != prev or entry_hash(prev, link.entry) != link.digest:
            return ChainCheck(ok=False, entries=count, broken_at=expected_seq, head=prev)
        prev = link.digest
    if head.seq != count or head.digest != prev:
        # 끝 줄이 지워졌거나(머리가 더 김) 머리를 갱신하지 않은 줄이 붙었다(사슬이 더 김)
        return ChainCheck(ok=False, entries=count, broken_at=min(head.seq, count) + 1, head=prev)
    return ChainCheck(ok=True, entries=count, broken_at=None, head=prev)
