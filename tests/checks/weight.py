"""블록별 강재 중량 변화(docs/engine.md(비용·일정) 12절, 계약 1.34.0): 정보 필드이고 새 가정값을 쓰지 않는다.

- 합계 = 블록 값의 합, 블록 값 = 그 블록 부재 값의 합(중량 정보 없는 부재는 빼고 따로 셈).
- 규격 단위 t 부재는 자재비 차이(C-01) 줄의 qty·new_qty와 같은 값 — 두께를 늘리면 차이가 양수이고
  새/원래 = 새/원래 두께, 강종만 바꾸면 차이 0.
- 중량이 바뀌는 부재가 없는 요청(관통부 추가만)은 빈 블록 목록 · 합계 0.
- 단위가 t가 아닌 부재는 지도의 부재 중량이 있을 때만 — 없으면 '중량 정보 없음'.
- 옛 기록(필드 없음)이 읽히고(None), None이면 직렬화에서 빠져 기록 본문 해시가 그대로다.
- 계약 검사가 합이 맞지 않는 값을 거절한다. 화면·엑셀 이름표가 같은 말이다.
"""

from __future__ import annotations

import json
from datetime import date

from harness import Checker

from checks.labels import ts_record
from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import Settings
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.change import AddPenetration, ChangeRequest, GradeChange, ThicknessChange
from ripple.contracts.domain import Relation
from ripple.contracts.params import ParamSet
from ripple.contracts.result import AnalysisResult, BlockWeight, PartWeight, WeightChange, WeightSource
from ripple.contracts.rulebook import RuleBook
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.ingest.out_labels import OP, WEIGHT_SOURCE

CASES = 120
TOL = 1e-5


def run(c: Checker) -> None:
    c.section("중량 변화: 블록별 강재 중량(명세 12절)")
    generated = generate(load_config())
    settings = Settings.from_env({})
    book, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    index = GraphIndex(generated.snapshot)
    results: list[AnalysisResult] = []
    for ecn in generated.ecns[:CASES]:
        try:
            results.append(analyze(index, AnalysisRequest(change=ecn.change, as_of=ecn.as_of), book, params))
        except RequestError:
            continue
    _sums(c, results)
    _thickness(c, index, results)
    _grade(c, index, results)
    _units(c, index, results)
    _empty(c, index, generated.ecns[0].as_of, book, params)
    _compat(c, results)
    _contract(c)
    _labels(c)


def _sums(c: Checker, results: list[AnalysisResult]) -> None:
    wrong: list[tuple[str | None, object]] = []
    for r in results:
        w = r.weight_change
        if w is None:
            wrong.append((r.request.change.ecn_id, "없음"))
            continue
        blocks_ok = all(
            abs(b.before_t - sum(p.before_t or 0 for p in b.parts)) < TOL
            and abs(b.after_t - sum(p.after_t or 0 for p in b.parts)) < TOL
            and abs(b.delta_t - (b.after_t - b.before_t)) < TOL
            for b in w.blocks
        )
        total_ok = (
            abs(w.delta_t - sum(b.delta_t for b in w.blocks)) < TOL
            and abs(w.before_t - sum(b.before_t for b in w.blocks)) < TOL
            and w.missing == sum(1 for b in w.blocks for p in b.parts if p.source is WeightSource.NONE)
        )
        if not (blocks_ok and total_ok):
            wrong.append((r.request.change.ecn_id, w.delta_t))
    c.check(
        f"새 분석 {len(results)}건 모두 중량 변화 있음 · 합계 = 블록 합 · 블록 = 부재 합 · 정보 없음 수 = 그런 부재 수",
        bool(results) and not wrong,
        wrong[:3],
    )


def _c01(result: AnalysisResult) -> dict[str, tuple[float, float]]:
    return {
        line.entity_id: (float(line.inputs["qty"]), float(line.inputs["new_qty"]))
        for line in result.cost_lines
        if line.rule_id == "C-01" and "new_qty" in line.inputs
    }


def _thickness(c: Checker, index: GraphIndex, results: list[AnalysisResult]) -> None:
    seen, wrong = 0, []
    for r in results:
        ops = r.request.change.ops
        if len(ops) != 1 or not isinstance(ops[0], ThicknessChange) or r.weight_change is None:
            continue
        op = ops[0]
        materials = _c01(r)
        for part in (p for b in r.weight_change.blocks for p in b.parts):
            if part.source is not WeightSource.QTY_T:
                continue
            seen += 1
            ratio = op.to_mm / op.from_mm
            delta = part.delta_t or 0
            c01 = materials.get(part.part_id)
            fine = (
                part.before_t == index.parts[part.part_id].qty
                and abs((part.after_t or 0) - (part.before_t or 0) * ratio) < TOL
                and (delta > 0) == (op.to_mm > op.from_mm)
                and (delta < 0) == (op.to_mm < op.from_mm)
                and (part.from_mm, part.to_mm) == (op.from_mm, op.to_mm)
                and (
                    c01 is None
                    or (abs(c01[0] - (part.before_t or 0)) < TOL and abs(c01[1] - (part.after_t or 0)) < TOL)
                )
            )
            if not fine:
                wrong.append((r.request.change.ecn_id, part.part_id, part.before_t, part.after_t))
    c.check(
        f"두께 변경 판 {seen}장: 원래 = 부재 수량(t), 새 = 원래 × 새 두께 ÷ 원래 두께(C-01 qty·new_qty와 같음), "
        "두께를 늘리면 차이 양수 · 줄이면 음수",
        seen > 0 and not wrong,
        wrong[:3],
    )


def _grade(c: Checker, index: GraphIndex, results: list[AnalysisResult]) -> None:
    seen, wrong = 0, []
    for r in results:
        ops = r.request.change.ops
        if len(ops) != 1 or not isinstance(ops[0], GradeChange) or r.weight_change is None:
            continue
        for part in (p for b in r.weight_change.blocks for p in b.parts):
            seen += 1
            if part.source is not WeightSource.NONE and part.delta_t != 0:
                wrong.append((r.request.change.ecn_id, part.part_id))
    c.check(f"강종만 바꾼 부재 {seen}개는 중량 그대로(차이 0)", seen > 0 and not wrong, wrong[:3])


def _units(c: Checker, index: GraphIndex, results: list[AnalysisResult]) -> None:
    """단위가 t가 아닌 기존 부재: 지도 중량이 있으면 weight_kg ÷ 1000, 없으면 정보 없음. 빼는 부재의 새 중량은 0."""
    wrong, missing, removed = [], 0, 0
    for r in results:
        if r.weight_change is None:
            continue
        for part in (p for b in r.weight_change.blocks for p in b.parts):
            known = index.parts.get(part.part_id)
            if known is None:
                continue
            unit = index.specs[known.spec_id].unit
            if part.source is WeightSource.NONE:
                missing += 1
            elif unit != "t":
                kg = known.weight_kg
                if (
                    part.source is not WeightSource.WEIGHT_KG
                    or kg is None
                    or abs((part.before_t or 0) - kg / 1000) > TOL
                ):
                    wrong.append(part.part_id)
            if {"remove_part", "reroute_pipe"} & set(part.ops) and part.source is not WeightSource.NONE:
                removed += 1
                if part.after_t != 0:
                    wrong.append(part.part_id)
    c.check(
        f"t가 아닌 부재는 지도 중량이 있을 때만(없으면 '중량 정보 없음' {missing}개) · 빼는 부재 {removed}개 새 중량 0",
        missing > 0 and not wrong,
        wrong[:3],
    )


def _empty(c: Checker, index: GraphIndex, as_of: date, book: RuleBook, params: ParamSet) -> None:
    """중량이 바뀌는 부재가 없는 요청(관통부 추가만) → 빈 블록 목록 · 합계 0(None이 아님)."""
    plate = next(p for p in index.parts.values() if p.kind.value == "plate")
    pipe = next(
        p
        for p in index.parts.values()
        if p.kind.value == "pipe_spool"
        and p.ship_id == plate.ship_id
        and p.part_id not in _penetrations(index, plate.part_id)
    )
    change = ChangeRequest(
        ecn_id="ECN-W-EMPTY",
        title="관통부 추가만",
        ship_ids=(plate.ship_id,),
        ops=(
            AddPenetration(
                op="add_penetration", plate_part_id=plate.part_id, pipe_part_id=pipe.part_id, diameter_mm=100
            ),
        ),
    )
    try:
        result = analyze(index, AnalysisRequest(change=change, as_of=as_of), book, params)
    except RequestError as error:
        c.check("관통부 추가만 요청이 분석됨", False, error)
        return
    w = result.weight_change
    c.check(
        "중량이 바뀌는 부재가 없는 요청(관통부 추가만): 빈 블록 목록 · 합계 0 · 부재 0",
        w is not None
        and w.blocks == ()
        and (w.before_t, w.after_t, w.delta_t, w.counted, w.missing) == (0, 0, 0, 0, 0),
        w,
    )


def _penetrations(index: GraphIndex, plate_id: str) -> set[str]:
    return set(index.out(plate_id, Relation.PENETRATION))


def _compat(c: Checker, results: list[AnalysisResult]) -> None:
    """옛 기록(1.33.0 전 — 필드 없음): 읽히면 None, None이면 직렬화에서 빠져 본문 해시가 같다."""
    sample = next(r for r in results if r.weight_change is not None and r.weight_change.blocks)
    body = json.loads(sample.model_dump_json())
    body.pop("weight_change")
    old = AnalysisResult.model_validate(body)
    again = json.loads(old.model_dump_json())
    c.check(
        "옛 기록(중량 변화 필드 없음)이 읽히고 None · 다시 직렬화해도 필드가 생기지 않음(기록 ID 그대로)",
        old.weight_change is None and "weight_change" not in again and again == body,
    )
    schema = AnalysisResult.model_json_schema(mode="serialization")
    c.check(
        "응답 스키마에서 weight_change는 필수도 기본값도 아님(화면 타입에서 '없을 수 있음')",
        "weight_change" not in schema.get("required", []) and "default" not in schema["properties"]["weight_change"],
    )


def _contract(c: Checker) -> None:
    part = PartWeight(
        part_id="P1",
        label="판 1",
        block_id="B1",
        ops=("thickness",),
        source=WeightSource.QTY_T,
        before_t=1.0,
        after_t=1.2,
    )
    good = BlockWeight(
        block_id="B1", name="B1", before_t=1.0, after_t=1.2, delta_t=0.2, counted=1, missing=0, parts=(part,)
    )
    rejected = 0
    for broken in (
        lambda: BlockWeight(
            block_id="B1", name="B1", before_t=1.0, after_t=1.3, delta_t=0.3, counted=1, missing=0, parts=(part,)
        ),
        lambda: WeightChange(blocks=(good,), before_t=1.0, after_t=1.2, delta_t=0.5, counted=1, missing=0),
        lambda: PartWeight(
            part_id="P2", label="x", ops=("dimension",), source=WeightSource.NONE, before_t=1.0, after_t=1.0
        ),
        lambda: WeightChange(blocks=(good, good), before_t=2.0, after_t=2.4, delta_t=0.4, counted=2, missing=0),
    ):
        try:
            broken()
        except ValueError:
            rejected += 1
    ok = WeightChange(blocks=(good,), before_t=1.0, after_t=1.2, delta_t=0.2, counted=1, missing=0)
    c.check(
        "계약 검사: 블록 합·합계 차이가 틀리거나 정보 없음인데 값이 있거나 블록이 겹치면 거절, 맞으면 받음",
        rejected == 4 and ok.delta_t == 0.2,
        rejected,
    )


def _labels(c: Checker) -> None:
    web_ops = ts_record("labels.ts", "OP_NAMES")
    web_sources = ts_record("weightChange.ts", "WEIGHT_SOURCE_NAMES")
    c.check(
        "이름표: 엑셀 변경 이름 = 화면 OP_NAMES · 중량 근거 이름이 계약 값을 모두 덮고 화면 lib/weightChange.ts와 같음",
        web_ops == OP and set(WEIGHT_SOURCE) == {s.value for s in WeightSource} and web_sources == WEIGHT_SOURCE,
        (web_ops, web_sources),
    )
