"""참 일정 망과 전진 계산(docs/engine.md(비용·일정) 6-1·6-2): 블록 공정 + 블록 공정 뒤의 구역 출구."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

from ripple.contracts.domain import Activity, ActivityKind

from .common import DAY, WORK


def network(activities: Mapping[str, Activity]) -> tuple[tuple[str, ...], dict[str, Activity]]:
    """망의 공정(블록 공정·구역 출구 이정표)과 위상 순서(준비된 것 중 ID가 가장 앞선 것부터)."""
    blocks = {a_id for a_id, a in activities.items() if a.kind is not ActivityKind.MILESTONE}
    exits = {
        a_id
        for a_id, a in activities.items()
        if a.kind is ActivityKind.MILESTONE and any(p.activity_id in blocks for p in a.predecessors)
    }
    nodes = {a_id: activities[a_id] for a_id in sorted(blocks | exits)}
    pending = {a_id: sum(p.activity_id in nodes for p in a.predecessors) for a_id, a in nodes.items()}
    order: list[str] = []
    while pending:
        ready = min(a_id for a_id, count in pending.items() if count == 0)
        order.append(ready)
        del pending[ready]
        for a_id, a in nodes.items():
            if any(p.activity_id == ready for p in a.predecessors):
                pending[a_id] -= 1
    return tuple(order), nodes


def forward(
    order: tuple[str, ...],
    nodes: Mapping[str, Activity],
    as_of: date,
    floors: Mapping[str, date],
    extra: Mapping[str, int] | None = None,
    gates: Mapping[str, date] | None = None,
) -> tuple[dict[str, date], dict[str, date]]:
    """(착수일, 완료일). 기준일까지의 실적은 그대로, 진행 중은 남은 기간 + 추가 일수,
    미착수는 계획 착수·기준일 다음 날·착수 하한·관문·선행 완료 + 지연 중 늦은 날.
    """
    es: dict[str, date] = {}
    ef: dict[str, date] = {}
    extra = extra or {}
    gates = gates or {}
    for a_id in order:
        a = nodes[a_id]
        started = a.actual_start if a.actual_start is not None and a.actual_start <= as_of else None
        finished = a.actual_finish if a.actual_finish is not None and a.actual_finish <= as_of else None
        if finished is not None and started is not None:
            es[a_id], ef[a_id] = started, finished
        elif started is not None:
            es[a_id] = started
            ef[a_id] = max(started + timedelta(days=a.duration_days), as_of + DAY) + timedelta(days=extra.get(a_id, 0))
        else:
            preds = [ef[p.activity_id] + timedelta(days=p.lag_days) for p in a.predecessors if p.activity_id in nodes]
            es[a_id] = max(a.planned_start, as_of + DAY, floors.get(a_id, date.min), gates.get(a_id, date.min), *preds)
            ef[a_id] = es[a_id] + timedelta(days=a.duration_days + extra.get(a_id, 0))
    return es, ef


def block_chain(nodes: Mapping[str, Activity], block_id: str) -> list[Activity]:
    """블록 하나의 공정을 작업 순서(BLOCK_ACTIVITY_ORDER)대로."""
    return sorted((a for a in nodes.values() if a.block_id == block_id), key=lambda a: WORK.index(a.kind.value))
