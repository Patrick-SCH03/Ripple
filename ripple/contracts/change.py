"""변경 계약: 설계변경(ECN) 요청과 변경 연산 8종.

자연어 해석(LLM·규칙 기반)의 출력도 이 스키마로 검증한다. 검증을 통과하지 못한
출력은 쓰지 않는다(안전장치).
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import Frozen
from .domain import PartKind


class ChangeIntent(StrEnum):
    """변경 의도. 대안은 같은 의도를 이루는 다른 연산이고, 적격 판정 기준이 의도마다 다르다."""

    STRENGTH = "strength"  # 강도 보강
    INTERFERENCE = "interference"  # 간섭 해소
    WEIGHT = "weight"  # 중량 조정
    OWNER_REQUEST = "owner_request"  # 선주 요청 사양 변경
    RULE_CHANGE = "rule_change"  # 규칙·선급 요구
    EQUIPMENT = "equipment"  # 장비 사양 변경 대응


class DesignStatus(StrEnum):
    """설계 문서(ECN)의 승인 상태(계약 1.23.0).

    Ripple 판단의 결재 흐름(records.EcnState)과 다른 축이다.

    입력하지 않으면 unknown(확인하지 않음). in_review·owner_pending이면 판정에 '승인 전 변경' 이유가
    붙는다(검토 필요 이상).
    """

    UNKNOWN = "unknown"  # 미입력
    IN_REVIEW = "in_review"  # 설계 검토 중
    OWNER_PENDING = "owner_pending"  # 선주 승인 대기
    APPROVED = "approved"  # 승인

    @property
    def pending(self) -> bool:
        return self in (DesignStatus.IN_REVIEW, DesignStatus.OWNER_PENDING)


class ChangeCause(StrEnum):
    """변경 원인(계약 1.28.0): 누가 일으킨 변경인가 — 비용 부담을 가를 때 먼저 묻는 축.

    1.29.0부터 선주 요청만 계산에 쓴다: 늘어난 인도 지연이 인도일 조정 대상(허용 지연)이라 지체상금 줄 대신 노출 금액
    (docs/engine.md(비용·일정) 4-6). 그 밖의 원인은 정보다.

    변경 의도(ChangeIntent, 무엇을 위해 바꾸나)와 다른 축이다. 원인이 기록에 없으면 협력사 대금 조정·정산에서
    어느 쪽 부담인지 가릴 근거가 남지 않는다(docs/domain.md 14절). 비워 두면 '미입력'.
    """

    OWNER_REQUEST = "owner_request"  # 선주 요청
    CLASS_RULE = "class_rule"  # 선급·규정
    DESIGN_ERROR = "design_error"  # 설계 오류·간섭(사내 설계)
    PRODUCTION = "production"  # 현장 오작·변형
    EQUIPMENT = "equipment"  # 기자재 사양(메이커)


class Effectivity(Frozen):
    """적용 범위(계약 1.23.0): 적용 호선은 요청의 ship_ids, 여기는 적용 시작일과 메모만. 계산에 쓰지 않는다.

    확정일(결정 시점)과 적용 시작일(생산에 반영되는 시점)은 다른 의미라 확정일을 덮어쓰지 않는다(docs/domain.md 13절).
    """

    effective_on: date | None = None
    note: str | None = Field(default=None, max_length=200)


class SourceKind(StrEnum):
    """1.27.0 문서 접수의 입력 형태."""

    TEXT = "text"  # 붙여 넣은 문서·메일 본문
    XLSX = "xlsx"  # 변경 리스트 엑셀


class SourceDocument(Frozen):
    """1.27.0 문서 접수로 만든 요청의 원문 문서 정보(정보, 계산에 안 씀 — 분석 ID 정규형에 넣지 않는다)."""

    kind: SourceKind
    ecn_ref: str | None = Field(default=None, max_length=120)  # 원문 설계변경 번호(기록 ID 규칙과 무관하게 그대로)
    revision: str | None = Field(default=None, max_length=40)  # 원문 문서 개정
    items: int = Field(ge=1)  # 분석에 넣은 항목 수
    dropped: int = Field(default=0, ge=0)  # 사람이 뺀 항목 수


class ThicknessChange(Frozen):
    op: Literal["thickness"] = "thickness"
    part_ids: tuple[str, ...] = Field(min_length=1)
    from_mm: float = Field(gt=0)
    to_mm: float = Field(gt=0)

    @model_validator(mode="after")
    def _changes(self) -> ThicknessChange:
        _require_change(self.from_mm, self.to_mm)
        return self


class GradeChange(Frozen):
    op: Literal["grade"] = "grade"
    part_ids: tuple[str, ...] = Field(min_length=1)
    from_grade: str = Field(min_length=1)
    to_grade: str = Field(min_length=1)

    @model_validator(mode="after")
    def _changes(self) -> GradeChange:
        _require_change(self.from_grade, self.to_grade)
        return self


class DimensionChange(Frozen):
    op: Literal["dimension"] = "dimension"
    part_ids: tuple[str, ...] = Field(min_length=1)
    field: Literal["length_mm", "width_mm", "height_mm", "diameter_mm"]
    from_value: float = Field(gt=0)
    to_value: float = Field(gt=0)

    @model_validator(mode="after")
    def _changes(self) -> DimensionChange:
        _require_change(self.from_value, self.to_value)
        return self


class AddPart(Frozen):
    op: Literal["add_part"] = "add_part"
    block_id: str
    kind: PartKind
    spec_id: str
    qty: float = Field(gt=0)
    attach_to_part_id: str | None = None  # 붙는 위치(예: 보강재를 붙일 판)


class RemovePart(Frozen):
    op: Literal["remove_part"] = "remove_part"
    part_ids: tuple[str, ...] = Field(min_length=1)


class ReroutePipe(Frozen):
    op: Literal["reroute_pipe"] = "reroute_pipe"
    removed_part_ids: tuple[str, ...] = ()
    added_spool_spec_ids: tuple[str, ...] = ()
    crosses_part_ids: tuple[str, ...] = ()  # 새 경로가 관통하는 판

    @model_validator(mode="after")
    def _not_empty(self) -> ReroutePipe:
        if not self.removed_part_ids and not self.added_spool_spec_ids:
            raise ValueError("빼는 스풀 또는 더하는 스풀 하나 이상 필요")
        return self


class EquipmentSpecChange(Frozen):
    op: Literal["equipment_spec"] = "equipment_spec"
    part_ids: tuple[str, ...] = Field(min_length=1)  # 밸브·펌프 등
    from_spec_id: str
    to_spec_id: str

    @model_validator(mode="after")
    def _changes(self) -> EquipmentSpecChange:
        _require_change(self.from_spec_id, self.to_spec_id)
        return self


class AddPenetration(Frozen):
    op: Literal["add_penetration"] = "add_penetration"
    plate_part_id: str
    pipe_part_id: str
    diameter_mm: float = Field(gt=0)


ChangeOp = Annotated[
    ThicknessChange
    | GradeChange
    | DimensionChange
    | AddPart
    | RemovePart
    | ReroutePipe
    | EquipmentSpecChange
    | AddPenetration,
    Field(discriminator="op"),
]

CHANGE_OP_TYPES: tuple[type[Frozen], ...] = (
    ThicknessChange,
    GradeChange,
    DimensionChange,
    AddPart,
    RemovePart,
    ReroutePipe,
    EquipmentSpecChange,
    AddPenetration,
)

OP_NAMES: frozenset[str] = frozenset(str(t.model_fields["op"].default) for t in CHANGE_OP_TYPES)

FieldChange = ThicknessChange | GradeChange | DimensionChange | EquipmentSpecChange
"""기존 부재의 성질 하나를 바꾸는 연산."""


def removed_part_ids(op: ChangeOp) -> tuple[str, ...]:
    """연산이 빼는 기존 부재."""
    if isinstance(op, RemovePart):
        return op.part_ids
    if isinstance(op, ReroutePipe):
        return op.removed_part_ids
    return ()


def referenced_part_ids(op: ChangeOp) -> tuple[str, ...]:
    """빼는 부재가 아닌데 연산이 가리키는 기존 부재."""
    if isinstance(op, FieldChange):
        return op.part_ids
    if isinstance(op, AddPart):
        return () if op.attach_to_part_id is None else (op.attach_to_part_id,)
    if isinstance(op, ReroutePipe):
        return op.crosses_part_ids
    if isinstance(op, AddPenetration):
        return (op.plate_part_id, op.pipe_part_id)
    return ()


class ChangeRequest(Frozen):
    """설계변경 요청 한 건. 여러 호선에 걸칠 수 있다(동형선)."""

    ecn_id: str
    title: str
    ship_ids: tuple[str, ...] = Field(min_length=1)
    intent: ChangeIntent | None = None  # 변경 사유. 없으면 '사유 미정'(엔진 계산에는 쓰지 않는다)
    ops: tuple[ChangeOp, ...] = Field(min_length=1)
    raw_text: str | None = None  # 사용자가 입력한 원문
    requested_by: str | None = None
    requested_on: date | None = None
    effectivity: Effectivity | None = None  # 1.23.0 적용 시작일·메모(정보, 계산에 안 씀)
    design_status: DesignStatus = DesignStatus.UNKNOWN  # 1.23.0 설계 승인 상태
    source: SourceDocument | None = None  # 1.27.0 문서 접수로 만든 요청의 원문 문서(정보)
    cause: ChangeCause | None = None  # 1.28.0 변경 원인. 1.29.0 선주 요청만 계산·분석 ID에 씀(허용 지연)

    @model_validator(mode="after")
    def _unique_ships(self) -> ChangeRequest:
        if len(set(self.ship_ids)) != len(self.ship_ids):
            raise ValueError("같은 호선 중복")
        return self


def _require_change(before: object, after: object) -> None:
    if before == after:
        raise ValueError("변경 전과 후가 같음")
