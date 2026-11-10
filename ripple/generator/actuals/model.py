"""숨긴 모델의 입구: 요인 고정·참 파라미터·사례 시드를 정하고, 항목·일정 계산 모듈을 차례로 불러 결과를 조립한다."""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Literal

import yaml

from ripple.contracts.change import ChangeRequest
from ripple.contracts.domain import Activity
from ripple.contracts.params import ParamSet

from ..build import Generated
from .amounts import merged
from .case import Case, held_arrivals
from .delivery import liquidated_damages
from .impacts import impacts
from .lead import drawn_lead_days
from .material import material_change, material_delta, stock_reallocation
from .network import forward, network
from .outcome import ActualOutcome, assemble, noisy_items, unmodeled_krw
from .params import case_rng, sample_params
from .purchase import purchase_costs
from .schedule import Demand, demand_dates, exit_delays, schedule_changes
from .work import minor_work, new_work, rework
from .world import World

Factor = Literal["params", "noise", "unmodeled", "start_floor", "order_date", "lead_time"]
FACTORS: tuple[Factor, ...] = ("params", "noise", "unmodeled", "start_floor", "order_date", "lead_time")
"""확인 모드가 대표값·없음으로 바꾸는 숨긴 요인: 참 파라미터, 항목 잡음, 미반영 비용, 공정 착수 하한,
미발주 품목의 실제 발주일(→ 계획 발주일), 새 규격 리드타임 변동(→ 표준 그대로).
원인 분리 진단(`scripts/eval_factors.py`)은 하나씩 고정한다."""


class HiddenModel:
    """숨긴 모델 하나(생성 결과 + 참 파라미터). 결과는 지도·엔진 밖에 둔다."""

    def __init__(
        self, generated: Generated, params_path: Path, *, oracle: bool = False, fixed: Iterable[Factor] = ()
    ) -> None:
        """oracle = 모든 요인을 고정(확인 모드). fixed = 고정할 요인만(원인 분리 진단 — 기준 판정에 쓰지 않음)."""
        chosen = frozenset(fixed)
        if chosen - set(FACTORS):
            raise ValueError(f"모르는 요인이에요: {sorted(chosen - set(FACTORS))}")
        self.generated = generated
        self.oracle = oracle
        self.fixed: frozenset[Factor] = frozenset(FACTORS) if oracle else chosen
        tree = yaml.safe_load(params_path.read_text(encoding="utf-8"))
        self.params = ParamSet.from_tree(tree)
        self.world = World(generated, self._sample_params())

    def _fixed(self, factor: Factor) -> bool:
        return factor in self.fixed

    def _sample_params(self) -> dict[str, float]:
        return sample_params(self.params, self.generated.seed, fixed=self._fixed("params"))

    @property
    def values(self) -> Mapping[str, float]:
        """참 파라미터 표본(지도·참 날짜와 함께 세계가 가진다)."""
        return self.world.values

    def param(self, key: str) -> float:
        return self.world.param(key)

    def _case_rng(self, change: ChangeRequest, *names: str) -> random.Random:
        """사례(설계변경)의 참값 시드: 확정일·보류와 무관하다(같은 세계에서 결정만 바꿔 비교할 수 있게, E7)."""
        return case_rng(self.generated.seed, change, *names)

    def _lead_days(self, change: ChangeRequest, spec_id: str, category: str, lead: int) -> int:
        """새 규격 자재가 오기까지 걸리는 날: 판은 리드타임 + 실제 입고 지연 분위수(PLATE_DELAY_DAYS), 그 밖은
        리드타임 × U(0.9, 1.2)(가정 — 형강 입고 지연은 집계 분포가 둘로 갈려 쓰지 않음).
        시드는 사례·규격(확정일·보류와 무관)."""
        if self._fixed("lead_time"):
            return lead
        return drawn_lead_days(self._case_rng(change, "lead", spec_id), category, lead)

    def _network(self, as_of: date, floors: Mapping[str, date]) -> tuple[tuple[str, ...], dict[str, Activity]]:
        return network(self.world.activities)

    def _forward(
        self,
        order: tuple[str, ...],
        nodes: Mapping[str, Activity],
        as_of: date,
        floors: Mapping[str, date],
        extra: Mapping[str, int] | None = None,
        gates: Mapping[str, date] | None = None,
    ) -> tuple[dict[str, date], dict[str, date]]:
        """전진 계산: 참 기준·보류·변경 일정이 모두 이 메서드를 거친다(하위 클래스가 바꿔 끼울 수 있게)."""
        return forward(order, nodes, as_of, floors, extra, gates)

    def _floors(self) -> dict[str, date]:
        """공정 참 착수 하한(요인 start_floor 고정이면 없음)."""
        return {} if self._fixed("start_floor") else self.generated.actual_activity_start_floor

    def _case(self, change: ChangeRequest, as_of: date, confirm_on: date, holds: Mapping[str, int] | None) -> Case:
        """결정을 검사하고 참 기준 일정(보류 없음)과 보류를 반영한 단계 판단용 착수일을 계산한다."""
        if confirm_on < as_of:
            raise ValueError("확정일은 기준일보다 앞설 수 없어요")
        held = dict(holds or {})
        if any(days < 0 for days in held.values()):
            raise ValueError("보류 일수는 음수일 수 없어요")
        floors = self._floors()
        order, nodes = self._network(as_of, floors)
        base_es, base_ef = self._forward(order, nodes, as_of, floors)
        held_gates = held_arrivals(self.world, held, nodes, base_es, as_of)
        stage_es = self._forward(order, nodes, as_of, floors, gates=held_gates)[0] if held_gates else base_es
        return Case(change, as_of, confirm_on, held, order, nodes, floors, base_es, base_ef, stage_es, held_gates)

    def _changed_schedule(
        self, case: Case, work_days: Mapping[str, int], demands: list[Demand]
    ) -> tuple[dict[str, date], dict[str, int], int | None]:
        """참 변경 일정의 (착수일, 구역 출구별 지연, 늘어난 인도 지연)."""
        extra, gates = schedule_changes(case, work_days, demands)
        changed_es, changed_ef = self._forward(case.order, case.nodes, case.as_of, case.floors, extra, gates)
        delays, delivery = exit_delays(self.world, case, changed_ef)
        return changed_es, delays, delivery

    def outcome(
        self,
        change: ChangeRequest,
        as_of: date,
        confirm_on: date,
        holds: Mapping[str, int] | None = None,
    ) -> ActualOutcome:
        case = self._case(change, as_of, confirm_on, holds)
        world = self.world
        material = material_change(world, change)
        changed, minor = impacts(world, change)
        material_costs = material_delta(world, material)
        new_work_costs = new_work(world, change)
        covered, stock_costs = stock_reallocation(world, change, as_of, material.materials)
        po_costs = purchase_costs(world, case, material, covered)
        work_days, rework_costs = rework(world, case, changed)
        minor_costs = minor_work(world, change, minor)
        demands = demand_dates(
            world, case, material.materials, covered, self._lead_days, planned_orders=self._fixed("order_date")
        )
        changed_es, delays, delivery = self._changed_schedule(case, work_days, demands)
        ld_costs = liquidated_damages(world, case, delivery)
        raw = merged(material_costs, new_work_costs, stock_costs, po_costs, rework_costs, minor_costs, ld_costs)
        items = noisy_items(raw, None if self._fixed("noise") else lambda key: self._case_rng(change, "item", key))
        unmodeled = unmodeled_krw(None if self._fixed("unmodeled") else self._case_rng(change, "unmodeled"), items)
        return assemble(items, unmodeled, delays, delivery, changed_es)
