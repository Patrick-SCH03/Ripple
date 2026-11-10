"""결정 도우미 서비스(docs/records.md(기록·결재) 결정 도우미 절): 결재할 개정의 기록 본문으로 만들고 잠깐 기억한다.

- 외부 AI 경계는 **기록 본문의 데이터 모드**로 정한다(활성 지도가 합성이어도 실데이터 기록을 열 수 있어서). 설정이
  실데이터 모드여도 부르지 않는다.
- 같은 기록 · 같은 개정 · 같은 업무상 오늘(자정에 D-n이 바뀜) · 같은 AI 경로(모델·판·부를 수 있는지)면 프로세스
  메모리에 둔 결과를 다시 쓴다(다시 열 때 AI를 또 부르지 않게, 개수 상한·시간 제한). 같은 본문(기록 ID)이 다른 개정으로
  다시 올 수 있어(A → B → A) 개정도 키에 둔다 — 결과에 개정이 적힌다.
- 더 저렴한 대안 권고: 기록 본문에 대안이 없으면(화면은 늘 대안 없이 기록) 기록의 지도를 서버가 갖고 있고 계산 판이
  같을 때만 그 기록 요청을 대안 포함으로 한 번 계산한다(recorded_alternatives) — 같은 지도·같은 판이면 결정적이라
  상세 대안 탭과 같은 숫자다. 조건이 안 맞으면 판정 줄로 간다. 기록 저장 형식은 그대로.
- 비슷한 과거 사례는 요청마다 넘겨받은 CaseFinder(기록이 깔린 지도 기준, ripple/api/past_cases.py)가 채운다.
  묶음을 아직 만드는 중(building)이면 기억하지 않는다 — 다 만든 뒤 다시 열면 사례가 보이게.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date

from ripple.brief import CaseFinder, build_brief, no_cases
from ripple.contracts.brief import DecisionBrief
from ripple.contracts.domain import DataMode
from ripple.contracts.records import RecordBody
from ripple.contracts.result import AnalysisResult
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.llm.base import Guarded, JsonModel, RoutedModel
from ripple.store.ttl import TtlStore

from .deps import AppContext
from .records import same_version_of
from .workspace import Workspaces

log = logging.getLogger(__name__)
CACHE_TTL_S = 900.0
CACHE_LIMIT = 200


class BriefService:
    def __init__(self, *, ttl_s: float = CACHE_TTL_S, limit: int = CACHE_LIMIT) -> None:
        self._cache: TtlStore[DecisionBrief] = TtlStore(ttl_s=ttl_s, limit=limit)
        self.cases: CaseFinder = no_cases

    def brief(
        self,
        body: RecordBody,
        *,
        record_id: str,
        revision: int,
        today: date,
        model: JsonModel | RoutedModel | None,
        configured: DataMode,
        cases: CaseFinder | None = None,
        alternatives: Callable[[], AnalysisResult | None] | None = None,
    ) -> DecisionBrief:
        """alternatives는 기억에 없을 때만 부른다(대안 포함 계산은 약 0.1~0.7초)."""
        mode = DataMode.REAL if DataMode.REAL in (configured, body.data_mode, body.result.data_mode) else body.data_mode
        llm = Guarded(model, mode)
        route = f"{llm.name}@{getattr(model, 'version', '')}" if llm.usable else "rule"
        # 같은 본문(기록 ID)이 다른 개정으로 다시 올 수 있어(A → B → A) 개정도 키에 둔다 — 결과에 개정이 적힌다
        key = f"{record_id}|{revision}|{today.isoformat()}|{route}"
        found = self._cache.get(key)
        if found is not None:
            return found
        finder = cases or self.cases
        made = build_brief(
            body,
            record_id=record_id,
            revision=revision,
            today=today,
            llm=llm,
            cases=finder,
            alternatives=alternatives() if alternatives is not None else None,
        )
        if made.cases.status != "building":
            self._cache.put(key, made)
        return made


def recorded_alternatives(context: AppContext, holder: Workspaces | None, body: RecordBody) -> AnalysisResult | None:
    """그 기록 요청을 대안 포함으로 계산한 결과. 기록에 이미 대안이 있거나, 기록의 지도를 서버가 모르거나, 계산 판이
    다르거나(배포로 규칙표·파라미터·엔진·계약이 바뀜), 계산이 기록 총액과 다르면 None(지어낸 권고 없음)."""
    request = body.result.request
    if request.include_alternatives or holder is None:
        return None
    found = holder.map_of(body.snapshot_id)
    if found is None or not same_version_of(context)(body):
        return None
    current = holder.current
    index = current.index if current is not None and current.snapshot.snapshot_id == body.snapshot_id else None
    try:
        result = analyze(
            index or GraphIndex(found[0]),
            request.model_copy(update={"include_alternatives": True}),
            context.rulebook,
            context.params,
            context.strength,
        )
    except (RequestError, ValueError):
        log.warning("결정 도우미 대안 계산 실패(%s)", body.ecn_id, exc_info=True)
        return None
    if result.total != body.result.total or result.versions.snapshot_id != body.snapshot_id:
        log.warning("결정 도우미 대안 계산이 기록과 불일치 — 사용 안 함(%s)", body.ecn_id)
        return None
    return result
