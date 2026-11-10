"""화면용 부분 그래프: 중심 엔터티에서 깊이 n까지의 이웃과 그 사이 엣지."""

from __future__ import annotations

from collections.abc import Sequence

from ripple.contracts.domain import Relation
from ripple.contracts.graphview import GraphEdge, GraphView
from ripple.engine.describe import describe
from ripple.engine.index import GraphIndex

DEFAULT_MAX_NODES = 300
SYMMETRIC = frozenset(
    {Relation.BUTT_WELD, Relation.FILLET_WELD, Relation.PENETRATION, Relation.SUPPORT, Relation.PIPE_JOINT}
)


def neighborhood(
    index: GraphIndex, centers: Sequence[str], depth: int, max_nodes: int = DEFAULT_MAX_NODES
) -> GraphView:
    unknown = [c for c in centers if index.type_of(c) is None]
    if unknown:
        raise KeyError(f"지도에 없는 엔터티: {unknown[:3]}")
    if depth < 0 or max_nodes < 1:
        raise ValueError("깊이는 0 이상, 노드 상한은 1 이상 필요")
    seen: dict[str, None] = dict.fromkeys(sorted(set(centers)))
    truncated = len(seen) > max_nodes
    frontier = list(seen)
    for _ in range(depth):
        following: list[str] = []
        for node in frontier:
            for neighbour, _relation in index.neighbours(node):
                if neighbour in seen:
                    continue
                if len(seen) >= max_nodes:
                    truncated = True
                    break
                seen[neighbour] = None
                following.append(neighbour)
        frontier = following
    chosen = set(list(seen)[:max_nodes])
    edges = tuple(
        GraphEdge(source=e.source, target=e.target, relation=e.relation)
        for e in index.edges()
        if e.source in chosen and e.target in chosen and (e.relation not in SYMMETRIC or e.source < e.target)
    )
    return GraphView(
        snapshot_id=index.snapshot.snapshot_id,
        nodes=tuple(describe(index, entity_id) for entity_id in list(seen)[:max_nodes]),
        edges=edges,
        truncated=truncated,
    )
