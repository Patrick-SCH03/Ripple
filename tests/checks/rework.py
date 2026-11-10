"""재작업 cost-v6(docs/engine.md(비용·일정) 4-4·4-4-1·4-4-2): 블록 난이도 계수 · 작업반 추가 공비 줄 ·
도장 뒤 고정 항목.

- 난이도 계수: 1 ≤ 계수 ≤ 상한, 세 계수의 곱(상한 적용), 형상·밀도 입력이 없으면 1.
  재작업 줄에만 붙고 재작업 배수 가정값과 따로 보인다(곱은 공수 산식에만).
- 작업반 줄: 수행 주체를 모두 지운 지도와 총액·블록별 재작업 합이 같다(금액 불변, 줄만 나뉨).
- 도장 뒤 고정 항목(C-04): 블록 단계가 선행도장 이후일 때만, 금액 = 고정 공수 합 × 선행도장 수행 주체 단가.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import Settings
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.domain import DIRECT_PERFORMER, ActivityKind, Block, BlockShape, BlockStage, GraphSnapshot
from ripple.contracts.params import ParamSet
from ripple.contracts.result import Amount, AnalysisResult, Determinacy
from ripple.contracts.rulebook import RuleBook
from ripple.engine.analyze import analyze
from ripple.engine.cost import Params, amount_of
from ripple.engine.cost.difficulty import block_difficulty
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.engine.state import rank
from ripple.generator.build import generate
from ripple.generator.io import load_config

CASES = 70  # 개발 설계변경 앞에서부터(기준일 확정 · 30일 뒤 확정 두 번)
AFTER_PAINT = ("after_paint.repaint_hours", "after_paint.scaffold_hours", "after_paint.hot_work_hours")


def run(c: Checker) -> None:
    config = load_config()
    snapshot = generate(config).snapshot
    settings = Settings.from_env({})
    book, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    ecns = [e for e in generate(config).ecns if e.split is EcnSplit.DEV][:CASES]
    requests = [
        AnalysisRequest(change=e.change, as_of=e.as_of, confirm_on=e.as_of + timedelta(days=days))
        for e in ecns
        for days in (0, 30)
    ]
    results = _analyses(GraphIndex(snapshot), requests, book, params)
    _difficulty_unit(c, snapshot, params)
    _difficulty_lines(c, GraphIndex(snapshot), params, results)
    _after_paint(c, GraphIndex(snapshot), params, results)
    _crew_invariance(c, snapshot, requests, book, params, results)


def _analyses(
    index: GraphIndex, requests: list[AnalysisRequest], book: RuleBook, params: ParamSet
) -> list[AnalysisResult]:
    found = []
    for request in requests:
        try:
            found.append(analyze(index, request, book, params))
        except RequestError:
            continue
    return found


def _difficulty_unit(c: Checker, snapshot: GraphSnapshot, params: ParamSet) -> None:
    c.section("재작업: 블록 난이도 계수의 범위·상한(명세 4-4)")
    p = Params(params)
    cap = params.value("difficulty.cap")
    factors = {b.block_id: block_difficulty(b, p).factor for b in snapshot.blocks}
    c.check(
        f"지도 블록 {len(factors)}개: 1 ≤ 계수 ≤ 상한, 의장 1~최댓값·전장 1~최댓값, 형상 계수 = 그 형상 파라미터",
        all(
            1 <= f.value <= cap
            and 1 <= f.outfit_factor <= params.value("difficulty.outfit_max")
            and 1 <= f.electric_factor <= params.value("difficulty.electric_max")
            and f.shape is not None
            and f.shape_factor == params.value(f"difficulty.shape.{f.shape.value}")
            for f in factors.values()
        ),
        {k: v.value for k, v in factors.items()},
    )
    c.check(
        "계수 = 세 계수의 곱(상한 아래면 상한 표시 없음)",
        all(
            abs(f.value - min(f.shape_factor * f.outfit_factor * f.electric_factor, cap)) < 1e-6
            for f in factors.values()
        ),
    )
    heavy = Block(
        block_id="S-1:X",
        ship_id="S-1",
        zone_id="S-1:Z",
        name="시험",
        steel_weight_t=100.0,
        shape=BlockShape.BOW_STERN,
        outfit_items=1000,
        electric_items=1000,
    )
    capped = block_difficulty(heavy, p).factor
    c.check(
        "선수미 × 의장 최대 × 전장 최대(1.5 × 1.4 × 1.2 = 2.52)는 상한 2.0으로 줄이고 상한 표시",
        capped.value == cap
        and capped.capped
        and capped.shape_factor * capped.outfit_factor * capped.electric_factor > cap,
        capped,
    )
    bare = block_difficulty(heavy.model_copy(update={"shape": None, "outfit_items": None, "electric_items": None}), p)
    c.check(
        "형상·의장품·전장품 수가 없는 블록(엑셀 가져오기 등)은 계수 1이고 가정값 키를 쓰지 않음",
        bare.value == 1.0 and bare.keys == () and not bare.factor.capped,
    )


def _difficulty_lines(c: Checker, index: GraphIndex, params: ParamSet, results: list[AnalysisResult]) -> None:
    c.section("재작업: 난이도 계수는 재작업 줄에만, 배수와 따로 보임")
    p = Params(params)
    rework = [line for r in results for line in r.cost_lines if line.rule_id == "R-B01"]
    others = [line for r in results for line in r.cost_lines if line.rule_id != "R-B01"]
    c.check(
        f"재작업 줄 {len(rework)}개: 블록 난이도 계수(별도 필드·입력값) = 그 블록 계수",
        bool(rework)
        and all(
            line.difficulty == block_difficulty(index.blocks[line.entity_id], p).factor
            and line.inputs.get("difficulty") == line.difficulty.value
            for line in rework
            if line.difficulty is not None
        )
        and all(line.difficulty is not None for line in rework),
    )
    c.check("재작업이 아닌 줄에는 난이도 계수가 없음", all(line.difficulty is None for line in others))

    def multipliers_untouched(line_factors: list[tuple[str, float, tuple[str, ...]]]) -> bool:
        return all(
            value == params.value(keys[0]) for label, value, keys in line_factors if label.startswith("재작업 배수")
        )

    separate = all(
        any(f.label.startswith("난이도") for f in line.factors)
        and multipliers_untouched([(f.label, f.value, f.keys) for f in line.factors])
        for line in rework
        if line.difficulty is not None and line.difficulty.value > 1
    )
    c.check("난이도가 1보다 큰 재작업 줄: 가정값에 난이도 항목이 따로 있고, 재작업 배수 값은 파라미터 그대로", separate)


def _after_paint(c: Checker, index: GraphIndex, params: ParamSet, results: list[AnalysisResult]) -> None:
    c.section("재작업: 도장 뒤 고정 항목(C-04)은 선행도장 이후에만(명세 4-4-2)")
    p = Params(params)
    seen, wrong, missing, amounts = 0, [], [], []
    for result in results:
        rework_stage: dict[str, BlockStage] = {}
        for line in result.cost_lines:
            if line.rule_id == "R-B01" and line.determinacy is Determinacy.KNOWN:
                rework_stage[line.entity_id] = BlockStage(str(line.inputs["stage"]))
        after = {line.entity_id: line for line in result.cost_lines if line.rule_id == "C-04"}
        for block_id, stage in rework_stage.items():
            painted = rank(stage) >= rank(BlockStage.PRE_PAINTING)
            if painted and block_id not in after:
                missing.append((result.request.change.ecn_id, block_id, stage.value))
            if not painted and block_id in after:
                wrong.append((result.request.change.ecn_id, block_id, stage.value))
        for block_id, line in after.items():
            seen += 1
            if block_id not in rework_stage:
                continue
            activity = next(
                a for a in index.activities.values() if a.block_id == block_id and a.kind is ActivityKind.PRE_PAINTING
            )
            labor = "crew" if activity.performer not in (None, DIRECT_PERFORMER) else "prime"
            expected = _fixed_items(p, f"labor_rate_per_hour.{labor}")
            if line.amount != expected:
                amounts.append((result.request.change.ecn_id, block_id, line.amount, expected))
    c.check(f"C-04 줄 {seen}개가 생김(선행도장 이후 단계 재작업이 있는 사례)", seen > 0, seen)
    c.check("단계를 아는 재작업에서 선행도장 전 단계 블록에는 C-04가 없음", not wrong, wrong[:3])
    c.check("단계를 아는 재작업에서 선행도장·PE·탑재 단계 블록에는 C-04가 있음", not missing, missing[:3])
    c.check(
        "C-04 금액 = (재도장 + 족장 + 화기작업 공수) × 선행도장 수행 주체 단가(시나리오 셋)", not amounts, amounts[:2]
    )


def _fixed_items(p: Params, rate_key: str) -> Amount:
    """명세 4-4-2: (재도장 + 족장 + 화기작업 공수) × 단가, 시나리오 셋."""
    return amount_of(lambda sc: sum(p.get(k, sc) for k in AFTER_PAINT) * p.get(rate_key, sc))


def _crew_invariance(
    c: Checker,
    snapshot: GraphSnapshot,
    requests: list[AnalysisRequest],
    book: RuleBook,
    params: ParamSet,
    results: list[AnalysisResult],
) -> None:
    c.section("재작업: 작업반 추가 공비 줄 — 금액 불변(명세 4-4-1)")
    stripped = snapshot.model_copy(
        update={"activities": tuple(a.model_copy(update={"performer": None}) for a in snapshot.activities)}
    )
    plain = {r.request.model_dump_json(): r for r in _analyses(GraphIndex(stripped), requests, book, params)}
    crews = {crew.crew_id: crew.name for crew in snapshot.crews}
    split, differ = 0, []
    for result in results:
        other = plain[result.request.model_dump_json()]
        mine: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        theirs: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        for lines, sums in ((result.cost_lines, mine), (other.cost_lines, theirs)):
            for line in lines:
                if line.rule_id == "R-B01":
                    for i, field in enumerate(("low", "value", "high")):
                        sums[line.entity_id][i] += getattr(line.amount, field)
        split += sum(1 for line in result.cost_lines if line.rule_id == "R-B01" and "@" in line.line_id)
        if result.total != other.total or dict(mine) != dict(theirs):
            differ.append(result.request.change.ecn_id)
    c.check(f"작업반 몫으로 나눈 재작업 줄이 생김({split}개)", split > 0, split)
    c.check(
        f"분석 {len(results)}건: 수행 주체를 모두 지운 지도와 총액·블록별 재작업 합(최소·대표·최대)이 같음",
        not differ,
        differ[:3],
    )
    crew_lines = [line for r in results for line in r.cost_lines if line.rule_id == "R-B01" and "@" in line.line_id]
    c.check(
        "작업반 줄: ID '재작업 줄@작업반', 이름에 작업반 이름과 '추가 공비', 작업반 단가 가정값",
        all(
            line.line_id.endswith(f"@{line.inputs['crew_id']}")
            and crews[str(line.inputs["crew_id"])] in line.label
            and "추가 공비" in line.label
            and "labor_rate_per_hour.crew" in line.param_keys
            for line in crew_lines
        ),
    )
