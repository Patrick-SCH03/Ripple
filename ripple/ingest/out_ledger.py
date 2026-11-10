"""결재·현황 → 엑셀(팀장, docs/records.md(기록·결재) 11절): 결재 대장 · 현황 · 상태별 · 블록별.

결재 대장은 결재함(검토·보류 중 개정, 결정 기한 급한 순 — 서버 순서 그대로)의 한 줄이 한 줄이고, 팀장이면 그 아래에
전결 묶음(파트장·본부장 단계에서 기다리는 건)을 '전결 가능'으로 잇는다. 줄마다 결재선(14절): 지금 단계 · 결재선 ·
승인한 단계(전결 표시) · 단계 대기 시간 · 남은 결재 계획(결재 올릴 기한·단계당 1일 기한·지남·결정은 빨라야 — 지남은
화면처럼 '대표만 지남(단계당 1일로는 가능)'과 '단계당 1일로도 지남'을 가름). 숫자는 ManageOverview 필드 그대로(금액은
원). 계산하지 않는다.
"""

from __future__ import annotations

from datetime import timedelta, timezone

from openpyxl import Workbook

from ripple.contracts.approval import ApprovalPlan
from ripple.contracts.manage import URGENT_DAYS, InboxItem, ManageOverview
from ripple.contracts.records import Actor, StepSign

from .out_labels import DATA_MODE, DEADLINE_KIND, ROLE, STATE, STEP, VERDICT, name
from .out_table import DAY, MONEY, Cell, Column, Item, items, save, sheet, table

__all__ = ["late_text", "ledger_workbook"]

KST = timezone(timedelta(hours=9))  # 서머타임 없음
HOURS = "#,##0.0"  # 기다린 시간: 값은 그대로 두고 소수 한 자리로만 보인다


def _who(actor: Actor) -> str:
    return f"{actor.name}({name(ROLE, actor.role)})"


def _block(block_id: str) -> str:
    return block_id[block_id.rfind(":") + 1 :]


MINE, PROXY = "내 결재", "전결 가능"
"""결재 대장의 '결재함' 칸: 보는 사람의 결재 단계 건 · 팀장의 전결 묶음(파트장·본부장 단계 건)."""


def _signed(signs: tuple[StepSign, ...]) -> str | None:
    """앞 단계 승인: '파트장 이파트장 · 팀장 박팀장(전결)'(없으면 빈칸)."""
    return " · ".join(f"{name(STEP, s.step)} {s.actor.name}{'(전결)' if s.proxy else ''}" for s in signs) or None


def _line(item: InboxItem) -> str:
    return f"{' → '.join(name(STEP, s) for s in item.steps)}({len(item.steps)}단계)"


LATE, LATE_FAST = "지남", "지남(단계당 1일로는 가능)"
"""'결재 기한 지남' 칸: 단계당 1일로도 지남(화면 위험 색) · 대표(단계당 2일) 기한만 지남(화면 주의 색 — 단계당 1일로
결재되면 아직 결정 기한 안). 단계당 1일 기한이 없는 옛 계획이면 '지남'만."""


def late_text(plan: ApprovalPlan) -> str | None:
    """결재 기한 지남 칸(화면 lib/approval submitLine의 주의·위험과 같은 뜻): 지나지 않았으면 빈칸."""
    if not plan.late:
        return None
    return LATE_FAST if plan.submit_by_low is not None and not plan.late_low else LATE


def _plan(item: InboxItem) -> list[Cell]:
    """남은 결재 계획(서버 결재 계획 그대로): 결재 올릴 기한 · 단계당 1일 기한 · 지남 · 기한 경과 시 결정 가능일."""
    plan = item.approval_plan
    if plan is None:
        return [None, None, None, None]
    return [plan.submit_by, plan.submit_by_low, late_text(plan), plan.earliest]


def _row(item: InboxItem, box: str) -> list[Cell]:
    return [
        item.ecn_id,
        item.title,
        item.revision,
        name(STATE, item.state),
        box,
        f"{name(STEP, item.step)}({item.steps.index(item.step) + 1}/{len(item.steps)}단계)",
        _line(item),
        _signed(item.signed),
        item.step_waiting_hours,
        *_plan(item),
        name(VERDICT, item.verdict),
        _who(item.requested_by),
        item.requested_at.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
        item.waiting_hours,
        item.deadline,
        name(DEADLINE_KIND, item.deadline_kind),
        item.days_left if item.deadline_kind.value != "none_in_horizon" else None,
        item.total.value,
        item.total.low,
        item.total.high,
        item.delay_from,
        item.delay_cost,
        item.cheaper_by,
        item.checklist or None,
        ", ".join(_block(b) for b in item.blocks) or None,
        name(DATA_MODE, item.data_mode),
        item.as_of,
        item.confirm_on,
    ]


LEDGER_COLUMNS = [
    Column("설계변경", 14),
    Column("제목", 40),
    Column("개정", 6),
    Column("상태", 8),
    Column("결재함", 10),
    Column("지금 단계", 14),
    Column("결재선", 26),
    Column("승인한 단계(전결 표시)", 30),
    Column("단계 대기(시간)", 12, HOURS),
    Column("남은 결재 올릴 기한", 14, DAY),
    Column("결재 올릴 기한(단계당 1일)", 16, DAY),
    Column("결재 기한 지남", 22),
    Column("기한 경과 시 결정 가능일", 14, DAY),
    Column("판정", 10),
    Column("요청자", 14),
    Column("요청 시각(KST)", 17),
    Column("대기 시간(시간)", 12, HOURS),
    Column("결정 기한", 14, DAY),
    Column("결정 기한 구분", 30),
    Column("남은 날(D-n, 음수 = 지남)", 14),
    Column("총변경비용 대표(원)", 18, MONEY),
    Column("최소(원)", 14, MONEY),
    Column("최대(원)", 14, MONEY),
    Column("미룰 때 손실 증가 시작일", 14, DAY),
    Column("해당일 증가 금액(원)", 18, MONEY),
    Column("더 저렴한 대안 차액(원)", 16, MONEY),
    Column("확인 필요(개)", 10),
    Column("블록", 16),
    Column("데이터", 10),
    Column("분석 기준일", 12, DAY),
    Column("확정일", 12, DAY),
]


def _status_items(overview: ManageOverview, exported_at: str) -> list[Item]:
    kpis = overview.kpis
    period = "전체 기간" if overview.performance.days is None else f"최근 {overview.performance.days}일"
    return [
        Item(
            "기준(오늘, KST)",
            overview.today,
            DAY,
            "실제 데이터 기록은 오늘, 합성 지도 기록은 그 지도의 기준일부터 결정 기한 산정",
        ),
        Item("결재 대기(건)", kpis.waiting, None, "검토·보류"),
        Item(f"결정 기한 {URGENT_DAYS}일 이내·지남(건)", kpis.urgent),
        Item("미결정 설계변경(건)", kpis.undecided, None, "분석·검토·보류"),
        Item("미결정 총변경비용 대표(원)", kpis.undecided_total.value, MONEY),
        Item("미결정 총변경비용 최소(원)", kpis.undecided_total.low, MONEY),
        Item("미결정 총변경비용 최대(원)", kpis.undecided_total.high, MONEY),
        Item("실행 중(건)", kpis.in_progress, None, "승인 후 현장 반영 중"),
        Item(f"{period} 새 기록(건)", kpis.recorded_recent),
        Item(f"{period} 종료(건)", kpis.closed_recent),
        Item("내보낸 시각", exported_at),
    ]


def ledger_workbook(overview: ManageOverview, *, exported_at: str) -> bytes:
    workbook = Workbook()
    rows = [*(_row(item, MINE) for item in overview.inbox), *(_row(item, PROXY) for item in overview.proxy)]
    table(sheet(workbook, "결재 대장", first=True), LEDGER_COLUMNS, rows)
    items(sheet(workbook, "현황"), _status_items(overview, exported_at))
    table(
        sheet(workbook, "상태별"),
        [Column("상태", 10), Column("설계변경(건)", 12)],
        ([name(STATE, s.state), s.count] for s in overview.states),
    )
    table(
        sheet(workbook, "블록별"),
        [Column("블록", 12), Column("진행 중(건)", 12), Column("총변경비용 합(원)", 18, MONEY)],
        ([_block(b.block_id), b.open, b.total_value] for b in overview.blocks),
    )
    return save(workbook)
