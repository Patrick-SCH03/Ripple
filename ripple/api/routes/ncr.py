"""합성 NCR 요약(1.32.0 안에서 추가, docs/records.md '합성 NCR').

GET /ncrs/summary?recent=(승인(결재자), 결정 도우미의 비슷한 과거 사례와 같은 권한): 유형별 건수(사전 점검 P-01~P-06 +
기타 2종)와 최근 n건. 모든 문장에 '합성 묶음(시연)', 건수만(비율·금액 없음). 활성 작업 공간이 실데이터 모드면 빈 요약 +
이유(available = false). 저장하지 않는다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ripple.contracts.ncr import NcrSummary

from ..ncr import ncr_summary
from ..security import AUTH_RESPONSES, require_approve
from ..workspace import Workspace, get_workspace

router = APIRouter(tags=["records"])


@router.get("/ncrs/summary", responses=AUTH_RESPONSES, dependencies=[Depends(require_approve)])
def synthetic_ncr_summary(
    workspace: Annotated[Workspace, Depends(get_workspace)],
    recent: Annotated[int | None, Query(ge=1, le=20, description="최근 몇 건(없으면 설정값)")] = None,
) -> NcrSummary:
    return ncr_summary(workspace.data_mode, recent)
