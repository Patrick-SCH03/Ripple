"""실적(예측 대비 실제) 계약(계약 1.24.0, docs/records.md(기록·결재) 11절): 실행·종료한 설계변경의 실제 비용·구역 출구
지연.

담당자가 실행을 시작했거나 끝낸 ECN에 넣는다. 승인한 개정의 예측(총변경비용 대표·범위, 구역 출구 최대 지연)과 비교해
결재·현황 성과에 보이고, 쌓이면 비용 파라미터를 고칠 근거가 된다(보정 자체는 이번 범위 밖).
기록·감사 사슬과 따로 저장하고,
고치면 새 줄을 덧붙여 마지막 줄을 지금 값으로 쓴다(누가·언제 바꿨는지 남게).
"""

from __future__ import annotations

from pydantic import AwareDatetime, Field

from .base import Frozen
from .records import Actor, EcnId, RecordId
from .result import Amount

COST_MAX = 10**12  # 1조원: 입력 실수(자릿수) 막는 상한
NOTE_MAX = 200


class OutcomeInput(Frozen):
    """PUT /api/ecns/{ecn_id}/outcome 본문."""

    cost_krw: int = Field(ge=0, le=COST_MAX)  # 실제로 든 변경 비용(원)
    exit_delay_days: int | None = Field(default=None, ge=0, le=3650)  # 실제 구역 출구 지연(일, 모르면 비움)
    note: str = Field(default="", max_length=NOTE_MAX)


class OutcomeEntry(Frozen):
    """실적 한 줄(지금 값 = 그 ECN의 마지막 줄)."""

    ecn_id: EcnId
    revision: int = Field(ge=1)  # 승인한 개정
    record_id: RecordId
    cost_krw: int = Field(ge=0, le=COST_MAX)
    exit_delay_days: int | None = Field(default=None, ge=0, le=3650)
    note: str = Field(default="", max_length=NOTE_MAX)
    entered_by: Actor
    entered_at: AwareDatetime


class OutcomeRow(Frozen):
    """성과 '예측 대비 실적' 표 한 줄."""

    ecn_id: str
    title: str
    revision: int = Field(ge=1)
    predicted: Amount  # 승인한 개정의 총변경비용(대표·범위)
    actual_krw: int = Field(ge=0)
    error_rate: float | None = None  # (실제 − 예측 대표) ÷ 예측 대표. 예측이 0이면 None
    in_range: bool  # 실제가 예측 범위(최소~최대) 안
    predicted_delay_days: int = Field(ge=0)  # 승인한 개정의 구역 출구 최대 지연
    actual_delay_days: int | None = None
    entered_at: AwareDatetime


class OutcomeSummary(Frozen):
    count: int = Field(ge=0)
    median_abs_error: float | None = None  # |오차율|의 중앙값(예측이 0인 건 제외)
    in_range_rate: float | None = None
    rows: tuple[OutcomeRow, ...] = ()
