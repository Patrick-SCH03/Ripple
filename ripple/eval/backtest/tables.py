"""결과 표(docs/backtest.md 5절): 엑셀과 마크다운이 같은 표를 쓴다.

원문 칸(변경 내용·블록·구역)은 사례에 없어 들어가지 않는다. 금액은 만원(소수 한 자리), 공수는 시간(소수 한 자리),
비율은 Pct로 둔다. 비교하지 못한 칸은 이유 문구를 넣는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ripple.engine.describe import BLOCK_STAGE_NAMES

from .case import CAUSES, PERFORMERS, WON_PER_MANWON
from .compare import CaseResult, Versus
from .engine import Engine
from .fixed import fixed_assumptions
from .scope import LABEL_OF_BASIS
from .summary import Metric, Summary


@dataclass(frozen=True, slots=True)
class Pct:
    value: float
    signed: bool = False


Cell = str | int | float | Pct | None


@dataclass(frozen=True, slots=True)
class Table:
    title: str
    headers: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]


CAUSE_LABELS = {cause: label for label, cause in CAUSES.items()}
PERFORMER_LABELS = {value: label for label, value in PERFORMERS.items()}
FAILED = "계산 불가"
NUMBER = "사례 번호"
CASE_HEADERS = (
    NUMBER,
    "계산",
    "발견 단계",
    "변경 원인",
    "수행 주체",
    "기준일",
    "확정일",
    "결정 일수",
    "가정 칸 수",
    "메모",
)
VERSUS_HEADERS = ("예측", "예측 최소", "예측 최대", "실제", "비(예측/실제)", "오차", "실제가 범위 안")
RIPPLE_HEADERS = ("지연 파급(총액 밖·가정)", "총액 + 지연 파급")
"""비용 표 끝 두 열: 엔진의 지연 파급 비용(대표값)과 총액에 더한 값. 실제 비용과는 총액(예측 열)만 견준다."""
NO_RIPPLE = "없음"
DELAY_HEADERS = (
    NUMBER,
    "예측 탑재 지연(일)",
    "예측 구역 출구 지연(일)",
    "예측 인도 지연(일, 늘어난)",
    "지연 기준",
    "실제 지연(일)",
    "차이(예측 − 실제)",
    "발주 변경(예측/사례)",
    "도면 개정(예측/사례)",
)


def case_tables(results: Sequence[CaseResult]) -> tuple[Table, ...]:
    """사례·비용·공수·지연·지도 네 표(첫 열은 모두 사례 번호). 공수 예측 = 전체 공수, 재작업 공수는 참고 열."""
    hours = [
        (r.case.number, *_versus(r.mh, 1.0), None if r.prediction is None else round(r.prediction.rework_mh.value, 1))
        for r in results
    ]
    return (
        Table("사례", CASE_HEADERS, tuple(_case_row(r) for r in results)),
        Table(
            "비용(만원)",
            (NUMBER, *VERSUS_HEADERS, *RIPPLE_HEADERS),
            tuple((r.case.number, *_versus(r.cost, WON_PER_MANWON), *_ripple(r)) for r in results),
        ),
        Table("공수(MH)", (NUMBER, *VERSUS_HEADERS, "그중 블록 재작업(예측)"), tuple(hours)),
        Table("지연·지도", DELAY_HEADERS, tuple(_delay_row(r) for r in results)),
    )


def _ripple(r: CaseResult) -> tuple[Cell, ...]:
    """지연 파급 비용(만원)과 총액 + 지연 파급(만원). 엔진이 내지 않았으면 '없음'과 총액."""
    p = r.prediction
    if p is None:
        return (None, None)
    total = p.total.value
    if p.delay_ripple is None:
        return (NO_RIPPLE, round(total / WON_PER_MANWON, 1))
    ripple = p.delay_ripple.value
    return (round(ripple / WON_PER_MANWON, 1), round((total + ripple) / WON_PER_MANWON, 1))


def _case_row(r: CaseResult) -> tuple[Cell, ...]:
    case, p, built = r.case, r.prediction, r.built
    memo = r.problem or ("판단 불가·계산 불가 이유 있음" if p is not None and p.uncertain else "")
    return (
        case.number,
        FAILED if p is None else "계산됨",
        BLOCK_STAGE_NAMES[case.stage] if case.stage else None,
        CAUSE_LABELS[case.cause] if case.cause else None,
        PERFORMER_LABELS[case.performer] if case.performer else None,
        p.as_of.isoformat() if p else None,
        p.confirm_on.isoformat() if p else None,
        case.decision_days,
        sum(a.blank for a in built.assumptions) if built else None,
        memo,
    )


def _versus(pair: Versus | None, scale: float) -> tuple[Cell, ...]:
    """예측 대표·최소·최대, 실제 대표(없으면 이유), 비, 오차, 범위 안."""
    if pair is None:
        return (None,) * len(VERSUS_HEADERS)
    band = pair.predicted
    return (
        round(band.value / scale, 1),
        round(band.low / scale, 1),
        round(band.high / scale, 1),
        pair.note if pair.actual is None else round(pair.actual / scale, 1),
        None if pair.ratio is None else round(pair.ratio, 2),
        None if pair.error is None else Pct(pair.error, signed=True),
        pair.note if pair.inside is None else ("예" if pair.inside else "아니오"),
    )


def _delay_row(r: CaseResult) -> tuple[Cell, ...]:
    p, case, built = r.prediction, r.case, r.built
    if p is None or built is None:
        return (case.number, None, None, None, None, case.delay_days, None, None, None)
    return (
        case.number,
        p.erection_delay,
        p.exit_delay,
        "계산 불가" if p.delivery_delay is None else p.delivery_delay,
        LABEL_OF_BASIS[built.scope.delay_basis],
        case.delay_days,
        r.delay_note if r.delay_diff is None else r.delay_diff,
        f"{p.po_changes}/{'—' if case.po_changes is None else case.po_changes}",
        f"{p.drawing_revisions}/{'—' if case.drawings is None else case.drawings}",
    )


def summary_table(summary: Summary, engine: Engine) -> Table:
    default_basis = LABEL_OF_BASIS[engine.defaults.delay_basis]
    rows: list[tuple[Cell, ...]] = [
        ("사례 수", summary.cases),
        ("계산한 사례", summary.computed),
        ("계산 불가 사례", summary.failed),
        ("비용 비교 기준", "총변경비용(총액) · 지연 파급 비용(총액 밖·가정)은 사례별 표에 따로"),
        *_metric_rows("비용", summary.cost),
        ("공수 비교 기준", "공수가 있는 모든 비용 줄의 합(변경 전체 공수)"),
        *_metric_rows("공수", summary.mh),
        ("지연 비교 기준", f"사례의 지연 기준(비면 {default_basis})"),
        ("지연 비교 사례", summary.delay_compared),
        ("지연 차이 중앙값(예측 − 실제, 일)", summary.delay_median),
        ("지연 절대 차이 중앙값(일)", summary.delay_abs_median),
        ("가정으로 채운 칸 수", summary.assumed_cells),
        *((f"판 · {name}", version) for name, version in engine.versions()),
    ]
    return Table("요약", ("항목", "값"), tuple(rows))


def _metric_rows(name: str, metric: Metric) -> list[tuple[Cell, ...]]:
    ratio, absolute, signed = metric.inside_ratio, metric.abs_error_median, metric.error_median
    return [
        (f"{name} 비교 사례", metric.compared),
        (f"{name} 실제가 예측 범위 안", f"{metric.inside}/{metric.compared}"),
        (f"{name} 범위 안 비율", None if ratio is None else Pct(ratio)),
        (f"{name} 절대 오차 중앙값", None if absolute is None else Pct(absolute)),
        (f"{name} 오차 중앙값(+ = 과대 예측)", None if signed is None else Pct(signed, signed=True)),
    ]


def assumption_tables(results: Sequence[CaseResult], engine: Engine) -> tuple[Table, Table]:
    rows = tuple(
        (r.case.number, a.item, a.value, a.reason, "빈 칸 채움" if a.blank else "변환 메모")
        for r in results
        if r.built
        for a in r.built.assumptions
    )
    return (
        Table("가정(사례별)", (NUMBER, "항목", "쓴 값", "이유", "구분"), rows),
        Table("고정 가정값", ("항목", "값", "출처"), fixed_assumptions(engine)),
    )
