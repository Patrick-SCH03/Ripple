"""요약 판정(docs/engine.md(비용·일정) 8-4): 승인 가능 · 검토 필요 · 경고. 이유는 숫자 없는 고정 문장이다."""

from __future__ import annotations

from ripple.contracts.domain import BlockStage
from ripple.contracts.result import Amount, CostLine, ImpactType, Unresolved, Verdict, VerdictLevel

from .cost.amounts import Params
from .state import rank

THRESHOLD = "verdict.approve_max_total_krw"
LATE_STAGE = BlockStage.ASSEMBLY  # 대조립(판넬조립으로 당기면 변별력이 없어짐)

EXIT_DELAY = "구역 출구 일정 지연 가능"
ERECTION_DELAY = "블록 탑재 지연 가능"
DAMAGES = "인도 지연 · 지체상금 발생 가능"
PERMISSIBLE = "인도일 조정 선주 합의 필요"
LATE_REWORK = "대조립 이후 블록 재작업 필요"
PO_CHANGE = "발주된 자재 변경·취소 필요"
REWORK = "블록 재작업 발생"
ON_BOARD = "의장품 탑재 후 선상 설치"
OVER_LIMIT = "총변경비용 바로 승인 기준 초과"
RISK_EXIT = "자재 납기 지연 시 구역 출구 지연 가능"
UNKNOWN = "판단 불가 항목 확인 필요"
SMALL = "발주 변경·재작업 없는 도면·자재 수정 수준"
DESIGN_PENDING = "설계 승인 전 변경 · 승인 상태 확인 필요"


def verdict(
    lines: tuple[CostLine, ...],
    total: Amount,
    max_exit_delay: int,
    unresolved: tuple[Unresolved, ...],
    params: Params,
    erection_delayed: bool = False,
    design_pending: bool = False,
    risk_exit_delay: int = 0,
    permissible_delay: bool = False,
) -> Verdict:
    """design_pending(설계 검토 중·선주 승인 대기, 계약 1.23.0)이면 이유를 더하고 최소 '검토 필요'.
    risk_exit_delay = 같은 확정일의 일정 위험(6-6) 구역 출구 최대 지연: 대표가 0일인데 위험만 늦으면 검토 필요 이유
    (8-4 검토 필요 5, 판정이 위험 일정을 쓰는 유일한 곳).
    permissible_delay = 허용 지연(4-6, 선주 요청)이고 인도 지연이 늘었음: 지체상금 대신 인도일 조정 합의(경고 3)."""
    # 작업반 몫으로 나눈 줄도 같은 블록 재작업. 공수가 없는 줄(선행의장 전 의장품만 바뀜)은 재작업이 아니다
    rework = [line for line in lines if line.rule_id == "R-B01" and line.amount.high > 0]
    late_rework = any(_late(line) for line in rework)
    damages = any(line.rule_id == "R-L01" and line.amount.high > 0 for line in lines)
    po_change = any(line.line_id.split(":")[1] == ImpactType.PO_CHANGE.value for line in lines if ":" in line.line_id)
    warn_checks = (
        (EXIT_DELAY, max_exit_delay > 0),
        (DAMAGES, damages),
        (PERMISSIBLE, permissible_delay),
        (ERECTION_DELAY, erection_delayed),
        (LATE_REWORK, late_rework),
    )
    warn = [reason for reason, hit in warn_checks if hit]
    if warn:
        return Verdict(level=VerdictLevel.WARN, reasons=(*warn, *((DESIGN_PENDING,) if design_pending else ())))
    review = [
        reason
        for reason, hit in (
            (PO_CHANGE, po_change),
            (REWORK, bool(rework)),
            (ON_BOARD, any(line.rule_id == "C-03" for line in lines)),
            (OVER_LIMIT, total.high > params.value(THRESHOLD)),
            (RISK_EXIT, max_exit_delay == 0 and risk_exit_delay > 0),
            (UNKNOWN, bool(unresolved)),
            (DESIGN_PENDING, design_pending),
        )
        if hit
    ]
    if review:
        return Verdict(level=VerdictLevel.REVIEW, reasons=tuple(review))
    return Verdict(level=VerdictLevel.APPROVE, reasons=(SMALL,))


def _late(line: CostLine) -> bool:
    """대조립 이후 블록 재작업(경고 5): 선체 부재를 대조립 이후에 다시 하거나, 의장품만이어도 도장이 시작된 뒤 다시
    설치. 선행의장 중 의장품만 다시 다는 것은 블록 재작업 발생(검토 필요)에 둔다."""
    stage = rank(BlockStage(str(line.inputs.get("stage"))))
    hull = line.inputs.get("hull_weight_t")  # 나눔이 없는 줄(0.12.0 전·검사용)은 선체 재작업으로 본다
    has_hull = hull is None or (isinstance(hull, int | float) and hull > 0)
    return stage >= rank(LATE_STAGE) and (has_hull or stage >= rank(BlockStage.PRE_PAINTING))
