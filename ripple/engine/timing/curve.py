"""추가손실 곡선(docs/engine.md(비용·일정) 8-1): 탐색 기간의 판정일마다 총액·추가손실·구역 출구 지연과 바뀐 줄.

추가손실 0 마감일은 이 곡선에서 계약의 expected_deadline이 찾는다.
"""

from __future__ import annotations

from datetime import date, timedelta

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.result import CurvePoint, additional_loss_of

from .evaluation import Evaluation

Curve = tuple[tuple[CurvePoint, ...], dict[date, Evaluation]]
"""곡선 점(판정일 순)과 판정일 → 평가."""


def search_days(request: AnalysisRequest) -> list[date]:
    """기준일부터 탐색 기간 끝까지의 판정일."""
    as_of, horizon = request.as_of, request.horizon_days
    return [as_of + timedelta(days=i) for i in range(horizon + 1)]


def curve_points(evaluations: dict[date, Evaluation], as_of: date) -> tuple[CurvePoint, ...]:
    """판정일 순 곡선 점: 추가손실은 기준일 총액 대비, 사건은 전날 평가와 달라진 것."""
    base = evaluations[as_of].total
    points: list[CurvePoint] = []
    previous: Evaluation | None = None
    for day in sorted(evaluations):
        ev = evaluations[day]
        points.append(
            CurvePoint(
                confirm_on=day,
                total=ev.total,
                additional_loss=additional_loss_of(ev.total, base),
                max_exit_delay_days=ev.max_exit_delay,
                events=_events(previous, ev),
            )
        )
        previous = ev
    return tuple(points)


def _events(previous: Evaluation | None, current: Evaluation) -> tuple[str, ...]:
    if previous is None:
        return ()
    before = {line.line_id: line.amount.value for line in previous.lines}
    changed = [line.label for line in current.lines if before.get(line.line_id) != line.amount.value][:5]
    if current.max_exit_delay != previous.max_exit_delay:
        changed.append(f"구역 출구 예상 지연 {current.max_exit_delay}일")
    return tuple(changed)
