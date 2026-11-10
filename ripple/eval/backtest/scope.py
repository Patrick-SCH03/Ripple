"""사례의 영향 범위 → 지도에 넣을 수와 방식(docs/backtest.md 3절), 그리고 가정 목록.

빈 칸은 기본값(defaults.yaml)으로 채우고 '가정'(빈 칸을 채움)으로, 지도로 나타낼 수 없어 바꾼 값은 '변환 메모'로 남긴다.
계산에 쓰이지 않는 빈 칸(스풀이 없을 때의 재제작 방식, 실제 지연이 없을 때의 지연 기준)은 가정으로 세지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ripple.contracts.change import ChangeCause

from .case import BLOCK_TYPES, DELAY_BASES, SPOOL_METHODS, Case
from .defaults import BacktestDefaults, BlockType, DelayBasis, Performer, SpoolMethod


class BuildError(ValueError):
    """사례를 지도로 바꿀 수 없음(사람이 읽는 이유)."""


@dataclass(frozen=True, slots=True)
class Assumption:
    item: str  # 항목(양식 열 이름 또는 지도 값)
    value: str  # 쓴 값
    reason: str
    blank: bool  # 빈 칸을 기본값으로 채웠나(요약의 '가정으로 채운 칸 수'). False = 변환 메모


@dataclass(frozen=True, slots=True)
class Scope:
    members: int  # 바뀐 부재(치수 변경 대상)
    spools: int  # 재제작 스풀
    spool_method: SpoolMethod  # 사내 재제작·사외 재발주 = 경로 변경, 치수 변경 = 같은 자재 다시 가공
    spool_lead_days: int | None  # 새 스풀 규격의 표준 리드타임(None = 엔진 파라미터 lead_time_days.pipe)
    drawings: int  # 개정 도면(바뀌는 부재·스풀이 나눠 그려짐)
    spool_lines: int  # 스풀을 나눠 담은 발주 품목 수(품목마다 발주 하나)
    force_order: bool  # 발주 변경이 있었으니 확정일에 스풀 발주가 '발주' 이상이어야 함
    weight_t: float
    block_type: BlockType | None  # 블록 형상(재작업 난이도 계수). None = 형상 없음(계수 1)
    delay_basis: DelayBasis  # 실제 지연과 견줄 예측(탑재·구역 출구·인도)
    performer: Performer | None  # 공정 수행 주체(직영·사내 협력사 작업반). None = 모름
    cause: ChangeCause | None


LABEL_OF_TYPE = {value: label for label, value in BLOCK_TYPES.items()}
LABEL_OF_METHOD = {value: label for label, value in SPOOL_METHODS.items()}
LABEL_OF_BASIS = {value: label for label, value in DELAY_BASES.items()}


def resolve_scope(case: Case, defaults: BacktestDefaults) -> tuple[Scope, list[Assumption]]:
    notes: list[Assumption] = []
    members, spools = _counts(case, defaults, notes)
    method = _spool_method(case, spools, defaults, notes)
    lines, force = _spool_lines(case, spools, method, defaults, notes)
    scope = Scope(
        members=members,
        spools=spools,
        spool_method=method,
        spool_lead_days=defaults.spool.in_house_lead_days if method == "in_house" else None,
        drawings=_drawings(case, members, spools, notes),
        spool_lines=lines,
        force_order=force,
        weight_t=_weight(case, defaults, notes),
        block_type=case.block_type,
        delay_basis=_delay_basis(case, defaults, notes),
        performer=case.performer,
        cause=case.cause,
    )
    if case.block_type is None:
        notes.append(Assumption("블록 종류", "미입력", "비어 있어 형상 난이도 계수 1(평블록과 같음)", True))
    if case.cause is None:
        notes.append(Assumption("변경 원인", "미입력", "비어 있어 선주 요청이 아닌 변경으로 계산(지체상금 계산)", True))
    return scope, notes


def _counts(case: Case, defaults: BacktestDefaults, notes: list[Assumption]) -> tuple[int, int]:
    members, spools = case.members, case.spools
    if members is None and spools is None:
        count = defaults.member.count
        notes.append(Assumption("바뀐 부재 수", str(count), "바뀐 부재 수·재제작 스풀 수가 모두 비어 기본값", True))
        notes.append(Assumption("재제작 스풀 수", "0", "비어 있어 0", True))
        return count, 0
    if members is None:
        notes.append(Assumption("바뀐 부재 수", "0", "비어 있어 0(재제작 스풀만 있는 변경)", True))
        members = 0
    if spools is None:
        notes.append(Assumption("재제작 스풀 수", "0", "비어 있어 0", True))
        spools = 0
    if members == 0 and spools == 0:
        raise BuildError("바뀐 부재·재제작 스풀 모두 0 · 계산할 변경 없음")
    return members, spools


def _spool_method(case: Case, spools: int, defaults: BacktestDefaults, notes: list[Assumption]) -> SpoolMethod:
    if case.spool_method is not None or spools == 0:
        return case.spool_method or defaults.spool.method
    method = defaults.spool.method
    lead = f", 새 스풀 리드타임 {defaults.spool.in_house_lead_days}일" if method == "in_house" else ""
    notes.append(Assumption("재제작 방식", LABEL_OF_METHOD[method], f"비어 있어 기본값{lead}", True))
    return method


def _drawings(case: Case, members: int, spools: int, notes: list[Assumption]) -> int:
    """도면 d장: 바뀌는 부재·스풀을 차례로 나눠 그린다(도면마다 하나 이상). 엔진은 그려진 도면마다 개정 하나를 낸다."""
    targets = members + spools
    if case.drawings is None:
        count = (1 if members else 0) + (1 if spools else 0)
        notes.append(Assumption("개정 도면 수", str(count), "비어 있어 부재 도면 1장·스풀 도면 1장으로", True))
        return count
    if case.drawings == 0:
        reason = "엔진은 바뀌는 부재가 그려진 도면을 늘 개정해 0건은 나타낼 수 없어 1장"
        notes.append(Assumption("개정 도면 수", "1", reason, False))
        return 1
    if case.drawings > targets:
        reason = f"바뀌는 부재·스풀({targets}개)보다 많은 {case.drawings}장은 지도에 미반영"
        reason += "(도면마다 부재 하나 이상)"
        notes.append(Assumption("개정 도면 수", str(targets), reason, False))
        return targets
    return case.drawings


def _spool_lines(
    case: Case, spools: int, method: SpoolMethod, defaults: BacktestDefaults, notes: list[Assumption]
) -> tuple[int, bool]:
    """발주 변경 p건 → 재제작 스풀을 나눠 담는 발주 품목 수(옛 스풀을 빼면 품목마다 발주 변경 하나, R-M02)."""
    wanted = case.po_changes
    if spools == 0:
        if wanted:
            reason = f"재제작 스풀 없음 · 발주 변경 {wanted}건 지도에 미반영"
            reason += "(바뀐 부재는 치수 변경이라 발주 유지)"
            notes.append(Assumption("발주 변경 건수", "0", reason, False))
        return 0, False
    if method == "dimension":
        if wanted:
            reason = "재제작 방식이 치수 변경(같은 자재 다시 가공) · 발주 변경 미반영"
            notes.append(Assumption("발주 변경 건수", "0", reason, False))
        return 1, False
    if wanted is None:
        lines = min(defaults.spool.po_lines, spools)
        notes.append(
            Assumption("발주 변경 건수", str(lines), "비어 있어 스풀 발주 품목 기본값(발주 단계는 계획대로)", True)
        )
        return lines, False
    if wanted == 0:
        reason = "스풀 발주 품목 1개는 계획대로 유지(확정일에 '발주' 이상이면 엔진이 발주 변경 산출)"
        notes.append(Assumption("발주 변경 건수", "0", reason, False))
        return 1, False
    if wanted > spools:
        reason = f"재제작 스풀({spools}개)보다 많은 {wanted}건은 지도에 미반영(스풀마다 발주 품목 하나까지)"
        notes.append(Assumption("발주 변경 건수", str(spools), reason, False))
    return min(wanted, spools), True


def _weight(case: Case, defaults: BacktestDefaults, notes: list[Assumption]) -> float:
    if case.block_weight_t is not None:
        return case.block_weight_t
    weight = defaults.block_weight_t.of(case.block_type)
    basis = f"블록 종류 '{LABEL_OF_TYPE[case.block_type]}'" if case.block_type else "블록 종류도 비어 공통"
    notes.append(Assumption("블록 무게(t)", f"{weight:g}", f"비어 있어 {basis} 기본값", True))
    return weight


def _delay_basis(case: Case, defaults: BacktestDefaults, notes: list[Assumption]) -> DelayBasis:
    if case.delay_basis is not None or case.delay_days is None:
        return case.delay_basis or defaults.delay_basis
    basis = defaults.delay_basis
    notes.append(Assumption("지연 기준", LABEL_OF_BASIS[basis], "비어 있어 기본값으로 실제 지연과 비교", True))
    return basis
