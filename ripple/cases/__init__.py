"""과거 사례(docs/records.md '합성 과거 사례'): 결재할 때 보는 '비슷한 과거 사례 3건'과 한 줄 요약.

- 합성 모드: 같은 생성기 세계의 개발 분할 설계변경(화면 샘플 제외)으로 시연용 합성 과거 사례 묶음을 만든다 —
  예측은 엔진, 실적은 숨긴 실제 모델, 결정 종류·시점만 시드 고정 가정(params/cases_v1.yaml). 늘 synthetic=True.
- 실데이터 모드: 기록 중 실적이 있는 종료 ECN만(synthetic=False, 없으면 빈 묶음).
- 비슷한 정도: 같은 연산 종류 안에서 같은 블록·구역·계통·변경 목적·크기 가까움(결정적 점수, 문턱 미만 제외).
- 합성 NCR(docs/records.md '합성 NCR', ncr.py): 사전 점검 유형별 부적합 보고 시연 재료. 합성 모드에서만, 건수만.
"""

from .features import Features, MapLookup, features_of, match
from .library import CaseLibrary, LibraryStatus, StoredCase, find_cases
from .materials import contradiction, unique_titles
from .ncr import NcrBundle, NcrSettings, load_ncr_settings, ncr_bundle
from .notes import summarize
from .real import real_cases, real_library
from .settings import CaseSettings, Choice, load_settings
from .shelf import CaseShelf, SamplePicker, WorkspaceLike
from .synthetic import EngineKit, World, build_library, regenerate, scenario_day

__all__ = [
    "CaseLibrary",
    "CaseSettings",
    "CaseShelf",
    "Choice",
    "EngineKit",
    "Features",
    "LibraryStatus",
    "MapLookup",
    "NcrBundle",
    "NcrSettings",
    "SamplePicker",
    "StoredCase",
    "WorkspaceLike",
    "World",
    "build_library",
    "contradiction",
    "features_of",
    "find_cases",
    "load_ncr_settings",
    "load_settings",
    "match",
    "ncr_bundle",
    "real_cases",
    "real_library",
    "regenerate",
    "scenario_day",
    "summarize",
    "unique_titles",
]
