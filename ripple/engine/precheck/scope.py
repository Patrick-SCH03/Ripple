"""사전 점검이 같이 쓰는 것: 변경 후 보기 · 바뀌는 부재 묶음 · 이 설계변경 범위 블록 · 지도에 있는 정보 ·
항목 만들기."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.change import AddPart, AddPenetration, ReroutePipe
from ripple.contracts.domain import BLOCK_ACTIVITY_ORDER, Activity, ConnectionKind, EntityType, PartKind, Relation
from ripple.contracts.result import (
    PRECHECK_RULE_NAMES,
    PRECHECK_TEXT_MAX,
    UNCHECKED_FINDING,
    AnalysisResult,
    ImpactType,
    PrecheckItem,
    PrecheckLevel,
    PrecheckLink,
    PrecheckRule,
)

from ..describe import PART_KIND_NAMES
from ..index import GraphIndex
from ..overlay import ChangeView
from ..schedule.baseline import Baseline
from ..state import ActivityStart
from .text import UNCHECKED_REASON, UNCHECKED_TEXT

PIPE_KINDS = frozenset({PartKind.PIPE_SPOOL, PartKind.VALVE, PartKind.EQUIPMENT})
"""배관 연결(pipe_joint)로 이어지는 부재."""


class Scope:
    """한 요청의 사전 점검 문맥. 원본 지도는 바꾸지 않고, 변경 후 보기(ChangeView)로 새 부재·새 연결을 본다."""

    def __init__(
        self, index: GraphIndex, request: AnalysisRequest, result: AnalysisResult, counts: Mapping[str, int] | None
    ) -> None:
        self.index = index
        self.view = ChangeView(index, request.change)
        self.as_of: date = request.as_of
        self.confirm_on: date = request.effective_confirm_on
        self._baseline: Baseline | None = None
        self.result = result
        self.counts = counts
        ops = [planned.op for planned in self.view.ops]
        self.reroutes: tuple[tuple[ReroutePipe, tuple[str, ...]], ...] = tuple(
            (p.op, p.new_ids) for p in self.view.ops if isinstance(p.op, ReroutePipe)
        )
        self.added_collars: frozenset[str] = frozenset(
            op.attach_to_part_id
            for op in ops
            if isinstance(op, AddPart) and op.kind is PartKind.COLLAR and op.attach_to_part_id
        )
        self.added_penetrations: frozenset[str] = frozenset(
            op.plate_part_id for op in ops if isinstance(op, AddPenetration)
        )
        existing = {t for p in self.view.ops for t in p.existing_targets()}
        crossed = {c for op, _ in self.reroutes for c in op.crosses_part_ids}
        self.changed: tuple[str, ...] = tuple(sorted(t for t in existing | crossed if t in index.parts))
        self.new_ids: tuple[str, ...] = tuple(sorted(self.view.new_parts))
        blocks = {self.view.block_of(p) for p in (*self.changed, *self.new_ids)}
        self.scope_blocks: frozenset[str] = frozenset(b for b in blocks if b is not None)
        self._kinds = frozenset(p.kind for p in index.parts.values())
        self.has_secondary = any(p.secondary_drawing_ids for p in index.parts.values())
        self.has_pipe_joints = any(c.kind is ConnectionKind.PIPE_JOINT for c in index.snapshot.connections)

    # ---------- 지도 조회 ----------

    def has_kind(self, kind: PartKind) -> bool:
        """지도에 그 종류 부재가 하나라도 있는가(없으면 그 규칙은 '점검 불가')."""
        return kind in self._kinds

    def kind(self, part_id: str) -> PartKind | None:
        if part_id in self.view.new_parts or part_id in self.index.parts:
            return self.view.kind(part_id)
        return None

    def label(self, part_id: str) -> str:
        """부재 이름: 새 부재면 '새 배관 스풀 1'(같은 연산의 몇 번째), 지도 부재면 지도 이름."""
        new = self.view.new_parts.get(part_id)
        if new is None:
            part = self.index.parts.get(part_id)
            return part.name if part is not None else part_id
        return f"새 {PART_KIND_NAMES[new.kind]} {part_id.rsplit(':', 1)[-1]}"

    def block_activities(self, block_id: str) -> tuple[Activity, ...]:
        """블록의 블록 공정(이정표 제외, 공정 순서)."""
        found = [
            self.index.activities[a]
            for a in self.index.into(block_id, Relation.PART_OF)
            if self.index.type_of(a) is EntityType.ACTIVITY
        ]
        chain = [a for a in found if a.kind in BLOCK_ACTIVITY_ORDER]
        return tuple(sorted(chain, key=lambda a: (BLOCK_ACTIVITY_ORDER.index(a.kind), a.activity_id)))

    def started(self, activity: Activity) -> bool:
        """기준일까지 실제로 착수했는가(현장 실적 — 계획 추정은 쓰지 않는다)."""
        return activity.actual_start is not None and activity.actual_start <= self.as_of

    def finished(self, activity: Activity) -> bool:
        return activity.actual_finish is not None and activity.actual_finish <= self.as_of

    def start_on_confirm(self, activity: Activity) -> ActivityStart:
        """확정일 평가와 같은 공정 시계: 기준 일정(Baseline — 실적, 없으면 변경 없는 CPM 착수일 ES⁰).
        상태 함수(Propagator.state)·R-B01이 쓰는 시계와 같다. 처음 쓸 때 한 번 만든다."""
        if self._baseline is None:
            self._baseline = Baseline(self.index, self.as_of)
        return self._baseline.start(activity.activity_id)

    def rework_blocks(self) -> frozenset[str]:
        """분석이 재작업으로 본 블록(R-B01 영향)."""
        return frozenset(
            i.entity_id
            for i in self.result.impacts
            if i.entity_type is EntityType.BLOCK and i.impact_type is ImpactType.REWORK
        )

    def revision_list(self) -> frozenset[str]:
        """분석의 도면 개정 목록(R-D01 영향의 도면 ID)."""
        return frozenset(i.entity_id for i in self.result.impacts if i.impact_type is ImpactType.DRAWING_REVISION)

    def revised_parts(self) -> frozenset[str]:
        """R-D01이 도면 개정의 출발로 본 지도 부재(대상 + 이어서 바뀌는 이웃) — '바뀌는 부재'."""
        found = {
            i.path[-1].src
            for i in self.result.impacts
            if i.impact_type is ImpactType.DRAWING_REVISION and i.path and i.path[-1].relation is Relation.DRAWN_IN
        }
        return frozenset(p for p in found | set(self.changed) if p in self.index.parts)

    # ---------- 항목 ----------

    def item(
        self,
        rule: PrecheckRule,
        tag: str,
        anchor: str,
        *,
        finding: str,
        level: PrecheckLevel,
        targets: Iterable[str],
        evidence: Iterable[PrecheckLink],
        text: str,
        reason: str,
    ) -> PrecheckItem:
        return PrecheckItem(
            key=f"{rule}:{tag}:{anchor}",
            rule_id=rule,
            name=PRECHECK_RULE_NAMES[rule],
            finding=finding,
            level=level,
            targets=tuple(dict.fromkeys(targets)),
            evidence=tuple(dict.fromkeys(evidence)),
            text=text if len(text) <= PRECHECK_TEXT_MAX else text[: PRECHECK_TEXT_MAX - 1] + "…",
            reason=reason,
            ncr_count=None if self.counts is None else self.counts.get(rule, 0),
        )

    def unchecked(self, rule: PrecheckRule, targets: Iterable[str] = (), **fields: str) -> PrecheckItem:
        """'지도에 정보 없음 — 점검 불가' 항목(지어내지 않는다)."""
        return self.item(
            rule,
            "unchecked",
            "map",
            finding=UNCHECKED_FINDING,
            level=PrecheckLevel.UNCHECKED,
            targets=targets,
            evidence=(),
            text=UNCHECKED_TEXT[rule].format(**fields),
            reason=UNCHECKED_REASON,
        )


def link(src: str, dst: str, relation: Relation | str, *, virtual: bool = False) -> PrecheckLink:
    return PrecheckLink.model_validate({"src": src, "dst": dst, "relation": relation, "virtual": virtual})
