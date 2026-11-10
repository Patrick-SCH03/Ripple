"""결정 도우미의 비슷한 과거 사례 연결(docs/records.md '합성 과거 사례'): **기록이 깔린 지도** 기준으로 묶음을 고른다.

- 합성 기록: 그 기록의 지도(상태 갱신 지도는 계보 시작)로 만든 합성 묶음. 묶음은 만드는 데 약 6초가 걸려 작업 공간이
  기본 지도를 깔 때(시작·날짜 전환) 백그라운드로 미리 만들고, 그 전에 온 요청은 status=building(빈 답)을 받는다.
- 실데이터 기록: 기록·실적 저장소의 실데이터 묶음(합성 사례는 섞지 않음).
- 기록의 지도를 지금 서버가 모르면(지난 날의 실시간 시연 세계 지도 등) 그 기록의 기준일로 생성기 세계를 다시 만들어
  지도 ID가 기록과 같을 때만 묶음을 만든다(백그라운드, 처음엔 building). 다르면 unavailable — 다른 지도의 사례를
  끌어오지 않는다.

합성 묶음 선반(CaseShelf)은 프로세스에 하나를 같은 엔진 입력(규칙표·비용 파라미터 판·파일)끼리 나눠 쓴다. 묶음은 지도와
엔진 입력만으로 정해지고(기록·실적을 보지 않음) 서버는 앱 하나라, 같은 프로세스에서 앱을 여러 번 만드는 검사가 같은
세계의 묶음을 앱마다 다시 만들지 않게 하려는 것이다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ripple.brief import CaseFinder
from ripple.cases import CaseShelf, EngineKit, MapLookup, find_cases, real_library
from ripple.contracts.brief import PastCases
from ripple.contracts.domain import DataMode, GraphSnapshot
from ripple.contracts.records import RecordBody
from ripple.contracts.workspace import SnapshotInfo
from ripple.generator.io import load_config
from ripple.store.outcomes import OutcomeLog
from ripple.store.records import RecordStore

from .deps import AppContext
from .samples import pick_samples
from .workspace import Workspaces

_SHELVES: dict[tuple[str, str, str, str], CaseShelf] = {}
_LOCK = threading.Lock()


def shared_shelf(context: AppContext) -> CaseShelf:
    """이 엔진 입력의 합성 과거 사례 선반(프로세스에 하나). 화면 샘플은 묶음에서 뺀다(지금 목록과 겹치지 않게)."""
    rulebook, params = context.rulebook, context.params
    config = context.settings.generator_config  # 기본 · 시연 합성 지도(세계를 다시 만들 생성기 설정)
    key = (rulebook.version, params.version, str(context.settings.params_path), str(config))
    with _LOCK:
        shelf = _SHELVES.get(key)
        if shelf is None:
            shelf = CaseShelf(
                EngineKit(rulebook, params),
                context.settings.params_path,
                lambda index, ecns: (sample.ecn_id for sample in pick_samples(index, ecns, rulebook)),
                config=load_config(config),
            )
            _SHELVES[key] = shelf
        return shelf


@dataclass(frozen=True, slots=True)
class RecordMap:
    """기록이 깔린 지도(선반의 WorkspaceLike): 지도 · 정보(계보) · 기록의 데이터 모드."""

    snapshot: GraphSnapshot
    info: SnapshotInfo
    data_mode: DataMode


def finder_for(
    shelf: CaseShelf,
    holder: Workspaces | None,
    body: RecordBody,
    records: RecordStore,
    outcomes: OutcomeLog | None,
) -> CaseFinder:
    """그 기록의 과거 사례 찾기. 실데이터 기록은 실데이터 묶음만, 합성 기록은 기록 지도의 합성 묶음만."""
    found = holder.map_of(body.snapshot_id) if holder is not None else None
    if body.data_mode is DataMode.REAL:
        current = holder.current if holder is not None else None
        snapshot = found[0] if found is not None else (current.snapshot if current is not None else None)
        if outcomes is None or snapshot is None:
            return lambda _result: PastCases()
        library = real_library(records, outcomes, shelf.settings.similarity, MapLookup.of(snapshot))
        return lambda result: find_cases(library, result)
    if found is None:  # 지난 날의 실시간 시연 세계 등: 그 기록의 기준일로 세계를 다시 만들어 지도 ID가 같으면 묶음
        root, day = body.snapshot_id, body.result.request.as_of
        return lambda result: find_cases(shelf.library_for_day(root, day), result)
    view = RecordMap(snapshot=found[0], info=found[1], data_mode=DataMode.SYNTHETIC)
    return lambda result: find_cases(shelf.library_for(view), result)
