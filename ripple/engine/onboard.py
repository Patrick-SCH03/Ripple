"""의장품 선상 설치(docs/engine.md(비용·일정) 6-3·6-8): 배 위로 보낼 수요를 고르고, 다른 실행 방식과의 비교를 만든다.

후보 = 판정일에 소비 공정이 끝나지 않았고(착수 전 또는 진행 중 — 선행의장 중이어도 아직 달지 않은 배관은 배 위로
돌릴 수 있다, 엔진 0.12.0) 탑재가 착수 전인 배관·밸브·배관 부속 수요. 그중 그대로 두면 탑재를 계획보다, 그리고 다른
이유(나머지 수요·재작업)보다 더 늦추는 것만 배 위로 보낸다(진행 중 소비 공정의 후보는 관문에 두면 생기는 재작업 관문
max(t + 1, 도착일) + d_B로 견준다 — _left_gate). 일정 위험(6-6)은 대표 일정이 고른 수요를 그대로 쓴다
(리드타임만 늘려 다시 고르면 고른 묶음이 바뀌어 위험 일정이 대표보다 이를 수 있어서).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from ripple.contracts.domain import ActivityKind
from ripple.contracts.result import Amount, OnboardDirection, OnboardOption, additional_loss_of

from .cost.demand import Demand
from .cost.onboard import CATEGORIES, OnboardBlock
from .schedule import Network, Times

ONE_DAY = timedelta(days=1)
DemandKey = tuple[str, str | None]


def demand_key(demand: Demand) -> DemandKey:
    return demand.part_id, demand.line_id


def onboard_demands(
    net: Network,
    base: Times,
    needed: tuple[Demand, ...],
    rework_days: Mapping[str, int],
    day: date,
    fixed: Collection[DemandKey] | None = None,
) -> dict[str, tuple[tuple[Demand, ...], str]]:
    """블록 → (선상 설치 수요(부재 ID 순), 탑재 공정). fixed가 있으면 그 수요만(후보 조건은 그대로 본다)."""
    candidates: dict[str, list[Demand]] = {}
    others: dict[str, list[date]] = {}
    started: dict[str, list[date]] = {}
    in_progress: set[DemandKey] = set()  # 소비 공정이 판정일에 진행 중인 후보
    for demand in needed:
        if demand.consumer is None or demand.arrival is None or demand.consumer not in net.nodes:
            continue
        block = net.nodes[demand.consumer].block_id or ""
        open_consumer = base.ef[demand.consumer] > day  # 소비 공정이 판정일에 끝나지 않음(착수 전 또는 진행 중)
        if demand.category in CATEGORIES and open_consumer and _erection(net, base, block, day) is not None:
            candidates.setdefault(block, []).append(demand)
            if base.es[demand.consumer] <= day:
                in_progress.add(demand_key(demand))
        elif base.es[demand.consumer] <= day:
            started.setdefault(block, []).append(demand.arrival)
        else:
            others.setdefault(block, []).append(demand.arrival + ONE_DAY)
    found: dict[str, tuple[tuple[Demand, ...], str]] = {}
    for block, items in sorted(candidates.items()):
        erection = _erection(net, base, block, day)
        assert erection is not None
        if fixed is not None:
            chosen = [d for d in items if demand_key(d) in fixed]
        else:
            limit = max([base.es[erection], *others.get(block, []), *_rework_gate(block, rework_days, started, day)])
            d_b = rework_days.get(block, 0)
            chosen = [d for d in items if (g := _left_gate(d, demand_key(d) in in_progress, d_b, day)) and g > limit]
        if chosen:
            found[block] = (tuple(sorted(chosen, key=lambda d: (d.part_id, d.line_id or ""))), erection)
    return found


def _left_gate(demand: Demand, in_progress: bool, d_b: int, day: date) -> date | None:
    """후보를 배 위로 보내지 않고 관문에 두면 생기는 값(6-3): 착수 전 소비 공정이면 도착일 + 1, 진행 중이면 재작업 관문
    max(t + 1, 도착일) + d_B(재작업이 없으면 관문을 만들지 않아 None — 늦추지 않으므로 고르지 않는다)."""
    if demand.arrival is None:
        return None
    if not in_progress:
        return demand.arrival + ONE_DAY
    return max(day + ONE_DAY, demand.arrival) + timedelta(days=d_b) if d_b > 0 else None


def _erection(net: Network, base: Times, block: str, day: date) -> str | None:
    """판정일에 착수 전인 그 블록 탑재 공정(사슬 끝이 탑재가 아니거나 이미 탑재했으면 None)."""
    chain = net.chains.get(block)
    if not chain or net.nodes[chain[-1]].kind is not ActivityKind.ERECTION or base.es[chain[-1]] <= day:
        return None
    return chain[-1]


def _rework_gate(
    block: str, rework_days: Mapping[str, int], started: Mapping[str, list[date]], day: date
) -> list[date]:
    """재작업 관문 R_B = max(t + 1, 이미 착수한 소비 공정으로 가는 수요의 도착일) + d_B(6-3, 재작업이 있을 때만)."""
    d = rework_days.get(block, 0)
    if d <= 0:
        return []
    return [max([day + ONE_DAY, *started.get(block, [])]) + timedelta(days=d)]


@dataclass(frozen=True, slots=True)
class Outcome:
    """한 실행 방식의 확정일 평가에서 비교에 쓰는 값(6-8)."""

    total: Amount
    erection_delay: int  # 대상 블록 탑재 지연의 최댓값
    exit_delay: int  # 구역 출구 지연 최댓값
    delivery_added: int | None  # 늘어난 인도 지연(None = 계산 불가)


def onboard_option(on_board: bool, blocks: Mapping[str, OnboardBlock], now: Outcome, then: Outcome) -> OnboardOption:
    """지금 방식(now)과 다른 방식(then)을 같은 확정일·보류로 평가한 값의 비교(6-8)."""
    return OnboardOption(
        direction=OnboardDirection.TO_WAIT if on_board else OnboardDirection.TO_ON_BOARD,
        block_ids=tuple(sorted(blocks)),
        part_ids=tuple(sorted({d.part_id for b in blocks.values() for d in b.demands})),
        on_board_days=max(b.days for b in blocks.values()),
        total_change=additional_loss_of(then.total, now.total),
        erection_delay_now_days=now.erection_delay,
        erection_delay_then_days=then.erection_delay,
        exit_delay_now_days=now.exit_delay,
        exit_delay_then_days=then.exit_delay,
        delivery_added_now_days=now.delivery_added,
        delivery_added_then_days=then.delivery_added,
    )
