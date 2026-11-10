"""2단계 분석 결과(docs/engine.md(비용·일정))와 결과 안의 성질 검사, 불변 분석본."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime
from itertools import pairwise

from pydantic import ConfigDict, Field, model_validator

from ..analysis import AnalysisRequest, Versions
from ..approval import ApprovalPlan
from ..base import Frozen, omittable
from ..domain import DataMode
from ..graphview import GraphView
from ..identity import analysis_id as compute_analysis_id
from ..identity import permissible_delay
from .alternatives import REQUEST_ALT, AlternativeResult, CheapestSpan, Recommendation
from .amount import Amount
from .basis import StateBasis, TraceChain
from .cost import HOURS_DIGITS, CostLine, CostSplit
from .delay import DelayRipple
from .impact import Impact, Unresolved
from .onboard import OnboardOption
from .precheck import PrecheckItem, precheck_order
from .report import graph_problem
from .schedule import ScheduleImpact
from .timing import TimingResult
from .verdict import Verdict
from .vocab import PURCHASE_ITEMS, AlternativeOrigin, CostKind, Eligibility, OnboardDirection, UnresolvedKind
from .weight import WeightChange

OMITTED_WHEN_EMPTY = ("prechecks", "approval_plan", "weight_change", "cost_split")
"""비면 직렬화에서 빠지는 필드: 응답 스키마에서 필수도 기본값도 아니게 둔다(base.omittable)."""


class AnalysisResult(Frozen):
    """2단계 분석 결과(docs/engine.md(비용·일정)). 화면은 이 응답 하나로 요약·근거·곡선·파급을 그린다."""

    model_config = ConfigDict(json_schema_extra=omittable(*OMITTED_WHEN_EMPTY))

    analysis_id: str
    versions: Versions
    request: AnalysisRequest
    data_mode: DataMode
    impacts: tuple[Impact, ...]
    cost_lines: tuple[CostLine, ...]
    total: Amount
    schedule: ScheduleImpact
    timing: TimingResult
    alternatives: tuple[AlternativeResult, ...] = ()
    recommendation: Recommendation | None = None
    cheapest_by_date: tuple[CheapestSpan, ...] = ()  # 대안 포함 분석에서만
    unresolved: tuple[Unresolved, ...] = ()
    graph: GraphView  # 대상·근거 경로의 노드와 연결(ImpactReport.graph와 같은 규칙)
    verdict: Verdict
    pending_rules: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    state_basis: tuple[StateBasis, ...] = ()  # 1.22.0 판단이 걸린 상태(옛 기록 본문에는 없음)
    trace: tuple[TraceChain, ...] | None = None  # 1.23.0 연결 추적. None = 추적 정보 미수록(옛 기록), () = 대상 없음
    onboard: OnboardOption | None = None  # 1.29.0 의장품 선상 설치 선택지(명세 6-8, 없으면 None)
    delay_ripple: DelayRipple | None = None  # 1.32.0 지연 파급 비용(총액 밖, 명세 4-11 — 없으면 None)
    # 1.32.0 설계변경 사전 점검(판정과 분리된 확인 항목, docs/engine.md(사전 점검)). 비면 직렬화에서 빼서 그 필드가 없던
    # 기록 본문의 기록 ID(본문 해시)가 그대로 맞는다(identity.snapshot_id의 LATER_FIELDS와 같은 생각)
    prechecks: tuple[PrecheckItem, ...] = Field(default=(), exclude_if=lambda items: not items)
    # 1.33.0 결재 계획(docs/records.md(기록·결재) 14절): 엔진은 채우지 않고 분석 API가 응답에 덧붙인다
    # (업무상 오늘에 따라 바뀌는 값). 없으면 직렬화에서 빠져 기록 본문·기록 ID·분석 ID와 무관하다
    approval_plan: ApprovalPlan | None = Field(default=None, exclude_if=lambda plan: plan is None)
    # 1.34.0 블록별 강재 중량 변화(정보, docs/engine.md(비용·일정) 12절). None = 이 판 전 기록(계산하지 않음) —
    # 직렬화에서 빠져 옛 기록 본문의 기록 ID(본문 해시)가 그대로 맞는다. 바뀌는 부재가 없으면 빈 블록 목록
    weight_change: WeightChange | None = Field(default=None, exclude_if=lambda weight: weight is None)
    # 1.35.0 총변경비용의 구분별 합(추가 공수 MH·공수 금액·재료비(구매 소계)·지체상금, docs/engine.md(비용·일정) 4-12).
    # None = 이 판 전 기록(비용 줄에도 구분 없음) — 직렬화에서 빠져 옛 기록 본문의 기록 ID가 그대로다
    cost_split: CostSplit | None = Field(default=None, exclude_if=lambda split: split is None)

    @model_validator(mode="after")
    def _consistent(self) -> AnalysisResult:
        """결과 안의 성질을 차례로 검사해 처음 어긋난 이유로 거절한다(뒤 검사는 앞 검사가 통과해야 의미가 있다)."""
        checks: tuple[Callable[[AnalysisResult], str | None], ...] = (
            _identity_problem,
            lambda r: graph_problem(r.graph, r.versions.snapshot_id, r.impacts),
            _amounts_problem,
            _risk_reasons_problem,
            _alternatives_problem,
            _spans_problem,
            _recommendation_problem,
            _permissible_problem,
            _onboard_problem,
            _delay_ripple_problem,
            _prechecks_problem,
            _split_problem,
        )
        for check in checks:
            problem = check(self)
            if problem:
                raise ValueError(problem)
        return self


def _identity_problem(result: AnalysisResult) -> str | None:
    """분석 ID = 버전·요청, 영향은 키 순으로 정렬되고 겹치지 않음."""
    if result.analysis_id != compute_analysis_id(result.versions, result.request):
        return "분석 ID와 버전·요청 불일치"
    keys = [impact.key for impact in result.impacts]
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        return "영향은 키 순 정렬·중복 없음 필요"
    return None


def _amounts_problem(result: AnalysisResult) -> str | None:
    """곡선은 기준일부터 탐색 기간 끝까지 하루씩, 비용 줄 ID는 겹치지 않고 총액 = 줄의 합, 인도 계산 불가에는 이유."""
    curve = result.timing.curve
    if curve[0].confirm_on != result.request.as_of or len(curve) != result.request.horizon_days + 1:
        return "추가손실 곡선은 기준일부터 탐색 기간 끝까지 하루 간격 필요"
    duplicated = [k for k, n in Counter(c.line_id for c in result.cost_lines).items() if n > 1]
    if duplicated:
        return f"비용 줄 ID 중복: {duplicated[:3]}"
    if result.total != Amount.total([c.amount for c in result.cost_lines]):
        return "총액과 비용 줄 합 불일치"
    if result.schedule.delivery is None and not any(u.kind is UnresolvedKind.DELIVERY for u in result.unresolved):
        return "인도 지연 미계산 시 이유 필요"
    return None


def _alternatives_problem(result: AnalysisResult) -> str | None:
    """대안: ID 겹침 없음, 충족 순위 1부터 빠짐없이, 대안을 켠 분석에만, 첫 항목은 요청안, 대안 ↔ 권고, 확정일 하한."""
    alternatives = result.alternatives
    alt_ids = [a.alt_id for a in alternatives]
    if len(set(alt_ids)) != len(alt_ids):
        return "대안 ID 중복"
    ranks = sorted(a.rank for a in alternatives if a.rank is not None)
    if ranks != list(range(1, len(ranks) + 1)):
        return "충족 대안 순위는 1부터 빠짐없이 필요"
    if alternatives and not result.request.include_alternatives:
        return "대안을 켜지 않은 분석에 대안 불가"
    if alternatives and (
        alternatives[0].origin is not AlternativeOrigin.REQUEST or alternatives[0].alt_id != REQUEST_ALT
    ):
        return f"대안 목록 첫 항목은 요청안({REQUEST_ALT}) 필요"
    if bool(alternatives) != (result.recommendation is not None):
        return "대안이 있으면 권고 필요, 없으면 권고 불가"
    earliest = result.request.effective_confirm_on
    if any(a.best_confirm_on is not None and a.best_confirm_on < earliest for a in alternatives):
        return "최적 조합 확정일이 요청 확정일(확정 가능일)보다 앞섬"
    return None


def _recommendation_problem(result: AnalysisResult) -> str | None:
    """권고는 충족 대안 중에서, 1위 대안의 최적 조합(확정일·보류·총액)과 같아야 한다."""
    recommendation = result.recommendation
    if recommendation is None:
        return None
    chosen = next((a for a in result.alternatives if a.alt_id == recommendation.alt_id), None)
    if chosen is None or chosen.eligibility.status is not Eligibility.MEETS:
        return "추천은 충족 대안 중에서만 가능"
    best = (chosen.rank, chosen.best_confirm_on, chosen.best_holds, chosen.best_total)
    advised = (1, recommendation.confirm_on, recommendation.holds, recommendation.total)
    if best != advised:
        return "권고와 1위 대안의 최적 조합(확정일·보류·총액) 불일치"
    return None


def _permissible_problem(result: AnalysisResult) -> str | None:
    """허용 지연 표시는 선주 요청에만, 표시가 있으면 지체상금 줄이 없다.

    표시 기준으로만 본다: 1.28.0 기록(선주 요청인데 지체상금 줄이 있고 표시 없음)도 읽혀야 한다
    — 옛 계산 판으로 보인다."""
    deliveries = (result.schedule.delivery, result.schedule.risk.delivery if result.schedule.risk else None)
    marked = [d for d in deliveries if d is not None and d.permissible]
    if marked and not permissible_delay(result.request):
        return "허용 지연은 선주 요청 변경에만 가능"
    if marked and any(line.rule_id == "R-L01" for line in result.cost_lines):
        return "허용 지연이면 지체상금 줄 불가(합의 못 할 때의 금액은 노출 금액으로)"
    return None


def _onboard_problem(result: AnalysisResult) -> str | None:
    """선상 설치 선택지의 방향은 요청의 방식과 반대이고, now 값은 이 분석의 일정과 같다."""
    option = result.onboard
    if option is None:
        return None
    expected = OnboardDirection.TO_WAIT if result.request.outfit_on_board else OnboardDirection.TO_ON_BOARD
    if option.direction is not expected:
        return "선상 설치 선택지는 요청 실행 방식과 반대 방향 필요"
    delivery = result.schedule.delivery
    now = (option.exit_delay_now_days, option.delivery_added_now_days)
    if now != (result.schedule.max_exit_delay_days, None if delivery is None else delivery.added_delay_days):
        return "선상 설치 선택지의 지금 값과 이 분석의 구역 출구·인도 지연 불일치"
    return None


def _delay_ripple_problem(result: AnalysisResult) -> str | None:
    """지연 파급 비용은 이 분석의 구역 출구 지연·늘어난 인도 지연과 맞는다
    (총액에 들어 있지 않음은 총액 = 줄의 합 검사가 본다)."""
    ripple = result.delay_ripple
    if ripple is None:
        return None
    delivery = result.schedule.delivery
    overlap = 0 if delivery is None else delivery.added_delay_days
    if ripple.exit_delay_days != result.schedule.max_exit_delay_days or ripple.delivery_overlap_days != overlap:
        return "지연 파급 비용의 구역 출구·인도 지연과 이 분석 일정 불일치"
    return None


def _prechecks_problem(result: AnalysisResult) -> str | None:
    """사전 점검: 키 고유, 규칙 ID → 키 순, 실데이터 결과에는 합성 NCR 건수가 없다."""
    items = result.prechecks
    keys = [item.key for item in items]
    if len(set(keys)) != len(keys) or list(items) != sorted(items, key=precheck_order):
        return "사전 점검 항목은 키 중복 없이 규칙 ID·키 순 필요"
    if result.data_mode is DataMode.REAL and any(item.ncr_count is not None for item in items):
        return "실데이터 분석에 합성 NCR 건수 불가"
    return None


def _split_problem(result: AnalysisResult) -> str | None:
    """비용 구분(1.35.0): 줄마다 구분이 모두 있거나(새 판) 모두 없고(옛 기록), 있으면 구분별 합이 비용 줄의 합이고
    공수 + 재료비 + 지체상금 = 총액(최소·대표·최대 모두). 공수(MH) 합은 반올림 오차 안에서 공수 줄 공수의 합."""
    lines, split = result.cost_lines, result.cost_split
    marked = [line.kind is not None for line in lines]
    if split is None:
        return "비용 줄 구분이 있으면 구분별 합 필요" if any(marked) else None
    if not all(marked):
        return "구분별 합이 있으면 모든 비용 줄에 구분 필요"

    def total(keep: Callable[[CostLine], bool]) -> Amount:
        return Amount.total([line.amount for line in lines if keep(line)])

    sums = (
        (split.labor, total(lambda line: line.kind is CostKind.LABOR)),
        (split.material, total(lambda line: line.kind is CostKind.MATERIAL)),
        (split.purchase, total(lambda line: line.item in PURCHASE_ITEMS)),
        (split.damages, total(lambda line: line.kind is CostKind.DAMAGES)),
    )
    if any(shown != summed for shown, summed in sums):
        return "구분별 합과 비용 줄 합 불일치"
    if Amount.total([split.labor, split.material, split.damages]) != result.total:
        return "공수 + 재료비 + 지체상금과 총액 불일치"
    hours = [line.hours for line in lines if line.hours is not None]
    slack = (len(hours) + 1) * 10.0**-HOURS_DIGITS
    for got, want in (
        (split.labor_hours.value, sum(h.value for h in hours)),
        (split.labor_hours.low, sum(h.low for h in hours)),
        (split.labor_hours.high, sum(h.high for h in hours)),
    ):
        if abs(got - want) > slack:
            return "추가 공수(MH)와 공수 줄 공수 합 불일치"
    return None


def _risk_reasons_problem(result: AnalysisResult) -> str | None:
    """위험 일정의 인도 계산 불가에는 이유가 있고(대표 또는 위험 전용), 위험 전용 이유는 대표 이유와 겹치지 않는다."""
    risk = result.schedule.risk
    if risk is None:
        return None
    if set(risk.unresolved) & set(result.unresolved):
        return "위험 일정에서만 생긴 계산 불가 사유가 대표 사유와 중복"
    reasons = (*result.unresolved, *risk.unresolved)
    if risk.delivery is None and not any(u.kind is UnresolvedKind.DELIVERY for u in reasons):
        return "위험 일정 인도 지연 미계산 시 이유 필요"
    return None


def _spans_problem(result: AnalysisResult) -> str | None:
    """날짜별 가장 싼 대안 구간: 대안이 있으면 기준일~탐색 기간 끝을 빈틈없이, 이웃은 다른 대안, 모두 충족."""
    spans = result.cheapest_by_date
    if not result.alternatives:
        return "대안이 없는데 날짜별 가장 싼 대안 구간 있음" if spans else None
    if not spans:
        return "대안이 있으면 날짜별 가장 싼 대안 구간 필요"
    curve = result.timing.curve
    if spans[0].start != curve[0].confirm_on or spans[-1].end != curve[-1].confirm_on:
        return "날짜별 가장 싼 대안 구간은 기준일부터 탐색 기간 끝까지 필요"
    for a, b in pairwise(spans):
        if (b.start - a.end).days != 1 or a.alt_id == b.alt_id:
            return "날짜별 가장 싼 대안 구간은 빈틈없이 연속·이웃은 다른 대안 필요"
    meets = {a.alt_id for a in result.alternatives if a.eligibility.status is Eligibility.MEETS}
    if any(s.alt_id not in meets for s in spans):
        return "날짜별 가장 싼 대안은 충족 대안 중에서만 선택"
    return None


class AnalysisRecord(Frozen):
    """불변 분석본. 승인·감사 기록은 analysis_id로 이것을 참조한다."""

    analysis_id: str
    created_at: datetime
    result: AnalysisResult

    @model_validator(mode="after")
    def _same_id(self) -> AnalysisRecord:
        if self.analysis_id != self.result.analysis_id:
            raise ValueError("분석본 ID와 결과 불일치")
        return self
