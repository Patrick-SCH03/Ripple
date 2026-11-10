"""작업 공간 지도 → 과거 사례 묶음(지도 ID 캐시, 백그라운드로 미리 만들기).

- 합성: 뿌리 지도 ID(상태 갱신 지도는 계보 시작)마다 한 번 만들어 기억한다(최근 keep_maps개). 만드는 데 몇 초 걸려
  작업 공간이 기본 지도를 깔 때(시작·날짜 전환) prepare로 백그라운드에서 미리 만든다. 그 전에 온 요청은 기다리지 않고
  status=building 묶음(빈 답)을 받는다 — 화면은 '과거 사례를 준비하는 중'.
- 실데이터: 요청마다 기록·실적 저장소에서 바로 만든다(합성 사례 없음).

통합: 작업 공간(ripple/api/workspace.py)이 기본 지도를 깐 뒤 `shelf.prepare(default_snapshot)`, 결정 도우미는
`lambda result: find_cases(shelf.library_for(workspace), result)`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path
from typing import Protocol

from ripple.contracts.dataset import EcnSplit, GeneratedEcn
from ripple.contracts.domain import DataMode, GraphSnapshot
from ripple.contracts.workspace import SnapshotInfo
from ripple.engine.index import GraphIndex
from ripple.generator.build import generate
from ripple.generator.config import GeneratorConfig
from ripple.generator.io import load_config
from ripple.store.outcomes import OutcomeLog
from ripple.store.records import RecordStore

from .features import MapLookup
from .library import CaseLibrary
from .real import real_library
from .settings import CaseSettings, load_settings
from .synthetic import EngineKit, World, build_library, regenerate

log = logging.getLogger(__name__)
RETRY_S = 60.0  # 만들다 실패한 묶음을 다시 시도하기까지(실패가 되풀이돼도 요청마다 만들지 않게)

SamplePicker = Callable[[GraphIndex, tuple[GeneratedEcn, ...]], Iterable[str]]
"""(지도 색인, 개발 분할 설계변경) → 화면 샘플 ECN 번호. API가 ripple/api/samples.py pick_samples로 넘긴다
(과거 사례가 지금 화면 목록과 겹치지 않게)."""


class WorkspaceLike(Protocol):
    """library_for가 읽는 작업 공간 세대의 부분(ripple/api/generation.py Workspace)."""

    @property
    def snapshot(self) -> GraphSnapshot: ...

    @property
    def info(self) -> SnapshotInfo: ...

    @property
    def data_mode(self) -> DataMode: ...


class CaseShelf:
    def __init__(
        self,
        kit: EngineKit,
        hidden_params: Path,
        samples: SamplePicker,
        *,
        config: GeneratorConfig | None = None,
        settings: CaseSettings | None = None,
        records: RecordStore | None = None,
        outcomes: OutcomeLog | None = None,
        retry_s: float = RETRY_S,
    ) -> None:
        """hidden_params = 숨긴 실제 모델이 참 파라미터를 뽑는 비용 파라미터 파일(엔진과 같은 params/cost_v1.yaml)."""
        self._kit = kit
        self._hidden_params = hidden_params
        self._samples = samples
        self._config = config or load_config()
        self.settings = settings or load_settings()
        self._records = records
        self._outcomes = outcomes
        self._lock = threading.Lock()
        self._libraries: OrderedDict[str, CaseLibrary] = OrderedDict()
        self._building: dict[str, threading.Thread] = {}
        self._failed: dict[str, float] = {}  # 만들다 실패한 묶음 → 그 시각(monotonic) — retry_s 뒤 다시 시도
        self._retry_s = retry_s

    def prepare(self, snapshot: GraphSnapshot, root_id: str | None = None, *, background: bool = True) -> None:
        """그 지도(뿌리 = root_id, 없으면 그 지도)의 합성 묶음을 만든다. 이미 있거나 만드는 중이면 아무것도 안 함."""
        root = root_id or snapshot.snapshot_id
        with self._lock:
            self._forget_failed(root)
            if root in self._libraries or root in self._building:
                return
            worker = self._worker(root, lambda: self._make(snapshot, root))
        if background:
            worker.start()
        else:
            worker.run()

    def library_for_day(self, root: str, day: date) -> CaseLibrary:
        """지도를 서버가 모르는 합성 기록(지난 날의 실시간 시연 세계 기본 지도 등)의 묶음: 그 기록의 기준일로 생성기
        세계를 다시 만들어 지도 ID가 기록과 같을 때만 만든다(백그라운드 — 처음엔 building, 다르면 unavailable).
        만든 묶음은 지도 ID로 기억한다(최근 keep_maps개)."""
        with self._lock:
            self._forget_failed(root)
            found = self._libraries.get(root)
            worker = (
                None
                if found is not None or root in self._building
                else self._worker(root, lambda: self._make_day(root, day))
            )
        if found is not None:
            return found
        if worker is not None:
            worker.start()
        return CaseLibrary(snapshot_id=root, status="building", synthetic=True, similarity=self.settings.similarity)

    def _worker(self, root: str, make: Callable[[], CaseLibrary]) -> threading.Thread:
        """(잠금 안에서) 묶음을 만들 스레드를 만들어 만드는 중으로 적는다(시작은 호출자가)."""
        worker = threading.Thread(target=self._build, args=(make, root), name=f"cases-{root}", daemon=True)
        self._building[root] = worker
        return worker

    def wait(self, timeout: float | None = None) -> None:
        """만드는 중인 묶음이 끝날 때까지(검사·스크립트용)."""
        with self._lock:
            workers = list(self._building.values())
        for worker in workers:
            if worker.is_alive():
                worker.join(timeout)

    def library_for(self, workspace: WorkspaceLike) -> CaseLibrary:
        """그 세대의 묶음. 실데이터면 지금 기록으로, 합성이면 기억한 것(없으면 만들기 시작하고 building)."""
        similarity = self.settings.similarity
        if workspace.data_mode is DataMode.REAL:
            if self._records is None or self._outcomes is None:
                return CaseLibrary(snapshot_id=None, status="ready", synthetic=False, similarity=similarity)
            return real_library(self._records, self._outcomes, similarity, MapLookup.of(workspace.snapshot))
        update = workspace.info.update
        root = update.lineage_root if update is not None else workspace.snapshot.snapshot_id
        with self._lock:
            self._forget_failed(root)
            found = self._libraries.get(root)
            building = root in self._building
        if found is not None:
            return found
        if not building:
            self.prepare(workspace.snapshot, root)
        return CaseLibrary(snapshot_id=root, status="building", synthetic=True, similarity=similarity)

    def _forget_failed(self, root: str) -> None:
        """(잠금 안에서) 실패한 지 retry_s가 지난 묶음을 잊어 다음 prepare·요청이 다시 만들게 한다."""
        failed = self._failed.get(root)
        if failed is not None and time.monotonic() - failed >= self._retry_s:
            self._failed.pop(root, None)
            self._libraries.pop(root, None)

    def _build(self, make: Callable[[], CaseLibrary], root: str) -> None:
        failed = False
        try:
            library = make()
        except Exception as error:  # 묶음을 못 만들어도 결정 도우미의 나머지는 돌아야 한다
            log.exception("과거 사례 묶음 생성 실패(%s) — %s초 뒤 재시도", root, self._retry_s)
            library = self._unavailable(root, f"과거 사례 묶음 생성 실패({type(error).__name__})")
            failed = True
        with self._lock:
            if failed:
                self._failed[root] = time.monotonic()
            self._libraries[root] = library
            self._libraries.move_to_end(root)
            while len(self._libraries) > self.settings.keep_maps:
                self._libraries.popitem(last=False)
            self._building.pop(root, None)

    def _make(self, snapshot: GraphSnapshot, root: str) -> CaseLibrary:
        world = regenerate(snapshot, root, self._config, self._hidden_params)
        if world is None:
            return self._unavailable(root, "생성기 기본 합성 지도에서 이어진 지도가 아님 — 합성 과거 사례 없음")
        return self._library(world)

    def _make_day(self, root: str, day: date) -> CaseLibrary:
        generated = generate(self._config.model_copy(update={"scenario_date": day}))
        world = (
            regenerate(generated.snapshot, root, self._config, self._hidden_params, generated)
            if generated.snapshot.snapshot_id == root
            else None
        )
        if world is None:
            return self._unavailable(root, "기록 기준일로 다시 만든 지도가 기록의 지도와 다름 — 합성 과거 사례 없음")
        return self._library(world)

    def _library(self, world: World) -> CaseLibrary:
        dev = tuple(e for e in world.generated.ecns if e.split is EcnSplit.DEV)
        exclude = set(self._samples(world.index, dev))
        return build_library(world, self._kit, self.settings, exclude)

    def _unavailable(self, root: str, problem: str) -> CaseLibrary:
        return CaseLibrary(
            snapshot_id=root, status="unavailable", synthetic=True, similarity=self.settings.similarity, problem=problem
        )
