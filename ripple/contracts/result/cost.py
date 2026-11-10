"""비용 줄 계약(docs/engine.md(비용·일정) 4절): 금액 한 줄(CostLine)과 그 줄이 쓴 가정값·확정이 늦어지면의 전망."""

from __future__ import annotations

from datetime import date

from pydantic import ConfigDict, Field, model_validator

from ..base import Frozen, omittable
from ..domain import BlockShape, SourceRef
from ..params import ParamStatus
from .amount import Amount
from .vocab import COST_ITEM_KIND, CostItem, CostKind, Determinacy, OutlookKind


class CostFactor(Frozen):
    """비용 줄이 쓴 가정값 하나(화면 '가정과 범위'). 파라미터 키 여러 개를 합친 값일 수 있다(단계까지의 톤당 공수 합).

    unit은 표시 단위다: "원/시간"·"원/t"(금액), "비율"(화면은 %), "시간"·"시간/t"·"시간/일"·"배"·"일"·"m"·"t".
    """

    label: str = Field(min_length=1)  # 현장 이름, 예: "인건비(직영)"
    unit: str
    value: float
    low: float
    high: float
    status: ParamStatus  # 합친 값은 가장 약한 상태(가정 < 현업 확인 < 근거 있음)
    mentor_question: int | None = Field(default=None, ge=1)  # docs/data.md(현업 확인 질문) 질문 번호
    keys: tuple[str, ...] = Field(min_length=1)  # 합친 파라미터 키(params YAML)

    @model_validator(mode="after")
    def _ordered(self) -> CostFactor:
        if not self.low <= self.value <= self.high:
            raise ValueError("가정값은 최소 ≤ 대표값 ≤ 최대 필요")
        return self


class LineOutlook(Frozen):
    """확정이 늦어지면: 확정일 다음날부터 탐색 기간 끝까지 이 비용 줄을 본 결과(분석 결과의 줄에만 둔다)."""

    kind: OutlookKind
    on: date | None = None  # CHANGES·REMOVED: 처음 그런 날
    amount: Amount | None = None  # CHANGES: 그날 확정하면 이 줄의 금액
    note: str | None = None  # CHANGES: 바뀐 이유(확정일 단계를 아는 줄의 단계 변화만)
    checked_until: date | None = None  # STEADY: 본 마지막 날

    @model_validator(mode="after")
    def _fields(self) -> LineOutlook:
        kind = self.kind
        if (self.on is not None) != (kind in (OutlookKind.CHANGES, OutlookKind.REMOVED)):
            raise ValueError("날짜는 금액이 바뀌거나 없어지는 경우에만 가능")
        if (self.amount is not None) != (kind is OutlookKind.CHANGES):
            raise ValueError("그날 금액은 금액이 바뀌는 경우에만 가능")
        if self.note is not None and kind is not OutlookKind.CHANGES:
            raise ValueError("바뀐 이유는 금액이 바뀌는 경우에만 가능")
        if (self.checked_until is not None) != (kind is OutlookKind.STEADY):
            raise ValueError("본 마지막 날은 그대로인 경우에만 가능")
        return self


class BlockDifficulty(Frozen):
    """블록 난이도 계수(1.32.0, docs/engine.md(비용·일정) 4-4): 형상 × 의장 밀도 × 전장품, 상한 cap.

    재작업 공수에만 곱하고 재작업 배수와 따로 보인다(화면이 '배수 n배' 하나로 합쳐 읽지 않게)."""

    shape: BlockShape | None = None  # 지도에 형상이 없으면 None(형상 계수 1)
    shape_factor: float = Field(ge=1)
    outfit_factor: float = Field(ge=1)
    electric_factor: float = Field(ge=1)
    cap: float = Field(ge=1)
    value: float = Field(ge=1)  # min(세 계수의 곱, cap)
    capped: bool = False  # 곱이 상한을 넘어 cap으로 줄였나

    @model_validator(mode="after")
    def _product(self) -> BlockDifficulty:
        product = self.shape_factor * self.outfit_factor * self.electric_factor
        if abs(self.value - min(product, self.cap)) > 1e-6 or self.capped != (product > self.cap + 1e-9):
            raise ValueError("난이도 계수는 세 계수의 곱(상한 적용) 필요")
        return self


HOURS_DIGITS = 3
"""공수(MH) 반올림 자리(비용 줄 inputs.hours와 같은 자리). 합계 검사는 반올림 오차((더한 수 + 1) × 1e-3) 안에서 본다."""
LINE_LATER_FIELDS = ("kind", "item", "hours")
"""1.35.0에 더한 비용 줄 필드: None이면 직렬화에서 빠져 옛 기록 본문의 기록 ID(본문 해시)가 그대로다. 응답 스키마에서도
필수·기본값이 아니게 둔다(base.omittable — AnalysisResult.weight_change와 같은 방식)."""


class WorkHours(Frozen):
    """공수(MH, 1.35.0): 대표 파라미터·범위 양 끝으로 계산한 시간. 그 줄의 금액(시나리오별)을 만든 바로 그 시간이다."""

    value: float = Field(ge=0)
    low: float = Field(ge=0)
    high: float = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> WorkHours:
        if not self.low <= self.value <= self.high:
            raise ValueError("공수는 최소 ≤ 대표값 ≤ 최대 필요")
        return self


class CostLine(Frozen):
    model_config = ConfigDict(json_schema_extra=omittable(*LINE_LATER_FIELDS))

    line_id: str
    rule_id: str
    entity_id: str
    label: str  # 화면에 보이는 항목 이름, 예: "PO-0123 변경·취소"
    formula: str  # 사람이 읽는 산식, 예: "취소율 30% × 발주액 1,240만원"
    inputs: dict[str, float | int | str]
    amount: Amount
    determinacy: Determinacy = Determinacy.KNOWN
    sources: tuple[SourceRef, ...] = ()
    param_keys: tuple[str, ...] = ()  # 쓴 파라미터 키(params YAML)
    reason: str | None = None  # 왜 생기나(현장 말 한 문장)
    factors: tuple[CostFactor, ...] = ()  # 쓴 가정값(param_keys를 현장 이름·단위·범위·근거 상태로)
    outlook: LineOutlook | None = None  # 확정이 늦어지면(분석 결과의 줄에만, 곡선 안의 줄은 없음)
    difficulty: BlockDifficulty | None = None  # 1.32.0 재작업 줄의 블록 난이도 계수(별도 표시)
    # 1.35.0 구분(docs/engine.md(비용·일정) 4-12): 공수 · 재료비 · 지체상금과 세부 구분, 공수 줄만 공수(MH).
    # None = 이 판 전 기록 — 직렬화에서 빠져 옛 기록 본문의 기록 ID가 그대로다
    kind: CostKind | None = Field(default=None, exclude_if=lambda kind: kind is None)
    item: CostItem | None = Field(default=None, exclude_if=lambda item: item is None)
    hours: WorkHours | None = Field(default=None, exclude_if=lambda hours: hours is None)

    @model_validator(mode="after")
    def _kind(self) -> CostLine:
        if (self.kind is None) != (self.item is None):
            raise ValueError("비용 줄 구분과 세부 구분은 함께 필요")
        if self.item is not None and COST_ITEM_KIND[self.item] is not self.kind:
            raise ValueError("비용 줄 세부 구분과 구분 불일치")
        if (self.hours is not None) != (self.kind is CostKind.LABOR):
            raise ValueError("공수(MH)는 공수 줄에만 필요")
        return self


class CostSplit(Frozen):
    """총변경비용의 구분별 합(1.35.0, docs/engine.md(비용·일정) 4-12): 공수 + 재료비 + 지체상금 = 총액(시나리오마다).

    재료비 = 자재 차이(자재비 차이·재고 전용) + 구매(발주 변경·취소·새 규격 발주 할증·잉여 자재 전용 취급비).
    공수(MH)는 공수 줄 공수의 합이다. 총액 밖 금액(지연 파급 비용·지체상금 노출)은 넣지 않는다."""

    labor_hours: WorkHours
    labor: Amount
    material: Amount
    material_diff: Amount
    purchase: Amount
    damages: Amount

    @model_validator(mode="after")
    def _material(self) -> CostSplit:
        if self.material != Amount.total([self.material_diff, self.purchase]):
            raise ValueError("재료비 = 자재 차이 + 구매 필요")
        return self
