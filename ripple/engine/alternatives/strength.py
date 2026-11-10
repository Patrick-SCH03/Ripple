"""강도 사전검사(docs/engine.md(대안) 2절): 판의 강도 여유 지표로 요청안 대비 대안의 이득을 상대 비교한다.

R(t, s, k) = (t − t_c) / (s · √k). 같은 판에서 수두 h는 요청안·대안이 같아 지표에서 뺀다.
순수 함수만 있다. 규칙 값은 호출자가 넘긴다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from ripple.contracts.result import Eligibility

TOLERANCE = 1e-9
MEETS_NOTE = "요청안 이상 강도 여유(예비 비교)"
SHORT_NOTE = "요청안보다 강도 여유 부족(예비 비교)"


@dataclass(frozen=True, slots=True)
class PlateState:
    """판 하나(국소 보강이면 그 패널)의 강도 지표 입력: 두께(mm), 보강재 간격(m), 재료 계수."""

    thickness_mm: float
    spacing_m: float
    k: float


def index_of(state: PlateState, corrosion_mm: float) -> float:
    """강도 여유 지표 R. 두께가 부식 여유 이하이면 계산하지 않는다(호출자가 설계자 확인으로 둠)."""
    net = state.thickness_mm - corrosion_mm
    if net <= 0:
        raise ValueError("두께가 부식 여유 이하")
    return net / (state.spacing_m * math.sqrt(state.k))


def gain(before: PlateState, after: PlateState, corrosion_mm: float) -> float:
    """지금 상태 대비 바뀐 뒤의 강도 여유 비."""
    return index_of(after, corrosion_mm) / index_of(before, corrosion_mm)


@dataclass(frozen=True, slots=True)
class Judgement:
    status: Eligibility
    ratio: float  # min_p G_alt(p) / G_req(p), 반올림 전
    note: str


def judge(required: dict[str, float], offered: dict[str, float]) -> Judgement:
    """판마다 대안 이득 / 요청안 이득의 최솟값이 1 이상이면 충족(예비), 아니면 부족."""
    if not required or set(required) != set(offered):
        raise ValueError("요청안과 대안의 비교 판 불일치")
    ratio = min(offered[p] / required[p] for p in sorted(required))
    if ratio >= 1 - TOLERANCE:
        return Judgement(Eligibility.MEETS, ratio, MEETS_NOTE)
    return Judgement(Eligibility.SHORT, ratio, SHORT_NOTE)


def round_up_half_mm(thickness_mm: float) -> float:
    """0.5mm 단위로 올림. 부동소수 오차(1e-9)는 내림 쪽으로 봐 15.0이 15.5가 되지 않게 한다."""
    return math.ceil(thickness_mm * 2 - TOLERANCE) / 2


def half_up(x: float) -> int:
    """반올림(.5는 위로). 파이썬 round()의 은행가 반올림을 쓰지 않는다."""
    return int(Decimal(repr(x)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round3(x: float) -> float:
    """소수 셋째 자리 반올림(.0005는 위로)."""
    return float(Decimal(repr(x)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
