"""결정 도우미 API(계약 1.31.0, docs/records.md(기록·결재) 결정 도우미 절).

GET /ecns/{ecn_id}/brief(승인(결재자) — 결재하는 사람만 보는 카드이고 외부 AI를 부를 수 있어 담당자·체험은 403):
그 ECN의 진행 중 검토(검토·보류) 개정의 기록 본문으로 세 줄 요약·서명 전 확인할 것을 만든다. 저장하지 않는다.
더 저렴한 대안 권고는 같은 지도·같은 계산 판일 때만 그 기록 요청을 대안 포함으로 한 번 계산해 쓴다(api/brief.py).
비슷한 과거 사례는 그 기록이 깔린 지도 기준(합성 기록 = 기록 지도 계보의 합성 묶음, 실데이터 기록 = 실데이터 묶음).
검토·보류 중이 아니면 409(invalid_transition), 기록이 없으면 404. 외부 AI 호출은 이 계정의 몫으로 센다.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from ripple.brief import BriefError
from ripple.cases import CaseShelf
from ripple.contracts.brief import DecisionBrief
from ripple.contracts.records import EcnState
from ripple.llm.quota import acting_as
from ripple.records.flow import FlowError
from ripple.records.metrics import business_today
from ripple.store.outcomes import OutcomeLog

from ..brief import BriefService, recorded_alternatives
from ..deps import AppContext, get_context
from ..generation import kst_today
from ..past_cases import finder_for
from ..security import ApprovePrincipal
from ..workspace import workspaces_of
from .records import PROBLEMS, EcnIdPath, Records, flow_problem, record_not_found

router = APIRouter(tags=["records"])
log = logging.getLogger(__name__)
WAITING = (EcnState.IN_REVIEW, EcnState.ON_HOLD)
BRIEF_RESPONSES: dict[int | str, dict[str, object]] = {
    **PROBLEMS,
    409: {"description": "검토·보류 중인 개정이 없음(detail = RecordProblem invalid_transition)"},
    500: {"description": "도우미 문장이 검사를 통과하지 못함(결재는 그대로 할 수 있음)"},
}


def get_brief(request: Request) -> BriefService:
    service = getattr(request.app.state, "brief", None)
    if not isinstance(service, BriefService):
        raise RuntimeError("결정 도우미 준비 안 됨")
    return service


@router.get("/ecns/{ecn_id}/brief", responses=BRIEF_RESPONSES)
def decision_brief(
    ecn_id: EcnIdPath,
    principal: ApprovePrincipal,
    request: Request,
    context: Annotated[AppContext, Depends(get_context)],
    records: Records,
    service: Annotated[BriefService, Depends(get_brief)],
) -> DecisionBrief:
    include_real = not principal.demo
    try:
        detail = records.detail(ecn_id, include_real=include_real, same_version=lambda _body: True)
        status = detail.status if detail is not None else None
        if detail is None or status is None:
            raise record_not_found()
        if status.state not in WAITING or status.review is None:
            raise flow_problem(FlowError(409, "invalid_transition", "결정 도우미는 검토·보류 중인 설계변경에서만 가능"))
        revision = status.review.revision
        summary = next((r for r in detail.revisions if r.revision == revision), None)
        found = records.record(summary.record_id, include_real=include_real) if summary is not None else None
    except FlowError as error:
        raise flow_problem(error) from None
    if summary is None or found is None:
        raise record_not_found()
    holder = workspaces_of(request)
    settings = context.settings
    shelf = getattr(request.app.state, "cases", None)
    outcomes = getattr(request.app.state, "outcomes", None)
    cases = (
        finder_for(shelf, holder, found.body, records, outcomes if isinstance(outcomes, OutcomeLog) else None)
        if isinstance(shelf, CaseShelf)
        else None
    )
    try:
        with acting_as(principal.login_id):
            return service.brief(
                found.body,
                record_id=summary.record_id,
                revision=revision,
                today=business_today(found.body, kst_today(), live=settings.live_world),
                model=None if holder is None else holder.model,
                configured=settings.data_mode,
                cases=cases,
                alternatives=lambda: recorded_alternatives(context, holder, found.body),
            )
    except BriefError as error:
        log.warning("결정 도우미 검사 불통과(%s %s): %s", ecn_id, summary.record_id, error)
        raise HTTPException(status_code=500, detail="결정 도우미 문장 생성 실패") from None
