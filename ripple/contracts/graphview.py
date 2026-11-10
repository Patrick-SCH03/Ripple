"""화면용 부분 그래프 계약. 원본 지도의 이웃과, 변경 후 보기에서 생긴 임시 노드·연결을 같은 형식으로 담는다."""

from __future__ import annotations

from pydantic import Field, model_validator

from .base import Frozen
from .domain import EntityType, Relation

AttrValue = str | float | int | bool | None


class GraphNode(Frozen):
    id: str
    type: EntityType
    label: str  # 화면에 보이는 이름
    attrs: dict[str, AttrValue] = Field(default_factory=dict)  # 두께·강종·단계 같은 일부 속성
    virtual: bool = False  # 변경 후 보기에서 생긴 임시 노드


class GraphEdge(Frozen):
    source: str
    target: str
    relation: Relation
    virtual: bool = False  # 변경 후 보기에서 생긴 임시 연결


class GraphView(Frozen):
    snapshot_id: str
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    truncated: bool = False  # 노드 상한에 걸려 일부만 담았으면 True

    @model_validator(mode="after")
    def _consistent(self) -> GraphView:
        ids = [n.id for n in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("노드 ID 중복")
        known = set(ids)
        if any(e.source not in known or e.target not in known for e in self.edges):
            raise ValueError("엣지 끝이 노드 목록에 없음")
        return self
