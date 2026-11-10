"""대안 계약(docs/engine.md(대안) 6절): 대안별 충족 여부·비용·최적 조합, 날짜별 가장 싼 대안, 권고."""

from __future__ import annotations

from datetime import date

from pydantic import Field, model_validator

from ..analysis import HoldAction
from ..base import Frozen
from ..change import ChangeOp
from .amount import Amount
from .timing import ZeroLossDeadline
from .vocab import AlternativeOrigin, Eligibility

REQUEST_ALT = "ALT-REQ"
"""요청안의 대안 ID(대안 목록의 첫 항목)."""


class EligibilityCheck(Frozen):
    status: Eligibility
    criterion: str  # 의도별 필수 조건, 예: "보강재 단면계수 비율 ≥ 1"
    basis: str = ""  # 쓴 식의 형태와 조항 번호(원문 없음)
    ratio_vs_request: float | None = None
    note: str = ""  # 왜 충족·부족·설계자 확인인지(현장 말)


class AlternativeResult(Frozen):
    alt_id: str
    label: str
    origin: AlternativeOrigin
    ops: tuple[ChangeOp, ...] = Field(min_length=1)
    scope_reduced: bool = False  # 적용 범위를 줄인 대안
    eligibility: EligibilityCheck
    total: Amount
    max_exit_delay_days: int = Field(ge=0)
    impacted_count: int = Field(ge=0)
    deadline: ZeroLossDeadline | None = None  # 이 대안의 추가손실 0 마감일
    best_confirm_on: date | None = None  # 최적 조합의 확정일(충족만)
    best_total: Amount | None = None  # 최적 조합의 총변경비용(충족만)
    best_holds: tuple[HoldAction, ...] = ()  # 최적 조합의 보류(발주·일수, 충족만)
    rank: int | None = Field(default=None, ge=1)  # 충족 대안 사이의 총비용 순위

    @model_validator(mode="after")
    def _gating(self) -> AlternativeResult:
        meets = self.eligibility.status is Eligibility.MEETS
        if self.scope_reduced and self.eligibility.status is not Eligibility.DESIGNER:
            raise ValueError("적용 범위를 줄인 대안은 항상 설계자 확인")
        if self.origin is AlternativeOrigin.REQUEST and not meets:
            raise ValueError("요청안은 비교 기준이라 늘 충족")
        best = (self.rank, self.best_confirm_on, self.best_total)
        if meets and any(value is None for value in best):
            raise ValueError("충족 대안은 순위·최적 확정일·최적 총액 필요")
        if not meets and (any(value is not None for value in best) or self.best_holds):
            raise ValueError("충족 아닌 대안은 순위·권고 시점 불가")
        return self


class CheapestSpan(Frozen):
    """확정일 구간마다 가장 싼 충족 대안(곡선의 대표값, 요청의 보류만). 확정을 미룰 때 무엇이 가장 싼지."""

    alt_id: str
    start: date
    end: date
    total: Amount  # 시작일의 총변경비용

    @model_validator(mode="after")
    def _ordered(self) -> CheapestSpan:
        if self.end < self.start:
            raise ValueError("구간 끝일이 시작일보다 앞섬")
        return self


class Recommendation(Frozen):
    """권고: 충족 대안 중 1위의 최적 조합(대안·확정일·보류 행동). 이 조건으로 다시 분석하면 총액이 같다."""

    alt_id: str
    confirm_on: date
    holds: tuple[HoldAction, ...] = ()
    total: Amount
