"""일정 망(docs/engine.md(비용·일정) 6-1): 호선마다 블록 공정과 구역 출구 이정표.

진수·인도처럼 이정표를 선행으로 갖는 이정표는 망에서 빼고, 인도 지연은 경계 조건으로 계산한다(delivery.py).
기준일 뒤 근거는 쓰지 않는다: 기준일까지 착수·완료한 실적만 실적으로 본다.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

from ripple.contracts.domain import BLOCK_ACTIVITY_ORDER, Activity, ActivityKind

from ..index import GraphIndex

BLOCK_SEQUENCE = BLOCK_ACTIVITY_ORDER


@dataclass(frozen=True, slots=True)
class Node:
    activity_id: str
    block_id: str | None
    kind: ActivityKind
    duration: int
    planned_start: date
    preds: tuple[tuple[str, int], ...]  # 망 안의 선행 (공정 ID, lag)
    started: date | None  # 기준일까지의 실제 착수일
    finished: date | None  # 기준일까지의 실제 완료일


@dataclass(frozen=True, slots=True)
class Network:
    ship_id: str
    as_of: date
    nodes: Mapping[str, Node]
    order: tuple[str, ...]  # 위상 순서(동률은 공정 ID 순)
    succs: Mapping[str, tuple[tuple[str, int], ...]]  # 공정 → (후행, lag)
    chains: Mapping[str, tuple[str, ...]]  # 블록 → 블록 공정(소조립 → … → 탑재 순)
    exits: tuple[str, ...]  # 구역 출구 이정표


def build_network(index: GraphIndex, ship_id: str, as_of: date) -> Network:
    activities = {a.activity_id: a for a in index.activities.values() if a.ship_id == ship_id}
    blocks = {a_id for a_id, a in activities.items() if a.kind is not ActivityKind.MILESTONE}
    exits = {
        a_id
        for a_id, a in activities.items()
        if a.kind is ActivityKind.MILESTONE and any(p.activity_id in blocks for p in a.predecessors)
    }
    members = blocks | exits
    return assemble(ship_id, as_of, [_node(activities[a_id], members, as_of) for a_id in sorted(members)])


def assemble(ship_id: str, as_of: date, nodes: list[Node]) -> Network:
    """공정 노드로 망을 만든다. 블록 공정(블록 ID가 있음)은 블록별 사슬로, 이정표는 구역 출구로 본다."""
    by_id = {node.activity_id: node for node in nodes}
    succs: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for node in nodes:
        for pred, lag in node.preds:
            succs[pred].append((node.activity_id, lag))
    chains: dict[str, list[str]] = defaultdict(list)
    blocks = [n for n in nodes if n.block_id is not None and n.kind in BLOCK_SEQUENCE]
    for node in sorted(blocks, key=lambda n: (n.block_id or "", BLOCK_SEQUENCE.index(n.kind))):
        chains[node.block_id or ""].append(node.activity_id)
    return Network(
        ship_id=ship_id,
        as_of=as_of,
        nodes=MappingProxyType(by_id),
        order=_topological(by_id),
        succs=MappingProxyType({k: tuple(sorted(v)) for k, v in succs.items()}),
        chains=MappingProxyType({k: tuple(v) for k, v in chains.items()}),
        exits=tuple(sorted(n.activity_id for n in nodes if n.kind is ActivityKind.MILESTONE)),
    )


def _node(activity: Activity, members: set[str], as_of: date) -> Node:
    started = activity.actual_start if activity.actual_start is not None and activity.actual_start <= as_of else None
    finished = (
        activity.actual_finish
        if started is not None and activity.actual_finish is not None and activity.actual_finish <= as_of
        else None
    )
    return Node(
        activity_id=activity.activity_id,
        block_id=activity.block_id,
        kind=activity.kind,
        duration=activity.duration_days,
        planned_start=activity.planned_start,
        preds=tuple(sorted((p.activity_id, p.lag_days) for p in activity.predecessors if p.activity_id in members)),
        started=started,
        finished=finished,
    )


def _topological(nodes: Mapping[str, Node]) -> tuple[str, ...]:
    """Kahn 알고리즘. 같은 차례면 공정 ID 순. 순환이 있으면 거부한다."""
    indegree = {a_id: len(node.preds) for a_id, node in nodes.items()}
    after: dict[str, list[str]] = defaultdict(list)
    for node in nodes.values():
        for pred, _ in node.preds:
            after[pred].append(node.activity_id)
    ready = [a_id for a_id, n in indegree.items() if n == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        current = heapq.heappop(ready)
        order.append(current)
        for nxt in after[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(ready, nxt)
    if len(order) != len(nodes):
        raise ValueError("공정 선후행에 순환 존재")
    return tuple(order)
