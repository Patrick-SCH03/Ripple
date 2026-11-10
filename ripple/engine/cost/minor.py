"""작은 작업(docs/engine.md(비용·일정) 4-5): 병합된 영향 하나 = 이음·작업 하나 × 공수 × 인건비.

도면 개정은 도면 분야로 공수를 고른다: 배관도는 `minor_work_hours.drawing_revision_piping`(현업 실제 사례), 그 밖은
`drawing_revision_per_drawing`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from ripple.contracts.domain import EntityType
from ripple.contracts.result import CostItem, CostLine, Impact, ImpactType, UnresolvedKind

from .amounts import Scenario, amount_of, hours_of
from .inputs import DESIGN_RATE, CostInput


@dataclass(frozen=True, slots=True)
class MinorWork:
    hours_key: str
    production: bool  # 생산 작업이면 블록 단가, 아니면 설계 단가
    label: str
    item: CostItem  # 공수 세부 구분(4-12): 용접 재검토 · 가공·수정 · 도면 개정


MINOR_WORKS: dict[ImpactType, MinorWork] = {
    ImpactType.TAPER: MinorWork("minor_work_hours.taper_per_joint", True, "테이퍼 가공", CostItem.MACHINING),
    ImpactType.WELD_RECHECK: MinorWork("minor_work_hours.weld_recheck_per_joint", False, "용접 재검토", CostItem.WELD),
    ImpactType.COLLAR_RESIZE: MinorWork(
        "minor_work_hours.collar_resize_each", True, "칼라 치수 변경", CostItem.MACHINING
    ),
    ImpactType.MODIFY_PART: MinorWork("minor_work_hours.modify_part_each", True, "부재 수정", CostItem.MACHINING),
    ImpactType.DRAWING_REVISION: MinorWork(
        "minor_work_hours.drawing_revision_per_drawing", False, "도면 개정", CostItem.DRAWING
    ),
}
REASONS: dict[tuple[str, ImpactType], str] = {
    ("R-T02", ImpactType.TAPER): "맞대기 용접한 {cause}의 두께 변경으로 두께 차 기준 초과 — 이음부 테이퍼 가공 필요",
    ("R-T03", ImpactType.WELD_RECHECK): "필릿 용접으로 붙은 {cause}의 두께 변경 — 용접 사양(각장 등) 재검토 필요",
    ("R-T04", ImpactType.COLLAR_RESIZE): "{cause}의 두께나 관통부 변경 — 이 배관이 지나는 칼라·슬리브 치수 변경 필요",
    ("R-P01", ImpactType.MODIFY_PART): "연결된 {cause}의 연결 규격(플랜지 등급·구경) 변경 — 플랜지·개스킷 교체 필요",
    (
        "R-P02",
        ImpactType.MODIFY_PART,
    ): "새 배관 경로가 이 판을 관통 — 관통부 가공 필요 · 구조 관통이라 설계자 확인 필요",
    ("R-P02", ImpactType.COLLAR_RESIZE): "새 배관 경로가 이 판을 관통 — 칼라·슬리브 새로 맞춤 필요",
    ("R-P03", ImpactType.MODIFY_PART): "이 서포트가 받치던 {cause}의 경로 변경 — 서포트 위치·형상 수정 필요",
    ("R-D01", ImpactType.DRAWING_REVISION): "바뀌는 부재가 그려진 도면 — 개정 필요(예: {cause})",
}
"""발생 사유: (규칙, 영향) → 문장. {cause}는 근거 경로의 마지막 단계에서 이 영향을 낸 엔터티."""
DRAWING_HOURS_BY_DISCIPLINE: dict[str, str] = {"piping": "minor_work_hours.drawing_revision_piping"}
"""도면 분야 → 도면 개정 공수 키(없는 분야는 MINOR_WORKS의 도면 하나 공수)."""
ASSUMED: dict[tuple[str, ImpactType], str] = {
    ("R-T02", ImpactType.TAPER): (
        "맞대기 용접한 {cause}의 두께 변경 · 이 판의 두께 정보 없음 — 테이퍼 가공 필요로 보고 계산(확인 필요)"
    ),
    ("R-P01", ImpactType.MODIFY_PART): (
        "연결된 {cause}의 새 사양 연결 규격(구경·압력 등급) 정보 없음 — 플랜지·개스킷 교체 필요로 보고 계산(확인 필요)"
    ),
}
"""근거 정보가 없어 영향을 가정한 경우의 문장(이웃 판 두께를 모름, 새 사양의 연결 규격을 모름): 단정하지 않는다."""


def minor_lines(inp: CostInput) -> tuple[CostLine, ...]:
    lines = []
    for impact in inp.propagation.impacts:
        work = MINOR_WORKS.get(impact.impact_type)
        if work is None:
            continue
        block = inp.view.block_of(impact.entity_id) if impact.entity_type is EntityType.PART else None
        rate_key = inp.production_rate(block) if work.production else DESIGN_RATE
        hours_key = _hours_key(inp, impact, work)
        hours, rate = inp.params.value(hours_key), inp.params.value(rate_key)

        def cost(s: Scenario, hours_key: str = hours_key, rate_key: str = rate_key) -> float:
            return inp.params.get(hours_key, s) * inp.params.get(rate_key, s)

        lines.append(
            inp.line(
                line_id=f"{impact.rule_id}:{impact.impact_type.value}:{impact.entity_id}",
                rule_id=impact.rule_id,
                entity_id=impact.entity_id,
                label=f"{inp.label(impact.entity_id)} {work.label}",
                formula=f"{hours:g}시간 × 인건비 {rate:,.0f}원/시간(대표값)",
                inputs={"count": 1},
                amount=amount_of(cost),
                param_keys=(hours_key, rate_key),
                item=work.item,
                hours=hours_of(partial(inp.params.get, hours_key)),
                reason=_reason(inp, impact, work),
            )
        )
    return tuple(lines)


def _hours_key(inp: CostInput, impact: Impact, work: MinorWork) -> str:
    """공수 키: 도면 개정이면 도면 분야별 키(배관도), 그 밖은 작업의 키."""
    if impact.impact_type is ImpactType.DRAWING_REVISION:
        drawing = inp.index.drawings.get(impact.entity_id)
        if drawing is not None:
            return DRAWING_HOURS_BY_DISCIPLINE.get(drawing.discipline, work.hours_key)
    return work.hours_key


def _reason(inp: CostInput, impact: Impact, work: MinorWork) -> str:
    cause = impact.path[-1].src if impact.path else None
    key = (impact.rule_id, impact.impact_type)
    template = ASSUMED.get(key) if cause is not None and _assumed(inp, impact, cause) else REASONS.get(key)
    if template is None or ("{cause}" in template and cause is None):
        return f"이 변경으로 {work.label} 작업 추가"
    return template.format(cause=inp.label(cause) if cause else "")


def _assumed(inp: CostInput, impact: Impact, cause: str) -> bool:
    """정보 부족으로 가정한 영향인가: 이웃 판 두께가 없음(R-T02), 새 사양의 연결 규격을 몰라 미해결로 남김(R-P01)."""
    if impact.rule_id == "R-T02":
        return inp.view.thickness(impact.entity_id) is None
    if impact.rule_id == "R-P01":
        return any(u.kind is UnresolvedKind.CONNECTION and u.entity_id == cause for u in inp.propagation.unresolved)
    return False
