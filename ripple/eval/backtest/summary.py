"""묶음 요약(docs/backtest.md 5절): 사례 수, 범위 안 비율, 오차 중앙값, 지연 차이, 가정으로 채운 칸 수."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from .compare import CaseResult, Versus


@dataclass(frozen=True, slots=True)
class Metric:
    """금액·공수 하나의 묶음 지표(비교한 사례만)."""

    compared: int
    inside: int  # 실제 대표값이 예측 범위 안인 사례 수
    abs_error_median: float | None  # |예측 − 실제| / 실제 의 중앙값(실제 0인 사례 제외)
    error_median: float | None  # (예측 − 실제) / 실제 의 중앙값(+ = 과대 예측)

    @property
    def inside_ratio(self) -> float | None:
        return self.inside / self.compared if self.compared else None


@dataclass(frozen=True, slots=True)
class Summary:
    cases: int
    computed: int
    failed: int
    cost: Metric
    mh: Metric
    delay_compared: int
    delay_median: float | None  # 예측 − 실제(일)의 중앙값
    delay_abs_median: float | None
    assumed_cells: int  # 빈 칸을 기본값으로 채운 칸 수(계산한 사례만)


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def metric(pairs: Sequence[Versus]) -> Metric:
    compared = [p for p in pairs if p.actual is not None]
    errors = [p.error for p in compared if p.error is not None]
    return Metric(
        compared=len(compared),
        inside=sum(bool(p.inside) for p in compared),
        abs_error_median=_median([abs(e) for e in errors]),
        error_median=_median(errors),
    )


def summarize(results: Sequence[CaseResult]) -> Summary:
    computed = [r for r in results if r.prediction is not None]
    delays = [r.delay_diff for r in computed if r.delay_diff is not None]
    return Summary(
        cases=len(results),
        computed=len(computed),
        failed=len(results) - len(computed),
        cost=metric([r.cost for r in computed if r.cost is not None]),
        mh=metric([r.mh for r in computed if r.mh is not None]),
        delay_compared=len(delays),
        delay_median=_median(delays),
        delay_abs_median=_median([abs(d) for d in delays]),
        assumed_cells=sum(a.blank for r in computed if r.built for a in r.built.assumptions),
    )
