"""새 부재의 정상 제작 공수(docs/engine.md(비용·일정) 4-1-2, 비용 항목 C-02).

부재 추가의 강재 새 부재(규격 분류 판·형강, 단위 t)마다 W × 블록 공정 7개(PE 포함)의 톤당 공수 합 × 생산 인건비.
확정일·블록 단계와 무관하다(언제 확정해도 새 부재는 만들어야 함). 블록이 작업 중이면 재작업(4-4)은 따로 더한다.
비용에만 넣고 공정 기간에는 더하지 않는다(사용자 확인 전 기본값, docs/engine.md(대안) 5절).
"""

from __future__ import annotations

from ripple.contracts.change import AddPart
from ripple.contracts.domain import BLOCK_ACTIVITY_ORDER
from ripple.contracts.result import CostItem, CostLine

from .amounts import Scenario, amount_of, hours_of
from .inputs import STEEL_CATEGORIES, CostInput, qty_text

ITEM = "C-02"
KIND = "new_work"
WORK_KEYS = tuple(f"base_work_hours_per_t.{kind.value}" for kind in BLOCK_ACTIVITY_ORDER)


def new_work_lines(inp: CostInput) -> tuple[CostLine, ...]:
    lines = [
        _line(inp, planned.op, planned.new_ids[0])
        for planned in inp.view.ops
        if planned.new_ids and _steel_part(inp, planned.op)
    ]
    return tuple(sorted(lines, key=lambda line: line.line_id))


def _steel_part(inp: CostInput, op: object) -> bool:
    if not isinstance(op, AddPart):
        return False
    spec = inp.index.specs.get(op.spec_id)
    return spec is not None and spec.unit == "t" and spec.category in STEEL_CATEGORIES


def _line(inp: CostInput, op: object, new_id: str) -> CostLine:
    assert isinstance(op, AddPart)
    weight = op.qty
    rate_key = inp.production_rate(op.block_id)

    def hours(sc: Scenario) -> float:
        return weight * sum(inp.params.get(key, sc) for key in WORK_KEYS)

    value_hours = hours(Scenario.VALUE)
    name = inp.label(new_id)
    return inp.line(
        line_id=f"{ITEM}:{KIND}:{new_id}",
        rule_id=ITEM,
        entity_id=new_id,
        label=f"{name} 제작·설치",
        formula=f"새 부재 {qty_text(weight, 't')} × 톤당 공수(소조립~탑재) × 인건비 = {value_hours:,.1f}시간(대표값)",
        inputs={"weight_t": round(weight, 6), "hours": round(value_hours, 3)},
        amount=amount_of(lambda sc: hours(sc) * inp.params.get(rate_key, sc)),
        param_keys=(*WORK_KEYS, rate_key),
        item=CostItem.NEW_WORK,
        hours=hours_of(hours),
        reason=(
            f"새로 붙이는 부재 {qty_text(weight, 't')} 제작·부착 정상 작업 · 블록 재작업과 별도 계산, 공정 기간 미반영"
        ),
    )
