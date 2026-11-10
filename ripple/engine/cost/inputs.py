"""비용 계산 입력: 판정일 t의 전파 결과(보기·상태·병합 전 발견)와 파라미터, 그리고 줄을 만드는 도구."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from fractions import Fraction

from ripple.contracts.domain import ActivityKind, EntityType, SourceRef
from ripple.contracts.result import (
    COST_ITEM_KIND,
    Amount,
    BlockDifficulty,
    CostItem,
    CostLine,
    Determinacy,
    ImpactType,
    WorkHours,
)

from ..describe import describe
from ..index import GraphIndex
from ..overlay import ChangeView
from ..propagate import Propagation
from ..rules import Finding
from ..state import StateModel
from .amounts import Params
from .factors import factors_for

STEEL_CATEGORIES = frozenset({"plate", "section"})
DESIGN_RATE = "labor_rate_per_hour.design"


@dataclass(frozen=True, slots=True)
class CostInput:
    index: GraphIndex
    propagation: Propagation
    params: Params
    horizon_days: int
    activity_of: Mapping[tuple[str, ActivityKind], str]  # (블록, 공정 종류) → 공정 ID(activity_map)
    lead_ratios: Mapping[str, Fraction] | None = None  # 일정 위험 평가(6-6)만: 새 자재 분류 → 리드타임 배율

    @property
    def view(self) -> ChangeView:
        return self.propagation.view

    @property
    def state(self) -> StateModel:
        return self.propagation.state

    @property
    def day(self) -> date:
        return self.propagation.judge_on

    def findings(self, rule_id: str, impact_type: ImpactType | None = None) -> Iterator[Finding]:
        for found_rule, finding in self.propagation.findings:
            if found_rule == rule_id and (impact_type is None or finding.impact_type is impact_type):
                yield finding

    def production_rate(self, block_id: str | None) -> str:
        """생산 작업 인건비 키: 사외 제작 블록이면 협력사, 아니면 원청(모르면 원청)."""
        block = self.index.blocks.get(block_id) if block_id else None
        if block is not None and block.fabricator_id:
            return "labor_rate_per_hour.subcontractor"
        return "labor_rate_per_hour.prime"

    def label(self, entity_id: str) -> str:
        if entity_id in self.view.new_parts:
            return self.view.new_node(entity_id).label
        if self.index.type_of(entity_id) is None:
            return entity_id
        return describe(self.index, entity_id).label

    def sources(self, entity_id: str) -> tuple[SourceRef, ...]:
        kind = self.index.type_of(entity_id)
        source: SourceRef | None = None
        if kind is EntityType.PART:
            source = self.index.parts[entity_id].source
        elif kind is EntityType.PO_LINE:
            source = self.index.lines[entity_id].source
        elif kind is EntityType.BLOCK:
            source = self.index.blocks[entity_id].source
        return () if source is None else (source,)

    def consumer_of(self, block_id: str | None, category: str) -> str | None:
        """새 부재의 소비 공정: 판·형강은 소조립, 그 밖에는 선행의장."""
        if block_id is None:
            return None
        kind = ActivityKind.SUB_ASSEMBLY if category in STEEL_CATEGORIES else ActivityKind.PRE_OUTFITTING
        return self.activity_of.get((block_id, kind))

    def line(
        self,
        line_id: str,
        rule_id: str,
        entity_id: str,
        label: str,
        formula: str,
        inputs: Mapping[str, float | int | str],
        amount: Amount,
        param_keys: tuple[str, ...],
        item: CostItem,
        hours: WorkHours | None = None,
        determinacy: Determinacy = Determinacy.KNOWN,
        reason: str | None = None,
        difficulty: BlockDifficulty | None = None,
    ) -> CostLine:
        """비용 줄 하나. reason은 발생 사유(현장 말 한 문장), 가정값은 param_keys로 채운다.
        item = 세부 구분(구분은 계약 표 COST_ITEM_KIND로 정해짐, 4-12), hours = 공수 줄이 금액을 만든 공수(MH).
        difficulty = 재작업 줄의 블록 난이도 계수(별도 표시, 4-4)."""
        keys = tuple(sorted(set(param_keys)))
        return CostLine(
            line_id=line_id,
            rule_id=rule_id,
            entity_id=entity_id,
            label=label,
            formula=formula,
            inputs=dict(inputs),
            amount=amount,
            determinacy=determinacy,
            sources=self.sources(entity_id),
            param_keys=keys,
            reason=reason,
            factors=factors_for(keys, self.params.raw),
            difficulty=difficulty,
            kind=COST_ITEM_KIND[item],
            item=item,
            hours=hours,
        )


def activity_map(index: GraphIndex) -> dict[tuple[str, ActivityKind], str]:
    """(블록, 공정 종류) → 공정 ID. 평가기가 요청마다 한 번 만든다."""
    return {(a.block_id, a.kind): a.activity_id for a in index.activities.values() if a.block_id is not None}


def won(amount: float) -> str:
    return f"{amount:,.0f}원"


def qty_text(qty: float, unit: str) -> str:
    return f"{qty:,.3f}".rstrip("0").rstrip(".") + unit
