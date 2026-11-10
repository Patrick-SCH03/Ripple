"""시연 합성 지도의 블록 사이 관계 보강(docs/data.md(생성기) 12절).

기본 지도를 다 만든 뒤(설계변경 이력까지) 설정 relations대로 관계만 더한다. 난수를 쓰지 않아 부재·발주·공정 날짜·
설계변경은 기본 지도와 같고, 지도 ID만 달라진다.

- 탑재 순서(erection_after): 후행 블록 탑재의 선행에 선행 블록 탑재(lag 0)를 더한다. 계획 날짜가 이 순서와 맞아야
  한다(후행 탑재 착수 계획일 ≥ 선행 탑재 완료 계획일) — 어긋나면 생성을 멈춘다(지도가 자기모순이 되지 않게).
"""

from __future__ import annotations

from datetime import timedelta

from ripple.contracts.domain import Activity, ActivityKind, GraphSnapshot, Precedence

from . import ids
from .config import RelationsConfig


class RelationsError(ValueError):
    """관계 보강이 지도와 맞지 않는다(계획 날짜가 탑재 순서와 어긋남 등)."""


def relate(relations: RelationsConfig, snapshot: GraphSnapshot, ship_id: str) -> GraphSnapshot:
    """관계를 더한 지도(지도 ID는 호출자가 다시 정한다)."""
    activities = {a.activity_id: a for a in snapshot.activities}
    added: dict[str, list[str]] = {}
    problems: list[str] = []
    for after, befores in sorted(relations.erection_after.items()):
        succ_id = ids.activity_id(ship_id, after, ActivityKind.ERECTION)
        succ = activities[succ_id]
        for before in sorted(befores):
            pred = activities[ids.activity_id(ship_id, before, ActivityKind.ERECTION)]
            finish = pred.planned_start + timedelta(days=pred.duration_days)
            if succ.planned_start < finish:
                problems.append(f"{after} 탑재 계획 {succ.planned_start} < {before} 탑재 완료 계획 {finish}")
            added.setdefault(succ_id, []).append(pred.activity_id)
    if problems:
        raise RelationsError("탑재 순서와 계획 날짜가 어긋나요: " + "; ".join(problems))
    return snapshot.model_copy(update={"activities": tuple(_with_preds(a, added) for a in snapshot.activities)})


def _with_preds(activity: Activity, added: dict[str, list[str]]) -> Activity:
    extra = added.get(activity.activity_id)
    if not extra:
        return activity
    have = {p.activity_id for p in activity.predecessors}
    preds = (*activity.predecessors, *(Precedence(activity_id=a) for a in extra if a not in have))
    return activity.model_copy(update={"predecessors": preds})
