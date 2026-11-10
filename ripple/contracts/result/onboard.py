"""의장품 선상 설치 선택지 계약(명세 6-8): 같은 확정일·보류로 다른 실행 방식을 한 번 더 평가한 비교."""

from __future__ import annotations

from pydantic import Field, model_validator

from ..base import Frozen
from .amount import Amount
from .vocab import OnboardDirection


class OnboardOption(Frozen):
    """의장품 선상 설치 선택지(명세 6-8, 계약 1.29.0): 같은 확정일·보류로 다른 실행 방식을 한 번 더 평가한 비교.

    now = 이 분석(요청의 방식), then = 다른 방식. 판정·곡선·보류 권고·대안에는 쓰지 않는다(정보)."""

    direction: OnboardDirection
    block_ids: tuple[str, ...] = Field(min_length=1)  # 선상 설치 수요가 있는 블록(ID 순)
    part_ids: tuple[str, ...] = Field(min_length=1)  # 그 수요를 만든 부재(ID 순)
    on_board_days: int = Field(ge=1)  # 배 위 설치 일수 d_on(블록 중 최댓값)
    total_change: Amount  # then 총액 − now 총액(시나리오별 차이의 최소~최대)
    erection_delay_now_days: int = Field(ge=0)  # 대상 블록 탑재 지연의 최댓값
    erection_delay_then_days: int = Field(ge=0)
    exit_delay_now_days: int = Field(ge=0)  # 구역 출구 지연 최댓값
    exit_delay_then_days: int = Field(ge=0)
    delivery_added_now_days: int | None = Field(default=None, ge=0)  # 늘어난 인도 지연(None = 계산 불가)
    delivery_added_then_days: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _sorted(self) -> OnboardOption:
        for ids in (self.block_ids, self.part_ids):
            if list(ids) != sorted(set(ids)):
                raise ValueError("선상 설치 대상 블록·부재는 ID 순·중복 없음 필요")
        return self
