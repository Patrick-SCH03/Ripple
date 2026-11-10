"""지체상금(docs/engine.md(비용·일정) 4-6, R-L01): 선가 × 일당 비율 × [L(D_after) − L(D_before)]."""

from __future__ import annotations

from ripple.contracts.result import CostItem, CostLine

from .amounts import Scenario, amount_of
from .inputs import CostInput

RULE = "R-L01"
DEFAULTS = "liquidated_damages"


def capped_days(days: int, grace: float, max_days: float) -> float:
    """L(x) = min(max(x − 유예일, 0), 최대 일수)."""
    return min(max(days - grace, 0.0), max_days)


def damages_line(inp: CostInput, ship_id: str, before: int, after: int) -> CostLine | None:
    ship = inp.index.ships[ship_id]
    terms = ship.ld_terms

    def term(name: str, scenario: Scenario) -> float:
        if terms is not None:
            return float(getattr(terms, name))
        return inp.params.get(f"{DEFAULTS}.{name}", scenario)

    def amount(scenario: Scenario) -> float:
        grace, max_days = term("grace_days", scenario), term("max_days", scenario)
        added = capped_days(after, grace, max_days) - capped_days(before, grace, max_days)
        return ship.contract_price_krw * term("rate_per_day_of_price", scenario) * added

    total = amount_of(amount)
    if total.high == 0:
        return None
    names = ("grace_days", "max_days", "rate_per_day_of_price")
    keys = () if terms is not None else tuple(f"{DEFAULTS}.{n}" for n in names)
    grace, max_days, rate = (term(n, Scenario.VALUE) for n in names)
    basis = "계약" if terms is not None else "기본 가정"
    reason = (
        f"이 변경으로 예상 인도 지연 {before}일 → {after}일 · {basis} 조건상 유예 {grace:g}일 초과분 하루마다"
        f" 선가의 {rate * 100:.4g}% 지체상금(최대 {max_days:g}일)"
    )
    return inp.line(
        line_id=f"{RULE}:ld:{ship_id}",
        rule_id=RULE,
        entity_id=ship_id,
        label=f"{ship_id} 지체상금",
        formula=(
            f"선가 {ship.contract_price_krw:,}원 × 일당 비율 × (인도 지연 {after}일 − 변경 전 {before}일,"
            " 유예·최대 일수 반영)"
        ),
        inputs={"delay_before_days": before, "delay_after_days": after},
        amount=total,
        param_keys=keys,
        item=CostItem.LIQUIDATED_DAMAGES,
        reason=reason,
    )
