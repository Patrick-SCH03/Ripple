"""작업 공간 한 세대(지도·색인·샘플·AI 비서·외부 모델 경계)와 그 세대의 유효 데이터 모드·토큰·업무상 오늘."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

from ripple.agent.flow import Assistant
from ripple.agent.intake import IntakeService
from ripple.contracts.domain import DataMode, GraphSnapshot
from ripple.contracts.workspace import SnapshotInfo
from ripple.engine.index import GraphIndex

from .samples import Sample

KST = timezone(timedelta(hours=9))  # 갱신 지도 이름의 시각


@dataclass(frozen=True, slots=True)
class Workspace:
    generation: int
    token: str  # 지도 ID.인스턴스.세대
    snapshot: GraphSnapshot
    info: SnapshotInfo
    index: GraphIndex
    samples: tuple[Sample, ...]
    assistant: Assistant
    intake: IntakeService  # 1.27.0 문서 접수(세대마다 새로 — 지도가 바뀌면 이전 제안은 없다)
    data_mode: DataMode  # 유효 데이터 모드
    llm_external: bool  # 이 세대의 비서가 외부 모델을 부를 수 있는가


def token_of(snapshot_id: str, instance: str, generation: int) -> str:
    """세대 토큰 = 지도 ID.인스턴스.세대(같은 지도를 다시 켜거나 서버를 다시 켜도 바뀐다)."""
    return f"{snapshot_id}.{instance}.{generation}"


def effective_mode(configured: DataMode, snapshot: GraphSnapshot) -> DataMode:
    """설정이나 지도 중 하나라도 real이면 real(실데이터 지도에서 외부 모델 호출 0)."""
    if DataMode.REAL in (configured, snapshot.data_mode):
        return DataMode.REAL
    return DataMode.SYNTHETIC


def kst_today() -> date:
    """한국 시간 오늘."""
    return datetime.now(UTC).astimezone(KST).date()


def business_today(workspace: Workspace, today: date, *, live: bool) -> date:
    """상태 확인에 쓰는 '오늘'(docs/domain.md 12절): 실제 데이터면 한국 시간 오늘(today).

    합성 지도는 실시간 시연 세계(live)면 역시 오늘이고, 날짜에 멈춘 시연 세계면 지도의 자료 기준일이다
    (멈춘 세계는 실제 오늘로 확인할 수 없다). 자료 기준일이 없으면 오늘.
    """
    if not live and workspace.data_mode is DataMode.SYNTHETIC and workspace.info.status_date is not None:
        return workspace.info.status_date
    return today
