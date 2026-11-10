"""수치 블록: METRICS 키 → 분석 결과 필드의 값 → 고정 라벨·단위·문장 틀(contracts/explain.py).

수치 블록의 숫자는 여기서만 만든다. 결과에 값이 없는 키(경계 조건이 없어 인도 지연 계산 불가 등)는 고를 수 없다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date

from ripple.contracts.explain import METRICS, MetricBlock, MetricUnit, TextPart
from ripple.contracts.result import Amount, AnalysisResult, DeadlineKind, ZeroLossDeadline

from .format import day, grouped, money, money_range

MetricValue = Amount | int | date | ZeroLossDeadline


def metric_value(result: AnalysisResult, key: str, entity_id: str | None = None) -> MetricValue | None:
    """결과에 있는 값(없으면 None). 목록 수치는 엔터티 ID로 고른다."""
    whole = _RESULT_METRICS.get(key)
    if whole is not None:
        return whole(result)
    return _entity_metric(result, key, entity_id)


def _delivery_delay(result: AnalysisResult) -> int | None:
    delivery = result.schedule.delivery
    return None if delivery is None else delivery.added_delay_days


_RESULT_METRICS: Mapping[str, Callable[[AnalysisResult], MetricValue | None]] = {
    "cost.total": lambda r: r.total,
    "timing.base_cost": lambda r: r.timing.base_cost,
    "timing.deadline": lambda r: r.timing.deadline,
    "schedule.max_exit_delay": lambda r: r.schedule.max_exit_delay_days,
    "schedule.delivery_delay": _delivery_delay,
    "impacts.count": lambda r: len(r.impacts),
    "recommendation.total": lambda r: None if r.recommendation is None else r.recommendation.total,
}
"""결과 전체에 하나뿐인 수치."""


def _entity_metric(result: AnalysisResult, key: str, entity_id: str | None) -> MetricValue | None:
    """엔터티(비용 줄·보류 발주·대안)마다 있는 수치."""
    if key == "cost.line":
        return next((line.amount for line in result.cost_lines if line.line_id == entity_id), None)
    if key == "alternative.total":
        return next((a.total for a in result.alternatives if a.alt_id == entity_id), None)
    hold = {h.po_id: h for h in result.timing.holds}.get(entity_id or "")
    if hold is None:
        return None
    if key == "hold.max_days":
        return hold.max_hold_days
    if key == "hold.until":
        return hold.hold_until
    if key == "hold.avoided":
        return hold.avoided
    return None


def available_metrics(result: AnalysisResult) -> tuple[MetricBlock, ...]:
    """이 분석에서 값이 있는 수치 블록 전부(LLM이 고를 수 있는 목록)."""
    found: list[MetricBlock] = []
    entities: Mapping[str, tuple[str, ...]] = {
        "cost.line": tuple(line.line_id for line in result.cost_lines),
        "hold.max_days": tuple(h.po_id for h in result.timing.holds),
        "hold.until": tuple(h.po_id for h in result.timing.holds),
        "hold.avoided": tuple(h.po_id for h in result.timing.holds),
        "alternative.total": tuple(a.alt_id for a in result.alternatives),
    }
    for key, spec in METRICS.items():
        for entity in entities.get(key, ()) if spec.per_entity else (None,):
            if metric_value(result, key, entity) is not None:
                found.append(MetricBlock(metric=key, entity_id=entity))
    return tuple(found)


@dataclass(frozen=True, slots=True)
class MetricText:
    text: str
    numbers: tuple[str, ...]  # 문장에 쓴 숫자 표기(독립 검출기가 결과와 대조)
    parts: tuple[TextPart, ...]  # 문장 조각(엔터티 이름 · 숫자 표기 · 그 밖의 글), 이으면 text


def _metric_text(*parts: TextPart) -> MetricText:
    """조각을 이어 문장을 만든다. 숫자 표기는 값 조각 그대로다(문장과 조각이 따로 놀지 않게)."""
    return MetricText(
        text="".join(p.text for p in parts),
        numbers=tuple(p.text for p in parts if p.value),
        parts=parts,
    )


def _plain(text: str) -> TextPart:
    return TextPart(text=text)


def _number(text: str) -> TextPart:
    return TextPart(text=text, value=True)


def render_metric(
    block: MetricBlock, result: AnalysisResult, names: Mapping[str, str], *, field: bool = False
) -> MetricText | None:
    """수치 블록 한 줄. field면 공식 메일용 '라벨: 값'(끝맺음 없음), 아니면 명사형 줄('총변경비용 298만원')."""
    value = metric_value(result, block.metric, block.entity_id)
    if value is None:
        return None
    spec = METRICS[block.metric]
    if field:
        return _field(block, spec.label, spec.unit, value, names)
    if block.entity_id is None:
        head: tuple[TextPart, ...] = (_plain(f"{spec.label} "),)
    else:
        name = names.get(block.entity_id) or block.entity_id
        head = (TextPart(text=name, entity_id=block.entity_id), _plain(f" {spec.label} "))
    if spec.unit is MetricUnit.KRW and isinstance(value, Amount):
        shown = money(value.value)
        if value.low == value.high:
            return _metric_text(*head, _number(shown))
        spread = money_range(value.low, value.high)
        return _metric_text(*head, _number(shown), _plain("(범위 "), _number(spread), _plain(")"))
    if spec.unit is MetricUnit.DAYS and isinstance(value, int):
        return _metric_text(*head, _number(f"{grouped(value)}일"))
    if spec.unit is MetricUnit.COUNT and isinstance(value, int):
        return _metric_text(*head, _number(f"{grouped(value)}개"))
    if spec.unit is MetricUnit.DATE and isinstance(value, date):
        return _metric_text(*head, _number(day(value)))
    if spec.unit is MetricUnit.DATE and isinstance(value, ZeroLossDeadline):
        shown = day(value.last_day)
        if value.kind is DeadlineKind.CONFIRM_NOW:
            return _metric_text(*head, _plain("오늘("), _number(shown), _plain(")"))
        if value.kind is DeadlineKind.NONE_IN_HORIZON:
            return _metric_text(*head, _plain("탐색 기간 끝("), _number(shown), _plain(")까지 없음"))
        return _metric_text(*head, _number(shown))
    raise ValueError(f"{block.metric}: 값 형식과 단위 불일치")


def _field(block: MetricBlock, label: str, unit: MetricUnit, value: object, names: Mapping[str, str]) -> MetricText:
    """'- PO-0130 보류 유지 가능 기한: 2026년 11월 11일'(공식 메일 본문의 항목 한 줄)."""
    if block.entity_id is None:
        head: tuple[TextPart, ...] = (_plain(f"- {label}: "),)
    else:
        name = names.get(block.entity_id) or block.entity_id
        head = (_plain("- "), TextPart(text=name, entity_id=block.entity_id), _plain(f" {label}: "))
    if unit is MetricUnit.KRW and isinstance(value, Amount):
        shown = money(value.value)
        if value.low == value.high:
            return _metric_text(*head, _number(shown))
        return _metric_text(
            *head, _number(shown), _plain(" (범위 "), _number(money_range(value.low, value.high)), _plain(")")
        )
    if unit is MetricUnit.DAYS and isinstance(value, int):
        return _metric_text(*head, _number(f"{grouped(value)}일"))
    if unit is MetricUnit.COUNT and isinstance(value, int):
        return _metric_text(*head, _number(f"{grouped(value)}개"))
    if unit is MetricUnit.DATE and isinstance(value, date):
        return _metric_text(*head, _number(day(value)))
    if unit is MetricUnit.DATE and isinstance(value, ZeroLossDeadline):
        return _metric_text(*head, _number(day(value.last_day)))
    raise ValueError(f"{block.metric}: 값 형식과 단위 불일치")
