"""서명 전 확인할 것 후보: 판단이 기대고 있는 가정·추정 상태와, 그것이 틀리면 무엇이 달라지는지(why).

규칙 순서(같은 결과면 늘 같은 순서): 넣은 보류 → 선상 설치로 계산 → 새 자재 리드타임(일정 위험) → 선주와 인도일 조정 →
변경 원인 미입력(지체상금) → 사전 점검 '확인 필요' → 기록의 확인 목록(판단 불가·엑셀 경고) →
사전 점검 '주의'·'점검 불가' → 판단이 걸린 상태(근거 없음 → 계획 추정 → 오래됨).
computed = why의 숫자가 엔진이 그 가정을 바꿔 이미 계산해 둔 값(선상 설치 선택지·일정 위험·노출 금액)일 때만 참이다.
다시 계산하지 않으므로 그런 값이 없으면 숫자 없는 일반 문장(computed 거짓)이다. 사전 점검 항목은 기록 본문의 항목 글을
그대로 쓰고(합성 NCR 건수는 글에, '틀리면'은 숫자 없는 위험 이유) computed 거짓이다.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import date

from ripple.contracts.brief import BriefCheck
from ripple.contracts.ncr import SYNTHETIC_LABEL
from ripple.contracts.records import ChecklistItem
from ripple.contracts.result import (
    AnalysisResult,
    BasisKind,
    OnboardDirection,
    PrecheckItem,
    PrecheckLevel,
    StateBasis,
)
from ripple.contracts.workspace import STALE_DAYS
from ripple.explain.format import object_particle, topic_particle

from .facts import Facts, cause_unknown_with_penalty
from .text import PO_STATUS_NAMES, amount_text, clip, code_of, cost_change, delay_changes, risk_basis, ro

STATE_ROWS = 4  # 상태 후보는 이만큼까지(확인할 것은 최대 3개라 AI 후보도 짧게)
PRECHECK_ROWS = 4  # 사전 점검 후보도 수준 무리마다 이만큼까지
PRECHECK_RANK = {PrecheckLevel.CHECK: 0, PrecheckLevel.CAUTION: 1, PrecheckLevel.UNCHECKED: 2}
CHECKLIST_WHY = {
    "delivery": "인도 조건 입력 시 인도 지연·지체상금 추가 계산 가능",
    "po_state": "실제 발주 단계에 따라 범위 안에서 변경·취소 손실 변동",
    "block_stage": "실제 블록 단계에 따라 재작업 비용·일정 변동",
    "connection": "연결이 빠진 곳의 영향은 비용·일정에 미반영",
    "strength_inputs": "강도 판정 입력 없음 — 대안 비교 제외",
}
IMPORT_WHY = "가져온 엑셀 값이 틀리면 이 분석의 숫자도 변동"
BASIS_TEXT = {BasisKind.PLAN: "계획으로 추정", BasisKind.OFF_PLAN: "계획과 어긋나 추정"}


def _check(key: str, text: str, why: str, *, computed: bool = False, entity_id: str | None = None) -> BriefCheck:
    return BriefCheck(key=key, text=clip(text), why=clip(why), computed=computed, entity_id=entity_id)


def _holds(result: AnalysisResult) -> BriefCheck | None:
    holds = result.request.holds
    if not holds:
        return None
    if len(holds) == 1:
        text = f"{holds[0].po_id} 발주를 {holds[0].hold_days}일 보류로 계산"
    else:
        text = f"발주 {len(holds)}건({', '.join(h.po_id for h in holds)}) 보류 포함 계산"
    return _check(
        "assume:holds",
        f"{text} — 협력사의 그 기간 제작·납품 중단 가능 여부 확인",
        "보류 불가 시 결정 기한·총변경비용이 이 분석과 다름 — 보류를 뺀 분석과 비교",
        entity_id=holds[0].po_id,
    )


def _onboard(result: AnalysisResult) -> BriefCheck | None:
    option = result.onboard
    if not result.request.outfit_on_board or option is None or option.direction is not OnboardDirection.TO_WAIT:
        return None
    block = option.block_ids[0]
    delays = delay_changes(option)
    change = f"{' · '.join(delays)} · " if delays else "일정 그대로 · "
    return _check(
        "assume:onboard",
        f"{code_of(block)} 블록 의장품을 탑재 후 선상 설치로 계산 — 현장 가능 여부 확인",
        f"자재 대기 후 탑재 전 블록 설치 시 {change}{cost_change(option.total_change.value)}",
        computed=True,
        entity_id=block,
    )


def _lead_time(result: AnalysisResult) -> BriefCheck | None:
    schedule, risk = result.schedule, result.schedule.risk
    if risk is None:
        return None
    parts = []
    if risk.max_exit_delay_days > schedule.max_exit_delay_days:
        parts.append(f"구역 출구 지연 {schedule.max_exit_delay_days}일 → {risk.max_exit_delay_days}일")
    now, then = schedule.delivery, risk.delivery
    if now is not None and then is not None and then.added_delay_days > now.added_delay_days:
        parts.append(f"늘어난 인도 지연 {now.added_delay_days}일 → {then.added_delay_days}일")
    if not parts:
        return None
    basis = risk_basis(risk.ratios)
    where = f"리드타임 범위 끝({basis})" if basis else "리드타임 범위 끝"
    return _check(
        "assume:lead_time",
        "새 자재 리드타임 대표값으로 계산 — 협력사 납기 확인",
        f"{where} 적용 시 {' · '.join(parts)}",
        computed=True,
    )


def _owner_deal(result: AnalysisResult) -> BriefCheck | None:
    delivery = result.schedule.delivery
    if delivery is None or not delivery.permissible or delivery.exposure is None:
        return None
    return _check(
        "assume:owner_deal",
        f"선주 요청 변경 — 늘어난 인도 지연 {delivery.added_delay_days}일을 인도일 조정으로 계산 · 선주 합의 가능 "
        "여부 확인",
        f"합의 불가 시 지체상금 {amount_text(delivery.exposure)} 추가 가능",
        computed=True,
    )


def _cause(result: AnalysisResult) -> BriefCheck | None:
    if not cause_unknown_with_penalty(result):
        return None
    return _check(
        "assume:cause",
        "변경 원인 미입력 — 선주 요청 변경 여부 확인",
        "선주 요청이면 늘어난 인도 지연이 지체상금 대신 인도일 조정 대상 · 총변경비용 변동",
    )


def _prechecks(result: AnalysisResult, levels: Collection[PrecheckLevel]) -> list[BriefCheck]:
    """사전 점검 항목(판정과 분리된 확인 항목): 확인 필요 → 주의 → 점검 불가, 같은 수준이면 결과 순서."""
    items = sorted(
        (item for item in result.prechecks if item.level in levels), key=lambda item: PRECHECK_RANK[item.level]
    )
    return [_precheck(item) for item in items[:PRECHECK_ROWS]]


def _precheck(item: PrecheckItem) -> BriefCheck:
    """'사전 점검 관통부 누락 의심: <항목 글> · 같은 유형 합성 NCR n건(합성 묶음(시연))'
    건수는 기록 본문의 항목 값(0건이면 쓰지 않음)."""
    ncr = f" · 같은 유형 합성 NCR {item.ncr_count}건({SYNTHETIC_LABEL})" if item.ncr_count else ""
    return _check(
        f"precheck:{item.key}",
        f"사전 점검 {item.finding}: {item.text}{ncr}",
        item.reason,
        entity_id=item.targets[0] if item.targets else None,
    )


def _checklist(item: ChecklistItem) -> BriefCheck:
    kind = item.key.rsplit(":", 1)[-1]
    why = IMPORT_WHY if item.source == "import" else CHECKLIST_WHY.get(kind, "확인 결과에 따라 판단 변동 가능")
    return _check(f"checklist:{item.key}", item.text, why)


def _need(row: StateBasis, today: date) -> int | None:
    """확인이 필요한 정도(작을수록 급함): 근거 없음 0 · 계획 추정 1 · 일주일 넘게 확인 안 함 2. 괜찮으면 None."""
    if row.basis is BasisKind.UNKNOWN:
        return 0
    fresh = row.last_confirmed is not None and (today - row.last_confirmed).days <= STALE_DAYS
    if row.basis in (BasisKind.PLAN, BasisKind.OFF_PLAN):
        return None if row.entity_type == "activity" and fresh else 1
    if row.entity_type == "activity" and row.actual_finish is not None:
        return None  # 끝난 공정은 다시 바뀌지 않는다(확인이 오래돼도 판단이 기대지 않음)
    return None if fresh else 2


ASK_NOW = "현장 확인"
ASK_STILL = "지금도 맞는지 확인"
STALE = "마지막 확인 후 일주일 넘게 지남"


def _state_text(row: StateBasis, need: int) -> str:
    """'PO-0130 발주 단계를 '자재 확보'로 보고 계산(계획으로 추정) — 현장 확인'."""
    basis = BASIS_TEXT.get(row.basis, "추정")
    if row.entity_type == "po":
        if row.po_status is None:
            return f"{row.label} 단계 미상 — 가능한 범위 전체로 계산 · {ASK_NOW}"
        status = PO_STATUS_NAMES.get(row.po_status.value, row.po_status.value)
        if need == 2:
            return f"{row.label} 단계 '{status}'{topic_particle(status)} {STALE} — {ASK_STILL}"
        return f"{row.label} 단계를 '{status}'{ro(status)} 보고 계산({basis}) — {ASK_NOW}"
    state = "완료" if row.actual_finish else ("진행 중" if row.actual_start else "착수 전")
    if need == 0:
        return f"{row.label} 상태 미상 — {ASK_NOW}"
    subject = f"{row.label}{object_particle(row.label)} '{state}'{ro(state)}"
    if need == 2:
        return f"{subject} 본 확인 후 일주일 넘게 지남 — {ASK_STILL}"
    return f"{subject} 보고 계산({basis}) — {ASK_NOW}"


def _state_why(row: StateBasis, need: int) -> str:
    if row.entity_type == "activity":
        return "실제 착수·완료가 다르면 재작업 비용·일정 변동"
    if need == 0:
        return "단계 미상 — 비용을 가능한 범위 전체로 계산 · 확인 시 범위 축소"
    if row.hold:
        return "보류 권고가 이 단계 기준 — 이미 더 진행됐으면 보류 불가 또는 손실 증가"
    if row.line_ids:
        return "실제 단계가 다르면 이 발주의 변경·취소 손실·결정 기한 변동"
    return "실제 단계가 다르면 비용·결정 기한 변동 가능"


def _states(result: AnalysisResult, today: date) -> list[BriefCheck]:
    covered = {u.entity_id for u in result.unresolved if u.entity_id}  # 판단 불가로 이미 확인 목록에 있는 것
    rows: list[tuple[tuple[int, int, int, int, str], StateBasis, int]] = []
    for row in result.state_basis:
        need = _need(row, today)
        if need is None or row.entity_id in covered:
            continue
        po = 0 if row.entity_type == "po" else 1  # 같은 급함이면 발주(취소·변경 손실이 걸림)가 공정보다 먼저
        rank = (0 if row.hold else 1, need, po, 0 if row.line_ids else 1, row.entity_id)
        rows.append((rank, row, need))
    rows.sort(key=lambda item: item[0])
    return [
        _check(f"state:{row.entity_id}", _state_text(row, need), _state_why(row, need), entity_id=row.entity_id)
        for _, row, need in rows[:STATE_ROWS]
    ]


def check_options(facts: Facts) -> list[BriefCheck]:
    """후보 전부(규칙 순서, 키 고유)."""
    result = facts.result
    found = [
        check
        for check in (_holds(result), _onboard(result), _lead_time(result), _owner_deal(result), _cause(result))
        if check is not None
    ]
    found += _prechecks(result, (PrecheckLevel.CHECK,))
    found += [_checklist(item) for item in facts.body.checklist]
    found += _prechecks(result, (PrecheckLevel.CAUTION, PrecheckLevel.UNCHECKED))
    found += _states(result, facts.today)
    seen: set[str] = set()
    unique = []
    for check in found:
        if check.key not in seen:
            seen.add(check.key)
            unique.append(check)
    return unique
