"""부재 표현 → 지도 부재: 결정적 일치와 후보 점수(docs/input.md(판단 계층) 3절 1).

- 결정적 일치: 코드가 지도 부재 하나를 가리키거나, 블록 단서 + 종류 + 번호(또는 이름만)가 부재 하나로
  정해질 때. 역할 슬롯(관통 판·붙일 판 등)은 이것으로만 채운다(아니면 사용자 확인).
- 후보 점수: 번호·코드·블록·종류·계통·밸브 종류 일치와 글자 2-gram 유사도로 휴리스틱 점수를 매겨
  순위를 정한다. 특징은 점수기(조건부 로지스틱)가 다시 가중한다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from .ref_types import Mention
from .vocab import MapVocabulary, PartEntry

Features = dict[str, float]
_STRIP = re.compile(r"[\d\s\-_#.,·/()]+")

_WEIGHTS = {
    "code": 4.0,
    "number": 3.0,
    "number_miss": -1.0,
    "block_in": 2.0,
    "block_unique": 1.0,
    "block_out": -2.0,
    "kind": 1.0,
    "kind_miss": -1.0,
    "system": 1.0,
    "system_miss": -1.0,
    "vtype": 1.0,
    "vtype_miss": -1.0,
    "sim": 2.0,
}


@dataclass(frozen=True, slots=True)
class Candidate:
    part_id: str
    score: float  # 휴리스틱 점수(후보 순위용)
    features: Features


def deterministic_part(mention: Mention, vocab: MapVocabulary, ship_ids: Sequence[str]) -> str | None:
    """표현이 지도 부재 하나로 정해지면 그 ID(코드 일치·사전 유일 일치), 아니면 None."""
    if mention.part_id is not None:
        return mention.part_id
    if mention.kind is None or not mention.block_ids or mention.fuzzy:
        return None  # 오타 허용으로 찾은 단서는 결정적 일치가 아니다
    if mention.code is not None:
        prefix = mention.code.split("-")[-2]
        found_codes = [
            e
            for e in vocab.parts_in(mention.block_ids, mention.kind)
            if e.prefix == prefix and e.number == mention.number and e.part.ship_id in ship_ids
        ]
        return found_codes[0].part_id if len(found_codes) == 1 else None
    found = [e for e in vocab.parts_in(mention.block_ids, mention.kind) if _fits(mention, e, ship_ids)]
    if mention.number is not None:
        found = [e for e in found if e.number == mention.number]
    return found[0].part_id if len(found) == 1 else None


def _fits(mention: Mention, entry: PartEntry, ship_ids: Sequence[str]) -> bool:
    part = entry.part
    if part.ship_id not in ship_ids:
        return False
    if mention.context.system is not None and part.system != mention.context.system:
        return False
    return mention.context.valve_type is None or entry.valve_type == mention.context.valve_type


def mention_candidates(mention: Mention, vocab: MapVocabulary, ship_ids: Sequence[str], text: str) -> list[Candidate]:
    """호선 안의 모든 부재를 점수 순으로(같으면 ID 순)."""
    surface = _surface(text[mention.phrase[0] : mention.phrase[1]])
    grams = _bigrams(surface)
    found = []
    for entry in vocab.parts.values():
        if entry.part.ship_id not in ship_ids:
            continue
        features = _features(mention, entry, grams, vocab)
        score = sum(_WEIGHTS[k] * v for k, v in features.items() if k in _WEIGHTS)
        found.append(Candidate(entry.part_id, round(score, 6), features))
    found.sort(key=lambda c: (-c.score, c.part_id))
    return found


def _features(mention: Mention, entry: PartEntry, grams: frozenset[str], vocab: MapVocabulary) -> Features:
    part = entry.part
    f: Features = {}
    if mention.fuzzy:
        f["fuzzy"] = 1.0
    if mention.part_id is not None and mention.part_id == part.part_id:
        f["code"] = 1.0
    if mention.number is not None and entry.number is not None:
        f["number" if entry.number == mention.number else "number_miss"] = 1.0
    if mention.block_ids:
        if part.block_id in mention.block_ids:
            f["block_in"] = 1.0
            if len(mention.block_ids) == 1:
                f["block_unique"] = 1.0
        else:
            f["block_out"] = 1.0
    if mention.kind is not None:
        f["kind" if part.kind is mention.kind else "kind_miss"] = 1.0
    if mention.context.system is not None:
        f["system" if part.system == mention.context.system else "system_miss"] = 1.0
    if mention.context.valve_type is not None:
        f["vtype" if entry.valve_type == mention.context.valve_type else "vtype_miss"] = 1.0
    block = vocab.blocks.get(part.block_id)
    names = (part.name, block.block.name if block else "", block.code if block else "")
    f["sim"] = round(max(_dice(grams, _name_grams(name)) for name in names), 4)
    return f


@lru_cache(maxsize=4096)
def _name_grams(name: str) -> frozenset[str]:
    return _bigrams(_surface(name))


def _surface(text: str) -> str:
    return _STRIP.sub("", text).lower()


def _bigrams(text: str) -> frozenset[str]:
    return frozenset(text[i : i + 2] for i in range(len(text) - 1)) if len(text) > 1 else frozenset({text})


def _dice(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))
