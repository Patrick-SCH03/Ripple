"""현장 공유(P-06): 이 변경이 닿는 블록에서 이미 착수·완료한 공정을 맡은 수행 주체(작업반·직영)에게 통보."""

from __future__ import annotations

from ripple.contracts.domain import DIRECT_PERFORMER, Activity, Relation
from ripple.contracts.result import PrecheckItem, PrecheckLevel, PrecheckLink

from ..describe import ACTIVITY_NAMES
from .scope import Scope, link
from .text import DIRECT_NAME, FINDINGS, REASONS, UNKNOWN_PERFORMER, code_of, joined, listed


def sharing(scope: Scope) -> list[PrecheckItem]:
    """P-06: 영향 블록(대상·새 부재의 블록 + 분석이 재작업으로 본 블록)마다, 기준일까지 실제 착수한 블록 공정이 있으면
    그 공정의 수행 주체에게 통보 필수(확인 필요). 수행 주체가 지도에 없으면 '수행 주체 미상'으로 적는다."""
    items: list[PrecheckItem] = []
    for block in sorted(scope.scope_blocks | scope.rework_blocks()):
        started = [a for a in scope.block_activities(block) if scope.started(a)]
        if not started:
            continue
        done = [ACTIVITY_NAMES[a.kind] for a in started if scope.finished(a)]
        running = [ACTIVITY_NAMES[a.kind] for a in started if not scope.finished(a)]
        who = joined((_performer(scope, a) for a in started), 5)
        evidence: list[PrecheckLink] = [link(a.activity_id, block, Relation.PART_OF) for a in started]
        evidence += [link(a.activity_id, a.performer, "performed_by") for a in started if a.performer is not None]
        items.append(
            scope.item(
                "P-06",
                "notify",
                block,
                finding=FINDINGS["notify"],
                level=PrecheckLevel.CHECK,
                targets=(block, *(a.activity_id for a in started)),
                evidence=evidence,
                text=(
                    f"{code_of(block)} 블록에서 이미 한 공정({listed([('완료', done), ('진행 중', running)])})을 맡은 "
                    f"{who}에 변경 내용 통보 필요"
                ),
                reason=REASONS["notify"],
            )
        )
    return items


def _performer(scope: Scope, activity: Activity) -> str:
    performer = activity.performer
    if performer is None:
        return UNKNOWN_PERFORMER
    if performer == DIRECT_PERFORMER:
        return DIRECT_NAME
    crew = scope.index.crews.get(performer)
    return crew.name if crew is not None else performer
