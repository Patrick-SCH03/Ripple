"""상태 갱신(docs/domain.md 12절): 구조는 그대로, 상태·날짜만 바뀌고, 문제가 하나라도 있으면 전부 거부한다."""

from __future__ import annotations

from datetime import date
from typing import Any

from fixtures import snapshot_body
from harness import Checker

from ripple.contracts.domain import ActivityCheck, GraphSnapshot, POStatus
from ripple.contracts.identity import snapshot_id
from ripple.contracts.updates import (
    ActivityActualItem,
    ActivityCheckItem,
    POEntryItem,
    POPlanItem,
    POStatusItem,
    StatusUpdate,
    UpdateItem,
    UpdateOrigin,
)
from ripple.engine.freshness import freshness
from ripple.engine.updates import apply_update, highest_status

PO = "PO-0001"
WORK = "S-001:T31C:assembly"
NEXT = "S-001:T31C:erection"


def _map() -> GraphSnapshot:
    body: dict[str, Any] = snapshot_body(
        suppliers=[{"supplier_id": "SUP-1", "name": "강재사", "kind": "steel"}],
        purchase_orders=[
            {
                "po_id": PO,
                "ship_id": "S-001",
                "supplier_id": "SUP-1",
                "planned_order_date": "2026-09-01",
                "material_secured_days": 10,
                "fabrication_start_days": 20,
                "lead_time_days": 40,
                "entered_on": {"ordered": "2026-09-02"},
                "observations": [{"status": "ordered", "observed_on": "2026-09-05"}],
            }
        ],
        po_lines=[
            {
                "po_id": PO,
                "line_no": 1,
                "spec_id": "PL-AH36-12.0",
                "qty": 1.2,
                "unit_price_krw": 900000,
                "part_ids": ["S-001:T31C-PL-0001"],
                "consumed_by_activity_id": WORK,
            }
        ],
        activities=[
            {
                "activity_id": WORK,
                "ship_id": "S-001",
                "block_id": "S-001:T31C",
                "kind": "assembly",
                "duration_days": 10,
                "planned_start": "2026-10-15",
                "actual_start": "2026-10-14",
            },
            {
                "activity_id": NEXT,
                "ship_id": "S-001",
                "block_id": "S-001:T31C",
                "kind": "erection",
                "duration_days": 2,
                "planned_start": "2026-11-01",
                "predecessors": [{"activity_id": WORK}],
            },
        ],
    )
    draft = GraphSnapshot.model_validate(body)
    return draft.model_copy(update={"snapshot_id": snapshot_id(draft)})


def _update(*items: UpdateItem) -> StatusUpdate:
    return StatusUpdate(origin=UpdateOrigin.CONFIRM, items=items)


def _structure(snapshot: GraphSnapshot) -> object:
    """구조: 상태·날짜를 뺀 지도(이 값은 갱신으로 바뀌면 안 된다)."""
    return snapshot.model_dump(
        exclude={
            "snapshot_id": True,
            "purchase_orders": {"__all__": {"entered_on", "observations", "planned_order_date", "lead_time_days"}},
            "activities": {"__all__": {"actual_start", "actual_finish", "confirmations"}},
        }
    )


def run(c: Checker) -> None:
    c.section("상태 갱신: 적용·거부·같은 갱신 두 번")
    base = _map()
    old_format = base.model_dump(mode="json")
    for activity in old_format["activities"]:
        del activity["confirmations"]  # 1.22.0 전 지도 파일에는 이 키가 없다
    c.check(
        "공정 현장 확인 키가 없는 옛 지도 파일도 같은 지도 ID(빈 확인은 정규형에 넣지 않음)",
        snapshot_id(GraphSnapshot.model_validate(old_format)) == base.snapshot_id,
    )

    advance = _update(POStatusItem(po_id=PO, status=POStatus.RECEIVED, observed_on=date(2026, 10, 11)))
    out = apply_update(base, advance)
    c.check(
        "발주 상태를 올리면 새 지도·새 ID, 단계 변화가 요약에",
        out.snapshot is not None
        and out.snapshot.snapshot_id != base.snapshot_id
        and [(s.before, s.after) for s in out.diff.status_changed] == [(POStatus.ORDERED, POStatus.RECEIVED)],
    )
    assert out.snapshot is not None
    c.check("구조(부재·블록·공정·선후행·품목)는 그대로", _structure(out.snapshot) == _structure(base))
    again = apply_update(out.snapshot, advance)
    c.check(
        "같은 갱신 두 번 = 한 번(같은 지도 ID, 확인만 1건)",
        again.snapshot is not None
        and again.snapshot.snapshot_id == out.snapshot.snapshot_id
        and not again.diff.changed
        and again.diff.confirmed_only == 1,
    )
    c.check("결정적: 같은 지도·같은 갱신이면 같은 ID", apply_update(base, advance).snapshot == out.snapshot)

    same_day = apply_update(
        base, _update(POStatusItem(po_id=PO, status=POStatus.MATERIAL_SECURED, observed_on=date(2026, 9, 5)))
    )
    observed = same_day.snapshot.purchase_orders[0].observations if same_day.snapshot else ()
    c.check(
        "같은 날 앞으로 진행이면 그날 관측을 나중 것으로 바꿔 넣음",
        [(o.observed_on, o.status) for o in observed] == [(date(2026, 9, 5), POStatus.MATERIAL_SECURED)],
    )
    back = apply_update(
        out.snapshot, _update(POStatusItem(po_id=PO, status=POStatus.ORDERED, observed_on=date(2026, 10, 11)))
    )
    c.check("같은 날 뒤로 가는 관측은 거부", back.snapshot is None and len(back.problems) == 1)
    regress = apply_update(
        out.snapshot, _update(POStatusItem(po_id=PO, status=POStatus.ORDERED, observed_on=date(2026, 10, 12)))
    )
    c.check("시간이 지나 단계가 되돌아가면 거부(계약 검사)", regress.snapshot is None and bool(regress.problems))

    mixed = apply_update(
        base,
        _update(
            POStatusItem(po_id=PO, status=POStatus.RECEIVED, observed_on=date(2026, 10, 11)),
            POStatusItem(po_id="PO-9999", status=POStatus.RECEIVED, observed_on=date(2026, 10, 11)),
        ),
    )
    c.check(
        "하나라도 문제면 전부 거부(일부만 반영 안 함), 문제는 항목 위치와 함께",
        mixed.snapshot is None and [p.index for p in mixed.problems] == [1],
    )
    entry = apply_update(base, _update(POEntryItem(po_id=PO, status=POStatus.ORDERED, entered_on=date(2026, 9, 3))))
    c.check("이미 확인된 진입일과 다른 날짜는 거부(정정은 전체 엑셀)", entry.snapshot is None and bool(entry.problems))

    c.section("상태 갱신: 납기·공정 실적·현장 확인")
    late = apply_update(base, _update(POPlanItem(po_id=PO, field="lead_time_days", value=47)))
    c.check(
        "납기 변경(리드타임) 전후 값이 요약에",
        [(p.field, p.before, p.after) for p in late.diff.plan_changed] == [("lead_time_days", 40, 47)],
    )
    wrong = apply_update(base, _update(POPlanItem(po_id=PO, field="planned_order_date", value=5)))
    c.check("계획 발주일에 일수를 넣으면 거부", wrong.snapshot is None)
    order_break = apply_update(base, _update(POPlanItem(po_id=PO, field="lead_time_days", value=5)))
    c.check("간격 순서(자재 확보 ≤ 제작 착수 ≤ 리드타임)를 깨면 거부", order_break.snapshot is None)

    done = apply_update(base, _update(ActivityActualItem(activity_id=WORK, actual_finish=date(2026, 10, 24))))
    c.check(
        "공정 실적 완료일이 들어가고 요약에",
        done.snapshot is not None
        and [(a.activity_id, a.finished) for a in done.diff.activities] == [(WORK, date(2026, 10, 24))],
    )
    redo = apply_update(base, _update(ActivityActualItem(activity_id=WORK, actual_start=date(2026, 10, 13))))
    c.check("이미 있는 실제 착수일과 다른 날짜는 거부", redo.snapshot is None)

    check = apply_update(
        base,
        _update(ActivityCheckItem(activity_id=NEXT, state=ActivityCheck.NOT_STARTED, confirmed_on=date(2026, 10, 11))),
    )
    c.check(
        "현장 확인은 지도에 남지만 계산 값(실적)은 그대로, 확인만 1건",
        check.snapshot is not None
        and check.snapshot.activities[1].confirmations[0].state is ActivityCheck.NOT_STARTED
        and check.snapshot.activities[1].actual_start is None
        and check.diff.confirmed_only == 1
        and not check.diff.changed,
    )
    contradict = apply_update(
        base,
        _update(ActivityCheckItem(activity_id=WORK, state=ActivityCheck.NOT_STARTED, confirmed_on=date(2026, 10, 20))),
    )
    c.check("실제 착수일이 있는데 미착수 확인이면 거부", contradict.snapshot is None)
    no_date = apply_update(
        base,
        _update(ActivityCheckItem(activity_id=NEXT, state=ActivityCheck.IN_PROGRESS, confirmed_on=date(2026, 10, 20))),
    )
    c.check("실제 착수일 없이 진행 중 확인은 거부(날짜를 넣어야 계산에 반영)", no_date.snapshot is None)
    c.check("가장 뒤 단계 = 관측·진입일 중 최댓값", highest_status(base.purchase_orders[0]) is POStatus.ORDERED)

    c.section("자료 날짜: 최신 날짜와 7일 이상 미확인 발주")
    today = date(2026, 10, 20)
    before = freshness(base, today)
    c.check(
        "발주 최신 9-05, 입고 전 발주 1건 중 오래됨 1건, 공정 최신 = 실적 착수 10-14",
        (before.po_latest, before.open_orders, before.stale_orders, before.activity_latest)
        == (date(2026, 9, 5), 1, 1, date(2026, 10, 14)),
    )
    seen = apply_update(base, _update(POStatusItem(po_id=PO, status=POStatus.ORDERED, observed_on=today))).snapshot
    assert seen is not None
    after = freshness(seen, today)
    c.check("오늘 확인하면 오래된 발주 0건·최신 날짜 = 오늘", (after.po_latest, after.stale_orders) == (today, 0))
    received = apply_update(
        base, _update(POStatusItem(po_id=PO, status=POStatus.RECEIVED, observed_on=date(2026, 9, 30)))
    )
    assert received.snapshot is not None
    c.check("입고한 발주는 더 바뀌지 않아 오래됨 수에서 빠짐", freshness(received.snapshot, today).open_orders == 0)
    c.check("오늘 뒤 날짜는 세지 않음", freshness(base, date(2026, 9, 3)).po_latest == date(2026, 9, 2))
