"""수행 주체 → 공정 수행(계약 1.32.0 `Activity.performer`·`Crew`, docs/backtest.md 3절).

- 직영: 블록 공정 모두 직영(`DIRECT_PERFORMER`) — 직영 단가.
- 사내 협력사: 탑재를 뺀 블록 공정(소조립~PE)을 작업반 하나가 맡고 탑재는 직영(생성기 v3와 같은 나눔).
  엔진은 작업반 몫을 따로 줄로 나누고 작업반 단가(cost-v6: 직영과 같음)를 쓴다.
- 비면: 수행 주체를 적지 않는다(엔진의 '모름' — 블록 제작 협력사 규칙, 이 지도에는 사외 제작이 없어 직영 단가).
"""

from __future__ import annotations

from ripple.contracts.domain import BLOCK_ACTIVITY_ORDER, DIRECT_PERFORMER, ActivityKind, Crew

from .defaults import Performer

CREW_ID = "CREW-BT"
CREW_NAME = "사내 협력사 작업반"
CREW_KINDS: tuple[ActivityKind, ...] = tuple(kind for kind in BLOCK_ACTIVITY_ORDER if kind is not ActivityKind.ERECTION)


def crews_for(performer: Performer | None) -> tuple[Crew, ...]:
    if performer != "in_house_subcontractor":
        return ()
    return (Crew(crew_id=CREW_ID, name=CREW_NAME, processes=CREW_KINDS),)


def performer_of(performer: Performer | None, kind: ActivityKind) -> str | None:
    """블록 공정 하나의 수행 주체(직영 = DIRECT_PERFORMER, 작업반 = 작업반 ID, 모름 = None)."""
    if performer is None:
        return None
    if performer == "in_house_subcontractor" and kind in CREW_KINDS:
        return CREW_ID
    return DIRECT_PERFORMER
