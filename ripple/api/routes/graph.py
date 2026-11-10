"""연결 지도 둘러보기: 중심 엔터티에서 깊이 n까지의 부분 그래프."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ripple.contracts.graphview import GraphView
from ripple.graph.view import DEFAULT_MAX_NODES, neighborhood

from ..workspace import Workspace, get_workspace

router = APIRouter(tags=["graph"])


@router.get("/graph/view", responses={status.HTTP_404_NOT_FOUND: {"description": "지도에 없는 엔터티"}})
def read_view(
    workspace: Annotated[Workspace, Depends(get_workspace)],
    center: Annotated[list[str], Query(min_length=1, description="중심 엔터티 ID(여러 개 가능)")],
    depth: Annotated[int, Query(ge=0, le=4)] = 1,
    max_nodes: Annotated[int, Query(ge=1, le=2000)] = DEFAULT_MAX_NODES,
) -> GraphView:
    try:
        return neighborhood(workspace.index, center, depth, max_nodes)
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error.args[0])) from None
