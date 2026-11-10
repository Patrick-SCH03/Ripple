"""판단 근거 계약: 판단이 걸린 상태(docs/domain.md 12절)와 연결 추적(docs/domain.md 13절)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import model_validator

from ..base import Frozen
from ..domain import POStatus
from .vocab import BasisKind


class StateBasis(Frozen):
    """이 판단이 걸린 상태 하나(docs/domain.md 12절): 기준일에 보류 없이 계산한 바탕 상태.

    확정일·곡선·보류 시나리오의 미래 상태는 넣지 않는다 — 화면의 '맞음'이 이 값을 그날(기준일)의 사실로 남기므로.
    """

    entity_type: Literal["po", "activity"]
    entity_id: str
    label: str
    as_of: date  # 이 상태를 계산한 날(기준일)
    po_status: POStatus | None = None  # 발주: 기준일의 대표 단계(None = 판단 불가)
    actual_start: date | None = None  # 공정: 기준일까지 확인된 실제 착수·완료일
    actual_finish: date | None = None
    expected_start: date | None = None  # 공정: 실적이 없으면 기준 일정의 예상 착수일
    basis: BasisKind
    last_confirmed: date | None = None  # 기준일까지 마지막으로 확인한 날(관측·진입일 / 실적·현장 확인)
    line_ids: tuple[str, ...] = ()  # 이 상태에 걸린 비용 줄
    hold: bool = False  # 보류 권고 대상 발주
    via: tuple[str, ...] = ()  # 이 항목을 데려온 발주 품목·블록(공정 행: '이 품목을 쓰는 공정')

    @model_validator(mode="after")
    def _shape(self) -> StateBasis:
        if self.entity_type == "activity" and self.po_status is not None:
            raise ValueError("공정 행에 발주 단계 불가")
        if self.entity_type == "po" and (self.actual_start or self.actual_finish or self.expected_start):
            raise ValueError("발주 행에 공정 날짜 불가")
        return self


class TraceLink(Frozen):
    """연결 추적의 고리 하나(계약 1.23.0, docs/domain.md 13절): 지도 연결과 이번 변경 영향을 따로 표시."""

    kind: Literal["drawing", "block", "po_line", "activity"]
    entity_id: str
    label: str
    status: str | None = None  # 기준일 상태(블록 단계·발주 단계 이름·공정 착수/완료). 모르면 None
    affected: bool = False  # 이번 변경의 영향·비용 줄이 이 엔터티를 가리킴


class TraceChain(Frozen):
    """대상 부재 하나의 EBOM → MBOM → 구매 → 시공 사슬. 고리가 없으면 gaps에 이유(지도 연결 없음)."""

    part_id: str
    label: str
    new: bool = False  # 이 변경이 새로 만드는 부재(NEW:…)
    removed: bool = False  # 이 변경이 빼는 부재
    drawing: TraceLink | None = None  # EBOM: 도면@개정
    block: TraceLink | None = None  # MBOM: 블록(생산 단위)
    po_lines: tuple[TraceLink, ...] = ()  # 구매: 공급 발주 품목(여럿일 수 있음)
    activities: tuple[TraceLink, ...] = ()  # 시공: 품목을 소비하는 공정 + 블록 공정(다음 착수)
    gaps: tuple[str, ...] = ()  # 끊긴 고리(지도에 연결이 없음)
