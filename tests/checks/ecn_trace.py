"""설계 승인 상태·적용 범위(정보)와 연결 추적(docs/domain.md 13절).

- 설계 승인 미입력·승인·적용 범위는 계산·분석 ID를 바꾸지 않는다.
- 검토 중·선주 승인 대기면 판정 이유가 붙고 최소 '검토 필요'.
- 적용 시작일이 확정일보다 앞서면 안내 한 줄(계산은 그대로).
- 연결 추적의 고리는 모두 지도에 있는 엔터티이고, 발주 품목은 지도 공급 관계 그대로(여럿 보존), 끊긴 연결은 gaps로.
- 옛 기록(trace 필드 없음)은 '미수록'(None)으로 읽힌다.
"""

from __future__ import annotations

from datetime import date, timedelta

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.change import AddPart, ChangeCause, DesignStatus, Effectivity, RemovePart, ThicknessChange
from ripple.contracts.domain import GraphSnapshot, PartKind, Relation
from ripple.contracts.params import ParamSet
from ripple.contracts.result import AnalysisResult, VerdictLevel
from ripple.contracts.rulebook import RuleBook
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.verdict import DESIGN_PENDING
from ripple.generator.build import generate
from ripple.generator.io import load_config

from .cost import T31C_PLATE, request_of


def _with(request: AnalysisRequest, **change: object) -> AnalysisRequest:
    return request.model_copy(update={"change": request.change.model_copy(update=change)})


def run(c: Checker) -> None:
    config = load_config()
    generated = generate(config)
    snapshot = generated.snapshot
    index = GraphIndex(snapshot)
    book = load_rulebook(PROJECT_ROOT / "rules" / "propagation.yaml")
    params = load_params(PROJECT_ROOT / "params" / "cost_v1.yaml")
    as_of = config.scenario_date
    plate = index.parts[T31C_PLATE]
    base = request_of(as_of, ThicknessChange(part_ids=(T31C_PLATE,), from_mm=plate.thickness_mm or 12, to_mm=25))
    _design_status(c, index, book, params, base)
    _effectivity(c, index, book, params, base, as_of)
    _cause(c, index, book, params, base)
    _trace(c, snapshot, index, book, params, base, as_of)
    _old_record(c, index, book, params, base)


def _design_status(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, base: AnalysisRequest) -> None:
    c.section("설계 승인 상태(계약 1.23.0)")
    plain = analyze(index, base, book, params)
    approved = analyze(index, _with(base, design_status=DesignStatus.APPROVED), book, params)
    c.check(
        "미입력과 승인은 같은 분석 ID·같은 판정(계산을 바꾸지 않음)",
        plain.analysis_id == approved.analysis_id and plain.verdict == approved.verdict,
    )
    c.check("미입력이면 '승인 전 변경' 이유 없음", DESIGN_PENDING not in plain.verdict.reasons)
    for status in (DesignStatus.IN_REVIEW, DesignStatus.OWNER_PENDING):
        pending = analyze(index, _with(base, design_status=status), book, params)
        c.check(
            f"{status.value}: 다른 분석 ID, 이유 추가, 최소 검토 필요, 금액·일정 그대로",
            pending.analysis_id != plain.analysis_id
            and DESIGN_PENDING in pending.verdict.reasons
            and pending.verdict.level in (VerdictLevel.REVIEW, VerdictLevel.WARN)
            and pending.total == plain.total
            and pending.schedule == plain.schedule,
            (pending.verdict.level, pending.verdict.reasons),
        )


def _effectivity(
    c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, base: AnalysisRequest, as_of: date
) -> None:
    c.section("적용 범위(정보, 계약 1.23.0)")
    confirm = as_of + timedelta(days=10)
    dated = base.model_copy(update={"confirm_on": confirm})
    plain = analyze(index, dated, book, params)
    later = analyze(
        index,
        _with(dated, effectivity=Effectivity(effective_on=confirm + timedelta(days=30), note="2번선부터")),
        book,
        params,
    )
    earlier = analyze(
        index,
        _with(dated, effectivity=Effectivity(effective_on=confirm - timedelta(days=3))),
        book,
        params,
    )
    c.check(
        "적용 시작일은 계산·분석 ID·확정일을 바꾸지 않음",
        plain.analysis_id == later.analysis_id == earlier.analysis_id
        and plain.total == later.total
        and later.request.effective_confirm_on == confirm,
    )
    warned = [n for n in earlier.notes if "적용 시작일" in n]
    c.check(
        "적용 시작일이 확정일보다 앞서면 안내 한 줄, 뒤면 없음",
        len(warned) == 1 and not any("적용 시작일" in n for n in later.notes),
        warned,
    )


def _cause(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, base: AnalysisRequest) -> None:
    c.section("변경 원인(계약 1.28.0 정보 · 1.29.0 선주 요청만 허용 지연)")
    plain = analyze(index, base, book, params)
    caused = {cause: analyze(index, _with(base, cause=cause), book, params) for cause in ChangeCause}
    c.check(
        "선주 요청이 아닌 원인은 분석 ID·판정·금액·일정을 바꾸지 않고 요청에 그대로 남음",
        all(
            r.analysis_id == plain.analysis_id
            and r.verdict == plain.verdict
            and r.total == plain.total
            and r.schedule == plain.schedule
            and r.request.change.cause is cause
            for cause, r in caused.items()
            if cause is not ChangeCause.OWNER_REQUEST
        ),
    )
    owner = caused[ChangeCause.OWNER_REQUEST]
    c.check(
        "선주 요청은 분석 ID가 다르고(허용 지연), 지체상금이 없는 이 요청에서는 금액·출구 지연이 같음",
        owner.analysis_id != plain.analysis_id
        and owner.total == plain.total
        and owner.schedule.zone_exits == plain.schedule.zone_exits
        and (owner.schedule.delivery is None or owner.schedule.delivery.permissible),
    )
    body = plain.model_dump(mode="json")
    body["request"]["change"].pop("cause", None)
    c.check(
        "원인 필드가 없는 옛 결과도 읽힘(미입력 = None)",
        AnalysisResult.model_validate(body).request.change.cause is None,
    )


def _trace(
    c: Checker,
    snapshot: GraphSnapshot,
    index: GraphIndex,
    book: RuleBook,
    params: ParamSet,
    base: AnalysisRequest,
    as_of: date,
) -> None:
    c.section("연결 추적(EBOM → MBOM → 구매 → 시공, docs/domain.md 13절)")
    result = analyze(index, base, book, params)
    chains = result.trace or ()
    c.check("대상 부재마다 사슬 하나", [ch.part_id for ch in chains] == [T31C_PLATE], [ch.part_id for ch in chains])
    chain = chains[0] if chains else None
    if chain is None:
        return
    supplied = index.out(T31C_PLATE, Relation.SUPPLIED_BY)
    c.check(
        "고리는 모두 지도 엔터티, 발주 품목 = 지도 공급 관계 그대로",
        chain.drawing is not None
        and chain.drawing.entity_id in index.drawings
        and chain.block is not None
        and chain.block.entity_id == index.parts[T31C_PLATE].block_id
        and tuple(link.entity_id for link in chain.po_lines) == supplied
        and all(a.entity_id in index.activities for a in chain.activities)
        and not chain.gaps,
        chain,
    )
    affected = {i.entity_id for i in result.impacts} | {line.entity_id for line in result.cost_lines}
    links = [chain.drawing, chain.block, *chain.po_lines, *chain.activities]
    c.check(
        "영향 표시 = 영향·비용 줄이 가리키는 엔터티",
        all(link is not None and link.affected == (link.entity_id in affected) for link in links),
    )
    # 결함 주입: 이 부재의 공급 관계를 지운 지도 → '발주 품목 연결 없음'
    cut = snapshot.model_copy(
        update={
            "po_lines": tuple(
                line.model_copy(update={"part_ids": tuple(p for p in line.part_ids if p != T31C_PLATE)})
                if T31C_PLATE in line.part_ids and len(line.part_ids) > 1
                else line
                for line in snapshot.po_lines
                if line.part_ids != (T31C_PLATE,)
            )
        }
    )
    cut_index = GraphIndex(cut)
    if T31C_PLATE in cut_index.line_of_part:
        c.check("결함 주입 준비: 공급 관계가 지워짐", False)
        return
    broken = analyze(cut_index, base, book, params)
    gaps = (broken.trace or ())[0].gaps if broken.trace else ()
    c.check("공급 관계를 지우면 '발주 품목 연결 없음'", "발주 품목 연결 없음" in gaps, gaps)
    # 새 부재와 빼는 부재
    stiff = next(p for p in snapshot.parts if p.kind is PartKind.STIFFENER and p.part_id != T31C_PLATE)
    mixed = analyze(
        index,
        request_of(
            as_of,
            RemovePart(part_ids=(stiff.part_id,)),
            AddPart(kind=PartKind.BRACKET, block_id=stiff.block_id, spec_id=stiff.spec_id, qty=1),
        ),
        book,
        params,
    )
    kinds = {(ch.new, ch.removed) for ch in mixed.trace or ()}
    c.check("새 부재·빼는 부재 표시", kinds == {(True, False), (False, True)}, mixed.trace)


def _old_record(c: Checker, index: GraphIndex, book: RuleBook, params: ParamSet, base: AnalysisRequest) -> None:
    c.section("옛 기록 호환(계약 1.23.0)")
    result = analyze(index, base, book, params)
    body = result.model_dump(mode="json")
    del body["trace"]
    for key in ("design_status", "effectivity"):
        body["request"]["change"].pop(key, None)
    old = AnalysisResult.model_validate(body)
    c.check(
        "trace·설계 승인 필드가 없는 결과도 읽힘(trace = 미수록 None, 승인 = 미입력)",
        old.trace is None and old.request.change.design_status is DesignStatus.UNKNOWN,
    )
