"""상태 갱신 적용(순수 계산, docs/domain.md 12절): 지금 지도 + StatusUpdate → 새 지도 + 바뀐 것 + 거부 이유.

구조(부재·블록·공정·선후행·발주 품목)는 그대로 두고 발주 관측·진입일·계획 열과 공정 실적·현장 확인만 바꾼다.
거부가 하나라도 있으면 새 지도를 만들지 않는다. 바뀐 것이 없으면 같은 지도(같은 ID)를 돌려준다 —
같은 갱신을 두 번 적용해도 한 번과 같다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, ValidationError

from ripple.contracts.domain import (
    PO_STATUS_ORDER,
    Activity,
    ActivityConfirmation,
    GraphSnapshot,
    POStatus,
    PurchaseOrder,
    SourceRef,
    StatusObservation,
)
from ripple.contracts.identity import snapshot_id
from ripple.contracts.updates import (
    ActivityActualItem,
    ActivityChange,
    ActivityCheckItem,
    MapDiff,
    PlanChange,
    POEntryItem,
    POPlanItem,
    POStatusItem,
    StatusChange,
    StatusUpdate,
    UpdateItem,
    UpdateOrigin,
    UpdateProblem,
)

_rank = PO_STATUS_ORDER.index


@dataclass(frozen=True, slots=True)
class UpdateOutcome:
    snapshot: GraphSnapshot | None  # 거부가 있으면 None
    diff: MapDiff
    problems: tuple[UpdateProblem, ...]


@dataclass(slots=True)
class _Order:
    """고치는 중인 발주 하나(관측은 날짜마다 하나)."""

    base: PurchaseOrder
    seen: dict[date, StatusObservation]
    entered: dict[POStatus, date]
    plan: dict[str, date | int | None]
    items: list[int] = field(default_factory=list)  # 이 발주를 바꾼 항목 위치
    changed: bool = False

    @classmethod
    def of(cls, po: PurchaseOrder) -> _Order:
        seen = {obs.observed_on: obs for obs in po.observations}
        plan = {
            "planned_order_date": po.planned_order_date,
            "material_secured_days": po.material_secured_days,
            "fabrication_start_days": po.fabrication_start_days,
            "lead_time_days": po.lead_time_days,
        }
        return cls(po, seen, dict(po.entered_on), plan)


@dataclass(slots=True)
class _Activity:
    base: Activity
    start: date | None
    finish: date | None
    checks: list[ActivityConfirmation]
    items: list[int] = field(default_factory=list)
    changed: bool = False


class _Applier:
    def __init__(self, snapshot: GraphSnapshot) -> None:
        self.snapshot = snapshot
        self.orders = {po.po_id: po for po in snapshot.purchase_orders}
        self.activities = {a.activity_id: a for a in snapshot.activities}
        self.open_orders: dict[str, _Order] = {}
        self.open_activities: dict[str, _Activity] = {}
        self.problems: list[UpdateProblem] = []
        self.noop: set[int] = set()  # 값이 그대로인 항목 위치
        self.status_items: dict[str, list[int]] = defaultdict(list)

    def problem(self, index: int, entity_id: str, message: str, source: SourceRef | None) -> None:
        self.problems.append(UpdateProblem(index=index, entity_id=entity_id, message=message, source=source))

    def order(self, index: int, po_id: str, source: SourceRef | None) -> _Order | None:
        if po_id not in self.orders:
            self.problem(index, po_id, f"지도에 없는 발주: {po_id}", source)
            return None
        return self.open_orders.setdefault(po_id, _Order.of(self.orders[po_id]))

    def activity(self, index: int, activity_id: str, source: SourceRef | None) -> _Activity | None:
        base = self.activities.get(activity_id)
        if base is None:
            self.problem(index, activity_id, f"지도에 없는 공정: {activity_id}", source)
            return None
        return self.open_activities.setdefault(
            activity_id, _Activity(base, base.actual_start, base.actual_finish, list(base.confirmations))
        )

    def apply(self, index: int, item: UpdateItem) -> None:
        if isinstance(item, POStatusItem):
            self._status(index, item)
        elif isinstance(item, POEntryItem):
            self._entry(index, item)
        elif isinstance(item, POPlanItem):
            self._plan(index, item)
        elif isinstance(item, ActivityActualItem):
            self._actual(index, item)
        else:
            self._check(index, item)

    def _status(self, index: int, item: POStatusItem) -> None:
        order = self.order(index, item.po_id, item.source)
        if order is None:
            return
        self.status_items[item.po_id].append(index)
        existing = order.seen.get(item.observed_on)
        if existing is not None and existing.status is item.status:
            self.noop.add(index)
            return
        if existing is not None and _rank(existing.status) > _rank(item.status):
            message = f"{item.observed_on}에 이미 더 뒤 단계({existing.status.value}) 관측됨"
            self.problem(index, item.po_id, message, item.source)
            return
        # 처음 보는 날이거나, 같은 날 앞으로 진행(나중 관측으로 바꿔 넣음)
        order.seen[item.observed_on] = StatusObservation(
            status=item.status, observed_on=item.observed_on, source=item.source
        )
        order.items.append(index)
        order.changed = True

    def _entry(self, index: int, item: POEntryItem) -> None:
        order = self.order(index, item.po_id, item.source)
        if order is None:
            return
        if item.status is POStatus.NOT_ORDERED:
            self.problem(index, item.po_id, "미발주에는 진입일 없음", item.source)
            return
        existing = order.entered.get(item.status)
        if existing == item.entered_on:
            self.noop.add(index)
            return
        if existing is not None:
            message = f"{item.status.value} 진입일이 이미 {existing}로 확인됨(정정은 전체 엑셀 다시 가져오기)"
            self.problem(index, item.po_id, message, item.source)
            return
        order.entered[item.status] = item.entered_on
        order.items.append(index)
        order.changed = True

    def _plan(self, index: int, item: POPlanItem) -> None:
        order = self.order(index, item.po_id, item.source)
        if order is None:
            return
        wants_date = item.field == "planned_order_date"
        if wants_date != isinstance(item.value, date):
            kind = "날짜" if wants_date else "일수"
            self.problem(index, item.po_id, f"'{item.field}'에는 {kind} 입력 필요", item.source)
            return
        if order.plan[item.field] == item.value:
            self.noop.add(index)
            return
        order.plan[item.field] = item.value
        order.items.append(index)
        order.changed = True

    def _actual(self, index: int, item: ActivityActualItem) -> None:
        work = self.activity(index, item.activity_id, item.source)
        if work is None:
            return
        changed = False
        for name, given, current in (
            ("착수", item.actual_start, work.start),
            ("완료", item.actual_finish, work.finish),
        ):
            if given is None or given == current:
                continue
            if current is not None:
                message = f"실제 {name}일이 이미 {current}로 입력됨(정정은 전체 엑셀 다시 가져오기)"
                self.problem(index, item.activity_id, message, item.source)
                return
            changed = True
        if not changed:
            self.noop.add(index)
            return
        work.start = item.actual_start or work.start
        work.finish = item.actual_finish or work.finish
        work.items.append(index)
        work.changed = True

    def _check(self, index: int, item: ActivityCheckItem) -> None:
        work = self.activity(index, item.activity_id, item.source)
        if work is None:
            return
        check = ActivityConfirmation(state=item.state, confirmed_on=item.confirmed_on)
        if check in work.checks:
            self.noop.add(index)
            return
        work.checks.append(check)
        work.items.append(index)
        work.changed = True

    # ---------- 다시 만들기 ----------

    def rebuilt_orders(self) -> dict[str, PurchaseOrder]:
        built: dict[str, PurchaseOrder] = {}
        for po_id, order in self.open_orders.items():
            if not order.changed:
                continue
            data = {
                **order.base.model_dump(exclude={"entered_on", "observations"}),
                **order.plan,
                "entered_on": order.entered,
                "observations": tuple(order.seen[day] for day in sorted(order.seen)),
            }
            model = self._validated(PurchaseOrder, data, order.items, po_id)
            if model is not None:
                built[po_id] = model
        return built

    def rebuilt_activities(self) -> dict[str, Activity]:
        built: dict[str, Activity] = {}
        for activity_id, work in self.open_activities.items():
            if not work.changed:
                continue
            checks = tuple(sorted(work.checks, key=lambda c: (c.confirmed_on, c.state.value)))
            data = {
                **work.base.model_dump(exclude={"confirmations"}),
                "actual_start": work.start,
                "actual_finish": work.finish,
                "confirmations": checks,
            }
            model = self._validated(Activity, data, work.items, activity_id)
            if model is not None:
                built[activity_id] = model
        return built

    def _validated[M: BaseModel](
        self, model: type[M], data: dict[str, object], items: list[int], entity_id: str
    ) -> M | None:
        try:
            return model.model_validate(data)
        except ValidationError as error:
            message = str(error.errors()[0]["msg"]).removeprefix("Value error, ")
            self.problem(items[-1], entity_id, message, None)
            return None


def apply_update(snapshot: GraphSnapshot, update: StatusUpdate) -> UpdateOutcome:
    applier = _Applier(snapshot)
    for index, item in enumerate(update.items):
        applier.apply(index, item)
    orders = applier.rebuilt_orders()
    activities = applier.rebuilt_activities()
    diff = _diff(applier, orders, activities, update)
    if applier.problems:
        return UpdateOutcome(None, diff, tuple(sorted(applier.problems, key=lambda p: p.index)))
    if not orders and not activities:
        return UpdateOutcome(snapshot, diff, ())
    draft = snapshot.model_copy(
        update={
            "purchase_orders": tuple(orders.get(po.po_id, po) for po in snapshot.purchase_orders),
            "activities": tuple(activities.get(a.activity_id, a) for a in snapshot.activities),
        }
    )
    return UpdateOutcome(draft.model_copy(update={"snapshot_id": snapshot_id(draft)}), diff, ())


def date_problems(update: StatusUpdate, today: date) -> tuple[UpdateProblem, ...]:
    """날짜 규칙: 사실(관측·진입·실적·확인) 날짜는 오늘 뒤일 수 없고, 화면 확인(맞음·고치기)의 관측·확인은 항상
    오늘 날짜다. 계획 열(납기)은 미래 날짜여도 된다."""
    problems: list[UpdateProblem] = []
    for index, item in enumerate(update.items):
        entity = item.activity_id if isinstance(item, (ActivityActualItem, ActivityCheckItem)) else item.po_id
        facts: list[date] = []
        stamped: date | None = None
        if isinstance(item, POStatusItem):
            facts, stamped = [item.observed_on], item.observed_on
        elif isinstance(item, POEntryItem):
            facts = [item.entered_on]
        elif isinstance(item, ActivityActualItem):
            facts = [d for d in (item.actual_start, item.actual_finish) if d is not None]
        elif isinstance(item, ActivityCheckItem):
            facts, stamped = [item.confirmed_on], item.confirmed_on
        if any(day > today for day in facts):
            problems.append(UpdateProblem(index=index, entity_id=entity, message="오늘 뒤 날짜 입력 불가"))
        elif update.origin is UpdateOrigin.CONFIRM and stamped is not None and stamped != today:
            message = "화면에서 확인한 상태는 오늘 날짜로만 기록"
            problems.append(UpdateProblem(index=index, entity_id=entity, message=message))
    return tuple(problems)


def highest_status(po: PurchaseOrder) -> POStatus | None:
    """관측·확인된 진입일 가운데 가장 뒤 단계(없으면 None)."""
    reached = [obs.status for obs in po.observations] + list(po.entered_on)
    return max(reached, key=_rank, default=None)


def _diff(
    applier: _Applier, orders: dict[str, PurchaseOrder], activities: dict[str, Activity], update: StatusUpdate
) -> MapDiff:
    status: list[StatusChange] = []
    plans: list[PlanChange] = []
    for po_id in sorted(orders):
        before, after = applier.orders[po_id], orders[po_id]
        old, new = highest_status(before), highest_status(after)
        if new is not None and new != old:
            status.append(StatusChange(po_id=po_id, before=old, after=new))
        for name in ("planned_order_date", "material_secured_days", "fabrication_start_days", "lead_time_days"):
            if getattr(before, name) != getattr(after, name):
                plans.append(
                    PlanChange(po_id=po_id, field=name, before=getattr(before, name), after=getattr(after, name))
                )
    changes: list[ActivityChange] = []
    for activity_id in sorted(activities):
        was, now = applier.activities[activity_id], activities[activity_id]
        started = now.actual_start if now.actual_start != was.actual_start else None
        finished = now.actual_finish if now.actual_finish != was.actual_finish else None
        if started or finished:
            changes.append(ActivityChange(activity_id=activity_id, started=started, finished=finished))
    # 확인만: 값이 그대로인 항목 + 공정 현장 확인 + 단계가 앞으로 가지 않은 발주의 상태 관측
    advanced = {change.po_id for change in status}
    confirmed = set(applier.noop)
    confirmed |= {i for i, item in enumerate(update.items) if isinstance(item, ActivityCheckItem)}
    confirmed |= {i for po_id, items in applier.status_items.items() if po_id not in advanced for i in items}
    return MapDiff(
        status_changed=tuple(status),
        plan_changed=tuple(plans),
        activities=tuple(changes),
        confirmed_only=len(confirmed),
    )
