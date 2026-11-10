"""발주 손실·할증과 잉여 자재 전용 줄(docs/engine.md(비용·일정) 4-2·4-3·4-7).

- 4-2 발주 변경·취소(R-T01·R-M02): 취소·변경률[판정일 품목 단계] × (영향 수량 − 다른 블록 전용 수량) × 단가
- 4-3 새 규격 발주 할증(R-T01): 할증률 × Σ(새 수량 − 재고 충당) × 새 단가
- 4-7 (가) 재고 사용 줄, (나) 다른 블록 전용 취급비 줄과 전용 기록
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from ripple.contracts.domain import PO_STATUS_ORDER, POStatus
from ripple.contracts.result import Amount, CostItem, CostLine, Determinacy, ImpactType, Reallocation

from ..describe import PO_STATUS_NAMES
from ..state import StageOn, rank
from .amounts import Scenario, amount_of, mixed, worst_case
from .inputs import STEEL_CATEGORIES, CostInput, qty_text, won
from .material import SpecChange
from .reallocation import STOCK_RULE, StockUse, allocate_stock, allocate_surplus

LOSS_RULES = ("R-M02", "R-T01")
HANDLING = "stock.reallocation_handling_per_t"
PREMIUM = "reorder.expedite_premium_ratio"
STEEL_CAP = "steel.max_cancel_loss_ratio"
"""강재(판·형강) 품목 취소·변경률 상한: 고철로 팔아 잔존가치를 건지므로 손실이 이 비율을 넘지 않는다(4-2)."""
STEEL_NOTE = " · 강재라 고철 잔존가치를 빼 손실률 상한 적용"
LOSS_ACTIONS = {
    "R-T01": ("규격 변경 — 기존 발주 변경·취소 필요", "바뀌는"),
    "R-M02": ("빼는 부재의 발주 축소·취소 필요", "줄이는"),
}
"""발주 변경·취소 줄의 이유: 규칙 → (무엇을 해야 하나, 손실을 보는 수량)."""


@dataclass(frozen=True, slots=True)
class Procurement:
    lines: tuple[CostLine, ...]
    reallocations: tuple[Reallocation, ...]
    covered: dict[str, float]  # 부재 → 재고 충당 수량 c_p


def procurement(inp: CostInput, changes: tuple[SpecChange, ...]) -> Procurement:
    by_part = {ch.part_id: ch for ch in changes}
    uses = allocate_stock(inp, changes)
    covered: dict[str, float] = defaultdict(float)
    for use in uses:
        covered[use.part_id] += use.qty

    starts: dict[tuple[str, str], set[str]] = defaultdict(set)
    for rule_id in LOSS_RULES:
        for finding in inp.findings(rule_id, ImpactType.PO_CHANGE):
            starts[(finding.entity_id, rule_id)].add(finding.origin)
    loss_parts = {key: tuple(sorted(parts)) for key, parts in starts.items()}
    quantities = {key: sum(inp.index.parts[p].qty for p in parts) for key, parts in loss_parts.items()}
    stages = {line_id: inp.state.line_stage_on(line_id, inp.day) for line_id, _ in loss_parts}
    known = {key: parts for key, parts in loss_parts.items() if stages[key[0]].likely is not None}
    moves = allocate_surplus(inp, known, quantities)
    moved: dict[tuple[str, str], float] = defaultdict(float)
    for move in moves:
        moved[(move.source_line, move.rule_id)] += move.qty

    lines: list[CostLine] = []
    for line_id, rule_id in sorted(loss_parts):
        lines.append(_loss_line(inp, line_id, rule_id, quantities[(line_id, rule_id)], moved[(line_id, rule_id)]))
    reorders: dict[str, set[str]] = defaultdict(set)
    for finding in inp.findings("R-T01", ImpactType.REORDER):
        reorders[finding.entity_id].add(finding.origin)
    for line_id, parts in sorted(reorders.items()):
        items = [by_part[p] for p in sorted(parts) if p in by_part]
        lines.append(_premium_line(inp, line_id, items, covered))
    records: list[Reallocation] = []
    for use in uses:
        line, record = _stock_use(inp, use, by_part[use.part_id])
        lines.append(line)
        records.append(record)
    pairs: dict[tuple[str, str], float] = defaultdict(float)
    for move in moves:
        pairs[(move.source_line, move.target_line)] += move.qty
    for (source_line, target_line), qty in sorted(pairs.items()):
        line, record = _surplus_move(inp, source_line, target_line, qty, stages[source_line])
        lines.append(line)
        records.append(record)
    return Procurement(lines=tuple(lines), reallocations=tuple(records), covered=dict(covered))


# ---------- 4-2 발주 변경·취소 ----------


def possible_stages(stage: StageOn[POStatus]) -> tuple[POStatus, ...]:
    """대표 단계가 있으면 그 단계, 없으면 가장 이른 경우~가장 늦은 경우의 모든 단계."""
    if stage.likely is not None:
        return (stage.likely,)
    return PO_STATUS_ORDER[rank(stage.earliest) : rank(stage.latest) + 1]


def _staged(
    stage: StageOn[POStatus], per_stage: Callable[[POStatus], Amount]
) -> tuple[Amount, Determinacy, POStatus | None]:
    if stage.likely is not None:
        return per_stage(stage.likely), Determinacy.KNOWN, stage.likely
    return worst_case([per_stage(s) for s in possible_stages(stage)]), Determinacy.STATE_UNKNOWN, None


def _stage_text(stage: StageOn[POStatus], chosen: POStatus | None) -> str:
    if chosen is not None:
        return PO_STATUS_NAMES[chosen]
    return f"{_possible(stage)} 중 판단 불가"


def _possible(stage: StageOn[POStatus]) -> str:
    return f"{PO_STATUS_NAMES[stage.earliest]}~{PO_STATUS_NAMES[stage.latest]}"


def is_steel(inp: CostInput, line_id: str) -> bool:
    return inp.index.specs[inp.index.lines[line_id].spec_id].category in STEEL_CATEGORIES


def cancel_ratio(inp: CostInput, line_id: str, stage: POStatus, scenario: Scenario = Scenario.VALUE) -> float:
    """취소·변경률 r[s](4-2). 강재 품목은 고철 잔존가치 상한(steel.max_cancel_loss_ratio)을 넘지 않는다 —
    두 값 모두 시나리오가 커질수록 커지므로 최소 ≤ 대표 ≤ 최대가 그대로다."""
    ratio = inp.params.get(f"po_cancel_ratio.{stage.value}", scenario)
    return min(ratio, inp.params.get(STEEL_CAP, scenario)) if is_steel(inp, line_id) else ratio


def _capped(inp: CostInput, line_id: str, stages: tuple[POStatus, ...]) -> bool:
    """상한이 어느 시나리오에서든 손실률을 낮추는가(가정값에 상한을 보일지)."""
    return is_steel(inp, line_id) and any(
        inp.params.get(f"po_cancel_ratio.{s.value}", sc) > inp.params.get(STEEL_CAP, sc)
        for s in stages
        for sc in Scenario
    )


def _loss_reason(inp: CostInput, line_id: str, rule_id: str, stage: StageOn[POStatus], chosen: POStatus | None) -> str:
    action, which = LOSS_ACTIONS.get(rule_id, ("발주 변경·취소 필요", "바뀌는"))
    if chosen is None:
        return (
            f"{action} · 확정일에 이 품목이 {_possible(stage)} 중 어느 단계인지 알 수 없어"
            " 손실이 가장 큰 단계로 계산" + (STEEL_NOTE if _capped(inp, line_id, possible_stages(stage)) else "")
        )
    ratio = cancel_ratio(inp, line_id, chosen)
    capped = ratio < inp.params.value(f"po_cancel_ratio.{chosen.value}")
    return (
        f"{action} · 확정일에 이 품목은 {PO_STATUS_NAMES[chosen]} 단계 —"
        f" {which} 수량 금액의 {ratio:.0%}를 손실로 산정" + (STEEL_NOTE if capped else "")
    )


def _loss_line(inp: CostInput, line_id: str, rule_id: str, qty: float, moved: float) -> CostLine:
    line = inp.index.lines[line_id]
    unit = inp.index.specs[line.spec_id].unit
    stage = inp.state.line_stage_on(line_id, inp.day)
    kept = qty - moved

    def per_stage(s: POStatus) -> Amount:
        return amount_of(lambda sc: cancel_ratio(inp, line_id, s, sc) * kept * line.unit_price_krw)

    amount, determinacy, chosen = _staged(stage, per_stage)
    ratio = "" if chosen is None else f" {cancel_ratio(inp, line_id, chosen):.0%}"
    stages = possible_stages(stage)
    moved_text = f"(다른 블록 전용 {qty_text(moved, unit)} 제외)" if moved else ""
    reason = _loss_reason(inp, line_id, rule_id, stage, chosen)
    if moved:
        reason += f" · 다른 블록으로 전용하는 {qty_text(moved, unit)}는 손실에서 제외"
    return inp.line(
        line_id=f"{rule_id}:{ImpactType.PO_CHANGE.value}:{line_id}",
        rule_id=rule_id,
        entity_id=line_id,
        label=f"{line_id} 발주 변경·취소",
        formula=(
            f"취소·변경률{ratio}({_stage_text(stage, chosen)}) × 수량 {qty_text(kept, unit)}{moved_text}"
            f" × 단가 {won(line.unit_price_krw)}"
        ),
        inputs={"qty": round(qty, 6), "moved_qty": round(moved, 6), "unit_price": line.unit_price_krw}
        | ({"stage": chosen.value} if chosen else {}),
        amount=amount,
        param_keys=tuple(f"po_cancel_ratio.{s.value}" for s in stages)
        + ((STEEL_CAP,) if _capped(inp, line_id, stages) else ()),
        item=CostItem.PO_CHANGE,
        determinacy=determinacy,
        reason=reason,
    )


# ---------- 4-3 새 규격 발주 할증 ----------


def _premium_line(inp: CostInput, line_id: str, items: list[SpecChange], covered: dict[str, float]) -> CostLine:
    stage = inp.state.line_stage_on(line_id, inp.day)
    bought = sum((ch.q_new - covered.get(ch.part_id, 0.0)) * ch.price_new for ch in items)

    def per_stage(s: POStatus) -> Amount:
        if rank(s) < rank(POStatus.ORDERED):
            return Amount.exact(0)
        return amount_of(lambda sc: inp.params.get(PREMIUM, sc) * bought)

    amount, determinacy, chosen = _staged(stage, per_stage)
    covered_qty = sum(covered.get(ch.part_id, 0.0) for ch in items)
    covered_text = (
        f"(재고 충당 {qty_text(covered_qty, items[0].unit)} 제외)"
        if items and any(covered.get(ch.part_id) for ch in items)
        else ""
    )
    if chosen is None:
        reason = (
            "새 규격 자재 긴급 재발주 시 할증 발생 · "
            f"확정일에 원래 발주가 {_possible(stage)} 중 어느 단계인지 알 수 없어"
            " 비용이 가장 큰 경우(할증 발생)로 계산"
        )
    elif rank(chosen) < rank(POStatus.ORDERED):
        reason = "확정일에 아직 발주 전 — 발주할 규격만 바꾸면 되어 할증 없음"
    else:
        reason = f"원래 규격 발주가 이미 {PO_STATUS_NAMES[chosen]} 단계 — 새 규격 자재 긴급 재발주 필요, 할증 발생"
    if covered_text:
        reason += f" · 재고로 충당하는 {qty_text(covered_qty, items[0].unit)}는 신규 구매가 없어 할증에서 제외"
    return inp.line(
        line_id=f"R-T01:{ImpactType.REORDER.value}:{line_id}",
        rule_id="R-T01",
        entity_id=line_id,
        label=f"{line_id} 새 규격 긴급 재발주(할증)",
        formula=(
            f"할증률 {inp.params.value(PREMIUM):.0%} × 신규 구매 자재 {won(bought)}{covered_text}"
            f"({_stage_text(stage, chosen)})"
        ),
        inputs={"bought_value": round(bought, 2)} | ({"stage": chosen.value} if chosen else {}),
        amount=amount,
        param_keys=(PREMIUM,),
        item=CostItem.REORDER,
        determinacy=determinacy,
        reason=reason,
    )


# ---------- 4-7 잉여 자재 전용 ----------


def _stock_use(inp: CostInput, use: StockUse, change: SpecChange) -> tuple[CostLine, Reallocation]:
    lot = inp.index.stock[use.lot_id]
    c, price = use.qty, change.price_new
    ordered = change.line_id is not None and (
        inp.state.line_stage_on(change.line_id, inp.day).at_least(POStatus.ORDERED) is not False
    )
    line = inp.line(
        line_id=f"{STOCK_RULE}:stock:{use.lot_id}:{use.part_id}",
        rule_id=STOCK_RULE,
        entity_id=use.lot_id,
        label=f"재고 {use.lot_id} 전용({inp.label(use.part_id)})",
        formula=(
            f"취급비 {qty_text(c, change.unit)} × 단가 − 구매 불필요 자재 {qty_text(c, change.unit)} × {won(price)}"
        ),
        inputs={"qty": round(c, 6), "new_unit_price": round(price, 2)},
        amount=amount_of(lambda s: c * inp.params.get(HANDLING, s) - c * price),
        param_keys=(HANDLING,),
        item=CostItem.STOCK,
        reason=(
            f"변경 뒤 규격과 같은 재고 {use.lot_id}에서 {qty_text(c, change.unit)} 전용 —"
            " 그만큼 신규 구매 불필요 · 옮기는 취급비만 발생"
        ),
    )

    def gain(s: Scenario) -> float:
        return c * price * (1 + (inp.params.get(PREMIUM, s) if ordered else 0.0))

    record = Reallocation(
        lot_id=use.lot_id,
        rule_id=STOCK_RULE,
        spec_id=lot.spec_id,
        to_block_id=inp.view.block_of(use.part_id) or "",
        qty=c,
        saved=mixed(gain, lambda s: c * inp.params.get(HANDLING, s)),
    )
    return line, record


def _surplus_move(
    inp: CostInput, source_line: str, target_line: str, m: float, stage: StageOn[POStatus]
) -> tuple[CostLine, Reallocation]:
    """L → O 전용 한 쌍(규칙이 달라도 합친 수량 m)의 취급비 줄과 전용 기록."""
    source = inp.index.lines[source_line]
    target = inp.index.lines[target_line]
    unit = inp.index.specs[source.spec_id].unit
    chosen = stage.likely or POStatus.RECEIVED
    line = inp.line(
        line_id=f"{STOCK_RULE}:handling:{source_line}:{target_line}",
        rule_id=STOCK_RULE,
        entity_id=target_line,
        label=f"{source_line} 잉여 자재를 {target_line}로 전용",
        formula=f"취급비 {qty_text(m, unit)} × 단가",
        inputs={"qty": round(m, 6)},
        amount=amount_of(lambda s: m * inp.params.get(HANDLING, s)),
        param_keys=(HANDLING,),
        item=CostItem.TRANSFER,
        reason=(
            f"{source_line}에서 잉여 자재 {qty_text(m, unit)}를 같은 규격이 필요한 {target_line}에 전용 —"
            " 취소 손실 대신 옮기는 취급비만 발생"
        ),
    )
    blocks = sorted(b for b in (inp.view.block_of(p) for p in target.part_ids if p in inp.index.parts) if b is not None)
    record = Reallocation(
        lot_id=source_line,
        rule_id=STOCK_RULE,
        spec_id=source.spec_id,
        to_block_id=blocks[0] if blocks else "",
        qty=m,
        saved=mixed(
            lambda s: m * source.unit_price_krw * cancel_ratio(inp, source_line, chosen, s),
            lambda s: m * inp.params.get(HANDLING, s),
        ),
    )
    return line, record


__all__ = ["Procurement", "procurement"]
