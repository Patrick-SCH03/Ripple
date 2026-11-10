"""분석 결과 → 엑셀(실무자가 엑셀로 다시 보고 거르는 용도, docs/records.md(기록·결재) 내보내기).

시트: 요약 · 영향 목록 · 비용 근거 · 가정값 · 확정 시점 곡선 · 중량 변화(1.34.0) · 대안 비교(대안 포함 분석이 있을
때만).
숫자는 분석 결과 필드 그대로 쓴다(금액은 원, 날짜는 날짜 칸). 새로 계산하지 않는다 — 결정 기한까지 남은 날(D-n)만 화면과
같이 기준일부터 센다.
"""

from __future__ import annotations

from openpyxl import Workbook

from ripple.contracts.domain import DataMode
from ripple.contracts.result import AnalysisResult

from .out_analysis_sheets import alternatives_sheet, cost_sheet, curve_sheet, factor_sheet, impact_sheet
from .out_labels import CAUSE, DATA_MODE, DEADLINE_KIND, DESIGN_STATUS, MATERIAL, TRANSPORT, VERDICT, name
from .out_table import DAY, DECIMAL, MONEY, Item, items, save, sheet
from .out_weight import weight_items, weight_sheet

__all__ = ["analysis_workbook", "summary_items"]

DELAY_RIPPLE_CONTRACT = "1.32.0"
"""지연 파급 비용을 계산하는 계약 판(화면 lib/delayRipple.ts와 같음). 이보다 앞 판의 기록은 그 줄을 쓰지 않는다."""


def _won(value: int) -> str:
    return f"{value:,}원"


def _head(result: AnalysisResult) -> list[Item]:
    request, change = result.request, result.request.change
    blank = " — 미입력 시 기준일로 계산" if request.confirm_on is None else ""
    rows = [
        Item("설계변경", change.ecn_id or "(번호 없음)"),
        Item("제목", change.title),
        Item("호선", ", ".join(change.ship_ids)),
        Item("기준일", request.as_of, DAY, "지금 알고 있는 발주·공정 상태의 날짜(추가손실·D-n의 기준)"),
        Item("확정일", request.effective_confirm_on, DAY, f"이날의 발주·블록 단계로 계산{blank}"),
        Item("변경 원인", name(CAUSE, change.cause) if change.cause else "미입력"),
        Item("설계 승인", name(DESIGN_STATUS, change.design_status)),
        Item("판정", name(VERDICT, result.verdict.level)),
    ]
    rows += [Item("판정 이유", reason) for reason in result.verdict.reasons]
    rows += _split(result)
    total = result.total
    rows += [
        Item(
            "총변경비용(대표, 원)", total.value, MONEY, "= 공수 금액 + 재료비(+ 지체상금)" if result.cost_split else ""
        ),
        Item("총변경비용(최소, 원)", total.low, MONEY, "가정값을 낮게 잡았을 때"),
        Item("총변경비용(최대, 원)", total.high, MONEY, "가정값을 높게 잡았을 때"),
    ]
    return rows


def _hours(value: float) -> str:
    return f"{value:,.1f}"


def _split(result: AnalysisResult) -> list[Item]:
    """1.35.0 구분별 합(화면 판단 요약 첫 줄과 같은 값): 추가 공수 MH · 공수 금액 · 재료비(그중 구매) ·
    지체상금(있을 때). 구분이 없는 옛 결과는 줄을 쓰지 않는다."""
    split = result.cost_split
    if split is None:
        return []
    hours, labor, material, purchase = split.labor_hours, split.labor, split.material, split.purchase
    rows = [
        Item("추가 공수(대표, MH)", hours.value, DECIMAL, f"범위 {_hours(hours.low)}~{_hours(hours.high)} MH"),
        Item("공수 금액(대표, 원)", labor.value, MONEY, f"범위 {_won(labor.low)}~{_won(labor.high)}"),
        Item(
            "추가 재료비(대표, 원)",
            material.value,
            MONEY,
            f"자재 차이 {_won(split.material_diff.value)} · 구매 {_won(purchase.value)} · "
            f"범위 {_won(material.low)}~{_won(material.high)}",
        ),
        Item(
            "그중 구매(대표, 원)",
            purchase.value,
            MONEY,
            "발주 변경·취소 · 새 규격 발주 할증 · 잉여 자재 전용 취급비",
        ),
    ]
    if split.damages.high != 0:
        rows.append(Item("지체상금(대표, 원)", split.damages.value, MONEY, "총변경비용 안 · 공수·재료비 밖"))
    return rows


def _deadline(result: AnalysisResult) -> list[Item]:
    deadline, curve = result.timing.deadline, result.timing.curve
    rows = [Item("결정 기한", deadline.last_day, DAY, name(DEADLINE_KIND, deadline.kind))]
    if deadline.kind.value != "none_in_horizon":
        rows.append(
            Item("결정 기한까지 남은 날(D-n)", (deadline.last_day - result.request.as_of).days, None, "기준일부터")
        )
    after = next((p for p in curve if p.confirm_on > deadline.last_day), None)
    if after is not None and deadline.kind.value != "none_in_horizon":
        loss = after.additional_loss
        note = f"{after.confirm_on.isoformat()} 확정 시 · 범위 {_won(loss.low)}~{_won(loss.high)}"
        rows.append(Item("결정 기한 다음 날 추가손실(대표, 원)", loss.value, MONEY, note))
    return rows


def _schedule(result: AnalysisResult) -> list[Item]:
    schedule = result.schedule
    worst = next((e for e in schedule.zone_exits if e.delay_days == schedule.max_exit_delay_days), None)
    where = (
        f"{worst.zone_name or worst.zone_id} 출구 {worst.base_date.isoformat()} → {worst.new_date.isoformat()}"
        if worst and schedule.max_exit_delay_days > 0
        else "대표 일정으로는 지연 없음"
    )
    rows = [Item("구역 출구 예상 최대 지연(일)", schedule.max_exit_delay_days, None, where)]
    risk = schedule.risk
    if risk is not None and risk.max_exit_delay_days > schedule.max_exit_delay_days:
        # 화면 구역 출구 카드(web lib/summary.ts exitRiskText)와 같은 근거: 늦춘 분류·배율 + 외자재 운송 일수
        basis = [f"{name(MATERIAL, key)} × {value:g}" for key, value in sorted(risk.ratios.items())]
        basis += [
            f"운송 {name(TRANSPORT, leg.mode)} {leg.days}일 포함{'(방식 없음 → 선박 가정)' if leg.assumed else ''}"
            for leg in risk.transport
        ]
        note = f"리드타임 범위 끝({' · '.join(basis)})" if basis else "리드타임 범위 끝"
        rows.append(Item("자재가 늦게 오면 최대 지연(일)", risk.max_exit_delay_days, None, note))
    delivery = schedule.delivery
    if delivery is None:
        rows.append(Item("늘어난 예상 인도 지연(일)", "계산 불가", None, "아래 '계산 불가 항목'"))
    elif delivery.added_delay_days > 0:
        note = "선주 요청 · 인도일 조정 대상(지체상금 제외)" if delivery.permissible else ""
        if delivery.exposure is not None:
            note += f" · 합의 불발 시 지체상금 {_won(delivery.exposure.value)}"
        rows.append(Item("늘어난 예상 인도 지연(일)", delivery.added_delay_days, None, note.strip(" ·")))
    rows += _delay_ripple(result)
    rows += weight_items(result)
    return rows


def _contract_at_least(version: str, least: str) -> bool:
    def parts(text: str) -> tuple[int, ...]:
        return tuple(int(p) if p.isdigit() else 0 for p in text.split("."))

    return parts(version) >= parts(least)


def _delay_ripple(result: AnalysisResult) -> list[Item]:
    """지연 파급 비용(1.32.0, 총액 밖·가정): 화면 비용 탭의 '총액 밖' 줄과 같은 값.

    0원이면 이유를 적고, 이 판을 계산하지 않은 옛 결과면 줄을 쓰지 않는다."""
    label = "지연 파급 비용(가정, 총액 밖, 원)"
    ripple = result.delay_ripple
    if ripple is None:
        if not _contract_at_least(result.versions.contract, DELAY_RIPPLE_CONTRACT):
            return []
        reason = (
            "지연일이 모두 인도 지연이라 지체상금에 포함되어 0원"
            if result.schedule.max_exit_delay_days > 0
            else "구역 출구 지연 없음 · 0원"
        )
        return [Item(label, 0, MONEY, reason)]
    daily = next((f for f in ripple.factors if f.unit == "원/일"), None)
    per_day = f" × 하루 비용 {_won(round(daily.value))}(가정)" if daily else ""
    overlap = f" · 인도 지연과 겹친 {ripple.delivery_overlap_days}일은 제외" if ripple.delivery_overlap_days else ""
    note = (
        f"지연 일수 {ripple.days}일{per_day}{overlap} · 범위 {_won(ripple.amount.low)}~{_won(ripple.amount.high)}"
        " · 총변경비용에 더하지 않고 판정·결정 기한·대안 비교에 쓰지 않음"
    )
    return [Item(label, ripple.amount.value, MONEY, note)]


def _assumptions(result: AnalysisResult) -> list[Item]:
    request = result.request
    rows = [Item("가정 계산: 발주 보류", f"{h.po_id} {h.hold_days}일") for h in request.holds]
    if request.outfit_on_board:
        rows.append(Item("가정 계산: 실행 방식", "후행 설치(탑재 뒤 선상에서 설치)"))
    # 보류 권고의 결재 기간 문구는 분석 응답의 결재 계획 값 그대로(규칙은 서버 ripple/records/approval.py 한 곳)
    plan = result.approval_plan
    windows = {hold.po_id: hold.text for hold in plan.holds} if plan is not None else {}
    for advice in result.timing.holds:
        text = f"{advice.po_id} 최대 {advice.max_hold_days}일({advice.hold_until.isoformat()}까지)"
        parts = (windows.get(advice.po_id), f"피하는 손실 {_won(advice.avoided.value)}", advice.reason)
        rows.append(Item("보류 권고", text, None, " · ".join(part for part in parts if part)))
    rows += [Item("가정·한계", note) for note in result.notes]
    rows += [Item("계산 불가 항목", u.reason, None, u.entity_id or "") for u in result.unresolved]
    return rows


def summary_items(result: AnalysisResult, *, exported_at: str, data_mode: DataMode | None = None) -> list[Item]:
    """요약 시트의 줄: 설계변경 → 판정 → 금액 → 결정 기한 → 일정 → 가정 → 추적 정보.

    data_mode = 내보낸 작업 공간의 유효 데이터 모드(설정·지도 중 하나라도 real이면 real — 기록·결재 대장·리포트와 같은
    표기). 없으면 분석 결과의 지도 모드(점검 D-7: 실데이터 모드에서 기본 합성 지도를 분석해도 '실제 데이터')."""
    v = result.versions
    mode = data_mode or result.data_mode
    synthetic = mode is DataMode.SYNTHETIC
    trace = [
        Item("데이터", name(DATA_MODE, mode), None, "합성 데이터로 만든 분석" if synthetic else ""),
        Item("분석 ID", result.analysis_id, None, "같은 ID면 같은 결과(화면·기록과 대조)"),
        Item("계산 판", f"계약 {v.contract} · 규칙 {v.rules} · 파라미터 {v.params} · 엔진 {v.engine}"),
        Item("내보낸 시각", exported_at),
    ]
    return [*_head(result), *_deadline(result), *_schedule(result), *_assumptions(result), *trace]


def analysis_workbook(
    result: AnalysisResult,
    *,
    alternatives: AnalysisResult | None,
    exported_at: str,
    data_mode: DataMode | None = None,
) -> bytes:
    """분석 결과 하나를 통합 문서로. alternatives = 같은 요청을 대안 포함으로 계산한 결과(대안 탭과 같음),
    data_mode = 내보낸 작업 공간의 유효 데이터 모드(summary_items)."""
    workbook = Workbook()
    items(sheet(workbook, "요약", first=True), summary_items(result, exported_at=exported_at, data_mode=data_mode))
    impact_sheet(sheet(workbook, "영향 목록"), result)
    cost_sheet(sheet(workbook, "비용 근거"), result)
    factor_sheet(sheet(workbook, "가정값"), result)
    curve_sheet(sheet(workbook, "확정 시점 곡선"), result)
    if result.weight_change is not None:
        weight_sheet(sheet(workbook, "중량 변화"), result.weight_change)
    if alternatives is not None and alternatives.alternatives:
        alternatives_sheet(sheet(workbook, "대안 비교"), alternatives, known_notes=result.notes)
    return save(workbook)
