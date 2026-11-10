"""설계변경 사전 점검(docs/engine.md(사전 점검), 1.32.0): 연결 지도에 거는 규칙 6개 → 판정과 분리된 확인 항목.

`precheck(index, request, result)`는 순수 함수다: 같은 입력이면 같은 항목·같은 순서(규칙 ID → 키). 분석 결과(영향·도면
개정 목록·재작업 블록)를 읽기만 하고 판정·총액·결정 기한·곡선·대안을 바꾸지 않는다(analyze가 결과를 다 만든 뒤 붙인다).

- P-01 설치 시점(install) · P-02 관통부 정합(penetration) · P-03 블록 경계 연결 · P-04 분야 간 도면(links) ·
  P-05 새 스풀 서포트(install) · P-06 현장 공유(field)
- 3D 형상·치수 검사가 아니다. 지도에 그 규칙을 볼 정보가 없으면 지어내지 않고 '점검 불가' 항목으로 낸다.
- 같은 유형 합성 NCR 건수(ncr_counts, 규칙 ID → 건수)는 합성 데이터 결과에만 싣는다(실데이터면 늘 None).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.domain import DataMode
from ripple.contracts.result import AnalysisResult, PrecheckItem, precheck_order

from ..index import GraphIndex
from .field import sharing
from .install import installation, supports
from .links import boundaries, secondary
from .penetration import penetrations
from .scope import Scope

RULES: tuple[Callable[[Scope], list[PrecheckItem]], ...] = (
    installation,
    penetrations,
    boundaries,
    secondary,
    supports,
    sharing,
)


def precheck(
    index: GraphIndex,
    request: AnalysisRequest,
    result: AnalysisResult,
    ncr_counts: Mapping[str, int] | None = None,
) -> tuple[PrecheckItem, ...]:
    """이 요청의 사전 점검 항목(규칙 ID → 키 순). result는 같은 요청의 분석 결과(사전 점검 없이 만든 것이어도 된다)."""
    counts = ncr_counts if result.data_mode is DataMode.SYNTHETIC else None
    scope = Scope(index, request, result, counts)
    items = [item for rule in RULES for item in rule(scope)]
    return tuple(sorted(items, key=precheck_order))


def with_prechecks(
    index: GraphIndex,
    request: AnalysisRequest,
    result: AnalysisResult,
    ncr_counts: Mapping[str, int] | None = None,
) -> AnalysisResult:
    """결과에 사전 점검 항목을 붙인다(없으면 결과 그대로). 다른 필드는 그대로 두고 계약 검사를 다시 거친다."""
    items = precheck(index, request, result, ncr_counts)
    if not items:
        return result
    fields = {name: getattr(result, name) for name in type(result).model_fields}
    return AnalysisResult.model_validate({**fields, "prechecks": items})


__all__ = ["RULES", "precheck", "with_prechecks"]
