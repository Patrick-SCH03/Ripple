"""일정 엔진(docs/engine.md(비용·일정) 6절): 전진 계산·가장 늦은 착수일·인도 지연·공정 시계."""

from __future__ import annotations

import random
from datetime import date, timedelta
from itertools import pairwise

from harness import Checker

from ripple.contracts.domain import ActivityKind
from ripple.engine.index import GraphIndex
from ripple.engine.schedule import (
    NO_ADJUSTMENTS,
    Adjustments,
    Baseline,
    Network,
    Node,
    Times,
    delivery_outcome,
    driving_path,
    forward,
    latest_starts,
)
from ripple.engine.schedule.network import assemble
from ripple.generator.build import generate
from ripple.generator.io import load_config

DAY = timedelta(days=1)


def run(c: Checker) -> None:
    _random_networks(c)
    _random_chains(c)
    snapshot = generate(load_config()).snapshot
    index = GraphIndex(snapshot)
    as_of = load_config().scenario_date
    baseline = Baseline(index, as_of)
    _real_map(c, index, baseline)
    _latest_starts(c, baseline)
    _delivery(c, index, baseline)


# ---------- 무작위 망 ----------


def _random_network(rng: random.Random) -> tuple[Network, Adjustments]:
    base = date(2026, 1, 1)
    as_of = base + timedelta(days=rng.randint(0, 15))
    nodes: list[Node] = []
    finish_of: dict[str, date | None] = {}
    for i in range(rng.randint(2, 10)):
        a_id = f"A{i:02d}"
        earlier = [n.activity_id for n in nodes]
        preds = tuple(sorted((p, rng.randint(0, 3)) for p in rng.sample(earlier, rng.randint(0, min(3, len(earlier))))))
        duration = rng.randint(0, 10)
        planned = base + timedelta(days=rng.randint(0, 20))
        started: date | None = None
        finished: date | None = None
        done = [f for f in (finish_of[p] for p, _ in preds) if f is not None]
        ready = len(done) == len(preds) and all(f <= as_of for f in done)
        if ready and rng.random() < 0.4:
            started = min(as_of, planned + timedelta(days=rng.randint(0, 3)))
            if all(f <= started for f in done):
                end = started + timedelta(days=duration)
                finished = end if end <= as_of and rng.random() < 0.7 else None
            else:
                started = None
        finish_of[a_id] = finished
        nodes.append(Node(a_id, None, ActivityKind.ASSEMBLY, duration, planned, preds, started, finished))
    ids = [n.activity_id for n in nodes]

    def pick(k: int) -> list[str]:
        return rng.sample(ids, min(k, len(ids)))

    edges = [(p, n.activity_id) for n in nodes for p, _ in n.preds]
    adjustments = Adjustments(
        extra_days={a: rng.randint(1, 6) for a in pick(rng.randint(0, 3))},
        extra_lag={e: rng.randint(1, 4) for e in rng.sample(edges, min(len(edges), rng.randint(0, 2)))},
        start_floor={a: as_of + timedelta(days=rng.randint(1, 30)) for a in pick(rng.randint(0, 2))},
        finish_floor={a: as_of + timedelta(days=rng.randint(1, 40)) for a in pick(rng.randint(0, 2))},
    )
    return assemble("S-X", as_of, nodes), adjustments


def _feasible_and_tight(net: Network, adj: Adjustments, times: Times) -> bool:
    """전진 계산 결과가 모든 제약을 지키고(가능), 착수 전 공정마다 묶인 제약이 하나 있다(가장 이름)."""
    tomorrow = net.as_of + DAY
    for a_id, node in net.nodes.items():
        es, ef = times.es[a_id], times.ef[a_id]
        extra = timedelta(days=adj.extra_days.get(a_id, 0))
        if node.finished is not None:
            if (es, ef) != (node.started, node.finished):
                return False
            continue
        if node.started is not None:
            expected = max(node.started + timedelta(days=node.duration), tomorrow) + extra
            expected = max(expected, adj.finish_floor.get(a_id, expected))
            if es != node.started or ef != expected:
                return False
            continue
        bounds = [node.planned_start, tomorrow]
        bounds += [adj.start_floor[a_id]] if a_id in adj.start_floor else []
        bounds += [times.ef[p] + timedelta(days=lag + adj.extra_lag.get((p, a_id), 0)) for p, lag in node.preds]
        if es != max(bounds) or es not in bounds:
            return False
        natural = es + timedelta(days=node.duration) + extra
        if ef != max(natural, adj.finish_floor.get(a_id, natural)):
            return False
    return True


def _recursive(net: Network, adj: Adjustments) -> dict[str, date]:
    """같은 정의를 메모 없이 위에서 아래로 다시 계산한다(순서·동률 처리와 무관한 기준값)."""
    tomorrow = net.as_of + DAY

    def ef(a_id: str) -> date:
        node = net.nodes[a_id]
        extra = timedelta(days=adj.extra_days.get(a_id, 0))
        if node.finished is not None:
            return node.finished
        if node.started is not None:
            value = max(node.started + timedelta(days=node.duration), tomorrow) + extra
        else:
            starts = [node.planned_start, tomorrow, *([adj.start_floor[a_id]] if a_id in adj.start_floor else [])]
            starts += [ef(p) + timedelta(days=lag + adj.extra_lag.get((p, a_id), 0)) for p, lag in node.preds]
            value = max(starts) + timedelta(days=node.duration) + extra
        return max(value, adj.finish_floor.get(a_id, value))

    return {a_id: ef(a_id) for a_id in net.nodes}


def _random_chains(c: Checker) -> None:
    """블록 공정 사슬(lag 포함)에서 LS에 착수하면 탑재가 그대로, 하루 늦으면 정확히 하루 늦음."""
    rng = random.Random(41)
    kinds = (ActivityKind.SUB_ASSEMBLY, ActivityKind.PANEL, ActivityKind.ASSEMBLY, ActivityKind.ERECTION)
    ok = total = 0
    for _ in range(200):
        as_of = date(2026, 1, 1)
        nodes: list[Node] = []
        for i, kind in enumerate(kinds):
            preds = () if i == 0 else ((nodes[-1].activity_id, rng.randint(0, 4)),)
            planned = as_of + timedelta(days=5 + 6 * i + rng.randint(0, 6))
            nodes.append(Node(f"B:{kind.value}", "B", kind, rng.randint(1, 8), planned, preds, None, None))
        net = assemble("S-X", as_of, nodes)
        base = forward(net)
        latest = latest_starts(net, base)
        erection = net.chains["B"][-1]
        for a_id in net.chains["B"][:-1]:
            total += 1
            on_time = forward(net, Adjustments(start_floor={a_id: latest[a_id]})).ef[erection] == base.ef[erection]
            late = (
                forward(net, Adjustments(start_floor={a_id: latest[a_id] + DAY})).ef[erection] - base.ef[erection]
            ).days
            ok += on_time and late == 1
    c.check(
        f"무작위 블록 사슬(lag 포함) {total}개 공정: LS에 착수하면 탑재 그대로, 하루 늦으면 정확히 하루", ok == total
    )


def _random_networks(c: Checker) -> None:
    c.section("일정: 무작위 망 전진 계산")
    rng = random.Random(20261007)
    feasible = same = monotone = fixed = drivers = 0
    total = 300
    for _ in range(total):
        net, adj = _random_network(rng)
        base, changed = forward(net), forward(net, adj)
        feasible += _feasible_and_tight(net, NO_ADJUSTMENTS, base) and _feasible_and_tight(net, adj, changed)
        same += dict(changed.ef) == _recursive(net, adj) and dict(base.ef) == _recursive(net, NO_ADJUSTMENTS)
        monotone += all(changed.ef[a] >= base.ef[a] and changed.es[a] >= base.es[a] for a in net.nodes)
        fixed += all(
            (changed.es[a], changed.ef[a]) == (n.started, n.finished) for a, n in net.nodes.items() if n.finished
        )
        drivers += all(
            changed.driver[a] is None
            or changed.es[a]
            == changed.ef[changed.driver[a] or ""]
            + timedelta(
                days=dict(net.nodes[a].preds)[changed.driver[a] or ""]
                + adj.extra_lag.get((changed.driver[a] or "", a), 0)
            )
            for a in net.nodes
        )
    c.check(
        f"무작위 망 {total}개: 모든 제약을 지키고 착수 전 공정마다 묶인 제약이 있음(가장 이른 일정)",
        feasible == total,
    )
    c.check("위에서 아래로 다시 계산한 값과 같음(조정 있는 경우·없는 경우)", same == total, same)
    c.check("조정(재작업·자재·lag)을 더하면 어떤 공정도 기준 일정보다 이르지 않음", monotone == total)
    c.check("기준일까지 끝난 공정은 실적 그대로", fixed == total)
    c.check("ES를 정한 선행은 실제로 그 날짜를 만든 선행", drivers == total)


# ---------- 합성 지도 ----------


def _real_map(c: Checker, index: GraphIndex, baseline: Baseline) -> None:
    c.section("일정: 합성 지도 기준 일정")
    schedule = baseline.ships["S-001"]
    net, base = schedule.network, schedule.base
    milestones = {a.activity_id for a in index.activities.values() if a.kind is ActivityKind.MILESTONE}
    c.check(
        "망 = 블록 공정 + 구역 출구 3개(진수·시운전·인도 이정표는 경계 조건으로 대신)",
        set(net.exits) == {"S-001:ZCT:exit", "S-001:ZER:exit", "S-001:ZFO:exit"}
        and milestones - set(net.nodes) == {"S-001:launch", "S-001:sea_trial", "S-001:delivery"},
        net.exits,
    )
    c.check("기준 일정이 계획 착수일·선행 조건·실적을 모두 지킴", _feasible_and_tight(net, NO_ADJUSTMENTS, base))
    t31c = "S-001:T31C"
    assembly, outfit = f"{t31c}:assembly", f"{t31c}:pre_outfitting"
    c.check(
        "앞 공정 지연을 넘김: T31C 조립이 늦게 끝나면 선행의장은 계획일이 아니라 조립 완료일에 착수",
        base.es[outfit] == max(base.ef[assembly], net.nodes[outfit].planned_start)
        and base.es[outfit] > net.nodes[outfit].planned_start,
        (base.ef[assembly], net.nodes[outfit].planned_start, base.es[outfit]),
    )
    clock = baseline.start(outfit)
    c.check(
        "상태 함수의 공정 시계 = 기준 일정 착수일(착수 전이면 ES⁰, 착수했으면 실적)",
        clock.expected == base.es[outfit]
        and clock.actual is None
        and baseline.start(assembly).actual == net.nodes[assembly].started,
    )
    c.check(
        "망에 없는 이정표는 1단계 시계 규칙(계획 착수일)",
        baseline.start("S-001:delivery").expected == index.activities["S-001:delivery"].planned_start,
    )
    path = driving_path(base, "S-001:ZCT:exit")
    c.check(
        "주 경로는 출구에서 ES를 정한 선행을 따라 거슬러 올라감",
        path[-1] == "S-001:ZCT:exit" and all(base.driver[b] == a for a, b in pairwise(path)),
        path,
    )


def _latest_starts(c: Checker, baseline: Baseline) -> None:
    c.section("일정: 가장 늦은 착수일(탑재일 고정)")
    schedule = baseline.ships["S-001"]
    net, base, latest = schedule.network, schedule.base, schedule.latest
    pending = [a for chain in net.chains.values() for a in chain if net.nodes[a].started is None and a != chain[-1]]
    c.check("착수 전 블록 공정마다 LS ≥ 기준 착수일", all(latest[a] >= base.es[a] for a in pending), len(pending))
    on_time = late_by_one = 0
    for a_id in pending:
        chain = next(ch for ch in net.chains.values() if a_id in ch)
        erection = chain[-1]
        held = forward(net, Adjustments(start_floor={a_id: latest[a_id]}))
        later = forward(net, Adjustments(start_floor={a_id: latest[a_id] + DAY}))
        on_time += held.ef[erection] == base.ef[erection]
        late_by_one += (later.ef[erection] - base.ef[erection]).days == 1
    c.check(
        f"LS에 착수하면 탑재일이 그대로, 하루 늦으면 탑재가 정확히 하루 늦음(공정 {len(pending)}개)",
        on_time == late_by_one == len(pending),
        (on_time, late_by_one, len(pending)),
    )


def _delivery(c: Checker, index: GraphIndex, baseline: Baseline) -> None:
    c.section("일정: 인도 지연(경계 조건)")
    schedule = baseline.ships["S-001"]
    net, base = schedule.network, schedule.base
    same = delivery_outcome(index, net, base, base)
    c.check("변경이 없으면 늘어난 인도 지연 0", same.added == 0 and not any(same.exit_delays.values()))
    exit_id = "S-001:ZER:exit"
    boundary = next(b for b in index.snapshot.boundaries if b.exit_activity_id == exit_id)
    erection = max((p for p, _ in net.nodes[exit_id].preds), key=lambda p: (base.ef[p], p))  # 출구를 정하는 탑재
    late_before = max(0, (base.ef[exit_id] - net.nodes[exit_id].planned_start).days)
    ok = True
    for extra in (1, boundary.float_to_delivery_days, boundary.float_to_delivery_days + 9):
        changed = forward(net, Adjustments(extra_days={erection: extra}))
        outcome = delivery_outcome(index, net, base, changed)
        d = outcome.exit_delays[exit_id]
        others = max(
            [0]
            + [
                max(0, (base.ef[b.exit_activity_id] - net.nodes[b.exit_activity_id].planned_start).days)
                - b.float_to_delivery_days
                for b in index.snapshot.boundaries
                if b.exit_activity_id != exit_id
            ]
        )
        before = max(others, late_before - boundary.float_to_delivery_days)
        after = max(others, late_before + d - boundary.float_to_delivery_days)
        ok &= outcome.before == before and outcome.after == after and d >= 0
    c.check("출구 지연이 여유를 넘는 만큼만 인도 지연이 늘어남(여유 안·경계·초과 세 경우 손 계산과 같음)", ok)
    bare = GraphIndex(
        index.snapshot.model_copy(
            update={"boundaries": tuple(b for b in index.snapshot.boundaries if b.exit_activity_id != exit_id)}
        )
    )
    changed = forward(net, Adjustments(extra_days={erection: 5}))
    missing = delivery_outcome(bare, net, base, changed)
    c.check(
        "경계 조건이 없는 구역 출구가 늦어지면 인도 지연은 계산 불가",
        missing.before is None and missing.after is None and missing.missing_boundary == (exit_id,),
    )
    untouched = delivery_outcome(bare, net, base, base)
    c.check("경계 조건이 없어도 그 구역이 늦어지지 않으면 계산함", untouched.added == 0)
