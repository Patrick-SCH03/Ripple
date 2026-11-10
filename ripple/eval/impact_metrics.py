"""영향 탐색 평가(E1): 관문 사례 채점과 where-used 기준선.

- 판정 단위: (엔터티 ID, 영향 종류, 규칙 ID). 관문 손 계산 사례의 정답 집합과 엔진 출력을 비교한다.
- 엔터티 단위: 영향을 받는 엔터티 ID 집합. 규칙·종류를 내지 않는 where-used 기준선과 비교할 때 쓴다.
- 기준선 두 가지: `where_used`(부재 → 블록·공급 품목, 처음 정한 좁은 기준선)와 `where_used_plm`(여기에 부재의 도면까지 —
  PLM·BOM 조회로 바로 얻는 1차 영향). 차별점은 PLM 기준선 밖의 정답(2차 영향: 용접 이웃·테이퍼·전용·관통 등)을 엔진이
  얼마나 찾는가(`second_order`, 엔터티 단위 재현율)로 본다.
재현율 = 맞힌 정답 / 전체 정답, 정밀도 = 맞힌 출력 / 전체 출력(정답에 없는 출력은 모두 오탐).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ripple.contracts.domain import EntityType, Relation
from ripple.contracts.evaluation import GateCase
from ripple.contracts.result import ImpactReport
from ripple.engine.index import GraphIndex
from ripple.engine.overlay import ChangeView

from .coverage import coverage_problems

Key = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class SetScore:
    expected: frozenset[object]
    produced: frozenset[object]

    @property
    def matched(self) -> frozenset[object]:
        return self.expected & self.produced

    @property
    def recall(self) -> float:
        return 1.0 if not self.expected else len(self.matched) / len(self.expected)

    @property
    def precision(self) -> float:
        return 1.0 if not self.produced else len(self.matched) / len(self.produced)

    @property
    def f1(self) -> float:
        total = self.recall + self.precision
        return 0.0 if total == 0 else 2 * self.recall * self.precision / total


@dataclass(frozen=True, slots=True)
class CaseScore:
    case_id: str
    impacts: SetScore  # 판정 단위
    entities: SetScore  # 엔터티 단위
    baseline: SetScore  # where-used 기준선(엔터티 단위, 블록·공급 품목)
    plm: SetScore  # PLM 수준 기준선(엔터티 단위, 블록·공급 품목·도면)
    second_order: SetScore  # PLM 기준선 밖의 정답 엔터티(2차 영향)를 엔진이 찾은 비율
    forbidden_hits: tuple[str, ...]
    unresolved_ok: bool

    @property
    def missed(self) -> list[object]:
        return sorted(self.impacts.expected - self.impacts.produced, key=str)

    @property
    def extra(self) -> list[object]:
        return sorted(self.impacts.produced - self.impacts.expected, key=str)


@dataclass(frozen=True, slots=True)
class GateScore:
    cases: tuple[CaseScore, ...]
    required: tuple[str, ...]  # 사례 입력 폴더의 사례 ID 전부

    @property
    def problems(self) -> tuple[str, ...]:
        return coverage_problems((case.case_id for case in self.cases), self.required)

    def pooled(self, attr: str) -> SetScore:
        """사례를 모은 판정(사례 ID를 붙여 겹치지 않게)."""
        expected = frozenset((c.case_id, k) for c in self.cases for k in getattr(c, attr).expected)
        produced = frozenset((c.case_id, k) for c in self.cases for k in getattr(c, attr).produced)
        return SetScore(expected, produced)

    def passed(self, recall: float = 1.0, precision: float = 0.9) -> bool:
        """1단계 관문: 필수 사례를 빠짐·겹침 없이 채점했고, 판정 단위 재현율 100%·정밀도 ≥ 0.9, 금지 영향 없음,
        계산 불가 이유 일치."""
        pooled = self.pooled("impacts")
        return (
            not self.problems
            and pooled.recall >= recall
            and pooled.precision >= precision
            and all(not c.forbidden_hits and c.unresolved_ok for c in self.cases)
        )


def produced_keys(report: ImpactReport) -> frozenset[Key]:
    return frozenset((i.entity_id, i.impact_type.value, i.rule_id) for i in report.impacts)


def where_used(index: GraphIndex, report: ImpactReport) -> frozenset[str]:
    """기준선: 대상 부재에서 소속 블록과 공급 발주 품목만 따라간다(연결·상태·도면·재고는 보지 않음)."""
    view = ChangeView(index, report.request.change)
    found: set[str] = set()
    for planned in view.ops:
        for part_id in planned.existing_targets():
            found.update(t for t in index.out(part_id, Relation.PART_OF) if index.type_of(t) is EntityType.BLOCK)
            found.update(view.lines_of(part_id))
    return frozenset(found)


def where_used_plm(index: GraphIndex, report: ImpactReport) -> frozenset[str]:
    """PLM 수준 기준선: 좁은 기준선 + 대상 부재의 도면(도면번호@개정). BOM·PLM 조회로 바로 얻는 1차 영향."""
    view = ChangeView(index, report.request.change)
    drawings = {
        index.drawing_of(index.parts[part_id]) for planned in view.ops for part_id in planned.existing_targets()
    }
    return where_used(index, report) | frozenset(drawings)


def score_case(case: GateCase, report: ImpactReport, index: GraphIndex) -> CaseScore:
    if report.versions.snapshot_id != case.snapshot.snapshot_id:
        raise ValueError(f"{case.case_id}: 사례 지도({case.snapshot.snapshot_id})와 분석 지도가 달라요")
    expected = frozenset(i.key for i in case.expected.impacts)
    produced = produced_keys(report)
    expected_entities = frozenset(i.entity_id for i in case.expected.impacts)
    produced_entities = frozenset(i.entity_id for i in report.impacts)
    hits = tuple(
        f.entity_id
        for f in case.expected.forbidden_impacts
        for i in report.impacts
        if f.hits(i.entity_id, i.impact_type, i.rule_id)
    )
    unresolved_expected = {(u.kind, u.entity_id) for u in case.expected.unresolved}
    unresolved_produced = {(u.kind, u.entity_id) for u in report.unresolved}
    plm = where_used_plm(index, report)
    beyond = expected_entities - plm
    return CaseScore(
        case_id=case.case_id,
        impacts=SetScore(frozenset(expected), frozenset(produced)),
        entities=SetScore(frozenset(expected_entities), frozenset(produced_entities)),
        baseline=SetScore(frozenset(expected_entities), frozenset(where_used(index, report))),
        plm=SetScore(frozenset(expected_entities), frozenset(plm)),
        second_order=SetScore(frozenset(beyond), frozenset(beyond & produced_entities)),
        forbidden_hits=tuple(sorted(set(hits))),
        unresolved_ok=unresolved_expected == unresolved_produced,
    )


def score_gate(scores: Iterable[CaseScore], required: Iterable[str]) -> GateScore:
    return GateScore(tuple(sorted(scores, key=lambda s: s.case_id)), tuple(sorted(required)))
