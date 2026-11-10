"""분석 결과 계약.

모든 숫자는 엔진이 만든다. 금액 한 줄(CostLine)마다 규칙 ID·산식·입력값·원본 위치를
남긴다. 금액은 대표값과 파라미터 범위 양 끝으로 계산한 최소·최대를 함께 가진다.
계약 안의 검사(validator)는 결과가 스스로 모순되지 않게 막는다.

주제별 모듈(앞 모듈만 import한다):
- vocab: 어휘(영향 종류·계산 불가 종류·판정 단계 등 열거형 전부)
- amount: 금액(대표값·최소·최대)
- impact: 영향과 근거 경로·계산하지 못한 항목
- cost: 비용 줄과 그 가정값·확정이 늦어지면의 전망·블록 난이도 계수·구분(1.35.0 공수·재료비·공수 MH·구분별 합)
- delay: 지연 파급 비용(총액 밖, 1.32.0)
- schedule: 구역 출구·인도 지연·일정 위험·출구 여유
- onboard: 의장품 선상 설치 선택지
- precheck: 설계변경 사전 점검 항목(판정과 분리된 확인 항목)
- timing: 확정 시점(추가손실 곡선·마감일·보류 권고·잉여 자재 전용)
- alternatives: 대안 비교·날짜별 가장 싼 대안·권고
- verdict: 요약 판정
- report: 1단계 영향 탐색 결과
- basis: 판단이 걸린 상태·연결 추적
- weight: 블록별 강재 중량 변화(정보, 1.34.0)
- analysis: 2단계 분석 결과·불변 분석본
"""

from .alternatives import REQUEST_ALT, AlternativeResult, CheapestSpan, EligibilityCheck, Recommendation
from .amount import Amount
from .analysis import AnalysisRecord, AnalysisResult
from .basis import StateBasis, TraceChain, TraceLink
from .cost import HOURS_DIGITS, BlockDifficulty, CostFactor, CostLine, CostSplit, LineOutlook, WorkHours
from .delay import DelayRipple
from .impact import Hop, Impact, Unresolved
from .onboard import OnboardOption
from .precheck import (
    PRECHECK_RULE_NAMES,
    PRECHECK_TEXT_MAX,
    UNCHECKED_FINDING,
    PrecheckItem,
    PrecheckLevel,
    PrecheckLink,
    PrecheckRule,
    precheck_order,
)
from .report import ImpactReport
from .schedule import DeliveryImpact, ExitMargin, ScheduleImpact, ScheduleRisk, TransportLeg, ZoneExitDelay
from .timing import (
    CurvePoint,
    HoldAdvice,
    Reallocation,
    TimingResult,
    ZeroLossDeadline,
    additional_loss_of,
    expected_deadline,
)
from .verdict import Verdict
from .vocab import (
    COST_ITEM_KIND,
    PURCHASE_ITEMS,
    VERDICT_NAMES,
    AlternativeOrigin,
    BasisKind,
    CostItem,
    CostKind,
    DeadlineKind,
    Determinacy,
    Eligibility,
    ImpactType,
    OnboardDirection,
    OutlookKind,
    Severity,
    UnresolvedKind,
    VerdictLevel,
    WeightSource,
)
from .weight import WEIGHT_DIGITS, BlockWeight, PartWeight, WeightChange

__all__ = [
    "COST_ITEM_KIND",
    "HOURS_DIGITS",
    "PRECHECK_RULE_NAMES",
    "PRECHECK_TEXT_MAX",
    "PURCHASE_ITEMS",
    "REQUEST_ALT",
    "UNCHECKED_FINDING",
    "VERDICT_NAMES",
    "WEIGHT_DIGITS",
    "AlternativeOrigin",
    "AlternativeResult",
    "Amount",
    "AnalysisRecord",
    "AnalysisResult",
    "BasisKind",
    "BlockDifficulty",
    "BlockWeight",
    "CheapestSpan",
    "CostFactor",
    "CostItem",
    "CostKind",
    "CostLine",
    "CostSplit",
    "CurvePoint",
    "DeadlineKind",
    "DelayRipple",
    "DeliveryImpact",
    "Determinacy",
    "Eligibility",
    "EligibilityCheck",
    "ExitMargin",
    "HoldAdvice",
    "Hop",
    "Impact",
    "ImpactReport",
    "ImpactType",
    "LineOutlook",
    "OnboardDirection",
    "OnboardOption",
    "OutlookKind",
    "PartWeight",
    "PrecheckItem",
    "PrecheckLevel",
    "PrecheckLink",
    "PrecheckRule",
    "Reallocation",
    "Recommendation",
    "ScheduleImpact",
    "ScheduleRisk",
    "Severity",
    "StateBasis",
    "TimingResult",
    "TraceChain",
    "TraceLink",
    "TransportLeg",
    "Unresolved",
    "UnresolvedKind",
    "Verdict",
    "VerdictLevel",
    "WeightChange",
    "WeightSource",
    "WorkHours",
    "ZeroLossDeadline",
    "ZoneExitDelay",
    "additional_loss_of",
    "expected_deadline",
    "precheck_order",
]
