"""결정 도우미 계약(계약 1.31.0): 팀장이 결재하는 순간 보는 세 줄 요약 · 서명 전 확인할 것 · 비슷한 과거 사례.

GET /api/ecns/{ecn_id}/brief가 돌려준다. 결재 대기(검토·보류) 중인 개정의 기록 본문(분석 결과)에서 읽을 때 계산하고
저장하지 않는다(기록 형식은 그대로). 숫자는 모두 엔진 결과·기록·실적에서 서버가 채운다 — AI는 미리 만든 후보 중에서
고르고 순서만 정한다(자유 글·숫자 없음). AI를 못 쓰면(꺼짐·실데이터·실패) 규칙 순서로 같은 모양을 만든다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import Frozen
from .domain import DataMode
from .records import EcnAction, EcnId, RecordId
from .result import Amount

BRIEF_TEXT_MAX = 300
BRIEF_TITLE_SHOWN = 120  # 세 줄의 change 줄에 싣는 변경 제목 글자 수(넘으면 말줄임표, 검사도 같은 값)


class BriefLine(Frozen):
    """세 줄 요약의 한 줄. 줄마다 종류가 하나씩(무엇이 바뀌나 → 안 정하면 무엇을 잃나 → 권고와 근거)."""

    kind: Literal["change", "loss", "advice"]
    text: str = Field(min_length=1, max_length=BRIEF_TEXT_MAX)  # 서버가 만든 문장(명사형, 숫자는 결과 필드에서)
    template_id: str = Field(min_length=1, max_length=80)  # 이 줄을 만든 서버 템플릿(검사·AI 고르기의 단위)


class BriefCheck(Frozen):
    """서명 전 확인할 것 하나: 판단이 기대고 있는 가정·추정 상태와, 그것이 틀리면 무엇이 달라지는지."""

    key: str = Field(min_length=1, max_length=200)  # 이 개정 안에서 고유
    text: str = Field(min_length=1, max_length=BRIEF_TEXT_MAX)  # 무엇을 확인할지(명사형)
    why: str = Field(min_length=1, max_length=BRIEF_TEXT_MAX)  # 틀리면 무엇이 달라지는지(명사형)
    computed: bool = False  # why가 그 가정을 바꿔 다시 계산한 결과인지(거짓이면 일반 안내 — 숫자 없음)
    entity_id: str | None = None  # 확인할 엔터티(발주·공정 등). 없으면 None


class PastCase(Frozen):
    """비슷한 과거 사례 하나(끝난 설계변경: 결정 · 예측 · 실적)."""

    case_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    same: tuple[str, ...] = ()  # 이번 건과 같은 점(예: '같은 블록 B31P', '같은 변경 종류 판 두께') — 비슷한 순서
    decision: Literal[EcnAction.APPROVE, EcnAction.REJECT, EcnAction.HOLD]
    chosen: str = Field(min_length=1, max_length=80)  # 무엇으로 진행했나(요청대로 · 대안 · 선상 설치 · 발주 보류 …)
    predicted: Amount  # 결정할 때의 총변경비용
    actual_krw: int | None = Field(default=None, ge=0)  # 실제로 든 변경 비용(실적이 없으면 None)
    predicted_delay_days: int = Field(default=0, ge=0)  # 결정할 때의 구역 출구 최대 지연
    actual_delay_days: int | None = Field(default=None, ge=0)
    days_before_deadline: int | None = None  # 추가손실 0 마감일보다 며칠 먼저 결정했나(음수 = 마감 뒤). 모르면 None
    note: str = Field(default="", max_length=BRIEF_TEXT_MAX)  # 한 줄 교훈(서버 템플릿)
    synthetic: bool  # 합성 과거 사례(시연용으로 만든 것)인지 — 화면에 늘 표시


class PastCases(Frozen):
    """비슷한 과거 사례 묶음과 한 줄 요약(예: '비슷한 3건 중 2건은 실적이 예측 초과')."""

    items: tuple[PastCase, ...] = ()  # 비슷한 순서, 최대 3건
    summary: str | None = Field(default=None, max_length=BRIEF_TEXT_MAX)  # 사례가 없으면 None
    library_size: int = Field(default=0, ge=0)  # 찾아본 과거 사례 수
    synthetic: bool = False  # 사례 묶음이 합성인지
    # 묶음 상태: ready = 찾아봄(0건일 수 있음) · building = 기본 지도를 깔 때 백그라운드로 만드는 중(빈 묶음) ·
    # unavailable = 이 지도에는 과거 사례 묶음이 없음(생성 세계와 다른 지도)
    status: Literal["ready", "building", "unavailable"] = "ready"


class DecisionBrief(Frozen):
    """결정 도우미 응답."""

    ecn_id: EcnId
    revision: int = Field(ge=1)
    record_id: RecordId
    data_mode: DataMode
    lines: tuple[BriefLine, ...] = Field(min_length=3, max_length=3)  # change · loss · advice 순서
    checks: tuple[BriefCheck, ...] = Field(default=(), max_length=3)
    cases: PastCases = PastCases()
    picked_by: Literal["ai", "rule"]  # 줄·확인할 것을 AI가 골랐나(숫자는 어느 쪽이든 엔진)
