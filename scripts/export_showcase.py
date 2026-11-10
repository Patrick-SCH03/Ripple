"""소개 화면 예시를 엔진 결과로 다시 만든다: web/src/pages/landing/example.json

실행: uv run python scripts/export_showcase.py
엔진·규칙·파라미터·생성기를 바꿔 예시 숫자가 달라지면 다시 실행해 커밋한다(tests/checks/showcase.py가 최신인지 검사).
지도는 시연 합성 지도 설정(generator/demo_map.yaml)으로 임시 폴더에 새로 만든다(저장소의 data/는 커밋하지 않는다).

ripple/api/showcase.py가 만든 값(영향 카드·결정 기한·다음 날 추가손실)에 소개 화면이 판단 요약 첫 줄로 보이는 값
(추가 공수·추가 재료비·이미 발주된 품목, 계약 1.35.0)과 블록별 강재 중량 변화(1.34.0)를 더한다 — 모두 같은
분석의 결과 필드를 옮길 뿐 새 계산은 없다(공수 작업 구분 순서·이미 발주 세기는 화면 lib/costSplit.ts·lib/ordered.ts와
같은 규칙).
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from ripple.api.deps import AppContext
from ripple.api.showcase import SHOWCASE_PATH, analyze_showcase, build_showcase, render_showcase
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.domain import EntityType
from ripple.contracts.result import PURCHASE_ITEMS, AnalysisResult, CostItem, CostKind, ImpactType
from ripple.generator.build import generate
from ripple.generator.io import DEMO_CONFIG_PATH, load_config, write_outputs

# 공수 카드의 작업 구분 순서(web/src/lib/costSplit.ts WORK_ORDER와 같음)
WORK_ORDER = (
    CostItem.REWORK,
    CostItem.NEW_WORK,
    CostItem.ONBOARD,
    CostItem.AFTER_PAINT,
    CostItem.WELD,
    CostItem.MACHINING,
    CostItem.DRAWING,
)
# 재료비 카드의 구매 속 순서(costSplit.ts materialParts와 같음)
PURCHASE_ORDER = (CostItem.PO_CHANGE, CostItem.REORDER, CostItem.TRANSFER)
# 기존 발주를 바꾸는 영향(web/src/lib/ordered.ts ORDER_IMPACTS와 같음)
ORDER_IMPACTS = (ImpactType.PO_CHANGE, ImpactType.REORDER)


def _amount(value: Any) -> dict[str, int]:
    return {"value": value.value, "low": value.low, "high": value.high}


def landing_cost(result: AnalysisResult) -> dict[str, Any]:
    """판단 요약 첫 줄의 값: 추가 공수(MH·금액·작업 구분) · 추가 재료비(자재 차이·구매·이미 발주 품목 수)."""
    split = result.cost_split
    if split is None:
        raise ValueError("소개 화면 예시는 비용 구분(계약 1.35.0)이 있는 분석이어야 함")
    lines = [line for line in result.cost_lines if line.amount.low != 0 or line.amount.high != 0]
    labor_items = {line.item for line in lines if line.kind is CostKind.LABOR}
    material = [line for line in lines if line.kind is CostKind.MATERIAL]
    bought = {line.item for line in material if line.item in PURCHASE_ITEMS}
    hours = split.labor_hours
    return {
        "labor_hours": {"value": hours.value, "low": hours.low, "high": hours.high},
        "labor": _amount(split.labor),
        "works": [item.value for item in WORK_ORDER if item in labor_items],
        "material": _amount(split.material),
        "material_diff": split.material_diff.value
        if any(line.item not in PURCHASE_ITEMS for line in material)
        else None,
        "purchase": split.purchase.value if bought else None,
        "purchases": [item.value for item in PURCHASE_ORDER if item in bought],
        "damages": split.damages.value,
        "ordered": _ordered(result),
    }


def _ordered(result: AnalysisResult) -> int:
    """확정일에 이미 발주가 나간 품목 수(발주 변경·새 규격 발주 영향을 받는 발주 품목 중 단계가 미발주가 아닌 것)."""
    ids = {
        i.entity_id for i in result.impacts if i.entity_type is EntityType.PO_LINE and i.impact_type in ORDER_IMPACTS
    }
    count = 0
    for line_id in ids:
        stage = next(
            (li.inputs["stage"] for li in result.cost_lines if li.entity_id == line_id and "stage" in li.inputs), None
        )
        if isinstance(stage, str) and stage != "not_ordered":
            count += 1
    return count


def landing_weight(result: AnalysisResult) -> dict[str, Any] | None:
    """블록별 강재 중량 변화의 합계(t)와 블록 수. 바뀌는 부재가 없으면 None."""
    weight = result.weight_change
    if weight is None or not weight.blocks:
        return None
    return {
        "before_t": weight.before_t,
        "after_t": weight.after_t,
        "delta_t": weight.delta_t,
        "blocks": len(weight.blocks),
        "counted": weight.counted,
    }


def showcase_document(context: AppContext) -> dict[str, Any]:
    """example.json 전체: ripple.api.showcase 값 + 판단 요약 첫 줄 값 + 중량 변화."""
    result = analyze_showcase(context).result
    return {**build_showcase(context), "cost": landing_cost(result), "weight": landing_weight(result)}


def synthetic_context(folder: Path) -> AppContext:
    """시연 합성 지도 설정(generator/demo_map.yaml — 공개 시연 배포 RIPPLE_SYNTHETIC_MAP=demo와 같은 지도)으로 만든
    합성 지도(임시 폴더)의 앱 문맥. 소개 화면 숫자가 라이브 업무 화면과 같게 한다(docs/data.md(생성기) 12절)."""
    write_outputs(generate(load_config(DEMO_CONFIG_PATH)), folder / "synthetic")
    settings = replace(
        Settings.from_env({"RIPPLE_SYNTHETIC_MAP": "demo"}), snapshot_path=folder / "synthetic" / "snapshot.json"
    )
    return AppContext.load(settings)


def main() -> int:
    with tempfile.TemporaryDirectory() as folder:
        text = render_showcase(showcase_document(synthetic_context(Path(folder))))
    target = PROJECT_ROOT / SHOWCASE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    print(f"썼어요: {target.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
