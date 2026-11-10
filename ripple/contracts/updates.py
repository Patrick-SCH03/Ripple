"""상태 갱신 계약(docs/domain.md 12절): 지금 지도에 발주 상태·진입일·납기(계획 열)·공정 실적·현장 확인만 덮어쓴다.

엑셀 '상태 올리기'(바뀌는 시트만)와 분석 화면의 '맞음/고치기'가 같은 갱신(StatusUpdate)을 만든다.
부재·블록·공정·선후행·발주 품목 같은 구조는 바꾸지 않는다. 지도에 없는 ID·상태 역행·날짜 순서 위반·
확인과 실적의 모순이 하나라도 있으면 갱신 전체를 거부하고 항목마다 이유를 돌려준다(일부만 반영하지 않음).
같은 날 같은 발주 상태가 앞으로 진행했으면 그날 관측을 나중 것으로 바꿔 넣는다.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from .base import Frozen
from .domain import ActivityCheck, POStatus, SourceRef
from .ingest import ImportSummary
from .records import Actor
from .workspace import SnapshotId, SnapshotList

PlanField = Literal["planned_order_date", "material_secured_days", "fabrication_start_days", "lead_time_days"]
"""발주 계획 열(납기 변경으로 바꿀 수 있는 것). 계획 발주일은 날짜, 나머지는 발주 뒤 일수."""


class POStatusItem(Frozen):
    """그날 확인한 발주 단계(발주 관측). 같은 날 앞 단계 관측이 있으면 이것으로 바꾼다."""

    kind: Literal["po_status"] = "po_status"
    po_id: str
    status: POStatus
    observed_on: date
    source: SourceRef | None = None


class POEntryItem(Frozen):
    """확인된 단계 진입일. 이미 다른 날짜가 확인돼 있으면 거부한다(정정은 전체 엑셀 다시 가져오기)."""

    kind: Literal["po_entry"] = "po_entry"
    po_id: str
    status: POStatus
    entered_on: date
    source: SourceRef | None = None


class POPlanItem(Frozen):
    """납기 변경: 발주 계획 열 하나의 새 값."""

    kind: Literal["po_plan"] = "po_plan"
    po_id: str
    field: PlanField
    value: date | int
    source: SourceRef | None = None


class ActivityActualItem(Frozen):
    """공정 실적: 빈 값은 바꾸지 않음. 이미 다른 날짜가 있으면 거부한다."""

    kind: Literal["activity_actual"] = "activity_actual"
    activity_id: str
    actual_start: date | None = None
    actual_finish: date | None = None
    source: SourceRef | None = None


class ActivityCheckItem(Frozen):
    """공정 현장 확인(계산 근거는 바뀌지 않음, 마지막 확인일 표시용)."""

    kind: Literal["activity_check"] = "activity_check"
    activity_id: str
    state: ActivityCheck
    confirmed_on: date
    source: SourceRef | None = None


UpdateItem = Annotated[
    POStatusItem | POEntryItem | POPlanItem | ActivityActualItem | ActivityCheckItem, Field(discriminator="kind")
]


class UpdateOrigin(StrEnum):
    EXCEL = "excel"  # 상태 올리기(바뀌는 시트만)
    CONFIRM = "confirm"  # 분석 화면의 확인·수정


class StatusUpdate(Frozen):
    origin: UpdateOrigin
    file_name: str | None = Field(default=None, max_length=200)  # 엑셀이면 파일 이름
    items: tuple[UpdateItem, ...] = Field(min_length=1, max_length=20000)
    # 이 갱신을 만든 화면·미리보기의 지도. 적용할 때 지금 지도와 다르면 409 — 그사이 바뀐 상태를 모르고 덮어쓰지 않게
    base_snapshot_id: SnapshotId | None = None


class UpdateProblem(Frozen):
    """거부한 항목과 이유(명사형). index = items 안의 위치."""

    index: int = Field(ge=0)
    entity_id: str
    message: str
    source: SourceRef | None = None


class StatusChange(Frozen):
    """상태가 앞으로 간 발주(그날 확인한 가장 뒤 단계 기준)."""

    po_id: str
    before: POStatus | None  # 갱신 전 가장 뒤로 관측·확인된 단계(없으면 None)
    after: POStatus


class PlanChange(Frozen):
    po_id: str
    field: PlanField
    before: date | int | None
    after: date | int


class ActivityChange(Frozen):
    activity_id: str
    started: date | None = None  # 이번에 새로 들어간 실제 착수일
    finished: date | None = None  # 이번에 새로 들어간 실제 완료일


class MapDiff(Frozen):
    """갱신으로 바뀐 것(미리보기·지도 목록·감사에 쓴다)."""

    status_changed: tuple[StatusChange, ...] = ()
    plan_changed: tuple[PlanChange, ...] = ()
    activities: tuple[ActivityChange, ...] = ()
    confirmed_only: int = Field(default=0, ge=0)  # 값은 그대로이고 확인만 남긴 항목 수(재확인)

    @property
    def changed(self) -> bool:
        return bool(self.status_changed or self.plan_changed or self.activities)


class UpdatePreview(Frozen):
    """갱신 미리보기: 거부 항목이 없을 때만 적용할 수 있다."""

    base_snapshot_id: str
    snapshot_id: str | None  # 적용하면 될 지도 ID(거부가 있으면 None)
    diff: MapDiff
    problems: tuple[UpdateProblem, ...] = ()


class UpdateEvent(Frozen):
    """적용한 갱신 하나(덧붙이기만 하는 기록). 내용이 예전 지도와 같아져도 이벤트는 새로 남는다."""

    event_id: str
    base_snapshot_id: str
    snapshot_id: str
    origin: UpdateOrigin
    file_name: str | None = None
    actor: Actor
    at: AwareDatetime
    diff: MapDiff
    items: int = Field(ge=1)  # 항목 수(원문 항목은 저장소에)


class UpdateApplied(Frozen):
    """적용 결과: 남긴 갱신 기록과 바뀐 작업 공간(새 토큰·지도 목록). 값이 그대로인 재확인이면 작업 공간도 그대로."""

    event: UpdateEvent
    snapshots: SnapshotList


class StatusImportPreview(Frozen):
    """상태 올리기 읽기 결과: 품질 리포트와(읽기 오류가 없으면) 지금 지도에 적용했을 때의 미리보기.
    거부 항목이 없을 때만 import_id·version으로 확정할 수 있다."""

    import_id: str | None = None
    version: int | None = Field(default=None, ge=1)
    summary: ImportSummary
    preview: UpdatePreview | None = None  # 읽기 오류가 있으면 None
