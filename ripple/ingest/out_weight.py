"""분석 결과 엑셀의 '중량 변화' 시트와 요약 줄(1.34.0, docs/engine.md(비용·일정) 12절): 값은 결과 필드 그대로다.

시트: 부재마다 한 줄(블록 ID 순 → 부재 ID 순) · 블록마다 소계 줄 · 마지막 합계 줄 · 아래 무게중심 안내.
중량 정보 없는 부재는 중량 칸을 비우고 근거에 '중량 정보 없음'을 적는다(0으로 쓰지 않음).
"""

from __future__ import annotations

from openpyxl.worksheet.worksheet import Worksheet

from ripple.contracts.result import AnalysisResult, BlockWeight, WeightChange

from .out_labels import COG_NOTE, OP, WEIGHT_SOURCE, name
from .out_table import DECIMAL, Cell, Column, Item, note_rows, table

__all__ = ["weight_items", "weight_sheet"]

WEIGHT = "#,##0.000"
"""중량(t) 칸: 소수 셋째 자리(kg)까지."""


def _t(value: float) -> str:
    return f"{value:,.3f}t"


def _signed(value: float) -> str:
    return f"+{_t(value)}" if value > 0 else _t(value)


def weight_items(result: AnalysisResult) -> list[Item]:
    """요약 시트 줄: 강재 중량 변화 합계(차이) + 원래 → 새 · 부재 수 · 중량 정보 없음. 계산하지 않은 옛 결과면 없음."""
    weight = result.weight_change
    if weight is None:
        return []
    if not weight.blocks:
        return [Item("강재 중량 변화(t)", 0, WEIGHT, "중량이 바뀌는 부재 없음")]
    parts = [f"원래 {_t(weight.before_t)} → 새 {_t(weight.after_t)}", f"부재 {weight.counted}개"]
    if weight.missing:
        parts.append(f"중량 정보 없음 {weight.missing}개(합계 제외)")
    parts += ["블록별은 '중량 변화' 시트", COG_NOTE]
    return [Item("강재 중량 변화(t)", weight.delta_t, WEIGHT, " · ".join(parts))]


def _block_rows(block: BlockWeight) -> list[list[Cell]]:
    rows: list[list[Cell]] = []
    for part in block.parts:
        rows.append(
            [
                block.block_id,
                block.name,
                part.part_id,
                part.label,
                ", ".join(name(OP, op) for op in part.ops),
                part.from_mm,
                part.to_mm,
                part.before_t,
                part.after_t,
                part.delta_t,
                name(WEIGHT_SOURCE, part.source),
            ]
        )
    missing = f"중량 정보 없음 {block.missing}개(소계 제외)" if block.missing else None
    head: list[Cell] = [block.block_id, block.name, None, f"블록 소계 · 부재 {block.counted}개", None, None, None]
    rows.append([*head, block.before_t, block.after_t, block.delta_t, missing])
    return rows


def weight_sheet(ws: Worksheet, weight: WeightChange) -> None:
    rows = [row for block in weight.blocks for row in _block_rows(block)]
    head: list[Cell] = [None, None, None, f"합계 · 부재 {weight.counted}개", None, None, None]
    missing = f"중량 정보 없음 {weight.missing}개(합계 제외)" if weight.missing else None
    rows.append([*head, weight.before_t, weight.after_t, weight.delta_t, missing])
    columns = [
        Column("블록", 14),
        Column("블록 이름", 22),
        Column("부재 ID", 24),
        Column("부재 이름", 30),
        Column("변경", 16),
        Column("원래 두께(mm)", 12, DECIMAL),
        Column("새 두께(mm)", 12, DECIMAL),
        Column("원래 중량(t)", 13, WEIGHT),
        Column("새 중량(t)", 13, WEIGHT),
        Column("차이(t)", 13, WEIGHT),
        Column("중량 근거", 34, wrap=True),
    ]
    table(ws, columns, rows)
    note_rows(
        ws,
        [
            "중량 근거: 규격 단위 t 부재는 자재비 차이(C-01)와 같은 수량(두께 변경은 원래 × 새 두께 ÷ 원래 두께), "
            "그 밖은 지도의 부재 중량이 있을 때만",
            COG_NOTE,
            f"블록별 차이 합계 {_signed(weight.delta_t)}",
        ],
    )
