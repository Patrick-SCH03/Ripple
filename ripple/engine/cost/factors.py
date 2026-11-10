"""비용 줄의 가정값(docs/engine.md(비용·일정) 4-9): 쓴 파라미터 키를 현장 이름·단위·대표값·범위·근거 상태로 묶는다.

블록 공정별 톤당 공수(base_work_hours_per_t.*)는 재작업 계산처럼 확정 단계까지 더한 값 하나로 보인다.
"""

from __future__ import annotations

from collections.abc import Iterable

from ripple.contracts.domain import (
    BLOCK_ACTIVITY_ORDER,
    BLOCK_STAGE_ORDER,
    PO_STATUS_ORDER,
    ActivityKind,
    BlockStage,
    PartKind,
    POStatus,
)
from ripple.contracts.params import Param, ParamSet, ParamStatus
from ripple.contracts.result import CostFactor

from ..describe import ACTIVITY_NAMES, BLOCK_STAGE_NAMES, PART_KIND_NAMES, PO_STATUS_NAMES

RATIO = "비율"
"""화면은 %로 보인다."""
WORK_HOURS = "base_work_hours_per_t."
GRADE_RATIO = "steel.grade_price_ratio."

LABOR = {"prime": "직영", "crew": "사내 협력사 작업반", "subcontractor": "사외 블록 제작 협력사", "design": "설계"}
SHAPE_NAMES = {"flat": "평블록", "curved": "곡블록", "bow_stern": "선수미 블록"}
MINOR = {
    "taper_per_joint": "테이퍼 가공 공수(이음 하나)",
    "weld_recheck_per_joint": "용접 재검토 공수(이음 하나)",
    "collar_resize_each": "칼라 치수 변경 공수(하나)",
    "modify_part_each": "배관 부재 수정 공수(하나)",
    "drawing_revision_per_drawing": "도면 개정 공수(도면 하나)",
    "drawing_revision_piping": "배관도 개정 공수(도면 하나)",
}
SINGLE: dict[str, tuple[str, str]] = {
    "rework.crew_hours_per_day": ("하루 투입 공수", "시간/일"),
    "reorder.expedite_premium_ratio": ("급발주 할증률", RATIO),
    "steel.max_cancel_loss_ratio": ("강재 취소·변경률 상한(고철 잔존가치)", RATIO),
    "stock.reallocation_handling_per_t": ("전용 취급비", "원/t"),
    "piping.new_spool_qty": ("새 스풀 길이", "m"),
    "outfitting.on_board_ratio": ("후행 설치 배수(선행의장 대비)", "배"),
    "difficulty.outfit_max": ("난이도: 의장 밀도 계수 최댓값", "배"),
    "difficulty.outfit_full_per_t": ("난이도: 의장 밀도 최댓값 기준(의장품 수 ÷ 강재 중량)", "개/t"),
    "difficulty.electric_max": ("난이도: 전장품 계수 최댓값", "배"),
    "difficulty.electric_full_per_t": ("난이도: 전장품 최댓값 기준(전장품 수 ÷ 강재 중량)", "개/t"),
    "difficulty.cap": ("난이도 계수 상한", "배"),
    "after_paint.repaint_hours": ("도장 뒤 재도장 공수", "시간"),
    "after_paint.scaffold_hours": ("도장 뒤 족장 설치·해체 공수", "시간"),
    "after_paint.hot_work_hours": ("도장 뒤 화기작업 안전 조치 공수", "시간"),
    "delay_ripple.cost_per_day_krw": ("지연 하루 파급 비용(작업반 대기·재배치)", "원/일"),
    "liquidated_damages.grace_days": ("지체상금 유예", "일"),
    "liquidated_damages.rate_per_day_of_price": ("지체상금 일당 비율(선가 대비)", RATIO),
    "liquidated_damages.max_days": ("지체상금 최대 일수", "일"),
}
ORDER = (
    WORK_HOURS,
    "rework.equivalent_weight_t.",
    "piping.",
    "after_paint.",
    "rework_multiplier.",
    "difficulty.",
    "outfitting.",
    "po_cancel_ratio.",
    "steel.max_cancel_loss_ratio",
    GRADE_RATIO,
    "reorder.",
    "minor_work_hours.",
    "stock.",
    "liquidated_damages.",
    "labor_rate_per_hour.",
    "delay_ripple.",
    "rework.crew_hours_per_day",
)
"""보이는 순서: 양(중량·공수) → 배수·비율(난이도 계수는 배수 다음, 따로) → 단가 → 일정 환산."""
SUB_ORDER: dict[str, tuple[str, ...]] = {
    "rework.equivalent_weight_t.": tuple(kind.value for kind in PartKind),
    "rework_multiplier.": tuple(stage.value for stage in BLOCK_STAGE_ORDER),
    "po_cancel_ratio.": tuple(status.value for status in PO_STATUS_ORDER),
    "minor_work_hours.": tuple(MINOR),
    "liquidated_damages.": ("rate_per_day_of_price", "grace_days", "max_days"),
    "labor_rate_per_hour.": tuple(LABOR),
    "after_paint.": ("repaint_hours", "scaffold_hours", "hot_work_hours"),
    "difficulty.": (
        *(f"shape.{shape}" for shape in SHAPE_NAMES),
        "outfit_max",
        "outfit_full_per_t",
        "electric_max",
        "electric_full_per_t",
        "cap",
    ),
}
"""같은 묶음 안의 순서: 단계·종류 순(단계를 몰라 여러 단계의 비율을 쓴 줄도 단계 순으로 보인다)."""
STRENGTH = {ParamStatus.ASSUMPTION: 0, ParamStatus.MENTOR: 1, ParamStatus.EVIDENCE: 2}


def factor_name(key: str) -> tuple[str, str] | None:
    """파라미터 키 → (현장 이름, 단위). 이름표에 없으면 None."""
    if key in SINGLE:
        return SINGLE[key]
    prefix, _, last = key.rpartition(".")
    if prefix == "labor_rate_per_hour" and last in LABOR:
        return f"인건비({LABOR[last]})", "원/시간"
    if prefix == "minor_work_hours" and last in MINOR:
        return MINOR[last], "시간"
    if key.startswith(GRADE_RATIO) and last:
        return f"{last} 단가 비율(AH36 대비)", "배"
    if prefix == "difficulty.shape" and last in SHAPE_NAMES:
        return f"난이도: 형상 계수({SHAPE_NAMES[last]})", "배"
    try:
        if prefix == "rework_multiplier":
            return f"재작업 배수({BLOCK_STAGE_NAMES[BlockStage(last)]})", "배"
        if prefix == "po_cancel_ratio":
            return f"취소·변경률({PO_STATUS_NAMES[POStatus(last)]})", RATIO
        if prefix == "rework.equivalent_weight_t":
            return f"환산 중량({PART_KIND_NAMES[PartKind(last)]})", "t"
        if prefix == "base_work_hours_per_t":
            return f"톤당 공수({ACTIVITY_NAMES[ActivityKind(last)]})", "시간/t"
    except ValueError:
        return None
    return None


def factors_for(keys: Iterable[str], params: ParamSet) -> tuple[CostFactor, ...]:
    """비용 줄의 param_keys → 가정값. 이름표에 없는 키는 키를 이름으로 둔다(검사가 이름표 누락을 막는다)."""
    chosen = sorted(set(keys), key=_rank)
    work = sorted(
        (k for k in chosen if k.startswith(WORK_HOURS)),
        key=lambda k: BLOCK_ACTIVITY_ORDER.index(ActivityKind(k.removeprefix(WORK_HOURS))),
    )
    factors: list[CostFactor] = []
    if work:
        names = [ACTIVITY_NAMES[ActivityKind(k.removeprefix(WORK_HOURS))] for k in work]
        label = f"톤당 누적 공수({names[0]}~{names[-1]})" if len(names) > 1 else f"톤당 공수({names[0]})"
        factors.append(_factor(label, "시간/t", [params.get(k) for k in work], tuple(work)))
    for key in chosen:
        if key.startswith(WORK_HOURS):
            continue
        label, unit = factor_name(key) or (key, "")
        factors.append(_factor(label, unit, [params.get(key)], (key,)))
    return tuple(factors)


def _factor(label: str, unit: str, items: list[Param], keys: tuple[str, ...]) -> CostFactor:
    return CostFactor(
        label=label,
        unit=unit,
        value=round(sum(p.value for p in items), 6),
        low=round(sum(p.low for p in items), 6),
        high=round(sum(p.high for p in items), 6),
        status=min((p.status for p in items), key=STRENGTH.__getitem__),
        mentor_question=next((p.mentor_question for p in items if p.mentor_question is not None), None),
        keys=keys,
    )


def _rank(key: str) -> tuple[int, int, str]:
    for index, prefix in enumerate(ORDER):
        if key.startswith(prefix):
            order = SUB_ORDER.get(prefix, ())
            last = key.removeprefix(prefix)
            return index, order.index(last) if last in order else len(order), key
    return len(ORDER), 0, key
