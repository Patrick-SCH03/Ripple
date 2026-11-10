"""합성 NCR 묶음 연결(docs/records.md '합성 NCR'): 프로세스에 하나인 합성 묶음과, 데이터 모드에 따른 건수·요약.

묶음은 기본 생성기 설정·씨앗과 params/ncr_v1.yaml만으로 정해진다(지도·기준일·기록을 보지 않음 — 실시간 시연
세계에서 날이 바뀌어도 같다). 처음 쓸 때 한 번 만든다(36건, 몇 밀리초). 실데이터 모드면 만들지 않고 빈 요약 + 이유.
분석(사전 점검 항목의 '같은 유형 합성 NCR n건')과 기록 본문 계산이 같은 건수를 쓴다(routes/analyses.py, records.py).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ripple.cases import NcrBundle, load_ncr_settings, ncr_bundle
from ripple.contracts.domain import DataMode
from ripple.contracts.ncr import NcrSummary
from ripple.generator.io import load_config

_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class _Shelf:
    bundle: NcrBundle
    recent: int  # 요약 최근 건수 기본값(설정)


_SHELF: list[_Shelf] = []


def _shelf() -> _Shelf:
    with _LOCK:
        if not _SHELF:
            settings = load_ncr_settings()
            _SHELF.append(_Shelf(ncr_bundle(load_config(), DataMode.SYNTHETIC, settings), settings.recent))
        return _SHELF[0]


def ncr_counts(data_mode: DataMode) -> dict[str, int] | None:
    """사전 점검에 싣는 유형별 합성 NCR 건수. 합성 모드에서만(실데이터면 None — 엔진도 한 번 더 막는다)."""
    return _shelf().bundle.counts() if data_mode is DataMode.SYNTHETIC else None


def ncr_summary(data_mode: DataMode, recent: int | None = None) -> NcrSummary:
    """유형별 건수 + 최근 n건(기본은 설정값). 실데이터 모드는 묶음을 만들지 않고 빈 요약 + 이유."""
    if data_mode is not DataMode.SYNTHETIC:
        return NcrBundle().summary(1)
    shelf = _shelf()
    return shelf.bundle.summary(recent or shelf.recent)
