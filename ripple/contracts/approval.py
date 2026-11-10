"""결재선·결재 계획 계약(계약 1.33.0, docs/records.md(기록·결재) 14절).

분석 결과(AnalysisResult.approval_plan — API가 응답에 덧붙임)·기록 상세·결재함 줄·기록 조회가 같은 결재 계획을 싣는다.
규칙(무비용 판정·결재선·단계당 근무일·주말 제외 날짜 셈·보류 권고의 결재 기간 문구)은 서버 ripple/records/approval.py
한 곳에만 있고, 화면·엑셀은 이 값만 쓴다. 엔진 계산·관문 값과는 무관하다(엔진 밖 설정).
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from .base import Frozen


class ApprovalStep(StrEnum):
    """결재선 단계(추가 비용 건: 파트장 → 팀장 → 본부장·실장). 단계 수는 검토 요청 때 ReviewInfo에 고정한다."""

    PART_LEAD = "part_lead"  # 파트장
    TEAM_LEAD = "team_lead"  # 팀장(관리자 역할 — 파트장·본부장 단계를 전결할 수 있음)
    EXECUTIVE = "executive"  # 본부장·실장


LEGACY_LINE: tuple[ApprovalStep, ...] = (ApprovalStep.TEAM_LEAD,)
"""형식 판 3까지의 검토(단계 없음) = 팀장 한 단계('1/1단계'로 읽는다)."""


class HoldApproval(Frozen):
    """보류 권고 하나와 결재 기간(기준일부터 결재선 전체 근무일)의 관계. 엔진 보류 권고(max_hold_days·hold_until)는
    그대로 두고 '결재 중 보류 유지 가능 · 권고 기간까지는 공급사 협의'로 읽게 하는 문구다(화면·엑셀이 그대로 씀).

    - outlasts: 권고 보류 마지막 날이 결재가 끝나는 날(approval_end)보다 뒤.
    - text: 한 줄(명사형 조각), short: 요약 복사용 꼬리. 무비용이면 둘 다 '담당자 처리 — 결재 없음'.
    """

    po_id: str
    outlasts: bool = False
    approval_end: date | None = None  # 기준일 + 결재선 전체 근무일(무비용이면 None)
    text: str = Field(min_length=1)
    short: str = Field(min_length=1)


class ApprovalPlan(Frozen):
    """결재 소요와 결재 올릴 기한. 읽을 때 계산하고 저장하지 않는다 — 업무상 오늘에 따라 바뀐다.

    - no_cost: 비용 줄이 도면 개정(R-D01)뿐(판단 불가 줄·지체상금 노출 없음)이고 판정이 '승인 가능' → 결재선 없이
      담당자 처리.
    - line: 결재선 단계 이름(검토 전 = 검토를 요청하면 고정될 결재선, 검토 중 = 그 검토에 고정한 결재선). 화면이
      결재선 글을 이 값으로 만든다(화면 상수 없음). 비면(옛 응답) 모른다.
    - steps: 남은 결재 단계(검토 전 = 결재선 전체, 검토 중 = 지금 단계부터). 무비용이고 검토 전이면 비움.
    - line_steps: 결재 기간에 세는 결재선 단계 수(검토 전 무비용이면 0, 그 밖은 결재선 전체) — 보류 권고의 결재
      기간(holds)에 쓴다. 무비용 개정도 검토 중이면 결재선 전체다.
    - submit_by: 결재 올릴 기한 — 그날부터 근무일(남은 단계 × 단계당 대표 근무일)이 지나도 결정 기한을 넘지 않는
      마지막 근무일(기한이 토·일이면 그날 이하 마지막 근무일 기준, 주말 제외·공휴일 무시). 남은 단계가 없거나
      탐색 기간 안 손실이 없으면(none_in_horizon) None.
    - late: 오늘 올려도 결정 기한 안에 결재가 끝나지 않음(업무상 오늘 + 근무일 > 결정 기한 — 이미 지남). 업무상
      오늘이 평일이면 submit_by가 오늘보다 앞인 것과 같고, 토·일이면 그 앞 금요일에 올린 것과 같다. 그때 earliest =
      업무상 오늘 + 같은 근무일(오늘 올려도 결정은 빨라야 이날) · earliest_loss = 그날 확정의 추가손실(곡선 대표값,
      곡선 밖이면 None).
    - holds: 분석의 보류 권고마다 결재 기간과의 관계(HoldApproval).
    - submit_by_low: 단계마다 하루(days_per_step_low)로 결재되면 결재 올릴 기한 — submit_by와 같은 규칙(남은 단계 ×
      단계당 1근무일). late_low = 단계당 1일로 결재돼도 오늘 올려서는 결정 기한 안에 끝나지 않음(late와 같은 꼴). 대표
      (단계당 2일) 기한이 지났어도 빠른 결재로 결정 기한 안에 들 수 있는지 보인다(1.33.0 안에서 더함, 선택).
    - decide_by_workday: 결정 기한 이하 마지막 근무일(토·일 기한이면 그 앞 금요일, 공휴일 무시). 확정 단추가 주말을
      권하지 않게 쓴다(결정 기한 표시는 그대로). 탐색 기간 안 손실이 없으면(none_in_horizon) None(1.33.0 안, 선택).
      그날이 업무상 오늘보다 앞이면(예: 업무상 오늘 토요일 · 결정 기한 일요일) None — 지난 근무일을 권하지 않는다.
    """

    no_cost: bool
    line: tuple[ApprovalStep, ...] = ()  # 결재선 단계 이름(1.33.0 안에서 더함, 선택)
    steps: tuple[ApprovalStep, ...] = ()
    line_steps: int = Field(default=0, ge=0)
    days_per_step_low: int = Field(ge=0)
    days_per_step: int = Field(ge=0)  # 단계당 대표 근무일
    workdays: int = Field(ge=0)  # 남은 결재 소요(근무일, 대표)
    submit_by: date | None = None
    late: bool = False
    earliest: date | None = None
    earliest_loss: int | None = None
    holds: tuple[HoldApproval, ...] = ()
    submit_by_low: date | None = None  # 단계당 1근무일로 결재되면 결재 올릴 기한(1.33.0 안에서 더함, 선택)
    late_low: bool = False
    decide_by_workday: date | None = None  # 결정 기한 이하 마지막 근무일(1.33.0 안에서 더함, 선택)

    @model_validator(mode="after")
    def _consistent(self) -> ApprovalPlan:
        if self.workdays != len(self.steps) * self.days_per_step or self.days_per_step_low > self.days_per_step:
            raise ValueError("결재 소요가 남은 단계 × 단계당 대표 근무일과 다름")
        if not self.steps and self.submit_by is not None:
            raise ValueError("남은 결재 단계가 없는데 결재 올릴 기한 있음")
        if self.line and (
            self.line_steps not in (0, len(self.line)) or self.line[len(self.line) - len(self.steps) :] != self.steps
        ):
            raise ValueError("남은 결재 단계가 결재선 뒤쪽이 아니거나 결재 기간 단계 수가 0·결재선 전체가 아님")
        if self.late != (self.earliest is not None) or (self.late and self.submit_by is None):
            raise ValueError("'결정은 빨라야' 날짜는 이미 지난 결재 올릴 기한에만 허용")
        if self.earliest_loss is not None and not self.late:
            raise ValueError("그날 추가손실은 이미 지난 기한에만 허용")
        if (self.submit_by_low is not None and self.submit_by is None) or (
            self.late_low and self.submit_by_low is None
        ):
            raise ValueError("단계당 1일 기한은 결재 올릴 기한이 있을 때만, 지남은 그 기한이 있을 때만 허용")
        if self.late_low and not self.late:
            raise ValueError("단계당 1일 기한은 지났는데 대표 기한은 안 지남")
        if self.decide_by_workday is not None and self.decide_by_workday.weekday() >= 5:
            raise ValueError("결정 기한의 근무일이 토·일")
        return self
