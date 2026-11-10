"""판단이 걸린 상태(docs/domain.md 12절): 기준일·보류 없는 바탕 상태로만, 엔진이 읽는 발주·소비 공정을 빠뜨리지 않는다.

개발 설계변경 앞 40건 + 확정일을 미루고 보류를 넣은 같은 요청: 확정일·보류가 달라도 같은 항목의 단계·근거는 같아야 한다
(미래 예측을 '오늘 확인' 값으로 쓰지 않음).
"""

from __future__ import annotations

from datetime import timedelta

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.analysis import AnalysisRequest, HoldAction
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.domain import EntityType
from ripple.contracts.result import AnalysisResult, BasisKind
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.engine.state import StateModel
from ripple.generator.build import generate
from ripple.generator.io import load_config

CASES = 40


def run(c: Checker) -> None:
    generated = generate(load_config())
    index = GraphIndex(generated.snapshot)
    book = load_rulebook(PROJECT_ROOT / "rules" / "propagation.yaml")
    params = load_params(PROJECT_ROOT / "params" / "cost_v1.yaml")
    requests = [AnalysisRequest(change=e.change, as_of=e.as_of) for e in generated.ecns if e.split is EcnSplit.DEV]
    results: list[AnalysisResult] = []
    for request in requests[:CASES]:
        try:
            results.append(analyze(index, request, book, params))
        except RequestError:
            continue
    c.section("판단이 걸린 상태: 대상 수집")
    c.check(
        f"개발 설계변경 {len(results)}건: 발주·품목·블록에 걸린 결과에만 목록이 있음(도면만 바뀌면 빈 목록)",
        all(bool(r.state_basis) == _depends(index, r) for r in results)
        and any(r.state_basis for r in results)
        and any(not r.state_basis for r in results),
    )
    missing = [r.request.change.ecn_id for r in results if not _covers(index, r)]
    c.check("비용 줄·보류 권고가 가리키는 발주와 품목의 소비 공정이 모두 있음", not missing, missing[:3])
    c.check(
        "보류 권고 발주는 hold 표시",
        all({b.entity_id for b in r.state_basis if b.hold} == {h.po_id for h in r.timing.holds} for r in results),
    )
    c.check(
        "모든 행의 조회 날짜 = 기준일, 발주 행 단계·근거 = 기준일 보류 없는 상태 함수",
        all(_matches_state(index, r) for r in results),
    )
    c.check(
        "공정 행 근거: 실적 착수일이 있으면 확인, 없으면 계획(예상 착수일 있음)",
        all(
            (b.basis is BasisKind.EVIDENCE) == (b.actual_start is not None)
            and (b.actual_start is not None or b.expected_start is not None)
            for r in results
            for b in r.state_basis
            if b.entity_type == "activity"
        ),
    )

    c.section("판단이 걸린 상태: 확정일·보류와 무관")
    same = True
    for result in results[:15]:
        request = result.request
        holds = tuple(HoldAction(po_id=b.entity_id, hold_days=10) for b in result.state_basis if b.entity_type == "po")
        later = request.model_copy(update={"confirm_on": request.as_of + timedelta(days=7), "holds": holds[:2]})
        try:
            other = analyze(index, later, book, params)
        except RequestError:
            continue
        before = {b.entity_id: (b.po_status, b.basis, b.as_of) for b in result.state_basis}
        after = {b.entity_id: (b.po_status, b.basis, b.as_of) for b in other.state_basis}
        same &= all(after[k] == v for k, v in before.items() if k in after)
    c.check("확정일을 미루고 보류를 넣어도 같은 항목의 단계·근거·조회 날짜가 같음(미래 예측을 넣지 않음)", same)


def _depends(index: GraphIndex, result: AnalysisResult) -> bool:
    """결과가 발주·품목·블록(상태를 읽는 엔터티)을 가리키는가."""
    stateful = {EntityType.PO, EntityType.PO_LINE, EntityType.BLOCK}
    ids = [line.entity_id for line in result.cost_lines] + [i.entity_id for i in result.impacts]
    ids += [u.entity_id for u in result.unresolved if u.entity_id] + [h.po_id for h in result.timing.holds]
    return any(index.type_of(entity_id) in stateful for entity_id in ids)


def _covers(index: GraphIndex, result: AnalysisResult) -> bool:
    rows = {b.entity_id for b in result.state_basis}
    for line in result.cost_lines:
        kind = index.type_of(line.entity_id)
        if kind is EntityType.PO_LINE:
            po_line = index.lines[line.entity_id]
            if po_line.po_id not in rows:
                return False
            if po_line.consumed_by_activity_id and po_line.consumed_by_activity_id not in rows:
                return False
        if kind is EntityType.PO and line.entity_id not in rows:
            return False
    return all(h.po_id in rows for h in result.timing.holds)


def _matches_state(index: GraphIndex, result: AnalysisResult) -> bool:
    as_of = result.request.as_of
    state = StateModel(index, as_of)
    for row in result.state_basis:
        if row.as_of != as_of:
            return False
        if row.entity_type == "po":
            stage = state.po_stage_on(row.entity_id, as_of)
            if (row.po_status, row.basis.value) != (stage.likely, stage.basis.value):
                return False
    return True
