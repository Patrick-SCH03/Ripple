"""규칙 함수가 주고받는 것: 입력 문맥과 발견(영향 후보)."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from ripple.contracts.domain import EntityType, Relation
from ripple.contracts.result import Hop, ImpactType, Unresolved
from ripple.contracts.rulebook import Rule

from ..overlay import ChangeView, PlannedOp
from ..state import Basis, StageOn, StateModel

BASIS_NAMES = {
    Basis.EVIDENCE: "근거",
    Basis.PLAN: "계획 추정",
    Basis.OFF_PLAN: "계획 이탈 추정",
    Basis.UNKNOWN: "알 수 없음",
}


@dataclass(frozen=True, slots=True)
class Finding:
    """규칙이 찾은 영향 후보. 엔진이 같은 키를 가장 짧은 경로 하나로 합친다."""

    entity_type: EntityType
    entity_id: str
    impact_type: ImpactType
    path: tuple[Hop, ...]
    origin: str  # 근거 경로의 출발 부재(경로가 없으면 대상 부재 자신)
    note: str = ""
    unresolved: Unresolved | None = None


@dataclass(frozen=True, slots=True)
class RuleContext:
    rule: Rule
    view: ChangeView
    state: StateModel
    judge_on: date  # 판정일 = 확정일(없으면 기준일)
    horizon_days: int
    ships: frozenset[str]
    used_relations: Mapping[str, frozenset[Relation]]  # 연산 이름 → 그 연산의 규칙이 따라가는 부재 관계
    changed: Mapping[str, tuple[Hop, ...]]  # 늦게 도는 규칙용: 바뀌는 부재 → 그 부재까지의 근거 경로

    def planned(self) -> tuple[PlannedOp, ...]:
        """이 규칙이 다루는 연산(규칙표의 ops)."""
        return self.view.planned(self.rule.ops)

    def hop(self, src: str, dst: str, relation: Relation) -> Hop:
        return Hop(src=src, dst=dst, relation=relation, rule_id=self.rule.id)


RuleFn = Callable[[RuleContext], Iterator[Finding]]


@dataclass(frozen=True, slots=True)
class RuleSpec:
    fn: RuleFn
    traverses: frozenset[Relation]  # 대상 부재에서 따라가는 관계(R-X01이 빠진 관계를 찾을 때 씀)
    late: bool = False  # 다른 규칙이 찾은 '이어서 바뀌는 부재'까지 출발점으로 쓰는 규칙(R-B01·R-D01)


def stage_note[S: StrEnum](title: str, state: StageOn[S], names: Mapping[S, str]) -> str:
    """'확정일 품목 단계 입고(근거)' 같은 근거 메모."""
    if state.likely is None:
        return f"{title}를 알 수 없음(가능 범위 {names[state.earliest]}~{names[state.latest]})"
    return f"{title} {names[state.likely]}({BASIS_NAMES[state.basis]})"
