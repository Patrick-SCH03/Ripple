"""화면의 샘플 설계변경 목록."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..samples import Sample
from ..workspace import Workspace, get_workspace

router = APIRouter(tags=["samples"])


@router.get("/samples")
def list_samples(workspace: Annotated[Workspace, Depends(get_workspace)]) -> list[Sample]:
    return list(workspace.samples)
