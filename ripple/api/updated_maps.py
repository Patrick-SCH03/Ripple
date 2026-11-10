"""상태 갱신으로 만든 지도(docs/domain.md 12절): 신뢰 경계·미리보기, 갱신 지도의 이름과 표지, 목록에 둘 것."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from ripple.contracts.domain import DataMode, GraphSnapshot
from ripple.contracts.identity import snapshot_id
from ripple.contracts.updates import StatusUpdate, UpdateEvent, UpdateOrigin, UpdatePreview
from ripple.contracts.workspace import SnapshotInfo, UpdateStamp
from ripple.engine.updates import UpdateOutcome
from ripple.store.updates import UpdateLog

from .generation import KST, Workspace
from .snapshot_info import info_of


def bounded(outcome: UpdateOutcome, update: StatusUpdate) -> UpdateOutcome:
    """신뢰 경계: 엑셀로 올린 상태는 실제 데이터로 본다(전체 가져오기와 같은 원칙).

    합성 지도에 상태 올리기를 하면 그 결과 지도는 실제 데이터(excel_import·real)가 되어 외부 AI 호출이 꺼진다.
    화면 확인은 지도 모드 그대로.
    """
    snapshot = outcome.snapshot
    if snapshot is None or update.origin is not UpdateOrigin.EXCEL or snapshot.data_mode is DataMode.REAL:
        return outcome
    real = snapshot.model_copy(update={"origin": "excel_import", "data_mode": DataMode.REAL})
    return replace(outcome, snapshot=real.model_copy(update={"snapshot_id": snapshot_id(real)}))


def preview_of(base_snapshot_id: str, outcome: UpdateOutcome) -> UpdatePreview:
    """적용하면 무엇이 바뀌는지. 거부 항목이 있으면(새 지도 없음) snapshot_id 없음."""
    return UpdatePreview(
        base_snapshot_id=base_snapshot_id,
        snapshot_id=outcome.snapshot.snapshot_id if outcome.snapshot else None,
        diff=outcome.diff,
        problems=outcome.problems,
    )


def updated_info(snapshot: GraphSnapshot, base: Workspace, event: UpdateEvent) -> SnapshotInfo:
    """갱신 지도의 정보: 이름 = 처음 지도 이름 · 상태 갱신 <월-일 시:분>, 표지 = 계보(처음 지도)·갱신 기록·바뀐 개수."""
    root = base.info.update.lineage_root if base.info.update else base.snapshot.snapshot_id
    diff = event.diff
    stamp = UpdateStamp(
        base_snapshot_id=base.snapshot.snapshot_id,
        lineage_root=root,
        event_id=event.event_id,
        at=event.at,
        by=event.actor.name,
        origin=event.origin.value,
        status_changed=len(diff.status_changed),
        plan_changed=len(diff.plan_changed),
        activities=len(diff.activities),
        confirmed_only=diff.confirmed_only,
    )
    base_name = base.info.name.split(" · 상태 갱신 ")[0]
    stamp_text = event.at.astimezone(KST).strftime("%m-%d %H:%M")
    info = info_of(snapshot, f"{base_name} · 상태 갱신 {stamp_text}", imported_at=event.at)
    return info.model_copy(update={"update": stamp})


def latest_lineage(infos: list[SnapshotInfo]) -> list[SnapshotInfo]:
    """상태 갱신으로 만든 지도는 계보(처음 지도)마다 가장 최근 것만 목록에 둔다(확인할 때마다 목록이 늘지 않게).
    활성 지도가 빠지면 listing이 따로 붙인다. 가져온 지도·기본 지도는 그대로."""
    latest: dict[str, tuple[datetime, str]] = {}
    for info in infos:
        stamp = info.update
        if stamp is not None and (stamp.lineage_root not in latest or stamp.at > latest[stamp.lineage_root][0]):
            latest[stamp.lineage_root] = (stamp.at, info.snapshot_id)
    keep = {snapshot_id for _, snapshot_id in latest.values()}
    return [info for info in infos if info.update is None or info.snapshot_id in keep]


def recorded(infos: list[SnapshotInfo], updates: UpdateLog | None) -> list[SnapshotInfo]:
    """상태 갱신 지도 가운데 갱신 기록이 확정된 것만(기록이 되돌려진 지도는 숨김)."""
    if updates is None:
        return infos
    stamped = [i.update.event_id for i in infos if i.update is not None]
    known = updates.known(stamped)
    return [i for i in infos if i.update is None or i.update.event_id in known]
