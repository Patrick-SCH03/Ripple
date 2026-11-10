"""사례 실행과 비교(docs/backtest.md 5절): 최소 지도 → 엔진 analyze → 예측(총액·공수·지연) → 실제와 견줌.

- 공수(MH)는 비용 줄에서 다시 읽는다: 인건비 키가 하나인 줄(재작업·작은 작업·새 부재 제작·선상 설치)은
  금액 = 공수 × 단가라 공수 = 금액 ÷ 단가(시나리오별).
- 전체 공수 = 그런 줄 모두의 합 — 실제 '추가 공수'(현장이 말하는 변경 전체 공수)와 견준다.
  재작업 공수 = 블록 재작업(R-B01) 줄의 합, 참고로 싣는다.
- 지연은 사례의 지연 기준(탑재·구역 출구·인도)과 같은 예측과 견준다. 인도는 늘어난 인도 지연.
- 실제 값은 최소·최대의 가운데를 대표값으로 쓴다. 실제 값이 없으면 '비교 불가'(지어내지 않음).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from ripple.contracts.params import ParamSet
from ripple.contracts.result import AnalysisResult, CostLine, Determinacy, ImpactType
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.validate import RequestError

from .build import Built, build_case
from .case import Case, Span
from .defaults import DelayBasis
from .engine import Engine
from .scope import BuildError

RATE_PREFIX = "labor_rate_per_hour."
REWORK_RULE = "R-B01"
NOT_COMPARABLE = "비교 불가(실제 값 없음)"
NO_DELIVERY = "비교 불가(인도 지연 계산 불가)"


@dataclass(frozen=True, slots=True)
class Band:
    """대표값과 범위(최소·최대). 금액(원) 또는 공수(시간)."""

    value: float
    low: float
    high: float


@dataclass(frozen=True, slots=True)
class Prediction:
    as_of: date
    confirm_on: date
    total: Band  # 총변경비용(원) — 실제 비용과 견주는 값
    delay_ripple: Band | None  # 지연 파급 비용(원, 총액 밖·가정 — 엔진 필드 그대로, 없으면 None). 비교에 쓰지 않음
    rework_mh: Band  # 블록 재작업(R-B01) 공수 합
    all_mh: Band  # 공수가 있는 모든 비용 줄의 공수 합
    exit_delay: int  # 구역 출구 지연(일)
    erection_delay: int  # 대상 블록 탑재 지연(일)
    delivery_delay: int | None  # 늘어난 인도 지연(일, 계산하지 못하면 None)
    po_changes: int  # 발주 변경·취소 영향 수
    drawing_revisions: int  # 도면 개정 영향 수
    uncertain: bool  # 판단 불가 줄이나 계산 불가 이유가 있음


@dataclass(frozen=True, slots=True)
class Versus:
    """예측 대 실제 하나(금액·공수). 실제가 없으면 note만 있다."""

    predicted: Band
    actual: float | None  # 실제 대표값(최소·최대의 가운데)
    ratio: float | None  # 예측 / 실제
    error: float | None  # (예측 − 실제) / 실제
    inside: bool | None  # 실제 대표값이 예측 범위(최소~최대) 안
    note: str = ""


@dataclass(frozen=True, slots=True)
class CaseResult:
    case: Case
    built: Built | None
    prediction: Prediction | None
    problem: str | None  # 계산하지 못한 이유
    cost: Versus | None = None
    mh: Versus | None = None
    delay_diff: float | None = None  # 예측 − 실제(일)
    delay_note: str = ""


def run_cases(cases: Iterable[Case], engine: Engine) -> tuple[CaseResult, ...]:
    return tuple(run_case(case, engine) for case in cases)


def run_case(case: Case, engine: Engine) -> CaseResult:
    try:
        built = build_case(case, engine.defaults, engine.generator)
        result = analyze(GraphIndex(built.snapshot), built.request, engine.rulebook, engine.params)
    except BuildError as error:
        return CaseResult(case=case, built=None, prediction=None, problem=str(error))
    except RequestError as error:
        return CaseResult(case=case, built=None, prediction=None, problem=f"엔진의 요청 거절: {error}")
    prediction = predict(result, built, engine.params)
    diff, note = delay_versus(prediction, built.scope.delay_basis, case.delay_days)
    return CaseResult(
        case=case,
        built=built,
        prediction=prediction,
        problem=None,
        cost=versus(prediction.total, case.cost_krw),
        mh=versus(prediction.all_mh, case.mh),
        delay_diff=diff,
        delay_note=note,
    )


def predicted_delay(prediction: Prediction, basis: DelayBasis) -> int | None:
    if basis == "erection":
        return prediction.erection_delay
    if basis == "exit":
        return prediction.exit_delay
    return prediction.delivery_delay


def delay_versus(prediction: Prediction, basis: DelayBasis, actual: float | None) -> tuple[float | None, str]:
    """(예측 − 실제 일수, 비교하지 못한 이유). 실제가 없거나 인도 지연을 계산하지 못하면 차이 없음."""
    if actual is None:
        return None, NOT_COMPARABLE
    predicted = predicted_delay(prediction, basis)
    if predicted is None:
        return None, NO_DELIVERY
    return predicted - actual, ""


def predict(result: AnalysisResult, built: Built, params: ParamSet) -> Prediction:
    lines = result.cost_lines
    schedule = result.schedule
    total = result.total
    ripple = result.delay_ripple.amount if result.delay_ripple is not None else None
    return Prediction(
        as_of=result.request.as_of,
        confirm_on=result.request.effective_confirm_on,
        total=Band(total.value, total.low, total.high),
        delay_ripple=None if ripple is None else Band(ripple.value, ripple.low, ripple.high),
        rework_mh=_hours((line for line in lines if line.rule_id == REWORK_RULE), params),
        all_mh=_hours(lines, params),
        exit_delay=schedule.max_exit_delay_days,
        erection_delay=schedule.added_days_by_activity.get(built.erection_id, 0),
        delivery_delay=None if schedule.delivery is None else schedule.delivery.added_delay_days,
        po_changes=sum(impact.impact_type is ImpactType.PO_CHANGE for impact in result.impacts),
        drawing_revisions=sum(impact.impact_type is ImpactType.DRAWING_REVISION for impact in result.impacts),
        uncertain=bool(result.unresolved) or any(line.determinacy is not Determinacy.KNOWN for line in lines),
    )


def line_hours(line: CostLine, params: ParamSet) -> Band | None:
    """공수 × 인건비 줄의 공수(시나리오별 금액 ÷ 같은 시나리오 단가): 재작업(작업반 몫으로 나뉜 줄 포함)·도장 뒤 고정
    항목(C-04)·작은 작업·새 부재 제작. 인건비 키가 여럿인 줄(공정마다 단가가 다른 재작업)은 엔진이 줄에 적은 대표 공수만
    (범위 없이), 인건비 키가 없으면 None."""
    rates = [key for key in line.param_keys if key.startswith(RATE_PREFIX)]
    if len(rates) == 1:
        rate = params.get(rates[0])
        amount = line.amount
        return Band(amount.value / rate.value, amount.low / rate.low, amount.high / rate.high)
    written = line.inputs.get("hours")
    if rates and isinstance(written, int | float):
        return Band(float(written), float(written), float(written))
    return None


def _hours(lines: Iterable[CostLine], params: ParamSet) -> Band:
    found = [hours for line in lines if (hours := line_hours(line, params)) is not None]
    return Band(sum(h.value for h in found), sum(h.low for h in found), sum(h.high for h in found))


def versus(predicted: Band, actual: Span | None) -> Versus:
    if actual is None:
        return Versus(predicted=predicted, actual=None, ratio=None, error=None, inside=None, note=NOT_COMPARABLE)
    mid = actual.mid
    inside = predicted.low <= mid <= predicted.high
    if mid == 0:
        return Versus(predicted, 0.0, None, None, inside, note="실제 0 · 비·오차 계산 제외")
    return Versus(predicted, mid, predicted.value / mid, (predicted.value - mid) / mid, inside)
