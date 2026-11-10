"""평가 계약: 관문 손 계산 사례(docs/gate_cases.md).

사례 입력(GateCaseInput)은 생성기 지도와 변경 요청이고, 계산자(엔진 코드를 보지 않는 사람 또는 AI 모델)가 기대 결과를
더해 사례(GateCase)가 된다. 1단계 기대 영향은 그 사례의 빠짐없는 전체 정답 집합이다. 2단계는 비용 줄(줄 ID 기준
전체 집합)·총액·일정·확정 시점·요약 판정을 기대값으로 둔다(docs/engine.md(비용·일정)). 3단계는 대안 목록·판정·대안별
총액·일정·마감일·최적 조합·순위·권고·날짜별 가장 싼 대안과 만들지 않은 대안의 이유를 둔다(docs/engine.md(대안)).
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from enum import StrEnum
from itertools import pairwise

from pydantic import Field, FiniteFloat, model_validator

from .analysis import AnalysisRequest, HoldAction
from .base import Frozen
from .change import ChangeOp
from .result import (
    REQUEST_ALT,
    DeadlineKind,
    Determinacy,
    Eligibility,
    ImpactType,
    OnboardDirection,
    UnresolvedKind,
    VerdictLevel,
    ZeroLossDeadline,
)

CASE_ID_PATTERN = r"^G[1-3]-\d{3}$"


class SnapshotRef(Frozen):
    generator_seed: int
    snapshot_id: str = Field(pattern=r"^G-[0-9a-f]{16}$")


class GateCaseInput(Frozen):
    """계산자에게 주는 사례 입력."""

    case_id: str = Field(pattern=CASE_ID_PATTERN)
    stage: int = Field(ge=1, le=3)
    title: str
    snapshot: SnapshotRef
    request: AnalysisRequest
    focus: str = ""  # 이 사례로 확인하려는 것(계산자에게는 힌트일 뿐 정답이 아님)


class ExpectedImpact(Frozen):
    entity_id: str
    impact_type: ImpactType
    rule_id: str = Field(pattern=r"^R-[A-Z]\d{2}$")

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.entity_id, self.impact_type.value, self.rule_id)


class ForbiddenImpact(Frozen):
    """특히 확인하려는 오탐. 적은 칸만 맞으면 오탐이다(영향 종류·규칙이 없으면 그 엔터티의 어떤 영향도)."""

    entity_id: str
    impact_type: ImpactType | None = None
    rule_id: str | None = Field(default=None, pattern=r"^R-[A-Z]\d{2}$")

    def hits(self, entity_id: str, impact_type: ImpactType, rule_id: str) -> bool:
        return (
            entity_id == self.entity_id and self.impact_type in (None, impact_type) and self.rule_id in (None, rule_id)
        )


class ExpectedUnresolved(Frozen):
    kind: UnresolvedKind
    entity_id: str | None = None


class ExpectedAmount(Frozen):
    """금액(원). 범위가 없으면 low·high를 비워 둔다(= 대표값)."""

    value_krw: int
    low_krw: int | None = None
    high_krw: int | None = None

    @property
    def low(self) -> int:
        return self.value_krw if self.low_krw is None else self.low_krw

    @property
    def high(self) -> int:
        return self.value_krw if self.high_krw is None else self.high_krw

    @property
    def key(self) -> tuple[int, int, int]:
        """(대표값, 최소, 최대): 범위를 생략한 표기와 같은 값을 적은 표기를 같은 금액으로 본다."""
        return (self.value_krw, self.low, self.high)

    @model_validator(mode="after")
    def _ordered(self) -> ExpectedAmount:
        if not self.low <= self.value_krw <= self.high:
            raise ValueError("금액 범위는 최소 ≤ 대표값 ≤ 최대 필요")
        return self


class ExpectedLine(Frozen):
    """2단계 비용 줄 하나(줄 ID는 docs/engine.md(비용·일정) 4절 형식, 새 부재 제작 공수 C-02·후행 설치 할증 C-03·
    1.32.0 도장 뒤 고정 항목 C-04, 작업반 몫 재작업 줄 'R-B01:rework:<블록>@<작업반>' 포함)."""

    line_id: str = Field(pattern=r"^(C-0[1-4]|R-[A-Z]\d{2}):[a-z_]+:\S+$")
    amount: ExpectedAmount
    determinacy: Determinacy = Determinacy.KNOWN
    formula: str = Field(min_length=1)  # 손 계산 산식(근거)


class ExpectedHold(Frozen):
    """발주 보류 권고(8-3). 피하는 손실 금액은 채점하지 않는다."""

    po_id: str
    max_hold_days: int = Field(ge=1)
    hold_until: date
    deadline_after: ZeroLossDeadline


class ExpectedOnboard(Frozen):
    """의장품 선상 설치 선택지(명세 6-8): now = 요청의 방식, then = 다른 방식. 금액은 then − now."""

    direction: OnboardDirection
    block_ids: tuple[str, ...] = Field(min_length=1)
    part_ids: tuple[str, ...] = Field(min_length=1)
    on_board_days: int = Field(ge=1)
    total_change: ExpectedAmount
    erection_delay_now_days: int = Field(ge=0)
    erection_delay_then_days: int = Field(ge=0)
    exit_delay_now_days: int = Field(ge=0)
    exit_delay_then_days: int = Field(ge=0)
    delivery_added_now_days: int | None = Field(default=None, ge=0)
    delivery_added_then_days: int | None = Field(default=None, ge=0)


class ExpectedTiming(Frozen):
    """일정 영향과 확정 시점(6·8절)."""

    zone_exit_delays: dict[str, int] = Field(default_factory=dict)  # 구역 ID → 출구 지연 일(0은 적지 않음)
    delivery_added_days: int | None = Field(default=None, ge=0)  # None = 인도 지연 계산 불가(이유 delivery)
    delivery_exposure: ExpectedAmount | None = None  # 허용 지연(선주 요청)의 노출 금액(4-6), 없으면 비움
    onboard: ExpectedOnboard | None = None  # 선상 설치 선택지(6-8), 없으면 비움
    delay_ripple: ExpectedAmount | None = None  # 1.32.0 지연 파급 비용(4-11, 총액 밖). 실제로 밀린 날이 없으면 비움
    deadline: ZeroLossDeadline
    deadline_total: ExpectedAmount  # 마감일 당일 확정 총액(기간 안 추가손실이 없으면 탐색 마지막 날)
    next_day_total: ExpectedAmount | None = None  # 마감일 다음 날 확정 총액(기간 안 추가손실이 없으면 비움)
    holds: tuple[ExpectedHold, ...] = ()  # 보류 권고의 전체 집합

    @model_validator(mode="after")
    def _consistent(self) -> ExpectedTiming:
        if any(days <= 0 for days in self.zone_exit_delays.values()):
            raise ValueError("구역 출구 지연은 0보다 큰 값만 기입")
        within = self.deadline.kind is not DeadlineKind.NONE_IN_HORIZON
        if within != (self.next_day_total is not None):
            raise ValueError("마감일 다음 날 총액은 기간 안에 추가손실이 생길 때만 기입")
        twice = [po for po, n in Counter(h.po_id for h in self.holds).items() if n > 1]
        if twice:
            raise ValueError(f"보류 권고 발주 중복: {twice[:3]}")
        return self


class ExpectedVerdict(Frozen):
    level: VerdictLevel
    reasons: tuple[str, ...] = Field(min_length=1)  # docs/engine.md(비용·일정) 8-4의 문장 그대로


# ---------- 3단계(대안 비교, docs/engine.md(대안)) ----------

ALT_ID_PATTERN = r"^ALT-(REQ|T[1-5])$"


class ExpectedEligibility(Frozen):
    status: Eligibility
    ratio_vs_request: FiniteFloat | None = None  # 판정 비율 ρ를 소수 셋째 자리로(설계자 확인이면 비움, NaN·무한대 거부)


class ExpectedBest(Frozen):
    """충족 대안의 최적 조합(확정일 × 보류 집합 중 대표값 총액 최소)."""

    confirm_on: date
    holds: tuple[HoldAction, ...] = ()  # 보류 행동(발주·일수)
    total: ExpectedAmount


class ExpectedAlternative(Frozen):
    alt_id: str = Field(pattern=ALT_ID_PATTERN)
    ops: tuple[ChangeOp, ...] = Field(min_length=1)  # 대안 연산(보강재 qty는 t 소수 셋째 자리)
    scope_reduced: bool = False
    eligibility: ExpectedEligibility
    total: ExpectedAmount  # 요청의 확정일에서의 총변경비용
    max_exit_delay_days: int = Field(ge=0)  # 같은 날의 구역 출구 지연 최댓값
    deadline: ZeroLossDeadline  # 이 대안(요청의 보류)의 추가손실 0 마감일
    best: ExpectedBest | None = None  # 충족 대안만
    rank: int | None = Field(default=None, ge=1)  # 충족 대안만
    formula: str = Field(min_length=1)  # 판정 비율·총액의 손 계산 근거

    @model_validator(mode="after")
    def _meets_only(self) -> ExpectedAlternative:
        meets = self.eligibility.status is Eligibility.MEETS
        if meets != (self.best is not None) or meets != (self.rank is not None):
            raise ValueError(f"{self.alt_id}: 최적 조합·순위는 충족 대안에만 기입")
        return self


class ExpectedRecommendation(Frozen):
    alt_id: str = Field(pattern=ALT_ID_PATTERN)
    confirm_on: date
    holds: tuple[HoldAction, ...] = ()
    total: ExpectedAmount


class ExpectedSpan(Frozen):
    """날짜별 가장 싼 대안 구간(요청의 보류만)."""

    alt_id: str = Field(pattern=ALT_ID_PATTERN)
    start: date
    end: date
    total: ExpectedAmount  # 시작일의 총변경비용


class OmissionReason(StrEnum):
    """이 요청에 해당하는 템플릿을 만들지 않은 이유(docs/engine.md(대안) 3·4절)."""

    NO_UPPER_GRADE = "no_upper_grade"  # 다음 강종이 없거나 그 강종의 단가가 없음(T2)
    NO_REFERENCE_STIFFENER = "no_reference_stiffener"  # 새 보강재 단면을 정할 기준 보강재가 없음(T1)
    MISSING_DATA = "missing_data"  # 판의 중량·스팬·간격·수두 같은 값이 없음
    INVALID_ON_MAP = "invalid_on_map"  # 대안 연산이 요청 검증을 통과하지 못함


class ExpectedOmission(Frozen):
    alt_id: str = Field(pattern=ALT_ID_PATTERN)
    reason: OmissionReason


def _holds_key(holds: tuple[HoldAction, ...]) -> tuple[tuple[str, int], ...]:
    """보류 행동 집합(적은 순서와 무관)."""
    return tuple(sorted((h.po_id, h.hold_days) for h in holds))


class ExpectedAlternatives(Frozen):
    """3단계 기대값. 대안 목록은 요청안을 포함한 전체 집합이다."""

    alternatives: tuple[ExpectedAlternative, ...] = Field(min_length=1)
    recommendation: ExpectedRecommendation
    cheapest_by_date: tuple[ExpectedSpan, ...] = Field(min_length=1)
    omitted: tuple[ExpectedOmission, ...] = ()  # 해당하지만 만들지 않은 템플릿의 전체 집합

    @model_validator(mode="after")
    def _consistent(self) -> ExpectedAlternatives:
        ids = [a.alt_id for a in self.alternatives]
        twice = [alt for alt, n in Counter(ids).items() if n > 1]
        if twice:
            raise ValueError(f"대안 ID 중복: {twice}")
        request = next((a for a in self.alternatives if a.alt_id == REQUEST_ALT), None)
        if request is None or request.eligibility.status is not Eligibility.MEETS:
            raise ValueError(f"대안 목록에 요청안({REQUEST_ALT}) 충족(비교 기준) 필요")
        both = sorted({o.alt_id for o in self.omitted} & set(ids))
        if both:
            raise ValueError(f"만들지 않은 대안이 목록에도 있음: {both}")
        ranked = sorted((a.rank, a.alt_id) for a in self.alternatives if a.rank is not None)
        if [rank for rank, _ in ranked] != list(range(1, len(ranked) + 1)):
            raise ValueError("순위는 충족 대안마다 1부터 빠짐없이 부여 필요")
        top = next(a for a in self.alternatives if a.rank == 1)
        rec = self.recommendation
        assert top.best is not None
        if (rec.alt_id, rec.confirm_on, _holds_key(rec.holds), rec.total.key) != (
            top.alt_id,
            top.best.confirm_on,
            _holds_key(top.best.holds),
            top.best.total.key,
        ):
            raise ValueError("권고는 1위 대안의 최적 조합(대안·확정일·보류·총액)과 일치 필요")
        meets = {a.alt_id for a in self.alternatives if a.eligibility.status is Eligibility.MEETS}
        spans = self.cheapest_by_date
        if any(s.alt_id not in meets or s.end < s.start for s in spans):
            raise ValueError("날짜별 구간은 충족 대안·시작일 ≤ 끝일 필요")
        for before, after in pairwise(spans):
            if after.start != before.end + timedelta(days=1) or after.alt_id == before.alt_id:
                raise ValueError("날짜별 구간은 빈틈없이 연속 · 이웃 구간은 서로 다른 대안 필요")
        return self


class CaseExpectation(Frozen):
    # 1단계(영향 탐색)
    impacts: tuple[ExpectedImpact, ...] = ()  # 빠짐없는 전체 정답 집합(1단계 사례는 비울 수 없음)
    forbidden_impacts: tuple[ForbiddenImpact, ...] = ()
    unresolved: tuple[ExpectedUnresolved, ...] = ()  # 계산 불가 이유(종류·엔터티)의 전체 집합(1·2단계)
    # 2단계(비용·일정·확정 시점·판정)
    cost_lines: tuple[ExpectedLine, ...] = ()  # 줄 ID 기준 전체 집합
    total: ExpectedAmount | None = None
    timing: ExpectedTiming | None = None
    verdict: ExpectedVerdict | None = None
    # 3단계(대안 비교)
    alternatives: ExpectedAlternatives | None = None

    @model_validator(mode="after")
    def _unique(self) -> CaseExpectation:
        twice = [key for key, n in Counter(i.key for i in self.impacts).items() if n > 1]
        if twice:
            raise ValueError(f"기대 영향 중복: {twice[:3]}")
        clash = [
            f.entity_id
            for f in self.forbidden_impacts
            if any(f.hits(i.entity_id, i.impact_type, i.rule_id) for i in self.impacts)
        ]
        if clash:
            raise ValueError(f"기대 영향과 금지 영향 중복: {clash[:3]}")
        lines = [line for line, n in Counter(c.line_id for c in self.cost_lines).items() if n > 1]
        if lines:
            raise ValueError(f"기대 비용 줄 ID 중복: {lines[:3]}")
        return self


class GateCase(GateCaseInput):
    expected: CaseExpectation
    computed_by: str  # 계산 주체(엔진 코드 미열람)
    computed_on: date
    checked_by: str | None = None  # 검토·승인한 사람(승인 전이면 None)
    notes: str = ""

    @model_validator(mode="after")
    def _stage_fields(self) -> GateCase:
        """단계마다 그 단계가 채점하는 기대값이 있어야 한다(3단계는 비용 줄 대신 대안별 총액·일정으로 채점)."""
        expected = self.expected
        if self.stage == 1 and not expected.impacts:
            raise ValueError("1단계 사례에 기대 영향 필요")
        if self.stage == 2 and (expected.total is None or expected.timing is None or expected.verdict is None):
            raise ValueError("2단계 사례에 총액·일정·판정 기대값 필요")
        if self.stage == 3 and expected.alternatives is None:
            raise ValueError("3단계 사례에 대안 기대값 필요")
        if self.stage == 3 and not self.request.include_alternatives:
            raise ValueError("3단계 사례의 요청은 대안 켜기 필요(include_alternatives)")
        return self
