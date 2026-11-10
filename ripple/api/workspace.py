"""작업 공간: 지금 분석에 쓰는 지도 한 벌(지도·색인·샘플·AI 비서·외부 모델 경계)과 그 세대 교체
(docs/operations.md(서비스) 6절).

- 지도를 바꾸면(활성화) 새 세대를 통째로 만든 뒤 한 번에 바꿔 끼운다. 만들다 실패하면 이전 세대가 그대로 남는다.
- 세대마다 토큰(지도 ID + 서버 프로세스 인스턴스 + 세대)이 있다. 같은 지도를 다시 켜거나 서버를 다시 켜도 바뀐다.
- 유효 데이터 모드 = 설정이 real이거나 지도가 real이면 real. 그 세대의 비서·외부 모델 경계(Guarded)가 이 모드를 써서
  실데이터 지도에서는 외부 모델을 부르지 않는다.
- 요청은 시작할 때(의존성) 세대를 한 번 잡고 끝까지 그 세대로 계산한다. 처리 중에 지도가 바뀌어도 결과는 잡은 세대
  기준이고, 응답 머리글(X-Ripple-Workspace)·분석 결과의 지도 ID로 드러난다. 요청 머리글의 기대 토큰이 지금 토큰과
  다르면 409로 거절한다.
- 대화는 세대마다 따로다(새 세대의 비서는 빈 대화 저장소로 시작).
- 활성 지도는 지도 저장소(ripple/store/snapshots.py)에 남겨 다시 켜도 그대로다. 기본 지도는 설정의 지도 파일이고,
  실시간 시연 세계(RIPPLE_SYNTHETIC_CLOCK=live)면 한국 시간 오늘로 만든 세계다(live_world — 날이 바뀌면 다음 요청에서
  새 날의 세계로 넘어가고, 기본 지도를 쓰던 세대만 새 세대가 된다). 새 날 훅(on_new_day — 시연 기록 날마다 새로 채우기,
  demo_daily.py)은 그 넘어가기 안에서 부른다: 다른 요청은 훅이 끝날 때까지 기다렸다가 새 세대를 본다.
- 엑셀 가져오기(docs/input.md(엑셀 양식) 4절): 올리기 → 매핑 제안(열 확인) → 덮어쓰기·확정 매핑 제출 → 읽기 결과 →
  확정. 가져오기 상태 버전은 덮어쓰기·제출마다 오르고 그 전의 읽기 결과를 지운다. 읽기는 시작할 때의 버전이 끝날 때도
  지금 버전일 때만 결과를 남기고, 확정은 지금 버전에서 오류 없이 만든 지도일 때만 받는다(아니면 ImportChanged → 409).

세대(generation) · 오류(workspace_errors) · 가져오기 대기(pending_imports) · 지도 정보(snapshot_info) · 상태 갱신
지도(updated_maps)는 옆 모듈에 두고, 여기에는 세대를 바꾸는 Workspaces와 요청 의존성을 둔다.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import Header, HTTPException, Request, Response, status

from ripple.agent.flow import Assistant
from ripple.agent.intake import IntakeService
from ripple.agent.resources import AssistantResources
from ripple.cases import CaseShelf
from ripple.contracts.domain import DataMode, GraphSnapshot
from ripple.contracts.ingest import ConfirmedMapping, MappingOverrides, MappingProposal, MappingSubmission
from ripple.contracts.records import Actor
from ripple.contracts.updates import StatusUpdate, UpdateEvent, UpdatePreview
from ripple.contracts.workspace import WORKSPACE_HEADER, ImportPreview, SnapshotInfo, SnapshotList
from ripple.engine.freshness import freshness
from ripple.engine.index import GraphIndex
from ripple.engine.updates import apply_update
from ripple.graph.files import load_snapshot
from ripple.graph.store import GraphStore
from ripple.ingest.build import build
from ripple.ingest.proposal import plan_file, to_contract
from ripple.ingest.workbook import RawSheet, read_workbook
from ripple.llm.base import Guarded, JsonModel, RoutedModel
from ripple.store.mappings import Kind as MappingKind
from ripple.store.mappings import MappingStore
from ripple.store.snapshots import SnapshotStore, SnapshotStoreError
from ripple.store.updates import UpdateLog

from .deps import AppContext
from .generation import Workspace, business_today, effective_mode, kst_today, token_of
from .live_world import live_world
from .mapping_memory import MappingMemory
from .pending_imports import IMPORT_WORDING, PENDING_TTL_S, BuiltImport, Claim, Confirmed, PendingImports
from .samples import SampleShelf
from .security import ViewPrincipal, demo_blocked
from .snapshot_info import default_info, default_name, info_of
from .updated_maps import bounded, latest_lineage, preview_of, recorded, updated_info
from .workspace_errors import Busy, ImportChanged, NotFound, StaleWorkspace, UpdateRejected, conflict


class Workspaces:
    """활성 작업 공간과 지도 전환. 전환(활성화·확정)은 잠금 하나로 차례로, 요청은 잠금 없이 지금 세대를 읽는다."""

    _realtime = False  # 실시간 시연 세계인가(기본은 날짜에 멈춘 세계 — 초기화를 건너뛴 대역도 그대로 동작)

    def __init__(
        self,
        context: AppContext,
        graph: GraphStore,
        model: JsonModel | RoutedModel | None,
        store: SnapshotStore,
        *,
        mappings: MappingStore | None = None,
        updates: UpdateLog | None = None,
        cases: CaseShelf | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = lambda: datetime.now(UTC),
        today: Callable[[], date] = kst_today,
    ) -> None:
        self._context = context
        self._graph = graph
        self._model = model
        self._store = store
        self._memory = MappingMemory(mappings, wall)
        self._updates = updates
        self._cases = cases  # 결정 도우미의 합성 과거 사례 선반(기본 지도를 깔 때 백그라운드로 미리 만듦)
        self._wall = wall
        self._today = today  # 한국 시간 오늘(검사는 바꿔 끼운다)
        self._realtime = context.settings.live_world
        self._world_day: date | None = None  # 실시간 시연 세계를 만든 날(새 날 넘어가기를 다 마친 뒤에 바뀜)
        self._new_day: Callable[[], None] | None = None  # 새 날 훅(on_new_day)
        self._instance = uuid.uuid4().hex[:8]  # 서버 프로세스마다 다름: 다시 켜면 토큰이 바뀐다
        self._switch = threading.Lock()
        self._parsing = threading.BoundedSemaphore(1)
        self._imports: PendingImports[BuiltImport, str] = PendingImports(IMPORT_WORDING, monotonic)  # 확정 = 지도 ID
        self._shelf = SampleShelf(context)
        self._current: Workspace | None = None
        self._generation = 0
        self._default: GraphSnapshot | None = None
        self._default_name = default_name(context.settings.generator_config)  # 기본 합성 · 시연 합성 지도
        self.restore_problem: str | None = None

    # ---------- 읽기 ----------

    @property
    def current(self) -> Workspace | None:
        return self._current

    @property
    def model(self) -> JsonModel | RoutedModel | None:
        """세대가 바뀌어도 같은 외부 모델(경로). 관리자 AI 호출 기록이 읽는다."""
        return self._model

    @contextmanager
    def pinned(self, token: str) -> Iterator[Workspace]:
        """기록·결정을 커밋하는 동안 지도를 바꾸지 못하게 전환 잠금을 잡고, 지금 세대가 token인지 본다.

        계산·검사는 잠금 밖에서 하고 저장소 커밋만 이 안에서 한다(docs/records.md(기록·결재) 5절) — 커밋 직전에 지도가
        바뀌어
        옛 지도 기준의 검토 요청·승인이 남지 않게. 다르면 StaleWorkspace(409)."""
        with self._switch:
            current = self._require()
            if current.token != token:
                raise StaleWorkspace(token, current)
            yield current

    def listing(self) -> SnapshotList:
        current = self._require()
        default = default_info(self.default_snapshot(), self._default_name)
        stored = latest_lineage(
            recorded([i for i in self._store.infos() if i.snapshot_id != default.snapshot_id], self._updates)
        )
        items = [default, *stored]
        if current.info.snapshot_id not in {i.snapshot_id for i in items}:
            items.append(current.info)  # 활성 지도의 정보 파일이 사라졌어도 목록에는 보인다(메모리의 정보)
        return SnapshotList(
            active_snapshot_id=current.snapshot.snapshot_id,
            workspace=current.token,
            instance=self._instance,
            generation=current.generation,
            data_mode=current.data_mode,
            llm_external=current.llm_external,
            restore_problem=self.restore_problem,
            items=tuple(items),
            today=self.today(),
            freshness=freshness(current.snapshot, self.today()),
        )

    def default_snapshot(self) -> GraphSnapshot:
        if self._default is None:
            raise RuntimeError("작업 공간 시작 전")
        return self._default

    def snapshot(self, key: str) -> GraphSnapshot:
        """목록의 지도(내보내기용). 없으면 NotFound, 손상이면 SnapshotStoreError."""
        default = self.default_snapshot()
        if key == default.snapshot_id:
            return default
        current = self._require()
        if key == current.snapshot.snapshot_id:
            return current.snapshot
        return self._stored(key)

    # ---------- 시작·전환 ----------

    def start(self) -> Workspace:
        """기본 지도(설정의 지도 파일)를 읽고, 저장된 활성 지도가 있으면 그 지도로 시작한다.

        기본 지도 파일이 없거나 잘못됐으면 시작하지 않는다. 저장된 활성 지도를 열지 못하면 기본 지도로 시작하고
        그 사유를 목록(restore_problem)에 남긴다 — 사용자가 다른 지도로 계산하는 줄 모르고 넘어가지 않게.
        활성 기록은 지우지 않는다(파일을 고치면 다음 시작에 다시 연다).
        """
        settings = self._context.settings
        if self._realtime:
            default, self._world_day = self._live_default()
        else:
            default = load_snapshot(settings.snapshot_path, settings.data_mode)
        self._default = default
        self._prepare_cases()
        target: str | None = None
        try:
            target = self._store.active()
        except SnapshotStoreError as error:
            self.restore_problem = f"최근 사용 지도 기록 읽기 실패 · 기본 지도로 시작({error})"
        with self._switch:
            if target is not None and target != default.snapshot_id:
                try:
                    snapshot = self._store.load(target)
                    info = self._store.info(target)
                    if not self._other_day(info):
                        return self._install(snapshot, info, persist=False)
                    self.restore_problem = (
                        "최근 사용 지도는 다른 날짜 시연 데이터에서 상태만 갱신한 지도 · 오늘 기본 지도로 시작"
                        "(지도 목록에서 다시 선택 가능)"
                    )
                except SnapshotStoreError as error:
                    self.restore_problem = f"최근 사용 지도 열기 실패 · 기본 지도로 시작({error})"
            return self._install(default, default_info(self.default_snapshot(), self._default_name), persist=False)

    def activate(self, key: str, expected: str | None) -> Workspace:
        """목록의 지도로 바꾼다. 같은 지도를 다시 켜도 새 세대(대화는 새로 시작)."""
        with self._switch:
            self._check(expected)
            if key == self.default_snapshot().snapshot_id:
                return self._install(
                    self.default_snapshot(), default_info(self.default_snapshot(), self._default_name), persist=True
                )
            snapshot = self._stored(key)
            return self._install(snapshot, self._store.info(key), persist=True)

    def stage(self, file_name: str, data: bytes) -> MappingProposal:
        """올린 엑셀을 읽어 매핑 제안(열 확인)을 낸다. 지도는 아직 만들지 않는다(확정 매핑을 받은 뒤 읽는다).

        한 번에 하나만 읽는다(읽는 중이면 Busy). 엑셀 파일이 아니거나 크기 상한을 넘으면 ValueError.
        """
        context = self._context
        with self.reading():
            raw = read_workbook(data)
            plan = plan_file(raw, context.columns, context.fields)
        import_id = self._imports.add(file_name, raw)
        proposal = to_contract(plan, raw, import_id, file_name, 1, context.columns)
        return self.with_remembered(proposal, raw, "full")

    def propose(self, import_id: str, overrides: MappingOverrides) -> MappingProposal:
        """사람이 정한 시트 상태·머리글 행으로 다시 제안한다(상태 버전 +1, 이전 읽기 결과 무효).

        모르는 시트·양식 시트, 비었거나 떨어진 머리글 행이면 ValueError(422).
        """
        context = self._context
        with self.reading():
            draft = self._imports.override(import_id, overrides)
            plan = plan_file(draft.raw, context.columns, context.fields, draft.overrides)
        return to_contract(plan, draft.raw, import_id, draft.file_name, draft.version, context.columns)

    def submit(self, import_id: str, submission: MappingSubmission) -> ImportPreview:
        """확정 매핑으로 읽는다(상태 버전 +1). 오류가 없고 그사이 버전이 그대로면 그 버전에서 확정할 수 있게 둔다."""
        with self.reading():
            draft = self._imports.advance(import_id, submission.version)
            snapshot, summary = build(draft.raw, draft.file_name, submission.mapping)
        if snapshot is None:
            return ImportPreview(summary=summary, version=draft.version)
        info = info_of(snapshot, draft.file_name, imported_at=self._wall(), summary=summary)
        self._imports.keep(draft, BuiltImport(draft.version, snapshot, info, submission.mapping))
        return ImportPreview(import_id=import_id, summary=summary, info=info, version=draft.version)

    def confirm(self, import_id: str, version: int, expected: str | None) -> Workspace:
        """확정: 그 버전에서 만든 지도를 지도 저장소에 저장하고 그 지도로 바꾼다.

        기대 토큰을 먼저 대조한다: 확정 응답을 잃은 화면이 옛 토큰으로 다시 보내면 409를 받아 지도 목록을 다시 읽는다.
        지금 버전이 아니거나 그 버전의 성공한 읽기 결과가 없으면 ImportChanged(409) — 열 확인을 고친 뒤의 결과만
        확정한다. 이미 확정한 가져오기를 같은 버전으로 다시 확정하면(30분 안) 그 지도가 지금 활성이면 그대로, 아니면
        그 지도로 바꾼다.
        """
        # 버전 대조 → 저장 → 전환 → 대기 항목 제거를 가져오기 잠금 안에서(PendingImports.confirm)
        with self._switch:
            self._check(expected)
            return self._imports.confirm(import_id, version, again=self._reconfirm, apply=self._adopt)

    def _adopt(self, claim: Claim[BuiltImport]) -> tuple[Workspace, str]:
        """확정(전환·가져오기 잠금 안에서): 읽은 지도를 저장하고 그 지도로 바꾼 뒤 매핑을 기억한다."""
        built = claim.built
        info = self._store.save(built.snapshot, built.info)
        workspace = self._install(built.snapshot, info, persist=True)
        self.remember_mapping(claim.pending.raw, built.mapping, "full", claim.pending.file_name)
        return workspace, built.snapshot.snapshot_id

    def _reconfirm(self, confirmed: Confirmed[str]) -> Workspace:
        """이미 같은 버전으로 확정한 가져오기를 다시 확정(전환·가져오기 잠금 안에서): 그 지도가 지금 활성이면 그대로,
        아니면 그 지도로 바꾼다."""
        current = self._require()
        if current.snapshot.snapshot_id == confirmed.result:
            return current
        snapshot = self._stored(confirmed.result)
        return self._install(snapshot, self._store.info(confirmed.result), persist=True)

    # ---------- 상태 갱신(docs/domain.md 12절) ----------

    def today(self) -> date:
        """지금 작업 공간의 업무상 오늘(business_today)."""
        return business_today(self._require(), self._today(), live=self._realtime)

    # ---------- 실시간 시연 세계 ----------

    def on_new_day(self, hook: Callable[[], None] | None) -> None:
        """기본 지도를 쓰던 세대가 새 날의 기본 지도로 넘어간 직후(전환 잠금 안) 부를 함수. 예외를 내지 않아야 한다."""
        self._new_day = hook

    def roll_day(self) -> None:
        """실시간 시연 세계에서 한국 시간 날짜가 바뀌었으면 새 날의 기본 지도로 바꾼다.

        기본 지도와 그 지도에서 상태만 바꾼 지도를 쓰던 세대는 새 세대로 넘기고(화면은 토큰이 바뀌어 다시 읽는다 —
        전날 세계의 갱신 지도는 날짜가 그날에 묶여 새 날의 샘플도 없다, 목록에는 남는다), 가져온 지도와 거기서 이어진
        갱신 지도를 쓰던 세대는 그대로 둔다.
        """
        if not self._realtime or self._world_day == self._today():
            return
        with self._switch:
            if self._world_day == self._today():
                return
            old = self.default_snapshot()
            before = self._shelf.ecns
            current = self._require()
            update = current.info.update
            follows = current.snapshot.snapshot_id == old.snapshot_id or (
                update is not None and update.lineage_root == old.snapshot_id
            )
            # 샘플은 새 세계의 설계변경에서 고르므로 설치 전에 새 날로 넘기되, 설치가 실패하면 되돌린다
            # — 날짜는 다 마친 뒤에만 바꿔 다음 요청이 다시 시도한다(활성이 전날 지도에 굳지 않게)
            self._default, day = self._live_default()
            try:
                if follows:
                    self._install(self._default, default_info(self._default, self._default_name), persist=False)
            except BaseException:
                self._default = old
                self._shelf.ecns = before
                raise
            self._prepare_cases()  # 바꿔 끼운 뒤에만(되돌리면 새 날 묶음을 만들기 시작하지 않음)
            try:
                if follows and self._new_day is not None:
                    self._new_day()  # 시연 기록 새로 채우기(잠금 안 — 다른 요청은 다 채운 뒤의 새 세대를 본다)
            finally:
                self._world_day = day

    def _other_day(self, info: SnapshotInfo) -> bool:
        """실시간 시연 세계에서 다른 날의 기본 지도에서 상태만 바꾼 지도인가(계보 시작이 오늘 기본 지도도, 저장된
        가져온 지도도 아님). 그날 세계의 날짜에 묶여 오늘 세계와 맞지 않고 샘플도 없어 시작할 때 다시 켜지 않는다."""
        if not self._realtime or info.update is None:
            return False
        root = info.update.lineage_root
        if root == self.default_snapshot().snapshot_id:
            return False
        try:
            self._store.info(root)
        except SnapshotStoreError:
            return True  # 계보 시작이 저장소에 없다 = 생성기가 만든 그날의 기본 지도
        return False

    def _live_default(self) -> tuple[GraphSnapshot, date]:
        """오늘 날짜로 만든 시연 세계의 기본 지도와 그 날(샘플은 그 세계의 설계변경 이력에서 고른다)."""
        world = live_world(self._today(), self._context.settings.generator_config)
        self._shelf.ecns = world.ecns
        return world.snapshot, world.day

    def _prepare_cases(self) -> None:
        """기본 지도의 합성 과거 사례 묶음을 백그라운드로 만들기 시작한다(이미 있거나 만드는 중이면 그대로, 시작을 막지
        않음 — 실패는 선반이 unavailable 묶음으로 남긴다)."""
        if self._cases is not None and self._default is not None:
            self._cases.prepare(self._default)

    def map_of(self, snapshot_id: str) -> tuple[GraphSnapshot, SnapshotInfo] | None:
        """그 ID의 지도와 정보(지금 · 기본 · 저장된 지도). 모르면 None(지난 날의 실시간 시연 세계 기본 지도 등)."""
        current = self._current
        if current is not None and current.snapshot.snapshot_id == snapshot_id:
            return current.snapshot, current.info
        default = self._default
        if default is not None and default.snapshot_id == snapshot_id:
            return default, default_info(default, self._default_name)
        try:
            return self._store.load(snapshot_id), self._store.info(snapshot_id)
        except SnapshotStoreError:
            return None

    def preview_update(self, update: StatusUpdate) -> UpdatePreview:
        """지금 지도에 적용하면 무엇이 바뀌는지(지도는 바꾸지 않음). 거부 항목이 있으면 snapshot_id 없음."""
        current = self._require()
        return preview_of(current.snapshot.snapshot_id, bounded(apply_update(current.snapshot, update), update))

    def apply_update(
        self, update: StatusUpdate, expected: str, actor: Actor, log: UpdateLog
    ) -> tuple[Workspace, UpdateEvent]:
        """지금 지도에 상태 갱신을 적용해 새 지도로 바꾼다(새 세대). 기대 토큰이 다르면 StaleWorkspace(409),
        거부 항목이 있으면 UpdateRejected(422 — 아무것도 바꾸지 않음). 바뀐 것이 없어도(재확인) 기록은 남긴다."""
        with self._switch:
            self._check(expected)
            current = self._require()
            if update.base_snapshot_id is not None and update.base_snapshot_id != current.snapshot.snapshot_id:
                raise StaleWorkspace(expected, current)  # 화면·미리보기 뒤에 지도가 바뀜: 새 상태로 다시 보고 하게
            outcome = bounded(apply_update(current.snapshot, update), update)
            if outcome.snapshot is None:
                raise UpdateRejected(preview_of(current.snapshot.snapshot_id, outcome))
            event = UpdateEvent(
                event_id=uuid.uuid4().hex,
                base_snapshot_id=current.snapshot.snapshot_id,
                snapshot_id=outcome.snapshot.snapshot_id,
                origin=update.origin,
                file_name=update.file_name,
                actor=actor,
                at=self._wall(),
                diff=outcome.diff,
                items=len(update.items),
            )
            if outcome.snapshot.snapshot_id == current.snapshot.snapshot_id:
                log.append(event, update)
                return current, event  # 값이 그대로인 재확인: 지도·세대 그대로, 기록만
            # 순서: 지도 파일 저장 → 기록 넣기 → 활성 전환 → 기록 확정(전환 실패면 기록 되돌림,
            # 확정 실패면 전환을 그 전 세대로 되돌림). 기록이 확정되지 않은 갱신 지도는 목록·전환에서 숨긴다(recorded) —
            # 기록 없이 쓰이는 갱신 지도도, 적용되지 않은 기록도 남지 않게
            info = self._store.save(outcome.snapshot, updated_info(outcome.snapshot, current, event))
            with log.recording(event, update, undo=lambda: self._restore(current)):
                workspace = self._install(outcome.snapshot, info, persist=True)
            return workspace, event

    # ---------- 열 매핑 기억(docs/input.md(엑셀 양식) 4절) ----------

    @property
    def context(self) -> AppContext:
        return self._context

    def with_remembered(
        self, proposal: MappingProposal, raw: dict[str, RawSheet], kind: MappingKind
    ) -> MappingProposal:
        """전에 확정한 같은 모양 파일의 매핑이 지금 파일에도 맞으면 제안에 싣는다(MappingMemory)."""
        return self._memory.with_remembered(proposal, raw, kind)

    def remember_mapping(
        self, raw: dict[str, RawSheet], mapping: ConfirmedMapping | None, kind: MappingKind, file_name: str
    ) -> None:
        """확정한 매핑을 파일 모양 지문과 함께 기억한다. 실패해도 확정은 그대로."""
        self._memory.remember(raw, mapping, kind, file_name)

    def forget_mappings(self) -> None:
        self._memory.forget()

    # ---------- 내부 ----------

    @contextmanager
    def reading(self) -> Iterator[None]:
        """엑셀 읽기·제안·확정 매핑 읽기는 한 번에 하나(무거운 계산이 겹치지 않게). 읽는 중이면 Busy."""
        if not self._parsing.acquire(blocking=False):
            raise Busy("다른 엑셀 파일 읽는 중 · 끝난 뒤 다시 시도")
        try:
            yield
        finally:
            self._parsing.release()

    def _require(self) -> Workspace:
        if self._current is None:
            raise RuntimeError("작업 공간 시작 전")
        return self._current

    def _check(self, expected: str | None) -> None:
        current = self._require()
        if expected is not None and expected != current.token:
            raise StaleWorkspace(expected, current)

    def _stored(self, key: str) -> GraphSnapshot:
        found = [i for i in self._store.infos() if i.snapshot_id == key]
        if not recorded(found, self._updates):  # 없거나, 갱신 기록이 되돌려진 상태 갱신 지도
            raise NotFound(f"목록에 없는 지도: {key[:40]}")
        return self._store.load(key)

    def _install(self, snapshot: GraphSnapshot, info: SnapshotInfo, *, persist: bool) -> Workspace:
        """새 세대를 다 만든 뒤 그래프 저장소에 넣고(persist면 활성 기록을 쓰고) 마지막에 바꿔 끼운다."""
        context = self._context
        mode = effective_mode(context.settings.data_mode, snapshot)
        index = GraphIndex(snapshot)
        samples = self._shelf.of(self._default, snapshot, info, index)
        resources = AssistantResources.build(
            snapshot,
            index,
            context.lexicon,
            context.decision,
            context.rulebook,
            context.params,
            mode,
            context.contacts,
            context.glossary,
        )
        guard = Guarded(self._model, mode)
        generation = self._generation + 1
        workspace = Workspace(
            generation=generation,
            token=token_of(snapshot.snapshot_id, self._instance, generation),
            snapshot=snapshot,
            info=info,
            index=index,
            samples=samples,
            assistant=Assistant(resources, llm=guard),
            intake=IntakeService(resources, llm=guard),
            data_mode=mode,
            llm_external=guard.usable,
        )
        self._graph.save(snapshot)
        if persist:
            self._store.set_active(None if info.default else snapshot.snapshot_id)
            self.restore_problem = None
        self._generation = generation
        self._current = workspace
        return workspace

    def _restore(self, previous: Workspace) -> None:
        """전환한 뒤 갱신 기록 확정이 실패: 그 전 세대(같은 토큰)로 되돌린다 — 그래프 저장소·활성 기록도."""
        self._graph.save(previous.snapshot)
        self._store.set_active(None if previous.info.default else previous.snapshot.snapshot_id)
        self._current = previous


# ---------- 요청 의존성 ----------


def workspaces_of(request: Request) -> Workspaces | None:
    holder = getattr(request.app.state, "workspaces", None)
    return holder if isinstance(holder, Workspaces) else None


def current_workspace(request: Request) -> Workspace | None:
    holder = workspaces_of(request)
    return None if holder is None else holder.current


def get_workspaces(request: Request) -> Workspaces:
    holder = workspaces_of(request)
    if holder is None or holder.current is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="연결 지도 준비 중")
    holder.roll_day()
    return holder


ExpectedWorkspace = Annotated[
    str | None,
    Header(
        alias=WORKSPACE_HEADER,
        description="화면이 아는 작업 공간 토큰. 지금 토큰과 다르면 409(workspace_changed). 없으면 대조하지 않는다.",
    ),
]


def get_workspace(
    request: Request, response: Response, principal: ViewPrincipal, expected: ExpectedWorkspace = None
) -> Workspace:
    """이 요청이 끝까지 쓸 세대. 기대 토큰이 다르면 409, 응답 머리글에 처리한 세대의 토큰을 단다.

    로그인·보기 권한을 요구하고, 체험이면 바로 이 세대의 유효 데이터 모드로 막는다. 검사한 세대와 처리하는
    세대가 같아서 검사 직후 관리자가 실데이터 지도로 바꿔도 이 요청은 검사한 합성 세대로 끝난다
    (docs/operations.md(서비스) 2절)."""
    workspace = get_workspaces(request).current
    assert workspace is not None
    if principal.demo and workspace.data_mode is not DataMode.SYNTHETIC:
        raise demo_blocked()
    if expected is not None and expected != workspace.token:
        raise conflict(StaleWorkspace(expected, workspace))
    response.headers[WORKSPACE_HEADER] = workspace.token
    return workspace


__all__ = [
    "PENDING_TTL_S",
    "Busy",
    "ExpectedWorkspace",
    "ImportChanged",
    "NotFound",
    "StaleWorkspace",
    "UpdateRejected",
    "Workspace",
    "Workspaces",
    "conflict",
    "current_workspace",
    "get_workspace",
    "get_workspaces",
    "info_of",
    "workspaces_of",
]
