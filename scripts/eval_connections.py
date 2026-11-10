"""연결 자료 제거 진단: 1단계 관문 30건을 연결(용접·관통·지지·배관 이음)이 있는 지도와 뺀 지도에서 다시 채점한다.

  uv run python scripts/eval_connections.py [결과 폴더]      기본 결과 폴더는 eval/reports

질문은 하나다 — 조선소가 부재 사이 연결 자료를 주지 못하면 무엇을 놓치나. 채점은 `ripple/eval/impact_metrics.py`
`score_case`와 같은 비교이고, 연결을 뺀 지도는 지도 ID가 달라 그 검사만 뺐다. 2차 영향(PLM 조회 기준선 밖 정답 엔터티)은
연결이 있는 지도의 기준선으로 센다. 전체 제거만 재고, 일부 누락(이웃 하나만 빠짐)은 재지 않는다.

진단이라 종료 코드는 늘 0이다. 결과 JSON: <결과 폴더>/connections_ablation.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.evaluation import GateCase
from ripple.contracts.identity import snapshot_id
from ripple.contracts.result import ImpactReport, ImpactType, UnresolvedKind
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import impact_report
from ripple.eval.impact_metrics import SetScore, produced_keys, where_used_plm
from ripple.generator.build import generate
from ripple.generator.io import load_config

CASES = PROJECT_ROOT / "eval" / "gate_cases" / "1"
CONFIRM = ImpactType.NEEDS_CONFIRMATION.value
Row = dict[str, Any]


def score(case: GateCase, report: ImpactReport, plm_index: GraphIndex) -> Row:
    """사례 하나: score_case와 같은 비교(지도 ID 검사 뺌) + 2차 영향·연결 확인 필요 수."""
    expected = frozenset(i.key for i in case.expected.impacts)
    produced = produced_keys(report)
    entities = SetScore(
        frozenset(i.entity_id for i in case.expected.impacts), frozenset(i.entity_id for i in report.impacts)
    )
    beyond = entities.expected - where_used_plm(plm_index, report)
    forbidden = {
        f.entity_id
        for f in case.expected.forbidden_impacts
        for i in report.impacts
        if f.hits(i.entity_id, i.impact_type, i.rule_id)
    }
    unresolved_expected = {(u.kind.value, u.entity_id) for u in case.expected.unresolved}
    unresolved_produced = {(u.kind.value, u.entity_id) for u in report.unresolved}
    return {
        "case_id": case.case_id,
        "expected": len(expected),
        "matched": len(expected & produced),
        "produced": len(produced),
        "matched_wo_confirm": len({k for k in expected & produced if k[1] != CONFIRM}),
        "produced_wo_confirm": len({k for k in produced if k[1] != CONFIRM}),
        "entities_expected": len(entities.expected),
        "entities_matched": len(entities.matched),
        "second_order_expected": sorted(beyond),
        "second_order_found": sorted(beyond & entities.produced),
        "missed": sorted(expected - produced),
        "extra": sorted(produced - expected),
        "forbidden_hits": sorted(forbidden),
        "unresolved_ok": unresolved_expected == unresolved_produced,
        "connection_unresolved": sorted(
            u.entity_id or "" for u in report.unresolved if u.kind is UnresolvedKind.CONNECTION
        ),
    }


def pooled(rows: list[Row]) -> Row:
    """30건 합산(GateScore.pooled와 같은 방식 — 키에 사례 ID가 붙어 겹치지 않음)."""

    def total(key: str) -> int:
        return sum(len(r[key]) if isinstance(r[key], list) else r[key] for r in rows)

    matched, expected, produced = total("matched"), total("expected"), total("produced")
    precision = matched / produced if produced else 1.0
    return {
        "recall": round(matched / expected, 4),
        "precision": round(precision, 4),
        "precision_without_needs_confirmation": round(total("matched_wo_confirm") / total("produced_wo_confirm"), 4),
        "impacts_expected_matched_produced": [expected, matched, produced],
        "entity_recall": round(total("entities_matched") / total("entities_expected"), 4),
        "second_order_expected_found": [total("second_order_expected"), total("second_order_found")],
        "cases_recall_1": sum(1 for r in rows if r["matched"] == r["expected"]),
        "cases_unresolved_ok": sum(1 for r in rows if r["unresolved_ok"]),
        "connection_unresolved_cases_entities": [
            sum(1 for r in rows if r["connection_unresolved"]),
            total("connection_unresolved"),
        ],
        "forbidden_hits": [(r["case_id"], h) for r in rows for h in r["forbidden_hits"]],
        "gate_passed": matched == expected
        and precision >= 0.9
        and all(not r["forbidden_hits"] and r["unresolved_ok"] for r in rows),
    }


def by_impact_type(cases: list[GateCase], rows_with: list[Row], rows_without: list[Row]) -> dict[str, list[int]]:
    """영향 종류마다 [기대, 연결 있음에서 찾음, 연결 없음에서 찾음]."""
    out: dict[str, list[int]] = {}
    for case, full, bare in zip(cases, rows_with, rows_without, strict=True):
        missed_full, missed_bare = set(map(tuple, full["missed"])), set(map(tuple, bare["missed"]))
        for impact in case.expected.impacts:
            row = out.setdefault(impact.impact_type.value, [0, 0, 0])
            row[0] += 1
            row[1] += impact.key not in missed_full
            row[2] += impact.key not in missed_bare
    return dict(sorted(out.items()))


def second_order_kinds(index: GraphIndex, rows: list[Row]) -> dict[str, dict[str, int]]:
    """연결 없는 지도에서 남은·사라진 2차 영향 엔터티의 종류(부재는 부재 종류까지)."""
    kept: Counter[str] = Counter()
    lost: Counter[str] = Counter()
    for row in rows:
        for entity in row["second_order_expected"]:
            kind = index.type_of(entity)
            name = "new_part" if kind is None else kind.value
            if name == "part":
                name = f"part/{index.parts[entity].kind.value}"
            (kept if entity in row["second_order_found"] else lost)[name] += 1
    return {"kept": dict(kept), "lost": dict(lost)}


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "eval" / "reports"
    paths = sorted(CASES.glob("G1-*.yaml"))
    cases = [GateCase.model_validate(yaml.safe_load(p.read_text(encoding="utf-8"))) for p in paths]
    (seed,) = {c.snapshot.generator_seed for c in cases}
    (case_map,) = {c.snapshot.snapshot_id for c in cases}
    full = generate(load_config(), seed).snapshot
    if full.snapshot_id != case_map:
        print(f"사례 지도 {case_map}와 생성 지도 {full.snapshot_id}가 달라요")
        return 0
    draft = full.model_copy(update={"connections": ()})
    bare = draft.model_copy(update={"snapshot_id": snapshot_id(draft)})
    index_full, index_bare = GraphIndex(full), GraphIndex(bare)
    rulebook = load_rulebook(PROJECT_ROOT / "rules" / "propagation.yaml")
    version = load_params(PROJECT_ROOT / "params" / "cost_v1.yaml").version
    rows_with: list[Row] = []
    rows_without: list[Row] = []
    for case in cases:
        request = AnalysisRequest.model_validate(case.request)
        rows_with.append(score(case, impact_report(index_full, request, rulebook, version), index_full))
        rows_without.append(score(case, impact_report(index_bare, request, rulebook, version), index_full))
    result = {
        "maps": {"with": full.snapshot_id, "without": bare.snapshot_id},
        "connections_removed": dict(Counter(c.kind.value for c in full.connections)),
        "with_connections": pooled(rows_with),
        "without_connections": pooled(rows_without),
        "by_impact_type_expected_with_without": by_impact_type(cases, rows_with, rows_without),
        "second_order_without_connections": second_order_kinds(index_full, rows_without),
        "cases_without_connections": rows_without,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "connections_ablation.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    for key in (
        "maps",
        "connections_removed",
        "with_connections",
        "without_connections",
        "by_impact_type_expected_with_without",
        "second_order_without_connections",
    ):
        print(f"{key}: {result[key]}")
    print(f"썼어요: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
