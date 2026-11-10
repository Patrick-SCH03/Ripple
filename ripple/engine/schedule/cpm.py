"""전진 계산과 가장 늦은 착수일(docs/engine.md(비용·일정) 6-2·6-3·6-5).

공정은 [ES, EF)를 차지하고(EF = ES + 기간), 후행은 ES ≥ EF(선행) + lag. 착수 전 공정은 계획 착수일과
기준일 다음 날보다 이르지 않다. 변경 일정은 기준 일정에 조정(Adjustments)을 더해 같은 함수로 계산한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from types import MappingProxyType

from .network import Network

ONE_DAY = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class Adjustments:
    """변경 일정의 조정. 비어 있으면 기준 일정이다."""

    extra_days: Mapping[str, int] = field(default_factory=dict)  # 공정 → 더하는 기간(재작업)
    extra_lag: Mapping[tuple[str, str], int] = field(default_factory=dict)  # (선행, 후행) → 더하는 lag
    start_floor: Mapping[str, date] = field(default_factory=dict)  # 착수 전 공정 → ES 하한(자재 도착)
    finish_floor: Mapping[str, date] = field(default_factory=dict)  # 공정 → EF 하한(재작업은 자재가 와야 시작)


NO_ADJUSTMENTS = Adjustments()


@dataclass(frozen=True, slots=True)
class Times:
    es: Mapping[str, date]
    ef: Mapping[str, date]
    driver: Mapping[str, str | None]  # ES를 정한 선행(계획·기준일·자재가 정했으면 None)


def forward(net: Network, adjustments: Adjustments = NO_ADJUSTMENTS) -> Times:
    es: dict[str, date] = {}
    ef: dict[str, date] = {}
    driver: dict[str, str | None] = {}
    tomorrow = net.as_of + ONE_DAY
    for a_id in net.order:
        node = net.nodes[a_id]
        extra = timedelta(days=adjustments.extra_days.get(a_id, 0))
        if node.finished is not None and node.started is not None:
            es[a_id], ef[a_id], driver[a_id] = node.started, node.finished, None
            continue
        if node.started is not None:
            start = node.started
            finish = max(start + timedelta(days=node.duration), tomorrow) + extra
            driver[a_id] = None
        else:
            ready = [
                (ef[pred] + timedelta(days=lag + adjustments.extra_lag.get((pred, a_id), 0)), pred)
                for pred, lag in node.preds
            ]
            floors = [node.planned_start, tomorrow]
            if a_id in adjustments.start_floor:
                floors.append(adjustments.start_floor[a_id])
            best_pred = min(ready, key=lambda item: (-item[0].toordinal(), item[1]), default=None)
            start = max([*floors, *(day for day, _ in ready)])
            driver[a_id] = best_pred[1] if best_pred is not None and best_pred[0] == start else None
            finish = start + timedelta(days=node.duration) + extra
        if a_id in adjustments.finish_floor:
            finish = max(finish, adjustments.finish_floor[a_id])
        es[a_id], ef[a_id] = start, finish
    return Times(es=MappingProxyType(es), ef=MappingProxyType(ef), driver=MappingProxyType(driver))


def latest_starts(net: Network, base: Times) -> dict[str, date]:
    """블록 탑재일을 늦추지 않는 가장 늦은 착수일. 블록 공정 사슬만 거슬러 계산한다."""
    latest: dict[str, date] = {}
    for chain in net.chains.values():
        finish = base.ef[chain[-1]]
        for position in range(len(chain) - 1, -1, -1):
            a_id = chain[position]
            node = net.nodes[a_id]
            if position < len(chain) - 1:
                nxt = chain[position + 1]
                lag = next((lag for pred, lag in net.nodes[nxt].preds if pred == a_id), 0)
                finish = latest[nxt] - timedelta(days=lag)
            latest[a_id] = finish - timedelta(days=node.duration)
    return latest


def driving_path(times: Times, end: str) -> tuple[str, ...]:
    """end에서 ES를 정한 선행을 따라 거슬러 올라간 공정 목록(앞에서 뒤 순서)."""
    path = [end]
    current = times.driver.get(end)
    while current is not None:
        path.append(current)
        current = times.driver.get(current)
    return tuple(reversed(path))
