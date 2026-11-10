"""지도 목록 한 줄(SnapshotInfo): 개수·배·자료 기준일, 기본 지도의 정보."""

from __future__ import annotations

from datetime import date, datetime
from functools import cache
from pathlib import Path

from ripple.contracts.domain import GraphSnapshot
from ripple.contracts.ingest import ImportSummary
from ripple.contracts.workspace import SnapshotCounts, SnapshotInfo
from ripple.generator.io import load_config

DEFAULT_NAME = "기본 합성 지도"


def status_date(snapshot: GraphSnapshot) -> date | None:
    """자료 기준일: 지도 안의 마지막 상태 날짜(발주 관측일·단계 진입일·공정 실적 착수·완료일). 없으면 None."""
    days: list[date] = []
    for po in snapshot.purchase_orders:
        days += [o.observed_on for o in po.observations]
        days += list(po.entered_on.values())
    for activity in snapshot.activities:
        days += [d for d in (activity.actual_start, activity.actual_finish) if d is not None]
    return max(days, default=None)


def info_of(
    snapshot: GraphSnapshot,
    name: str,
    *,
    default: bool = False,
    imported_at: datetime | None = None,
    summary: ImportSummary | None = None,
) -> SnapshotInfo:
    counts = SnapshotCounts(
        ships=len(snapshot.ships),
        blocks=len(snapshot.blocks),
        parts=len(snapshot.parts),
        purchase_orders=len(snapshot.purchase_orders),
        activities=len(snapshot.activities),
    )
    return SnapshotInfo(
        snapshot_id=snapshot.snapshot_id,
        name=name,
        origin=snapshot.origin,
        data_mode=snapshot.data_mode,
        default=default,
        imported_at=imported_at,
        counts=counts,
        ship_ids=tuple(s.ship_id for s in snapshot.ships),
        status_date=status_date(snapshot),
        summary=summary,
    )


@cache
def default_name(generator_config: Path) -> str:
    """기본 지도 자리의 이름: 시연 합성 지도 설정(relations.name)이면 그 이름, 아니면 '기본 합성 지도'."""
    relations = load_config(generator_config).relations
    return DEFAULT_NAME if relations is None else relations.name


def default_info(snapshot: GraphSnapshot, name: str = DEFAULT_NAME) -> SnapshotInfo:
    """기본 지도(설정의 지도 파일)의 정보: 이름은 설정마다 늘 같고 가져온 시각이 없다."""
    return info_of(snapshot, name, default=True)
