"""분석 결과의 어휘(열거형): 영향 종류·심각도·확정성·계산 불가·확정 지연 전망·마감일·충족 여부·판정·대안 출처·
선상 설치 방향·중량 출처·비용 구분·상태 근거."""

from __future__ import annotations

from enum import StrEnum


class ImpactType(StrEnum):
    MODIFY_PART = "modify_part"
    PO_CHANGE = "po_change"  # 발주 변경·취소
    REORDER = "reorder"  # 새 규격 발주
    PO_HOLD = "po_hold"  # 발주 보류 권고
    REWORK = "rework"  # 블록 재작업
    TAPER = "taper"  # 인접 판 두께 전이 가공
    WELD_RECHECK = "weld_recheck"
    COLLAR_RESIZE = "collar_resize"
    DRAWING_REVISION = "drawing_revision"
    SCHEDULE_DELAY = "schedule_delay"
    DELIVERY_DELAY = "delivery_delay"
    REALLOCATE_STOCK = "reallocate_stock"  # 잉여 자재 전용
    NEEDS_CONFIRMATION = "needs_confirmation"  # 연결이 끊겨 계산에서 뺀 경로


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Determinacy(StrEnum):
    KNOWN = "known"  # 상태를 알고 계산함(범위는 파라미터 범위만)
    STATE_UNKNOWN = "state_unknown"  # 상태를 몰라 가능한 구간 전체를 범위로 냄 → 화면에 '판단 불가'


class UnresolvedKind(StrEnum):
    DELIVERY = "delivery"  # 경계 조건이 없어 인도 지연·지체상금 계산 불가
    PO_STATE = "po_state"
    BLOCK_STAGE = "block_stage"
    CONNECTION = "connection"  # 연결 정보 없음(R-X01)
    STRENGTH_INPUTS = "strength_inputs"  # 강도 사전검사 입력 부족


class OutlookKind(StrEnum):
    """확정이 늦어지면 이 비용 줄이 어떻게 되는가(확정일 다음날부터 탐색 기간 끝까지 본 결과)."""

    CHANGES = "changes"  # 금액이 처음 바뀌는 날이 있음
    REMOVED = "removed"  # 금액이 바뀌기 전에 이 비용이 없어지는 날이 있음
    STEADY = "steady"  # 본 마지막 날까지 그대로
    UNCHECKED = "unchecked"  # 확정일 뒤로 평가한 날이 없음(확정일이 탐색 기간 끝)


class DeadlineKind(StrEnum):
    CONFIRM_NOW = "confirm_now"  # 다음 날 바로 추가손실이 생김
    BY_DATE = "by_date"  # 마감일까지 확정하면 추가손실 0
    NONE_IN_HORIZON = "none_in_horizon"  # 탐색 기간 끝까지 추가손실 0


class Eligibility(StrEnum):
    MEETS = "meets"  # 충족(예비)
    SHORT = "short"  # 부족
    DESIGNER = "designer"  # 설계자 확인


class VerdictLevel(StrEnum):
    APPROVE = "approve"  # 승인 가능
    REVIEW = "review"  # 검토 필요
    WARN = "warn"  # 경고


VERDICT_NAMES: dict[str, str] = {
    VerdictLevel.APPROVE: "승인 가능",
    VerdictLevel.REVIEW: "검토 필요",
    VerdictLevel.WARN: "경고",
}
"""판정 이름(결정 도우미·AI 비서 답·엑셀 내보내기가 같은 이름을 쓴다, 화면은 web/src/lib/labels.ts)."""


class AlternativeOrigin(StrEnum):
    REQUEST = "request"  # 요청안
    TEMPLATE = "template"
    LLM = "llm"
    USER = "user"


class OnboardDirection(StrEnum):
    TO_ON_BOARD = "to_on_board"  # 지금은 탑재를 기다림 → 선상 설치로 바꾸면
    TO_WAIT = "to_wait"  # 지금은 선상 설치 → 탑재를 기다리는 방식으로 되돌리면


class WeightSource(StrEnum):
    """부재 중량을 무엇으로 셌나(1.34.0 중량 변화, docs/engine.md(비용·일정) 12절)."""

    QTY_T = "qty_t"  # 규격 단위 t의 수량(자재비 차이 C-01 줄의 qty·new_qty와 같은 값)
    WEIGHT_KG = "weight_kg"  # 지도의 부재 중량(Part.weight_kg ÷ 1000) — 단위가 t가 아닌 부재
    NONE = "none"  # 중량 정보 없음(새 중량을 정할 규칙·값이 없음)


class CostKind(StrEnum):
    """비용 줄 구분(1.35.0, docs/engine.md(비용·일정) 4-12): 추가 공수 · 추가 재료비 · 지체상금(둘에 맞지 않음)."""

    LABOR = "labor"  # 공수(시간 × 인건비) — 줄에 그 금액을 만든 공수(MH)
    MATERIAL = "material"  # 재료비(자재 차이 · 구매)
    DAMAGES = "damages"  # 지체상금(총액 안, 공수·재료비 밖)


class CostItem(StrEnum):
    """비용 줄 세부 구분(1.35.0): 공수는 작업 종류, 재료비는 자재 차이 묶음과 구매 묶음."""

    REWORK = "rework"  # 블록 재작업(R-B01, 작업반 몫 포함)
    NEW_WORK = "new_work"  # 새 부재 제작(C-02)
    ONBOARD = "onboard"  # 후행 설치 할증(C-03)
    AFTER_PAINT = "after_paint"  # 도장 뒤 재작업 고정 항목(C-04)
    WELD = "weld"  # 용접 재검토(R-T03)
    MACHINING = "machining"  # 가공·수정(테이퍼 R-T02 · 칼라 R-T04·R-P02 · 부재 수정 R-P01·R-P02·R-P03)
    DRAWING = "drawing"  # 도면 개정(R-D01)
    MATERIAL_DIFF = "material_diff"  # 자재비 차이(C-01)
    STOCK = "stock"  # 재고 전용(R-M01 가) — 사지 않는 자재비 − 취급비
    PO_CHANGE = "po_change"  # 발주 변경·취소(R-T01·R-M02) — 구매
    REORDER = "reorder"  # 새 규격 발주 할증(R-T01) — 구매
    TRANSFER = "transfer"  # 잉여 자재 다른 블록 전용 취급비(R-M01 나) — 구매
    LIQUIDATED_DAMAGES = "liquidated_damages"  # 지체상금(R-L01)


COST_ITEM_KIND: dict[CostItem, CostKind] = {
    CostItem.REWORK: CostKind.LABOR,
    CostItem.NEW_WORK: CostKind.LABOR,
    CostItem.ONBOARD: CostKind.LABOR,
    CostItem.AFTER_PAINT: CostKind.LABOR,
    CostItem.WELD: CostKind.LABOR,
    CostItem.MACHINING: CostKind.LABOR,
    CostItem.DRAWING: CostKind.LABOR,
    CostItem.MATERIAL_DIFF: CostKind.MATERIAL,
    CostItem.STOCK: CostKind.MATERIAL,
    CostItem.PO_CHANGE: CostKind.MATERIAL,
    CostItem.REORDER: CostKind.MATERIAL,
    CostItem.TRANSFER: CostKind.MATERIAL,
    CostItem.LIQUIDATED_DAMAGES: CostKind.DAMAGES,
}
"""세부 구분 → 구분(계약 검사가 줄의 두 값이 맞는지 본다)."""
PURCHASE_ITEMS = frozenset({CostItem.PO_CHANGE, CostItem.REORDER, CostItem.TRANSFER})
"""재료비 중 '구매' 묶음: 발주 변경·취소 · 새 규격 발주 할증 · 잉여 자재 전용 취급비. 나머지는 '자재 차이' 묶음."""


class BasisKind(StrEnum):
    """상태를 무엇으로 정했나(engine.state.Basis와 같은 값)."""

    EVIDENCE = "evidence"  # 확인된 진입일·관측·실적으로
    PLAN = "plan"  # 계획으로 추정
    OFF_PLAN = "off_plan"  # 계획이 근거와 어긋나 가까운 끝값으로(계획 이탈)
    UNKNOWN = "unknown"  # 정할 수 없음
