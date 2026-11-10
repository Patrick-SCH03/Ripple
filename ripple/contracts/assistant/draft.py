"""변경 초안 계약: 연산별 슬롯 정의(OP_SLOTS)·채움 방법과 원문 근거·초안(ChangeDraft)과 변경 요청 조립."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from pydantic import Field, TypeAdapter, model_validator

from ..base import Frozen
from ..change import CHANGE_OP_TYPES, ChangeIntent, ChangeOp, ChangeRequest
from ..domain import PartKind


class FillMethod(StrEnum):
    RULE = "rule"  # 원문에서 결정적으로: 부재·블록 코드, 규격 ID, 사전 유일 일치, 값 정규화
    DECISION = "decision"  # 판단 계층(보정한 대상 부재·연산·의도)의 최상위
    MAP = "map"  # 지도 현재값(변경 전 값)
    CONTEXT = "context"  # 화면 맥락(호선)
    USER = "user"  # 사용자가 확인·선택·입력
    GUESS = "guess"  # 추정: 모호한 값 표현, 지도와 다른 변경 전 값, 규칙 기반 기본값
    LLM = "llm"  # 외부 모델이 채움(합성 모드)


READY_METHODS: frozenset[FillMethod] = frozenset(
    {FillMethod.RULE, FillMethod.DECISION, FillMethod.MAP, FillMethod.CONTEXT, FillMethod.USER}
)
"""자동 진행 자격이 있는 채움 방법. 추정·LLM은 사용자가 확인하면 USER가 된다."""


class SourceSpan(Frozen):
    """원문 속 위치 [start, end)와 그 조각."""

    start: int = Field(ge=0)
    end: int = Field(ge=1)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> SourceSpan:
        if self.end - self.start != len(self.text):
            raise ValueError("원문 위치와 조각 길이 불일치")
        return self


class SlotKind(StrEnum):
    PARTS = "parts"  # 부재 ID 묶음
    PART = "part"  # 부재 ID 하나
    BLOCK = "block"
    SPEC = "spec"
    SPECS = "specs"  # 규격 ID 목록(받은 순서 그대로)
    GRADE = "grade"
    MILLIMETER = "millimeter"  # mm 값
    QUANTITY = "quantity"  # 규격 단위(t·ea·m) 수량
    DIMENSION = "dimension"  # 치수 종류(length_mm·width_mm·height_mm·diameter_mm)
    PART_KIND = "part_kind"


LIST_KINDS = frozenset({SlotKind.PARTS, SlotKind.SPECS})
NUMBER_KINDS = frozenset({SlotKind.MILLIMETER, SlotKind.QUANTITY})


class SlotSpec(Frozen):
    name: str  # 변경 연산 필드 이름
    kind: SlotKind
    label: str  # 질문·화면에 쓰는 이름
    required: bool = True
    calibrated: bool = False  # 판단 계층(대상 부재 주제)으로 채우는 슬롯. 나머지는 결정적 일치나 사용자 확인만
    from_map: bool = False  # 변경 전 값: 대상이 정해지면 지도 현재값으로 채운다
    part_kinds: tuple[PartKind, ...] = ()  # 부재 슬롯이 받는 종류(비면 아무 종류)


def _slots(*specs: SlotSpec) -> tuple[SlotSpec, ...]:
    return specs


_HULL = (PartKind.PLATE, PartKind.STIFFENER, PartKind.BRACKET)
OP_SLOTS: Mapping[str, tuple[SlotSpec, ...]] = MappingProxyType(
    {
        "thickness": _slots(
            SlotSpec(name="part_ids", kind=SlotKind.PARTS, label="두께를 바꿀 부재", calibrated=True, part_kinds=_HULL),
            SlotSpec(name="from_mm", kind=SlotKind.MILLIMETER, label="지금 두께", from_map=True),
            SlotSpec(name="to_mm", kind=SlotKind.MILLIMETER, label="바꿀 두께"),
        ),
        "grade": _slots(
            SlotSpec(name="part_ids", kind=SlotKind.PARTS, label="강종을 바꿀 부재", calibrated=True, part_kinds=_HULL),
            SlotSpec(name="from_grade", kind=SlotKind.GRADE, label="지금 강종", from_map=True),
            SlotSpec(name="to_grade", kind=SlotKind.GRADE, label="바꿀 강종"),
        ),
        "dimension": _slots(
            SlotSpec(
                name="part_ids",
                kind=SlotKind.PARTS,
                label="치수를 바꿀 부재",
                calibrated=True,
                part_kinds=(*_HULL, PartKind.PIPE_SPOOL),
            ),
            SlotSpec(name="field", kind=SlotKind.DIMENSION, label="치수 종류"),
            SlotSpec(name="from_value", kind=SlotKind.MILLIMETER, label="지금 치수"),
            SlotSpec(name="to_value", kind=SlotKind.MILLIMETER, label="바꿀 치수"),
        ),
        "add_part": _slots(
            SlotSpec(name="block_id", kind=SlotKind.BLOCK, label="부재를 더할 블록"),
            SlotSpec(name="kind", kind=SlotKind.PART_KIND, label="더할 부재 종류"),
            SlotSpec(name="spec_id", kind=SlotKind.SPEC, label="더할 부재 규격"),
            SlotSpec(name="qty", kind=SlotKind.QUANTITY, label="수량(규격 단위)"),
            SlotSpec(name="attach_to_part_id", kind=SlotKind.PART, label="붙일 부재", required=False),
        ),
        "remove_part": _slots(
            SlotSpec(name="part_ids", kind=SlotKind.PARTS, label="뺄 부재", calibrated=True),
        ),
        "reroute_pipe": _slots(
            SlotSpec(
                name="removed_part_ids",
                kind=SlotKind.PARTS,
                label="빼는 스풀",
                required=False,
                part_kinds=(PartKind.PIPE_SPOOL,),
            ),
            SlotSpec(name="added_spool_spec_ids", kind=SlotKind.SPECS, label="더하는 스풀 규격", required=False),
            SlotSpec(
                name="crosses_part_ids",
                kind=SlotKind.PARTS,
                label="새 경로가 관통하는 판",
                required=False,
                part_kinds=(PartKind.PLATE,),
            ),
        ),
        "equipment_spec": _slots(
            SlotSpec(
                name="part_ids",
                kind=SlotKind.PARTS,
                label="사양을 바꿀 장비",
                calibrated=True,
                part_kinds=(PartKind.VALVE, PartKind.EQUIPMENT),
            ),
            SlotSpec(name="from_spec_id", kind=SlotKind.SPEC, label="지금 규격", from_map=True),
            SlotSpec(name="to_spec_id", kind=SlotKind.SPEC, label="바꿀 규격"),
        ),
        "add_penetration": _slots(
            SlotSpec(name="plate_part_id", kind=SlotKind.PART, label="관통되는 판", part_kinds=(PartKind.PLATE,)),
            SlotSpec(name="pipe_part_id", kind=SlotKind.PART, label="관통하는 배관", part_kinds=(PartKind.PIPE_SPOOL,)),
            SlotSpec(name="diameter_mm", kind=SlotKind.MILLIMETER, label="관통부 지름"),
        ),
    }
)
"""연산마다 채울 슬롯. 이름·필수 여부는 변경 연산 필드와 같다(tests/checks/contracts.py가 검사)."""

ANY_OF: Mapping[str, tuple[str, ...]] = MappingProxyType({"reroute_pipe": ("removed_part_ids", "added_spool_spec_ids")})
"""하나 이상은 채워야 하는 선택 슬롯 묶음(경로 변경: 빼는 스풀이나 더하는 스풀)."""

OP_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "thickness": "두께 변경",
        "grade": "강종 변경",
        "dimension": "치수 변경",
        "add_part": "부재 추가",
        "remove_part": "부재 삭제",
        "reroute_pipe": "배관 경로 변경",
        "equipment_spec": "장비 사양 변경",
        "add_penetration": "관통부 추가",
    }
)

INTENT_LABELS: Mapping[ChangeIntent, str] = MappingProxyType(
    {
        ChangeIntent.STRENGTH: "강도 보강",
        ChangeIntent.INTERFERENCE: "간섭 해소",
        ChangeIntent.WEIGHT: "중량 조정",
        ChangeIntent.OWNER_REQUEST: "선주 요청",
        ChangeIntent.RULE_CHANGE: "규칙·선급 요구",
        ChangeIntent.EQUIPMENT: "장비 사양 대응",
    }
)

SlotValue = str | float | tuple[str, ...]

_OP_ADAPTER: TypeAdapter[ChangeOp] = TypeAdapter(ChangeOp)


class SlotFill(Frozen):
    value: SlotValue
    method: FillMethod
    span: SourceSpan | None = None  # 원문 근거(지도·화면 맥락에서 채웠으면 없음)


class ChangeDraft(Frozen):
    """해석 중인 변경 요청. 연산이 정해져야 슬롯을 채울 수 있다."""

    text: str = Field(min_length=1, max_length=1000)  # 사용자가 입력한 원문
    ship_ids: tuple[str, ...] = Field(min_length=1)
    op: SlotFill | None = None
    intent: SlotFill | None = None
    slots: dict[str, SlotFill] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistent(self) -> ChangeDraft:
        if self.op is not None and self.op.value not in OP_SLOTS:
            raise ValueError(f"없는 변경 연산 · {self.op.value}")
        if self.intent is not None and self.intent.value not in set(ChangeIntent):
            raise ValueError(f"없는 변경 의도 · {self.intent.value}")
        specs = {s.name: s for s in self.specs()}
        unknown = sorted(set(self.slots) - set(specs))
        if unknown:
            raise ValueError(f"이 연산에 없는 슬롯 · {', '.join(unknown)}")
        for name, fill in self.slots.items():
            check_value(specs[name], fill.value)
        return self

    def specs(self) -> tuple[SlotSpec, ...]:
        return OP_SLOTS[str(self.op.value)] if self.op is not None else ()

    def missing(self) -> tuple[str, ...]:
        """채우지 않은 필수 슬롯(연산 포함). 하나 이상 묶음이 비면 묶음의 첫 슬롯.

        변경 사유(의도)는 분석 뒤에 기록하므로 필수가 아니다(사유 미정으로 분석한다).
        """
        absent = ["op"] if self.op is None else []
        absent += [s.name for s in self.specs() if s.required and s.name not in self.slots]
        group = ANY_OF.get(str(self.op.value)) if self.op is not None else None
        if group and not any(name in self.slots for name in group):
            absent.append(group[0])
        return tuple(absent)

    def unconfirmed(self) -> tuple[str, ...]:
        """자동 진행 자격이 없는 방법(추정·LLM)으로 채운 것(연산 포함, 분석 뒤에 정하는 사유는 빼고)."""
        fills = {"op": self.op, **self.slots}
        return tuple(name for name, fill in fills.items() if fill is not None and fill.method not in READY_METHODS)

    @property
    def ready(self) -> bool:
        """자동 진행 자격: 빠진 슬롯이 없고 모든 채움이 결정적·보정·지도·맥락·사용자 확인."""
        return not self.missing() and not self.unconfirmed()

    def to_change(self, ecn_id: str, title: str) -> ChangeRequest:
        """채운 슬롯으로 변경 요청을 조립한다. 빠진 슬롯이 있거나 연산 계약에 어긋나면 ValueError."""
        absent = self.missing()
        if absent or self.op is None:
            raise ValueError(f"빈 슬롯 · {', '.join(absent)}")
        body: dict[str, object] = {"op": self.op.value}
        body.update({name: fill.value for name, fill in self.slots.items()})
        op = _OP_ADAPTER.validate_python(body)
        return ChangeRequest(
            ecn_id=ecn_id,
            title=title,
            ship_ids=self.ship_ids,
            intent=ChangeIntent(str(self.intent.value)) if self.intent is not None else None,
            ops=(op,),
            raw_text=self.text,
        )


def check_value(spec: SlotSpec, value: SlotValue) -> None:
    if spec.kind in LIST_KINDS:
        ok = isinstance(value, tuple) and bool(value) and all(isinstance(v, str) and v for v in value)
    elif spec.kind in NUMBER_KINDS:
        ok = isinstance(value, float) and value > 0
    else:
        ok = isinstance(value, str) and bool(value)
    if not ok:
        raise ValueError(f"{spec.name}({spec.kind}) 슬롯 값 형식 오류 · {value!r}")


def op_types() -> tuple[str, ...]:
    """OP_SLOTS가 다루는 연산(변경 연산 계약의 순서)."""
    return tuple(str(t.model_fields["op"].default) for t in CHANGE_OP_TYPES)
