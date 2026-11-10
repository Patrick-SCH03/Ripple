"""바뀌는 규격의 수량·단가(docs/engine.md(비용·일정) 4-0)와 자재비 차이(4-1, 비용 규칙 C-01).

자재비 차이는 정상 가격으로 새로 살 때의 차이이고 판정일과 무관하다. 재고 충당은 전용 줄(4-7 가)이 뺀다.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from statistics import fmean
from typing import NamedTuple

from ripple.contracts.change import AddPart, RemovePart, ReroutePipe
from ripple.contracts.domain import ASSUMED_TRANSPORT_NOTE, MaterialSpec, Part, TransportMode
from ripple.contracts.result import Amount, CostItem, CostLine

from ..index import GraphIndex
from ..overlay import ChangeView
from .amounts import Params, round_won
from .inputs import CostInput, qty_text, won

SPEC_OPS = ("thickness", "grade", "equipment_spec")
MATERIAL_RULE = "C-01"


@dataclass(frozen=True, slots=True)
class SpecChange:
    """두께·강종·장비 사양 변경의 대상 부재 하나(4-0)."""

    part_id: str
    line_id: str | None  # 공급 발주 품목(여럿이면 ID 순 첫째)
    category: str
    unit: str
    q: float
    price: float
    q_new: float
    price_new: float
    lead_time_days: int  # 새 규격 리드타임 LT'(외자재 운송 일수는 빼고)
    lead_time_basis: str
    param_keys: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    transport: TransportMode | None = None  # 1.33.0 새로 발주할 때 더할 운송 방식(5절, LT'가 생산 리드타임인 외자재만)
    transport_assumed: bool = False  # 외자재인데 운송 방식이 비어 선박으로 가정함
    shipped_spec_id: str | None = None  # 운송을 더할 때 사는 외자재 규격(가정 안내 문장에 씀)


def assumed_transport_note(spec_id: str) -> str:
    """운송 방식을 가정한 외자재 규격의 안내(분석 안내·비용 줄 이유에 같은 말)."""
    tail = "선박 운송 일수로 새 자재 도착일 계산"
    return f"{ASSUMED_TRANSPORT_NOTE}: 외자재 규격 {spec_id} 운송 방식 미입력 — {tail}"


def supply_price(index: GraphIndex, view: ChangeView, part_id: str) -> tuple[str | None, float]:
    """원래 단가: 공급 발주 품목 단가(ID 순 첫째), 없으면 부재 규격 단가."""
    lines = sorted(view.lines_of(part_id))
    if lines:
        return lines[0], float(index.lines[lines[0]].unit_price_krw)
    return None, float(index.specs[index.parts[part_id].spec_id].unit_price_krw)


def spec_changes(index: GraphIndex, view: ChangeView, params: Params) -> tuple[SpecChange, ...]:
    changes = []
    for part_id in sorted(set(view.targets(SPEC_OPS)) - set(view.new_parts)):
        part = index.parts[part_id]
        spec = index.specs[part.spec_id]
        line_id, price = supply_price(index, view, part_id)
        target = _target(index, view, params, part_id, price)
        lead, basis, shipped = _lead_time(index, params, target.spec_id, line_id, spec)
        transport = None if shipped is None else shipped.import_transport
        assumed = shipped is not None and shipped.transport_assumed
        # 가정 안내는 도착일을 실제로 계산한 수요에서만 붙인다(demand.demands·material_lines의 waited)
        changes.append(
            SpecChange(
                part_id=part_id,
                line_id=line_id,
                category=spec.category,
                unit=spec.unit,
                q=part.qty,
                price=price,
                q_new=target.q_new,
                price_new=target.price_new,
                lead_time_days=lead,
                lead_time_basis=basis,
                param_keys=target.keys,
                notes=target.notes,
                transport=transport,
                transport_assumed=assumed,
                shipped_spec_id=None if transport is None or shipped is None else shipped.spec_id,
            )
        )
    return tuple(changes)


class _Target(NamedTuple):
    """바뀐 뒤의 수량·단가와 새 규격 ID(지도에 없거나 고를 수 없으면 None), 쓴 파라미터 키·안내."""

    q_new: float
    price_new: float
    spec_id: str | None
    keys: tuple[str, ...]
    notes: tuple[str, ...]


def _target(index: GraphIndex, view: ChangeView, params: Params, part_id: str, price: float) -> _Target:
    """4-0: 두께는 t 단위 수량 비례, 강종은 단가 비율, 규격을 직접 바꾸면 그 규격 단가, 아니면 맞는 규격을 고른다."""
    part = index.parts[part_id]
    spec = index.specs[part.spec_id]
    q_new, price_new = part.qty, price
    keys: list[str] = []
    notes: list[str] = []
    new_spec_id: str | None = None
    thickness, grade = view.thickness(part_id), view.grade(part_id)
    if thickness is not None and part.thickness_mm is not None and thickness != part.thickness_mm:
        if spec.unit == "t":
            q_new = part.qty * thickness / part.thickness_mm
        else:
            notes.append(f"{spec.spec_id} 단위가 t 이외 — 두께 변경 수량 그대로 유지")
    if grade is not None and part.grade is not None and grade != part.grade:
        if spec.unit == "t":
            ratio, ratio_keys, ratio_note = _grade_ratio(params, part.grade, grade)
            price_new = price * ratio
            keys += ratio_keys
            notes += ratio_note
        else:
            notes.append(f"{spec.spec_id} 단위가 t 이외 — 강종 단가 차이 미반영")
    if view.spec_id(part_id) != part.spec_id:
        new_spec_id = view.spec_id(part_id)
        new_spec = index.specs.get(new_spec_id)
        if new_spec is None:
            notes.append(f"새 규격 {new_spec_id} 단가가 지도에 없음 — 원래 단가로 계산")
            new_spec_id = None
        else:
            price_new = float(new_spec.unit_price_krw)
    elif thickness is not None or grade is not None:
        new_spec_id, picked = _matching_spec(index, part, spec.category, grade, thickness)
        notes += picked
    return _Target(q_new, price_new, new_spec_id, tuple(keys), tuple(notes))


def _grade_ratio(params: Params, old: str, new: str) -> tuple[float, list[str], list[str]]:
    keys = [f"steel.grade_price_ratio.{g}" for g in (old, new)]
    missing = [g for g, k in zip((old, new), keys, strict=True) if not params.has(k)]
    if missing:
        return 1.0, [], [f"강종 {', '.join(missing)}의 단가 비율이 파라미터에 없음 — 강종 단가 차이 0으로 처리"]
    return params.value(keys[1]) / params.value(keys[0]), keys, []


def _matching_spec(
    index: GraphIndex, part: Part, category: str, grade: str | None, thickness: float | None
) -> tuple[str | None, list[str]]:
    """두께·강종이 바뀐 부재의 새 규격(4-0)과 가정 문구: 분류·강종·두께가 바뀐 값과 맞는 규격.

    후보가 여럿이면 ① 바꾸는 부재와 같은 부재 종류의 부재가 쓰는 규격 ② 옛 규격과 같은 ID 접두(첫 '-' 앞) ③ ID 순으로
    줄인다(각 단계는 남는 후보가 있을 때만 적용). ①②로 하나가 되지 않으면 ID 순 첫째를 고르고 그 사실을 가정으로 남긴다
    — 판 두께 변경이 같은 분류의 브라켓 규격(외자재 표시·표준 리드타임이 다른)을 조용히 고르지 않게(점검 D-1)."""
    pool = sorted(
        spec_id
        for spec_id, spec in index.specs.items()
        if spec.category == category and spec.grade == grade and spec.thickness_mm == thickness
    )
    if len(pool) <= 1:
        return (pool[0] if pool else None), []
    same_kind = {p.spec_id for p in index.parts.values() if p.kind is part.kind}
    prefix = _id_prefix(part.spec_id)
    for keep in (same_kind, {s for s in pool if _id_prefix(s) == prefix}):
        pool = [s for s in pool if s in keep] or pool
        if len(pool) == 1:
            return pool[0], []
    return pool[0], [SPEC_PICK_NOTE.format(candidates=", ".join(pool), chosen=pool[0])]


SPEC_PICK_NOTE = (
    "가정(새 규격 후보 여럿 → ID 순 첫째): 바뀐 두께·강종에 맞는 규격 {candidates} 중 {chosen} 기준으로 새 자재 "
    "리드타임·운송 산정"
)
"""두께·강종 변경의 새 규격을 같은 부재 종류·같은 ID 접두로도 하나로 줄이지 못했을 때의 분석 안내(4-0)."""


def _id_prefix(spec_id: str) -> str:
    """규격 ID의 첫 '-' 앞(예: PL-AH36-12.0 → PL, BR-AH36-12.0 → BR)."""
    return spec_id.split("-", 1)[0]


def _lead_time(
    index: GraphIndex, params: Params, new_spec_id: str | None, line_id: str | None, spec: MaterialSpec
) -> tuple[int, str, MaterialSpec | None]:
    """LT'와 그 근거, 운송을 더할지 볼 사는 규격(5절): 새 규격 표준 → 원래 발주 → 파라미터 순.

    운송은 LT'가 생산 리드타임(새 규격 표준·파라미터)이고 사는 규격이 외자재일 때만 더한다(사는 규격을 돌려줌). 원래
    발주의 리드타임은 이미 운송을 포함한 값이라 더하지 않는다(None).
    """
    bought = spec if new_spec_id is None else index.specs[new_spec_id]
    if new_spec_id is not None and bought.std_lead_time_days is not None:
        return bought.std_lead_time_days, f"새 규격 {new_spec_id} 표준 리드타임", bought
    if line_id is not None:
        return index.orders[index.lines[line_id].po_id].lead_time_days, "원래 발주의 리드타임", None
    key = f"lead_time_days.{spec.category}"
    return round(params.value(key)), f"파라미터 {key}", bought


def new_spool_qty(index: GraphIndex, op: ReroutePipe, params: Params) -> float:
    """새 스풀 하나의 수량: 빼는 스풀 수량의 평균, 없으면 파라미터."""
    removed = [index.parts[p].qty for p in op.removed_part_ids if p in index.parts]
    return fmean(removed) if removed else params.value("piping.new_spool_qty")


class _Row(NamedTuple):
    """자재비 차이 줄 하나가 될 값(금액은 원 단위로 반올림하기 전)."""

    entity_id: str
    value: float
    formula: str
    inputs: dict[str, float | int | str]
    param_keys: tuple[str, ...]
    reason: str


def material_lines(
    inp: CostInput, changes: tuple[SpecChange, ...], waited: frozenset[str] = frozenset()
) -> tuple[CostLine, ...]:
    """자재비 차이 줄(엔터티마다 하나, 0이면 내지 않음). waited = 그날 도착일을 실제로 계산한 새 자재 수요의 부재
    (도착일·소비 공정이 있음) — 운송 방식을 가정한 외자재의 '도착일에 운송 일수 가산'은 그 부재 줄에만 붙인다."""
    rows = [*(_spec_row(ch, ch.part_id in waited) for ch in changes), *_op_rows(inp, waited)]
    lines = []
    for row in sorted(rows, key=lambda r: r.entity_id):
        amount = round_won(row.value)
        if amount == 0:
            continue
        lines.append(
            inp.line(
                line_id=f"{MATERIAL_RULE}:material:{row.entity_id}",
                rule_id=MATERIAL_RULE,
                entity_id=row.entity_id,
                label=f"{inp.label(row.entity_id)} 자재비 차이",
                formula=row.formula,
                inputs=row.inputs,
                amount=Amount.exact(amount),
                param_keys=row.param_keys,
                item=CostItem.MATERIAL_DIFF,
                reason=row.reason,
            )
        )
    return tuple(lines)


def _spec_row(ch: SpecChange, waits: bool) -> _Row:
    """두께·강종·사양 변경: 새 수량 × 새 단가 − 원래 수량 × 원래 단가."""
    formula = (
        f"새 {qty_text(ch.q_new, ch.unit)} × {won(ch.price_new)} − 원래 {qty_text(ch.q, ch.unit)} × {won(ch.price)}"
    )
    inputs: dict[str, float | int | str] = {
        "qty": ch.q,
        "unit_price": ch.price,
        "new_qty": round(ch.q_new, 6),
        "new_unit_price": round(ch.price_new, 2),
    }
    delta = ch.q_new * ch.price_new - ch.q * ch.price
    reason = _spec_reason(ch) + (ASSUMED_REASON if ch.transport_assumed and waits else "")
    return _Row(ch.part_id, delta, formula, inputs, ch.param_keys, reason)


def _op_rows(inp: CostInput, waited: frozenset[str]) -> Iterator[_Row]:
    """새 부재(AddPart)·빼는 부재(RemovePart)·배관 경로 변경(ReroutePipe의 빼는 스풀과 새 스풀), 연산 순."""
    for planned in inp.view.ops:
        op = planned.op
        if isinstance(op, AddPart):
            spec = inp.index.specs[op.spec_id]
            new_id = planned.new_ids[0]
            formula = f"{qty_text(op.qty, spec.unit)} × {won(spec.unit_price_krw)}"
            inputs: dict[str, float | int | str] = {"qty": op.qty, "unit_price": spec.unit_price_krw}
            reason = "새로 넣는 부재 — 자재 신규 구매 필요" + _assumed_reason(spec, waits=new_id in waited)
            yield _Row(new_id, op.qty * spec.unit_price_krw, formula, inputs, (), reason)
        elif isinstance(op, RemovePart | ReroutePipe):
            yield from _removed_rows(inp, op)
            if isinstance(op, ReroutePipe):
                yield from _spool_rows(inp, planned.new_ids, op, waited)


def _removed_rows(inp: CostInput, op: RemovePart | ReroutePipe) -> Iterator[_Row]:
    """빼는 부재·스풀: −수량 × 원래 단가."""
    index = inp.index
    removed = op.part_ids if isinstance(op, RemovePart) else op.removed_part_ids
    for part_id in removed:
        part = index.parts[part_id]
        _, price = supply_price(index, inp.view, part_id)
        unit = index.specs[part.spec_id].unit
        formula = f"− {qty_text(part.qty, unit)} × {won(price)}"
        inputs: dict[str, float | int | str] = {"qty": part.qty, "unit_price": price}
        reason = REMOVED_REASON[isinstance(op, ReroutePipe)]
        yield _Row(part_id, -part.qty * price, formula, inputs, (), reason)


def _spool_rows(inp: CostInput, new_ids: tuple[str, ...], op: ReroutePipe, waited: frozenset[str]) -> Iterator[_Row]:
    """배관 경로를 바꿔 새로 사는 스풀: 스풀 하나의 수량(new_spool_qty) × 새 규격 단가."""
    index = inp.index
    each = new_spool_qty(index, op, inp.params)
    keys: tuple[str, ...] = () if op.removed_part_ids else ("piping.new_spool_qty",)
    length = "빼는 스풀의 평균" if op.removed_part_ids else "가정값(빼는 스풀 없음)"
    reason = f"배관 경로 변경 — 새 스풀 구매 필요 · 스풀 길이는 {length} 기준"
    for new_id, spec_id in zip(new_ids, op.added_spool_spec_ids, strict=True):
        spec = index.specs[spec_id]
        formula = f"{qty_text(each, spec.unit)} × {won(spec.unit_price_krw)}"
        inputs: dict[str, float | int | str] = {"qty": round(each, 6), "unit_price": spec.unit_price_krw}
        reason_end = _assumed_reason(spec, waits=new_id in waited)
        yield _Row(new_id, each * spec.unit_price_krw, formula, inputs, keys, reason + reason_end)


ASSUMED_REASON = f" · 외자재 규격이라 새 자재 도착일에 운송 일수 가산 — {ASSUMED_TRANSPORT_NOTE}"
"""운송 방식이 빈 외자재 규격을 사는 자재비 줄의 이유 끝(비용 줄 근거에 가정을 남김)."""


def _assumed_reason(spec: MaterialSpec, waits: bool) -> str:
    """새로 사는 규격이 운송 방식 없는 외자재이고 도착일을 실제로 계산했으면(waits) 가정 문장, 아니면 빈 글."""
    return ASSUMED_REASON if waits and spec.transport_assumed else ""


ALREADY_ORDERED = "이미 발주한 몫의 취소 손실은 발주 변경·취소 줄에서 별도 계산"
REMOVED_REASON = {
    False: f"빼는 부재 — 해당 수량만큼 자재비 감소 · {ALREADY_ORDERED}",
    True: f"경로 변경으로 빼는 스풀 — 해당 수량만큼 자재비 감소 · {ALREADY_ORDERED}",
}
"""빼는 부재 줄의 이유: 배관 경로 변경에서 빼는 스풀인가 → 문장."""


def _spec_reason(ch: SpecChange) -> str:
    """두께·강종·사양 변경: 무엇이 바뀌어 신규 구매 자재비가 늘거나 주는가(정상 가격 기준)."""
    more = ch.q_new * ch.price_new > ch.q * ch.price
    changed = "강종" if any(k.startswith("steel.grade_price_ratio.") for k in ch.param_keys) else "규격"
    measure = "중량" if ch.unit == "t" else "수량"
    if ch.q_new != ch.q and ch.price_new != ch.price:
        cause = f"두께·{changed} 변경으로 {measure}·단가 변동"
    elif ch.q_new != ch.q:
        cause = f"두께 변경으로 {measure} {'증가' if ch.q_new > ch.q else '감소'}"
    else:
        cause = f"{changed} 변경으로 단가 {'상승' if ch.price_new > ch.price else '하락'}"
    effect = "증가" if more else "감소"
    return f"{cause} → 신규 구매 자재비 {effect} · 정상 가격 기준, 급발주 할증·발주 취소 손실은 별도 계산"
