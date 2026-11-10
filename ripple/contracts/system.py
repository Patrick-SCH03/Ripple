"""시스템 상태 응답 계약. 배포 뒤 라이브 주소에서 버전을 확인하는 데 쓴다."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from .auth import AuthOptions
from .base import Frozen
from .domain import DataMode


class Health(Frozen):
    status: Literal["ok"] = "ok"
    app_version: str
    contract_version: str
    engine_version: str
    rules_version: str
    params_version: str
    strength_version: str  # 대안 강도 사전검사 규칙(rules/strength.yaml)
    decision_version: str
    # 활성 작업 공간의 유효 데이터 모드: 설정이나 활성 지도가 real이면 real(앱 시작 전이면 설정 값)
    data_mode: DataMode
    snapshot_id: str | None = None  # 활성 연결 지도(앱 시작 전이면 None)
    workspace: str | None = None  # 활성 작업 공간 토큰(ripple.contracts.workspace, 앱 시작 전이면 None)
    llm_external: bool = False  # 지금 외부 생성 모델을 부를 수 있는가(키가 있고 유효 모드가 synthetic)
    build: str | None = None  # 배포한 커밋(RIPPLE_BUILD·RAILWAY_GIT_COMMIT_SHA) — 라이브 주소의 버전 확인
    auth: AuthOptions | None = None  # 로그인 설정(앱 시작 전이면 None)


class LlmCall(Frozen):
    """외부 생성 모델 호출 한 번. 문장·응답·키는 담지 않는다."""

    at: datetime  # 호출이 끝난 시각(UTC)
    task: str  # rewrite(해석 보조) · explain(설명 고르기)
    model: str  # 어댑터 이름(제공자 모델 ID와 생각 깊이)
    ok: bool  # 오류 없이 답을 받았는가(작업 검사·사실 검사 전)
    error: str = ""  # 실패 종류(예외 이름)만
    latency_ms: int


class LlmCalls(Frozen):
    """관리자용 최근 외부 AI 호출(서버 메모리, 다시 켜면 비워짐). 최근 것부터."""

    external: bool  # 지금 외부 생성 모델을 부를 수 있는가(Health.llm_external과 같음)
    calls: tuple[LlmCall, ...] = ()
