"""상태·버전 확인."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ripple import __version__
from ripple.contracts.base import CONTRACT_VERSION
from ripple.contracts.system import Health
from ripple.engine import ENGINE_VERSION

from ..deps import AppContext, get_context
from ..security import get_auth
from ..workspace import current_workspace

router = APIRouter(tags=["system"])


@router.get("/health")
def read_health(request: Request, context: Annotated[AppContext, Depends(get_context)]) -> Health:
    workspace = current_workspace(request)
    return Health(
        app_version=__version__,
        contract_version=CONTRACT_VERSION,
        engine_version=ENGINE_VERSION,
        rules_version=context.rulebook.version,
        params_version=context.params.version,
        strength_version=context.strength.version,
        decision_version=context.decision.version,
        data_mode=context.settings.data_mode if workspace is None else workspace.data_mode,
        snapshot_id=None if workspace is None else workspace.snapshot.snapshot_id,
        workspace=None if workspace is None else workspace.token,
        llm_external=False if workspace is None else workspace.llm_external,
        build=context.settings.build,
        auth=get_auth(request).options() if workspace is not None else None,
    )
