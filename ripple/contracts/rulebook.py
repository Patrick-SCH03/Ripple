"""전파 규칙표 계약(rules/*.yaml).

판단 로직은 엔진의 같은 ID 함수에 있고, 규칙표는 규칙의 범위·문턱값·출처를 담는다.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Literal

from pydantic import Field, model_validator

from .base import Frozen
from .change import OP_NAMES
from .domain import Relation
from .result import ImpactType, Severity


class Rule(Frozen):
    id: str = Field(pattern=r"^R-[A-Z]\d{2}$")
    ops: tuple[str, ...] = Field(min_length=1)
    relation: Relation | Literal["any"]  # any는 R-X01(따라갈 연결 없음) 전용
    when: str
    effect: tuple[ImpactType, ...] = Field(min_length=1)
    severity: Severity = Severity.MEDIUM
    settings: dict[str, Any] = Field(default_factory=dict)  # 규칙별 문턱값
    note: str = ""
    source: str | None = None

    @model_validator(mode="after")
    def _known_ops(self) -> Rule:
        unknown = set(self.ops) - OP_NAMES
        if unknown:
            raise ValueError(f"{self.id}: 계약에 없는 연산 {sorted(unknown)}")
        if len(set(self.ops)) != len(self.ops):
            raise ValueError(f"{self.id}: 연산 중복")
        return self

    @property
    def is_fallback(self) -> bool:
        return self.relation == "any"


class RuleBook(Frozen):
    version: str = Field(pattern=r"^rules-v\d+$")
    updated: date
    rules: tuple[Rule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _well_formed(self) -> RuleBook:
        duplicated = [k for k, n in Counter(r.id for r in self.rules).items() if n > 1]
        if duplicated:
            raise ValueError(f"규칙 ID 중복: {duplicated}")
        fallbacks = [r for r in self.rules if r.is_fallback]
        if len(fallbacks) != 1:
            raise ValueError("연결이 끊긴 경로를 받는 규칙(relation: any) 정확히 하나 필요")
        fallback = fallbacks[0]
        if set(fallback.ops) != OP_NAMES or ImpactType.NEEDS_CONFIRMATION not in fallback.effect:
            raise ValueError("relation: any 규칙의 판정은 모든 연산에서 '확인 필요'만 가능")
        return self

    def get(self, rule_id: str) -> Rule:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        raise KeyError(f"규칙표 {self.version}에 {rule_id} 없음")
