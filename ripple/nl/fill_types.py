"""초안 채우기가 주고받는 값: 대상 최상위(TargetPick), 확인할 것(SlotIssue), 수치 슬롯 연산 표, 문장 확인 표시."""

from __future__ import annotations

from dataclasses import dataclass

from ripple.contracts.assistant import FillMethod, SlotValue

from .ref_types import Mention
from .values import Measure

TEXT_ISSUE = "__text__"
"""슬롯 하나로 묶을 수 없는 확인할 것(문장에 있는데 어디에도 안 쓴 부재 표현·숫자·규격·강종, 읽지 못한 번호 범위).
요청을 다시 설명받는다."""

NUMERIC_SLOTS: dict[str, Measure] = {
    "thickness": "thickness",
    "dimension": "length",
    "add_part": "mass",
    "add_penetration": "diameter",
}
"""수치 슬롯이 있는 연산과 그 값 종류. 나머지 연산의 문장에 숫자가 있으면 어디에 쓸지 모르는 것이다."""


@dataclass(frozen=True, slots=True)
class TargetPick:
    """대상 질문 하나의 최상위: 표현과 고른 부재(해당 없음이면 None)."""

    mention: Mention
    part_id: str | None
    method: FillMethod = FillMethod.DECISION


@dataclass(frozen=True, slots=True)
class SlotIssue:
    """확인·입력이 필요한 슬롯: 추정 값이나 고를 후보가 있으면 함께."""

    slot: str
    reason: str
    proposal: SlotValue | None = None
    options: tuple[str, ...] = ()
    span: tuple[int, int] | None = None
    map_mismatch: bool = False  # 문장의 지금 값이 지도와 다름(문서 접수가 따로 표시)
