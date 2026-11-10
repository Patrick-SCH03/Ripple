"""지도 어휘: 해석기가 문장 속 표현을 지도의 부재·블록·규격에 맞춰 볼 때 쓰는 색인.

부재 ID 형식 `<호선>:<블록 코드>-<접두>-<번호>`(생성기·지정 양식)에서 블록 코드·접두·번호를 읽고,
블록 이름 단어('No.3 COT 횡격벽' → 화물탱크 번호 3, 단어 {횡격벽})와 배관 계통·밸브 종류를 모은다.
ID 형식이 다른 부재(엑셀 가져오기)는 번호 없이 이름·종류로만 찾는다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from ripple.contracts.domain import Block, GraphSnapshot, MaterialSpec, Part, PartKind

_PART_ID = re.compile(r"^(?P<ship>[^:]+):(?P<code>[A-Za-z0-9]+)-(?P<prefix>[A-Za-z]+)-(?P<num>\d+)$")
_COT = re.compile(r"No\.?\s?(\d+)\s?COT", re.IGNORECASE)
_WORD_SPLIT = re.compile(r"[\s·()/,]+")
SIDES = {"좌": "P", "우": "S"}


@dataclass(frozen=True, slots=True)
class PartEntry:
    part: Part
    block_code: str | None
    prefix: str | None
    number: int | None
    valve_type: str | None  # 'globe' 등(배관 부품 분류에서)

    @property
    def part_id(self) -> str:
        return self.part.part_id


@dataclass(frozen=True, slots=True)
class BlockEntry:
    block: Block
    code: str
    cot: int | None  # 화물탱크 번호(No.3 COT → 3)
    side: str | None  # 'P'·'S'
    words: frozenset[str]  # 이름 단어(화물탱크 번호·좌우 빼고)


class MapVocabulary:
    def __init__(self, snapshot: GraphSnapshot) -> None:
        self.snapshot_id = snapshot.snapshot_id
        self.ship_ids = tuple(s.ship_id for s in snapshot.ships)
        self.blocks: dict[str, BlockEntry] = {b.block_id: _block_entry(b) for b in snapshot.blocks}
        self.block_by_code: dict[tuple[str, str], str] = {
            (e.block.ship_id, e.code.upper()): block_id for block_id, e in self.blocks.items()
        }
        self.parts: dict[str, PartEntry] = {p.part_id: _part_entry(p) for p in snapshot.parts}
        self.specs: dict[str, MaterialSpec] = {s.spec_id: s for s in snapshot.specs}
        self.spec_by_key: dict[str, str] = {spec_key(s.spec_id): s.spec_id for s in snapshot.specs}
        self.by_code: dict[tuple[str, str, str, int], str] = {}
        self.by_block: dict[str, list[PartEntry]] = defaultdict(list)
        self.system_blocks: dict[str, set[str]] = defaultdict(set)
        self.prefix_kind: dict[str, PartKind] = {}
        self.prefix_system: dict[str, str] = {}
        for entry in self.parts.values():
            part = entry.part
            self.by_block[part.block_id].append(entry)
            if part.system:
                self.system_blocks[part.system].add(part.block_id)
            if entry.block_code and entry.prefix and entry.number is not None:
                self.by_code[(part.ship_id, entry.block_code.upper(), entry.prefix.upper(), entry.number)] = (
                    part.part_id
                )
                self.prefix_kind[entry.prefix.upper()] = part.kind
                if part.system:
                    self.prefix_system[entry.prefix.upper()] = part.system
        self.systems = frozenset(self.system_blocks)
        self.valve_types = frozenset(e.valve_type for e in self.parts.values() if e.valve_type)
        self.kinds = frozenset(e.part.kind for e in self.parts.values())

    def parts_in(self, block_ids: Iterable[str], kind: PartKind | None = None) -> list[PartEntry]:
        return [e for b in block_ids for e in self.by_block.get(b, ()) if kind is None or e.part.kind is kind]

    def block_name_words(self) -> frozenset[str]:
        return frozenset(word for e in self.blocks.values() for word in e.words)


def spec_key(spec_id: str) -> str:
    """규격 ID 비교용 키: 대소문자·구분자(-·공백·_)를 무시한다."""
    return re.sub(r"[\s\-_]", "", spec_id).upper()


def _block_entry(block: Block) -> BlockEntry:
    code = block.block_id.split(":")[-1]
    cot_match = _COT.search(block.name)
    rest = _COT.sub(" ", block.name)
    words = [w for w in _WORD_SPLIT.split(rest) if w]
    side = SIDES.get(words[-1]) if words else None
    if side:
        words = words[:-1]
    return BlockEntry(
        block=block,
        code=code,
        cot=int(cot_match.group(1)) if cot_match else None,
        side=side,
        words=frozenset(words),
    )


def _part_entry(part: Part) -> PartEntry:
    match = _PART_ID.match(part.part_id)
    valve_type = None
    if part.kind is PartKind.VALVE and part.pid_class and part.pid_class.endswith("_valve"):
        valve_type = part.pid_class.removesuffix("_valve")
    if match is None:
        return PartEntry(part=part, block_code=None, prefix=None, number=None, valve_type=valve_type)
    return PartEntry(
        part=part,
        block_code=match.group("code"),
        prefix=match.group("prefix"),
        number=int(match.group("num")),
        valve_type=valve_type,
    )
