"""지도 목록·전환·가져오기 미리보기 계약(docs/operations.md(서비스) 6절).

작업 공간 = 지금 분석에 쓰는 지도 한 벌(지도·색인·샘플·AI 비서·외부 모델 경계). 지도를 바꾸면(같은 지도를 다시 켜도)
작업 공간 세대가 통째로 바뀌고 토큰도 바뀐다. 토큰 = 지도 ID + 서버 프로세스 인스턴스 + 세대라 서버를 다시 켜도 바뀐다.
화면은 요청 머리글 `X-Ripple-Workspace`에 자기가 아는 토큰을 싣고, 서버는 지금 토큰과 다르면 409(WorkspaceConflict)로
거절한다 — 지도가 바뀌었거나 대화가 사라진 줄 모르는 화면이 다른 지도의 결과를 섞어 보이지 않게.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from .base import Frozen
from .domain import DataMode
from .ingest import ImportSummary

STALE_DAYS = 7
"""마지막 확인이 이 일수보다 오래되면 '오래됨'(자료 날짜 · 판단이 걸린 상태 · 결정 도우미 확인할 것,
화면 stateBasis와 같음)."""

SNAPSHOT_ID_PATTERN = r"^G-[0-9a-f]{16}$"
"""지도 ID(내용 해시, ripple.contracts.identity). 파일 경로에 쓰기 전에 이 형식인지 먼저 본다."""

SnapshotId = Annotated[str, Field(pattern=SNAPSHOT_ID_PATTERN)]

WORKSPACE_HEADER = "X-Ripple-Workspace"
"""요청: 화면이 아는(기대하는) 작업 공간 토큰. 응답: 그 요청을 처리한 작업 공간의 토큰."""


class SnapshotCounts(Frozen):
    """지도에 든 항목 수(목록·확인 화면용)."""

    ships: int = Field(ge=0)
    blocks: int = Field(ge=0)
    parts: int = Field(ge=0)
    purchase_orders: int = Field(ge=0)
    activities: int = Field(ge=0)


class UpdateStamp(Frozen):
    """상태 갱신으로 만든 지도의 표시(docs/domain.md 12절): 무엇에서 누가 언제 무엇을 바꿨나(원문은 갱신 기록에)."""

    base_snapshot_id: SnapshotId  # 바탕 지도
    lineage_root: SnapshotId  # 갱신 계보의 처음 지도(기본 합성 지도에서 이어지면 샘플 목록을 그대로 쓴다)
    event_id: str
    at: AwareDatetime
    by: str = Field(min_length=1)  # 갱신한 사람 이름
    origin: Literal["excel", "confirm"]
    status_changed: int = Field(ge=0)  # 단계가 앞으로 간 발주 수
    plan_changed: int = Field(ge=0)  # 납기(계획 열)가 바뀐 항목 수
    activities: int = Field(ge=0)  # 실적 날짜가 들어간 공정 수
    confirmed_only: int = Field(ge=0)  # 값은 그대로이고 확인만 남긴 항목 수


class SnapshotInfo(Frozen):
    snapshot_id: SnapshotId
    name: str = Field(min_length=1)  # 화면 이름: 기본 지도 = '기본 합성 지도', 가져온 지도 = 올린 파일 이름
    origin: Literal["generator", "excel_import"]
    data_mode: DataMode  # 지도 자체의 데이터 모드(올린 엑셀은 항상 real)
    default: bool = False  # 설정의 지도 파일(시작 기본값)
    imported_at: AwareDatetime | None = None  # 가져와 저장한 시각(기본 지도는 None)
    counts: SnapshotCounts
    ship_ids: tuple[str, ...]  # 지도의 호선(분석 기준 고르기)
    # 자료 기준일: 지도 안의 마지막 상태 날짜(발주 관측일·단계 진입일·공정 실적 착수·완료일의 최댓값). 없으면 None
    status_date: dt.date | None = None
    summary: ImportSummary | None = None  # 가져오기 품질 리포트(경고·없던 선택 시트 포함)
    update: UpdateStamp | None = None  # 1.22.0 상태 갱신으로 만든 지도면 그 표시

    @model_validator(mode="after")
    def _consistent(self) -> SnapshotInfo:
        if self.summary is not None and self.summary.snapshot_id != self.snapshot_id:
            raise ValueError("가져오기 요약의 지도 ID와 지도 불일치")
        if self.origin == "excel_import" and self.data_mode is not DataMode.REAL:
            raise ValueError("올린 엑셀로 만든 지도는 실제 데이터(real)만 가능")
        if len(self.ship_ids) != self.counts.ships:
            raise ValueError("호선 목록과 호선 수 불일치")
        return self


class Freshness(Frozen):
    """자료 날짜(1.22.0): 상태가 언제 기준인지 — 최신 날짜와 오래된 항목 수(오늘 = 업무상 오늘)."""

    today: dt.date
    po_latest: dt.date | None = None  # 발주 관측·확인된 진입일 최신
    open_orders: int = Field(ge=0)  # 아직 입고 전 발주 수
    stale_orders: int = Field(ge=0)  # 그중 마지막 확인이 7일 넘게 전이거나 없는 발주 수
    activity_latest: dt.date | None = None  # 공정 실적·현장 확인 최신


class SnapshotList(Frozen):
    """지도 목록과 지금 활성 작업 공간."""

    active_snapshot_id: SnapshotId
    workspace: str = Field(min_length=1)  # 활성 작업 공간 토큰(요청 머리글 X-Ripple-Workspace에 싣는 값)
    # 서버 프로세스 인스턴스와 그 안의 세대(지도를 바꿀 때마다, 같은 지도를 다시 켜도 늘어남). 화면은 같은 인스턴스에서
    # 세대가 낮은 목록(늦게 온 응답)을 적용하지 않는다
    instance: str = Field(min_length=1)
    generation: int = Field(ge=1)
    data_mode: DataMode  # 활성 세대의 유효 데이터 모드: 설정이나 지도가 real이면 real(외부 모델 호출 0)
    llm_external: bool  # 지금 외부 생성 모델을 부를 수 있는가(키가 있고 유효 모드가 synthetic)
    restore_problem: str | None = None  # 시작 때 저장된 활성 지도를 열지 못해 기본 지도로 시작했으면 그 사유
    # 업무상 오늘(상태 확인 날짜, 1.22.0): 실제 데이터는 한국 시간 오늘, 합성 지도는 지도의 자료 기준일
    # (가상 날짜에 멈춘 시연 세계)
    today: dt.date
    freshness: Freshness | None = None  # 활성 지도의 자료 날짜
    items: tuple[SnapshotInfo, ...]  # 기본 지도가 맨 앞, 나머지는 가져온 시각 순

    @model_validator(mode="after")
    def _consistent(self) -> SnapshotList:
        ids = [item.snapshot_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("지도 목록에 같은 ID 중복")
        if self.active_snapshot_id not in ids:
            raise ValueError("활성 지도가 목록에 없음")
        return self


class ImportPreview(Frozen):
    """확정 매핑으로 읽은 결과: 품질 리포트와(오류가 없으면) 확정할 수 있는 가져오기 ID·지도 정보, 상태 버전."""

    import_id: str | None = None  # 오류가 있으면 None(지도를 만들지 않아 확정할 수 없음)
    summary: ImportSummary
    info: SnapshotInfo | None = None
    version: int | None = Field(default=None, ge=1)  # 이 결과의 가져오기 상태 버전(확정할 때 보냄)

    @model_validator(mode="after")
    def _consistent(self) -> ImportPreview:
        if (self.import_id is not None) != self.summary.ok or (self.info is not None) != self.summary.ok:
            raise ValueError("ID·지도 정보는 오류 없이 지도를 만든 가져오기에만 있음")
        return self


class ImportConflict(Frozen):
    """409 응답 detail: 화면이 보낸 가져오기 상태 버전이 지금 것이 아니거나, 그 버전에서 오류 없이 만든 지도가 없다."""

    code: Literal["import_changed"] = "import_changed"
    message: str
    version: int = Field(ge=1)  # 지금 가져오기 상태 버전


class WorkspaceConflict(Frozen):
    """409 응답 detail: 요청이 기대한 작업 공간이 지금 것이 아니다(지도가 바뀌었거나 서버가 다시 켜짐)."""

    code: Literal["workspace_changed"] = "workspace_changed"
    message: str
    expected: str
    active: str
    active_snapshot_id: str
