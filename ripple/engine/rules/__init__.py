"""규칙 함수: 규칙표의 규칙 ID마다 함수 하나(docs/engine.md(전파) 5절).

판단 로직은 여기, 범위(어느 연산)·문턱값·출처는 규칙표(rules/propagation.yaml)에 있다. 규칙표에 있는데 여기
없는 규칙(일정·보류·인도)은 아직 계산하지 않고 보고서의 pending_rules에 적힌다.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from ripple.contracts.domain import Relation

from .base import Finding, RuleContext, RuleSpec
from .connection import r_x01
from .location import r_b01, r_d01
from .piping import r_p01, r_p02, r_p03
from .procurement import r_m01, r_m02, r_t01
from .structure import r_t02, r_t03, r_t04

RULES: Mapping[str, RuleSpec] = MappingProxyType(
    {
        "R-T01": RuleSpec(r_t01, frozenset({Relation.SUPPLIED_BY})),
        "R-M02": RuleSpec(r_m02, frozenset({Relation.SUPPLIED_BY})),
        "R-T02": RuleSpec(r_t02, frozenset({Relation.BUTT_WELD})),
        "R-T03": RuleSpec(r_t03, frozenset({Relation.FILLET_WELD})),
        "R-T04": RuleSpec(r_t04, frozenset({Relation.PENETRATION})),
        "R-P01": RuleSpec(r_p01, frozenset({Relation.PIPE_JOINT})),
        "R-P02": RuleSpec(r_p02, frozenset()),
        "R-P03": RuleSpec(r_p03, frozenset({Relation.SUPPORT})),
        "R-M01": RuleSpec(r_m01, frozenset({Relation.SUPPLIED_BY})),
        "R-B01": RuleSpec(r_b01, frozenset({Relation.PART_OF}), late=True),
        "R-D01": RuleSpec(r_d01, frozenset({Relation.DRAWN_IN}), late=True),
        "R-X01": RuleSpec(r_x01, frozenset()),
    }
)

__all__ = ["RULES", "Finding", "RuleContext", "RuleSpec"]
