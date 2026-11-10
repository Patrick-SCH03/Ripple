"""과거 사례 묶음과 비슷한 사례 찾기(계약 ripple/contracts/brief.py의 PastCases·PastCase 그대로)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.brief import PastCase, PastCases
from ripple.contracts.domain import DataMode
from ripple.contracts.result import AnalysisResult

from .features import Features, MapLookup, features_of, match
from .notes import CaseFacts, summarize
from .settings import Similarity

LibraryStatus = Literal["ready", "building", "unavailable"]
"""ready = 찾을 수 있음 · building = 백그라운드로 만드는 중(빈 답 — 화면은 '과거 사례를 준비하는 중') ·
unavailable = 이 지도로는 만들 수 없음(생성기 세계가 아닌 합성 지도 등, 빈 답)."""


@dataclass(frozen=True, slots=True)
class StoredCase:
    """묶음의 사례 하나: 계약 모양(same은 찾을 때 채움) + 특징 + 검사용 근거."""

    case: PastCase
    features: Features
    source_id: str  # 재료 설계변경 번호(합성: 개발 분할 ECN, 실데이터: 기록 ECN)
    request: AnalysisRequest | None = None  # 결정할 때 분석한 요청(합성 — 예측을 엔진으로 다시 계산할 수 있게)
    facts: CaseFacts | None = None  # 교훈을 고른 값(합성)
    note_id: str = ""  # 고른 교훈 템플릿


@dataclass(frozen=True, slots=True)
class CaseLibrary:
    """지도(합성 스냅샷) 하나 — 또는 실데이터 기록 — 의 과거 사례 묶음."""

    snapshot_id: str | None  # 합성: 뿌리 지도 ID(상태 갱신 지도는 계보 시작), 실데이터: None
    status: LibraryStatus
    synthetic: bool
    similarity: Similarity
    cases: tuple[StoredCase, ...] = ()
    lookup: MapLookup = field(default_factory=MapLookup)
    built_seconds: float | None = None  # 만드는 데 걸린 시간(합성)
    problem: str | None = None  # unavailable 사유(명사형)

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    @property
    def size(self) -> int:
        return len(self.cases)


def find_cases(library: CaseLibrary, result: AnalysisResult, limit: int = 3) -> PastCases:
    """이번 분석과 비슷한 과거 사례 최대 limit건과 한 줄 요약.

    순서: 같은 블록 무리 → 다른 블록 무리, 무리 안에서는 실적이 있는 사례(승인)를 앞에 — 반려·보류(실적 없음)는 같은
    무리의 실적 있는 사례가 모자랄 때만 — 그다음 점수 순, 같으면 사례 ID 순.
    같은 연산 종류만 보고 문턱 미만은 뺀다. 같은 변경(연산이 똑같음)·같은 ECN 번호는 자기 자신이라 뺀다.
    실데이터 결과에는 합성 묶음을 쓰지 않는다(빈 답, unavailable). 묶음이 준비되지 않았으면(만드는 중·만들 수 없음)
    빈 답이고, 그 상태를 status로 싣는다(화면이 '준비하는 중'과 '그리지 않음'을 가른다)."""
    if library.synthetic and result.data_mode is DataMode.REAL:
        return PastCases(status="unavailable")  # 실데이터 결재에 합성 사례를 섞지 않는다(묶음을 고른 쪽과 따로 막음)
    if not library.ready or limit <= 0:
        return PastCases(synthetic=library.synthetic, status=library.status)
    query = features_of(result, library.lookup)
    ecn_id = result.request.change.ecn_id
    scored = []
    for stored in library.cases:
        if stored.features.ops_key == query.ops_key or stored.source_id == ecn_id or stored.case.case_id == ecn_id:
            continue
        found = match(query, stored.features, library.similarity, library.lookup)
        if found is not None and found.score >= library.similarity.threshold:
            other_block = 0 if query.blocks & stored.features.blocks else 1
            unmeasured = 0 if stored.case.actual_krw is not None else 1
            key = (other_block, unmeasured, -found.score, stored.case.case_id)
            scored.append((key, stored, found.same))
    scored.sort(key=lambda row: row[0])
    items = tuple(stored.case.model_copy(update={"same": same}) for _, stored, same in scored[:limit])
    return PastCases(items=items, summary=summarize(items), library_size=library.size, synthetic=library.synthetic)
