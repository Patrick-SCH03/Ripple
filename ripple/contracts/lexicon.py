"""해석기 사전 계약: 현장 용어·약어 → 지도 어휘(rules/lexicon.yaml).

규칙 기반 해석기(ripple.nl)가 연산·의도 단서, 부재 종류, 블록 이름 조각, 배관 계통, 밸브 종류,
값의 방향·치수 종류, 역할 단서를 찾는 데 쓴다. 문장 생성기(ripple.generator)는 이 사전을 보지 않는다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .base import Frozen
from .change import OP_NAMES, ChangeIntent
from .domain import PartKind

Aliases = tuple[str, ...]
Dimension = Literal["length_mm", "width_mm", "height_mm", "diameter_mm"]
Role = Literal["crosses", "attach", "remove", "add"]


class Lexicon(Frozen):
    version: str = Field(pattern=r"^lexicon-v\d+$")
    part_kinds: dict[PartKind, Aliases]
    block_words: dict[str, Aliases]  # 블록 이름 속 단어(지도 표기) → 별칭
    systems: dict[str, Aliases]  # 배관 계통(지도 이름) → 별칭
    valve_types: dict[str, Aliases]  # 밸브 종류(지도 이름) → 별칭
    ops: dict[str, Aliases]  # 변경 연산 → 단서
    intents: dict[ChangeIntent, Aliases]  # 변경 의도 → 단서
    increase: Aliases  # 값을 올리는 표현
    decrease: Aliases  # 값을 내리는 표현
    dimensions: dict[Dimension, Aliases]  # 치수 종류 → 단서
    grades: Aliases  # 강종 표기
    roles: dict[Role, Aliases]  # 역할 단서

    @model_validator(mode="after")
    def _consistent(self) -> Lexicon:
        unknown = sorted(set(self.ops) - OP_NAMES)
        if unknown:
            raise ValueError(f"없는 변경 연산의 단서 · {', '.join(unknown)}")
        groups: list[Aliases] = [self.increase, self.decrease, self.grades]
        for table in (self.part_kinds, self.block_words, self.systems, self.valve_types, self.ops):
            groups.extend(table.values())
        groups.extend(self.intents.values())
        groups.extend(self.dimensions.values())
        groups.extend(self.roles.values())
        if any(not group or any(not alias.strip() for alias in group) for group in groups):
            raise ValueError("별칭 묶음에 빈 글자 불가")
        return self
