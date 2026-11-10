"""분석 요청 계약과 버전 묶음.

분석 ID(identity.analysis_id)는 결과를 바꾸는 입력만으로 정한다: 버전 묶음 +
정규화된 요청. 같은 ID면 같은 결과여야 한다.
"""

from __future__ import annotations

from datetime import date

from pydantic import Field, model_validator

from .base import Frozen
from .change import ChangeRequest


class Versions(Frozen):
    contract: str
    snapshot_id: str  # 연결 지도 내용 해시
    rules: str  # 전파 규칙표 버전
    params: str  # 비용 파라미터 버전
    engine: str
    strength: str | None = None  # 강도 사전검사 규칙 버전(대안 포함 분석에서만, docs/engine.md(대안) 6절)


MAX_HOLD_DAYS = 365
"""발주 보류 하루 상한. 엔진의 보류 권고 기간도 이 상한으로 자른다(docs/engine.md(비용·일정) 8-3)."""


class HoldAction(Frozen):
    """발주 보류: 기준일부터 hold_days 동안 그 발주의 남은 단계를 모두 미룬다."""

    po_id: str
    hold_days: int = Field(ge=1, le=MAX_HOLD_DAYS)


class AnalysisRequest(Frozen):
    change: ChangeRequest
    as_of: date  # 기준일
    confirm_on: date | None = None  # 확정일. 없으면 기준일
    horizon_days: int = Field(default=60, ge=1, le=365)  # 추가손실 곡선 탐색 기간
    holds: tuple[HoldAction, ...] = ()
    include_alternatives: bool = False
    # 1.29.0 의장품 선상 설치: 늦게 오는 배관·밸브·부속 때문에 탑재를 기다리지 않고 탑재 뒤 배 위에서 설치(명세 6-3)
    outfit_on_board: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> AnalysisRequest:
        if self.confirm_on is not None and self.confirm_on < self.as_of:
            raise ValueError("확정일이 기준일보다 앞섬")
        po_ids = [h.po_id for h in self.holds]
        if len(set(po_ids)) != len(po_ids):
            raise ValueError("같은 발주 보류 중복")
        return self

    @property
    def effective_confirm_on(self) -> date:
        return self.confirm_on or self.as_of
