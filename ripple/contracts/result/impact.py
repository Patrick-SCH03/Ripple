"""영향 계약(docs/engine.md(전파)): 근거 경로 한 걸음(Hop)·영향(Impact)·계산하지 못한 항목(Unresolved)."""

from __future__ import annotations

from itertools import pairwise

from pydantic import model_validator

from ..base import Frozen
from ..domain import EntityType, Relation
from .vocab import ImpactType, Severity, UnresolvedKind


class Hop(Frozen):
    src: str
    dst: str
    relation: Relation
    rule_id: str


class Impact(Frozen):
    entity_type: EntityType
    entity_id: str
    ship_id: str
    impact_type: ImpactType
    severity: Severity
    rule_id: str
    path: tuple[Hop, ...] = ()  # 변경 지점부터 이 엔터티까지의 근거 경로
    note: str = ""

    @model_validator(mode="after")
    def _path_reaches_entity(self) -> Impact:
        if not self.path:
            return self
        if any(a.dst != b.src for a, b in pairwise(self.path)):
            raise ValueError("근거 경로 중간 끊김")
        if self.path[-1].dst != self.entity_id or self.path[-1].rule_id != self.rule_id:
            raise ValueError("근거 경로 끝은 영향 엔터티·영향 규칙 필요")
        return self

    @property
    def key(self) -> tuple[str, str, str, str]:
        """병합·정렬 키(docs/engine.md(전파) 6절)."""
        return (self.entity_type.value, self.entity_id, self.rule_id, self.impact_type.value)


class Unresolved(Frozen):
    """계산하지 못한 항목과 이유. 화면에 '계산 불가' 또는 '확인 필요'로 보인다."""

    kind: UnresolvedKind
    reason: str
    entity_id: str | None = None
