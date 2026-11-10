"""1단계 영향 탐색 결과(docs/engine.md(전파))와, 2단계 분석 결과도 같이 쓰는 영향 그래프 검사."""

from __future__ import annotations

from pydantic import model_validator

from ..analysis import AnalysisRequest, Versions
from ..base import Frozen
from ..domain import DataMode
from ..graphview import GraphView
from ..identity import analysis_id as compute_analysis_id
from .impact import Impact, Unresolved


def graph_problem(graph: GraphView, snapshot_id: str, impacts: tuple[Impact, ...]) -> str | None:
    if graph.snapshot_id != snapshot_id:
        return "영향 그래프 지도와 분석 지도 불일치"
    drawn = {node.id for node in graph.nodes}
    needed = {i.entity_id for i in impacts} | {end for i in impacts for h in i.path for end in (h.src, h.dst)}
    if not needed <= drawn:
        return f"영향 그래프에 없는 엔터티: {sorted(needed - drawn)[:3]}"
    return None


class ImpactReport(Frozen):
    """1단계 영향 탐색 결과(docs/engine.md(전파)). 금액·일정은 2단계 AnalysisResult가 더한다."""

    analysis_id: str
    versions: Versions
    request: AnalysisRequest
    data_mode: DataMode
    impacts: tuple[Impact, ...]
    unresolved: tuple[Unresolved, ...] = ()
    graph: GraphView  # 대상·근거 경로의 노드와 연결. 원본 지도에 없는 노드·연결(변경으로 생김)은 virtual(점선)
    pending_rules: tuple[str, ...] = ()  # 규칙표에 있지만 아직 계산하지 않는 규칙
    notes: tuple[str, ...] = ()  # 화면 안내 문구

    @model_validator(mode="after")
    def _consistent(self) -> ImpactReport:
        if self.analysis_id != compute_analysis_id(self.versions, self.request):
            raise ValueError("분석 ID와 버전·요청 불일치")
        keys = [impact.key for impact in self.impacts]
        if keys != sorted(keys) or len(set(keys)) != len(keys):
            raise ValueError("영향은 키 순 정렬·중복 없음 필요")
        problem = graph_problem(self.graph, self.versions.snapshot_id, self.impacts)
        if problem:
            raise ValueError(problem)
        return self
