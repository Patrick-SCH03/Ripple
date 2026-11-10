"""블록 하나의 재작업 줄(docs/engine.md(비용·일정) 4-4·4-4-1·4-4-2).

- 공정 k의 몫 = 영향 중량(k) × 톤당 공수(k) × 재작업 배수(확정일 단계) × 블록 난이도 계수 × 그 공정 수행 주체의 인건비.
  다시 할 공정은 소조립부터 확정일 단계의 공정까지(CUMULATIVE). 영향 중량(k) = 선체 부재 중량 + (k가 선행의장 이후면)
  의장품 중량 — 의장품은 선행의장에서 블록에 달기 때문에 소조립~대조립 공정을 다시 하지 않는다(OUTFIT_WORK).
  몫마다 원 단위로 반올림해 더한다 — 작업반 몫으로 나눈 줄의 합이 나누지 않을 때와 같다(4-4-1).
- 수행 주체: 작업반이면 작업반 단가, 직영이면 직영 단가, 모르면 블록 제작 협력사 규칙(2절).
  우선순위 performer > fabricator.
- 작업반이 맡은 공정이 있으면 '○○ 작업반 추가 공비' 줄(R-B01:rework:<블록>@<작업반>)로 나누고
  직영 몫은 원래 줄 ID에 둔다.
  단계를 모르면(판단 불가) 나누지 않는다.
- 선행도장 이후 단계면 도장 뒤 고정 항목(재도장·족장·화기작업) 줄 C-04를 더한다(4-4-2, 단계를 모르면 가능한 단계로 2절).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ripple.contracts.domain import (
    BLOCK_ACTIVITY_ORDER,
    BLOCK_STAGE_ORDER,
    DIRECT_PERFORMER,
    ActivityKind,
    BlockStage,
)
from ripple.contracts.result import Amount, CostItem, CostLine, Determinacy, ImpactType, WorkHours

from ..describe import ACTIVITY_NAMES, BLOCK_STAGE_NAMES
from ..state import StageOn, rank
from .amounts import Scenario, amount_of, hours_of, worst_case, worst_hours
from .difficulty import Difficulty, block_difficulty
from .inputs import CostInput, qty_text

RULE = "R-B01"
CREW = "rework.crew_hours_per_day"
PRIME, CREW_RATE = "labor_rate_per_hour.prime", "labor_rate_per_hour.crew"
AFTER_PAINT = ("after_paint.repaint_hours", "after_paint.scaffold_hours", "after_paint.hot_work_hours")
AFTER_PAINT_ITEM = "C-04"

STAGE_KINDS = BLOCK_ACTIVITY_ORDER
CUMULATIVE: dict[BlockStage, tuple[ActivityKind, ...]] = {
    stage: STAGE_KINDS[: max(0, rank(stage) - 1)] for stage in BLOCK_STAGE_ORDER
}
"""단계 → 그 단계까지의 블록 공정(미착수·강재 입고는 없음, 탑재는 일곱 공정 모두). 블록 단계 = 미착수·강재 입고 + 블록
공정과 1:1이라(PE 포함) 단계 순서에서 2를 뺀 자리까지가 다시 할 공정이다(검사 tests/checks/cost.py)."""
OUTFIT_WORK = frozenset(STAGE_KINDS[STAGE_KINDS.index(ActivityKind.PRE_OUTFITTING) :])
"""의장품 중량이 들어가는 공정: 선행의장부터 탑재까지(그 앞 공정은 선체 부재만 다시 한다)."""


@dataclass(frozen=True, slots=True)
class Performer:
    """공정 하나를 누가 하나: 단가 키와 작업반(직영·모름은 None)."""

    rate_key: str
    crew: str | None


@dataclass(frozen=True, slots=True)
class BlockRework:
    lines: tuple[CostLine, ...]
    days: int  # 재작업 일수 d_B(대표값)


def performers(inp: CostInput, block_id: str) -> dict[ActivityKind, Performer]:
    """블록 공정마다 수행 주체(4-4-1). 공정이 지도에 없거나 수행 주체를 모르면 블록 제작 협력사 규칙(2절)."""
    found: dict[ActivityKind, Performer] = {}
    for kind in STAGE_KINDS:
        activity_id = inp.activity_of.get((block_id, kind))
        performer = inp.index.activities[activity_id].performer if activity_id else None
        if performer is None:
            found[kind] = Performer(inp.production_rate(block_id), None)
        elif performer == DIRECT_PERFORMER:
            found[kind] = Performer(PRIME, None)
        else:
            found[kind] = Performer(CREW_RATE, performer)
    return found


def block_rework(inp: CostInput, block_id: str, hull: float, outfit: float, weight_keys: frozenset[str]) -> BlockRework:
    """hull = 선체 부재 중량(t), outfit = 의장품 중량(t, 선행의장 공정부터만)."""
    stage = inp.state.block_stage_on(block_id, inp.day)
    difficulty = block_difficulty(inp.index.blocks.get(block_id), inp.params)
    who = performers(inp, block_id)
    context = _Context(inp, block_id, hull, outfit, weight_keys, difficulty, who)
    if stage.likely is not None:
        chosen = stage.likely
        groups = _groups(tuple(k for k in CUMULATIVE[chosen] if context.weight(k) > 0), who)
        lines = context.split_lines(stage, chosen, groups)
    else:
        possible = BLOCK_STAGE_ORDER[rank(stage.earliest) : rank(stage.latest) + 1]
        chosen = max(possible, key=lambda s: (context.amount(s, CUMULATIVE[s]).value, rank(s)))
        amount = worst_case([context.amount(s, CUMULATIVE[s]) for s in possible])
        per_stage = {s: context.work_hours(s, CUMULATIVE[s]) for s in possible}
        hours = worst_hours(list(per_stage.values()), per_stage[chosen])
        kinds = tuple(k for k in CUMULATIVE[chosen] if context.weight(k) > 0)
        lines = [context.line(stage, chosen, kinds, None, amount, hours, Determinacy.STATE_UNKNOWN, False)]
    after = _after_paint(inp, block_id, stage, who)
    return BlockRework(lines=(*lines, *((after,) if after else ())), days=context.days(chosen))


def _groups(
    kinds: Iterable[ActivityKind], who: Mapping[ActivityKind, Performer]
) -> dict[str | None, tuple[ActivityKind, ...]]:
    """수행 주체별 공정(직영·모름 = None 먼저, 작업반은 ID 순)."""
    found: dict[str | None, list[ActivityKind]] = {}
    for kind in kinds:
        found.setdefault(who[kind].crew, []).append(kind)
    order = sorted(found, key=lambda crew: (crew is not None, crew or ""))
    return {crew: tuple(found[crew]) for crew in order}


@dataclass(frozen=True, slots=True)
class _Context:
    inp: CostInput
    block_id: str
    hull: float
    outfit: float
    weight_keys: frozenset[str]
    difficulty: Difficulty
    who: Mapping[ActivityKind, Performer]

    def weight(self, kind: ActivityKind) -> float:
        """공정 k에서 다시 하는 중량: 선체 부재 + (선행의장 이후 공정이면) 의장품."""
        return self.hull + (self.outfit if kind in OUTFIT_WORK else 0.0)

    def hours(self, stage: BlockStage, kind: ActivityKind, sc: Scenario) -> float:
        params = self.inp.params
        base = params.get(f"base_work_hours_per_t.{kind.value}", sc)
        return self.weight(kind) * base * params.get(f"rework_multiplier.{stage.value}", sc) * self.difficulty.value

    def weight_text(self, kinds: tuple[ActivityKind, ...]) -> str:
        """줄의 공정에 들어간 중량(작업반 몫이 선행의장 전 공정만이면 선체 부재만)."""
        outfit = self.outfit if not kinds or any(k in OUTFIT_WORK for k in kinds) else 0.0
        if outfit <= 0:
            return f"영향 중량 {self.hull:.3f}t"
        if self.hull <= 0:
            return f"의장품 중량 {outfit:.3f}t(선행의장부터)"
        return f"영향 중량 선체 {self.hull:.3f}t + 의장품 {outfit:.3f}t(선행의장부터)"

    def amount(self, stage: BlockStage, kinds: Iterable[ActivityKind]) -> Amount:
        """공정마다 원 단위로 반올림한 몫의 합(4-4-1: 나눠도 합이 같게)."""
        return Amount.total([self.share(stage, kind) for kind in kinds])

    def share(self, stage: BlockStage, kind: ActivityKind) -> Amount:
        """공정 하나의 몫: 공수 × 그 공정 수행 주체의 단가(시나리오 셋, 원 단위 반올림)."""
        rate_key = self.who[kind].rate_key
        return amount_of(lambda sc: self.hours(stage, kind, sc) * self.inp.params.get(rate_key, sc))

    def value_hours(self, stage: BlockStage, kinds: Iterable[ActivityKind]) -> float:
        return sum(self.hours(stage, kind, Scenario.VALUE) for kind in kinds)

    def work_hours(self, stage: BlockStage, kinds: Iterable[ActivityKind]) -> WorkHours:
        """줄의 공수(MH) 시나리오 셋: 금액 몫(share)이 단가를 곱하기 전에 쓴 공정별 공수의 합(4-12)."""
        chosen = tuple(kinds)
        return hours_of(lambda sc: sum(self.hours(stage, kind, sc) for kind in chosen))

    def days(self, stage: BlockStage) -> int:
        hours = self.value_hours(stage, CUMULATIVE[stage])
        return math.ceil(hours / self.inp.params.value(CREW)) if hours > 0 else 0

    def split_lines(
        self, stage: StageOn[BlockStage], chosen: BlockStage, groups: Mapping[str | None, tuple[ActivityKind, ...]]
    ) -> list[CostLine]:
        split = any(crew is not None for crew in groups)
        return [
            self.line(
                stage,
                chosen,
                kinds,
                crew,
                self.amount(chosen, kinds),
                self.work_hours(chosen, kinds),
                Determinacy.KNOWN,
                split,
            )
            for crew, kinds in groups.items()
        ] or [
            self.line(stage, chosen, (), None, Amount.exact(0), self.work_hours(chosen, ()), Determinacy.KNOWN, False)
        ]

    def line(
        self,
        stage: StageOn[BlockStage],
        chosen: BlockStage,
        kinds: tuple[ActivityKind, ...],
        crew: str | None,
        amount: Amount,
        work: WorkHours,
        determinacy: Determinacy,
        split: bool,
    ) -> CostLine:
        inp, block_id = self.inp, self.block_id
        hours = self.value_hours(chosen, kinds)
        days = self.days(chosen)
        stage_text = (
            BLOCK_STAGE_NAMES[chosen]
            if stage.likely is not None
            else f"{BLOCK_STAGE_NAMES[stage.earliest]}~{BLOCK_STAGE_NAMES[stage.latest]} 중 판단 불가"
        )
        name = inp.label(block_id)
        crew_name = self.crew_name(crew)
        share = f"{crew_name} 몫({_span(kinds)}) " if crew is not None else ("직영 몫 " if split else "")
        return inp.line(
            line_id=f"{RULE}:{ImpactType.REWORK.value}:{block_id}" + (f"@{crew}" if crew else ""),
            rule_id=RULE,
            entity_id=block_id,
            label=f"{name} 블록 재작업" + (f" — {crew_name} 추가 공비" if crew else (" — 직영" if split else "")),
            formula=(
                f"{share}{self.weight_text(kinds)} × 누적 공수({stage_text}) × 재작업 배수"
                f" × 난이도 {self.difficulty.value:.2f} × 인건비 = {hours:,.1f}시간(대표값), 블록 {days}일"
            ),
            inputs={
                "weight_t": round(self.hull + self.outfit, 6),
                "hull_weight_t": round(self.hull, 6),
                "outfit_weight_t": round(self.outfit, 6),
                "hours": round(hours, 3),
                "days": days,
                "stage": chosen.value,
                "difficulty": self.difficulty.value,
                **({"crew_id": crew} if crew else {}),
            },
            amount=amount,
            param_keys=self.param_keys(chosen, kinds),
            item=CostItem.REWORK,
            hours=work,
            determinacy=determinacy,
            reason=_reason(
                name,
                self,
                stage,
                chosen,
                tuple(k for k in kinds if self.weight(k) > 0),
                crew_name if crew else ("직영" if split else None),
            ),
            difficulty=self.difficulty.factor,
        )

    def param_keys(self, chosen: BlockStage, kinds: tuple[ActivityKind, ...]) -> tuple[str, ...]:
        """줄에 쓴 가정값: 중량이 들어간 공정(의장품만이면 선행의장부터)의 톤당 공수·단가만."""
        used = tuple(k for k in kinds if self.weight(k) > 0)
        return (
            *(f"base_work_hours_per_t.{k.value}" for k in used),
            f"rework_multiplier.{chosen.value}",
            *sorted({self.who[k].rate_key for k in used}),
            CREW,
            *self.weight_keys,
            *self.difficulty.keys,
        )

    def crew_name(self, crew: str | None) -> str:
        if crew is None:
            return "직영"
        found = self.inp.index.crews.get(crew)
        return found.name if found is not None else crew


def _span(kinds: tuple[ActivityKind, ...]) -> str:
    return "·".join(ACTIVITY_NAMES[k] for k in kinds)


def _reason(
    name: str,
    context: _Context,
    stage: StageOn[BlockStage],
    chosen: BlockStage,
    kinds: tuple[ActivityKind, ...],
    owner: str | None,
) -> str:
    """발생 사유: 확정일 블록 단계와 다시 할 공정(중량이 들어가는 공정만 — 단계를 모르면 비용이 가장 큰 단계로 본다는
    것), 나눈 줄이면 누구 몫인지. 의장품만 바뀌고 선행의장 전이면 아직 달기 전이라 재작업 없음."""
    works = [ACTIVITY_NAMES[kind] for kind in kinds]
    stage_name = BLOCK_STAGE_NAMES[chosen]
    if not works:
        if context.hull <= 0 < context.outfit and rank(chosen) >= rank(BlockStage.SUB_ASSEMBLY):
            where = (
                f"{stage_name} 단계(선행의장 전)"
                if stage.likely is not None
                else f"{BLOCK_STAGE_NAMES[stage.earliest]}~{BLOCK_STAGE_NAMES[stage.latest]} 중 어느 단계든 선행의장 전"
            )
            return f"확정일에 {name} 블록은 {where} — 바뀌는 의장품은 아직 블록에 달기 전, 재작업 없음"
        return f"확정일에 {name} 블록은 아직 {stage_name} 단계 — 재작업 없음"
    span = f"{works[0]} 공정에서" if len(works) == 1 else f"{works[0]}부터 {works[-1]}까지"
    if owner is not None:
        span = f"{owner}이 맡은 {'·'.join(works)} 공정에서"
    if context.hull <= 0:
        redo = f"바뀌는 의장품 {qty_text(context.outfit, 't')}를 {span} 다시 설치"
    elif context.outfit > 0:
        redo = (
            f"바뀌는 선체 부재 {qty_text(context.hull, 't')}·의장품 {qty_text(context.outfit, 't')}"
            f"(선행의장부터)를 {span} 재작업"
        )
    else:
        redo = f"바뀌는 부재 {qty_text(context.hull, 't')}를 {span} 재작업"
    if stage.likely is None:
        possible = f"{BLOCK_STAGE_NAMES[stage.earliest]}~{BLOCK_STAGE_NAMES[stage.latest]}"
        return (
            f"확정일에 {name} 블록이 {possible} 중 어느 단계인지 알 수 없어 "
            f"비용이 가장 큰 {stage_name} 단계로 보고 계산 — {redo}"
        )
    tail = (
        " · 작업반 단가 확인 전 — 직영과 같은 단가로 계산(줄만 나누고 금액 동일)" if owner not in (None, "직영") else ""
    )
    return f"확정일에 {name} 블록은 이미 {stage_name} 단계 — {redo} 필요{tail}"


def _after_paint(
    inp: CostInput, block_id: str, stage: StageOn[BlockStage], who: Mapping[ActivityKind, Performer]
) -> CostLine | None:
    """도장 뒤 재작업 고정 항목(4-4-2, C-04): 선행도장 이후 단계면 재도장·족장·화기작업 공수 × 선행도장 수행 주체 단가.
    단계를 모르면 가능한 단계마다(선행도장 전은 0) 계산해 2절 규칙으로(판단 불가)."""
    rate = who[ActivityKind.PRE_PAINTING].rate_key
    params = inp.params

    def spent(s: BlockStage, sc: Scenario) -> float:
        """그 단계에서 드는 고정 공수(선행도장 전이면 0)."""
        return sum(params.get(key, sc) for key in AFTER_PAINT) if rank(s) >= rank(BlockStage.PRE_PAINTING) else 0.0

    def amount(s: BlockStage) -> Amount:
        if rank(s) < rank(BlockStage.PRE_PAINTING):
            return Amount.exact(0)
        return amount_of(lambda sc: spent(s, sc) * params.get(rate, sc))

    def work(s: BlockStage) -> WorkHours:
        return hours_of(lambda sc: spent(s, sc))

    if stage.likely is not None:
        chosen, total, determinacy = stage.likely, amount(stage.likely), Determinacy.KNOWN
        work_hours = work(chosen)
    else:
        possible = BLOCK_STAGE_ORDER[rank(stage.earliest) : rank(stage.latest) + 1]
        chosen = max(possible, key=rank)
        total, determinacy = worst_case([amount(s) for s in possible]), Determinacy.STATE_UNKNOWN
        work_hours = worst_hours([work(s) for s in possible], work(chosen))
    if total.high <= 0:
        return None
    hours = sum(params.value(key) for key in AFTER_PAINT)
    name = inp.label(block_id)
    return inp.line(
        line_id=f"{AFTER_PAINT_ITEM}:after_paint:{block_id}",
        rule_id=AFTER_PAINT_ITEM,
        entity_id=block_id,
        label=f"{name} 블록 도장 뒤 재작업(재도장·족장·화기작업)",
        formula=f"재도장 + 족장 + 화기작업 안전 조치 = {hours:,.1f}시간(대표값) × 인건비",
        inputs={"hours": round(hours, 3), "stage": chosen.value},
        amount=total,
        param_keys=(*AFTER_PAINT, rate),
        item=CostItem.AFTER_PAINT,
        hours=work_hours,
        determinacy=determinacy,
        reason=(
            f"확정일에 {name} 블록은 이미 {BLOCK_STAGE_NAMES[chosen]} 단계(도장 시작 뒤) — 재작업 시 재도장·"
            "족장 재설치·화기작업 안전 조치 필요(재작업 크기와 무관한 고정 항목, 가정)"
            if determinacy is Determinacy.KNOWN
            else f"확정일에 {name} 블록의 도장 시작 여부를 알 수 없어 도장 뒤라면 드는 고정 항목을 범위로 계산"
        ),
    )
