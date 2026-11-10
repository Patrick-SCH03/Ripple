"""합성 생성기의 성질: 결정적이고, 참조가 끊기지 않고, 데모 조건이 성립한다."""

from __future__ import annotations

import re
import tempfile
from collections import Counter, deque
from datetime import date
from pathlib import Path

from harness import Checker

from ripple.config.loaders import load_lexicon
from ripple.config.settings import Settings
from ripple.contracts.change import (
    AddPart,
    AddPenetration,
    ChangeRequest,
    EquipmentSpecChange,
    GradeChange,
    RemovePart,
    ReroutePipe,
    ThicknessChange,
)
from ripple.contracts.dataset import EcnSplit, NlSplit
from ripple.contracts.domain import ActivityKind, GraphSnapshot, PartKind, POStatus
from ripple.contracts.identity import snapshot_id
from ripple.engine.describe import describe
from ripple.engine.index import GraphIndex
from ripple.engine.overlay import ChangeView
from ripple.generator.build import Generated, demo_problems, generate
from ripple.generator.ecn import make_ecns
from ripple.generator.io import load_config, write_outputs
from ripple.generator.nl import load_nl_lexicon, nl_samples
from ripple.generator.structure import VALVE_LABELS, VALVE_TYPES


def run(c: Checker) -> None:
    config = load_config()
    first = generate(config)
    _determinism(c, config.seed, first)
    _integrity(c, first.snapshot)
    _schedule(c, first.snapshot, config.scenario_date)
    _demo(c, first)
    _ecns(c, first)
    _field_names(c, first)


def _determinism(c: Checker, seed: int, first: Generated) -> None:
    c.section("생성기: 결정성·규모")
    config = load_config()
    second = generate(config)
    c.check("같은 시드면 지도와 설계변경이 같음", first.snapshot == second.snapshot and first.ecns == second.ecns)
    with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
        written = write_outputs(first, Path(left))
        write_outputs(second, Path(right))
        same = all((Path(right) / p.name).read_bytes() == p.read_bytes() for p in written)
    c.check("같은 시드면 출력 파일 바이트가 같음", same)
    other = generate(config, seed=seed + 1)
    c.check("다른 시드면 다른 지도", other.snapshot.snapshot_id != first.snapshot.snapshot_id)
    snapshot = first.snapshot
    c.check("스냅샷 ID는 내용 해시", snapshot.snapshot_id == snapshot_id(snapshot))
    c.check("부재 500~1,000개(설계 규모)", 500 <= len(snapshot.parts) <= 1000, len(snapshot.parts))
    c.check("발주 100건 이상(설계 규모)", len(snapshot.purchase_orders) >= 100, len(snapshot.purchase_orders))
    c.check("블록 10~15개(설계 규모)", 10 <= len(snapshot.blocks) <= 15, len(snapshot.blocks))
    splits = Counter(e.split for e in first.ecns)
    c.check("설계변경 개발 200 · 평가 100", splits == Counter({EcnSplit.DEV: 200, EcnSplit.EVAL: 100}), splits)


def _integrity(c: Checker, snapshot: GraphSnapshot) -> None:
    c.section("생성기: 참조 무결성")
    parts = {p.part_id for p in snapshot.parts}
    blocks = {b.block_id for b in snapshot.blocks}
    specs = {s.spec_id for s in snapshot.specs}
    drawings = {(d.drawing_no, d.revision) for d in snapshot.drawings}
    activities = {a.activity_id for a in snapshot.activities}
    orders = {p.po_id for p in snapshot.purchase_orders}
    c.check(
        "부재의 블록·규격·도면이 모두 있음",
        all(
            p.block_id in blocks and p.spec_id in specs and (p.drawing_no, p.revision) in drawings
            for p in snapshot.parts
        ),
    )
    c.check("연결의 양 끝 부재가 모두 있음", all(x.a in parts and x.b in parts for x in snapshot.connections))
    c.check(
        "발주 품목의 발주·규격·부재·소비 공정이 모두 있음",
        all(
            li.po_id in orders
            and li.spec_id in specs
            and set(li.part_ids) <= parts
            and li.consumed_by_activity_id in activities
            for li in snapshot.po_lines
        ),
    )
    supplied = Counter(part_id for li in snapshot.po_lines for part_id in li.part_ids)
    c.check(
        "모든 부재가 발주 품목 하나에 정확히 한 번 들어감", set(supplied) == parts and set(supplied.values()) == {1}
    )
    c.check("발주마다 품목이 하나 이상", {li.po_id for li in snapshot.po_lines} == orders)
    c.check(
        "공정의 선행 공정·블록이 모두 있음",
        all(
            all(p.activity_id in activities for p in a.predecessors) and (a.block_id is None or a.block_id in blocks)
            for a in snapshot.activities
        ),
    )
    zones = {z.zone_id for z in snapshot.zones}
    c.check(
        "경계 조건의 구역·출구 이정표가 있고 구역마다 하나",
        all(b.zone_id in zones and b.exit_activity_id in activities for b in snapshot.boundaries)
        and {b.zone_id for b in snapshot.boundaries} == zones,
    )
    c.check(
        "재고의 규격·예약 블록이 있음",
        all(
            s.spec_id in specs and (s.reserved_block_id is None or s.reserved_block_id in blocks)
            for s in snapshot.stock
        ),
    )
    connected = [s for s in snapshot.specs if s.category in {"pipe", "valve"}]
    c.check(
        "배관·밸브 규격에 연결 규격(구경·압력 등급)이 있음",
        bool(connected) and all(s.nominal_diameter_dn is not None and s.pressure_class is not None for s in connected),
    )


def _schedule(c: Checker, snapshot: GraphSnapshot, as_of: date) -> None:
    c.section("생성기: 일정")
    by_id = {a.activity_id: a for a in snapshot.activities}
    indegree = {a.activity_id: len(a.predecessors) for a in snapshot.activities}
    successors: dict[str, list[str]] = {a.activity_id: [] for a in snapshot.activities}
    for activity in snapshot.activities:
        for predecessor in activity.predecessors:
            successors[predecessor.activity_id].append(activity.activity_id)
    queue = deque(sorted(k for k, v in indegree.items() if v == 0))
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for nxt in successors[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    c.check("공정 선후행 그래프에 순환이 없음", visited == len(snapshot.activities))
    c.check(
        "실제 착수·완료일은 기준일 이전",
        all(
            (a.actual_start is None or a.actual_start <= as_of)
            and (a.actual_finish is None or a.actual_finish <= as_of)
            for a in snapshot.activities
        ),
    )

    def finished_before(predecessor_id: str, start: date) -> bool:
        finish = by_id[predecessor_id].actual_finish
        return finish is not None and finish <= start

    ordered = all(
        all(finished_before(p.activity_id, a.actual_start) for p in a.predecessors)
        for a in snapshot.activities
        if a.kind is not ActivityKind.MILESTONE and a.actual_start is not None
    )
    c.check("블록 공정은 앞 공정이 끝난 뒤에 실제 착수", ordered)
    delivery = next(a for a in snapshot.activities if a.activity_id.endswith(":delivery"))
    c.check("인도 이정표 = 계약 인도일", delivery.planned_start == snapshot.ships[0].delivery_date)
    c.check("경계 조건의 여유는 0 이상", all(b.float_to_delivery_days >= 0 for b in snapshot.boundaries))


def _demo(c: Checker, generated: Generated) -> None:
    c.section("생성기: 데모 조건과 발주 근거")
    config = load_config()
    problems = demo_problems(config, generated.snapshot)
    c.check("데모 고정점(T31C 조립 중·판 가공, P11C 미착수·밸브 미발주, 선수부 미착수)이 성립", not problems, problems)
    orders = generated.snapshot.purchase_orders
    c.check("확인된 진입일이 있는 발주가 있음", any(p.entered_on for p in orders))
    c.check(
        "확인된 진입일이 있는 발주는 기준일 상태 관측도 가짐(발주대장 내보내기)",
        all(any(o.observed_on == config.scenario_date for o in p.observations) for p in orders if p.entered_on),
    )
    c.check("관측만 있는 발주가 있음", any(p.observations and not p.entered_on for p in orders))
    c.check(
        "정보가 없는 발주(판단 불가 시험용)가 있음",
        any(p.planned_order_date is None and not p.entered_on and not p.observations for p in orders),
    )
    c.check(
        "입고까지 끝난 발주와 아직 발주 전인 발주가 함께 있음",
        any(POStatus.RECEIVED in p.entered_on for p in orders)
        and any(p.planned_order_date is not None and p.planned_order_date > config.scenario_date for p in orders),
    )


def _ecns(c: Checker, generated: Generated) -> None:
    c.section("생성기: 설계변경 사례")
    snapshot = generated.snapshot
    parts = {p.part_id: p for p in snapshot.parts}
    specs = {s.spec_id for s in snapshot.specs}
    blocks = {b.block_id for b in snapshot.blocks}
    ids = [e.change.ecn_id for e in generated.ecns]
    c.check("ECN 번호가 겹치지 않음", len(ids) == len(set(ids)))
    dev_ops = {op.op for e in generated.ecns if e.split is EcnSplit.DEV for op in e.change.ops}
    c.check("개발 분할에 연산 8종이 모두 있음", len(dev_ops) == 8, sorted(dev_ops))
    problems = []
    for ecn in generated.ecns:
        for op in ecn.change.ops:
            if isinstance(op, ThicknessChange) and any(parts[p].thickness_mm != op.from_mm for p in op.part_ids):
                problems.append(f"{ecn.change.ecn_id}: 변경 전 두께가 현재와 다름")
            if isinstance(op, GradeChange) and any(parts[p].grade != op.from_grade for p in op.part_ids):
                problems.append(f"{ecn.change.ecn_id}: 변경 전 강종이 현재와 다름")
            if isinstance(op, EquipmentSpecChange) and any(parts[p].spec_id != op.from_spec_id for p in op.part_ids):
                problems.append(f"{ecn.change.ecn_id}: 변경 전 사양이 현재와 다름")
            if isinstance(op, AddPart) and (
                op.block_id not in blocks
                or op.spec_id not in specs
                or (op.attach_to_part_id is not None and op.attach_to_part_id not in parts)
            ):
                problems.append(f"{ecn.change.ecn_id}: 추가 부재의 블록·규격·위치가 없음")
            if isinstance(op, RemovePart | ReroutePipe) and not set(
                op.part_ids if isinstance(op, RemovePart) else op.removed_part_ids
            ) <= set(parts):
                problems.append(f"{ecn.change.ecn_id}: 지울 부재가 없음")
            if isinstance(op, AddPenetration) and not {op.plate_part_id, op.pipe_part_id} <= set(parts):
                problems.append(f"{ecn.change.ecn_id}: 관통부의 판·배관이 없음")
    c.check("설계변경의 대상·변경 전 값이 지도와 맞음", not problems, problems[:3])


def _field_names(c: Checker, generated: Generated) -> None:
    c.section("생성기: 현장 이름(코드 표기 없음)")
    snapshot = generated.snapshot
    keys = sorted({p.system for p in snapshot.parts if p.system})
    # 규격 ID(VL-GLOBE-…)는 대문자 코드라 소문자 영어 종류 이름에 걸리지 않는다
    code = re.compile("|".join(keys) + r"|(?<![A-Za-z])(?:" + "|".join(VALVE_TYPES) + r")(?![A-Za-z])")
    texts = (
        [p.name for p in snapshot.parts]
        + [d.title for d in snapshot.drawings]
        + [s.description for s in snapshot.specs]
        + [e.change.title for e in generated.ecns]
    )
    left = [t for t in texts if code.search(t)]
    c.check("부재 이름·도면 제목·규격 설명·설계변경 제목에 계통 키·영어 밸브 종류가 없음", not left, left[:3])

    named = {s.system: s.name for s in snapshot.pipe_systems}
    lexicon = load_lexicon(Settings.from_env({}).lexicon_path)
    c.check(
        "배관 계통마다 이름표가 있고 그 이름은 해석기 사전의 별칭(보이는 이름을 그대로 적어도 읽힘)",
        sorted(named) == keys and all(name in lexicon.systems[key] for key, name in named.items()),
        named,
    )
    c.check(
        "밸브 종류 현장 이름도 해석기 사전의 별칭",
        all(label in lexicon.valve_types[key] for key, label in VALVE_LABELS.items()),
    )

    index = GraphIndex(snapshot)
    valve = next(p for p in snapshot.parts if p.kind is PartKind.VALVE and p.system)
    c.check(
        "그래프 상세의 계통 속성은 현장 이름",
        describe(index, valve.part_id).attrs["system"] == named[str(valve.system)],
        describe(index, valve.part_id).attrs,
    )
    spool = min((p for p in snapshot.parts if p.kind is PartKind.PIPE_SPOOL and p.system), key=lambda p: p.part_id)
    reroute = ReroutePipe(removed_part_ids=(spool.part_id,), added_spool_spec_ids=(spool.spec_id,))
    view = ChangeView(index, ChangeRequest(ecn_id="ECN-T", title="검사", ship_ids=(spool.ship_id,), ops=(reroute,)))
    added = view.new_node(next(iter(view.new_parts)))
    c.check("경로 변경으로 생긴 새 배관의 계통 속성도 현장 이름", added.attrs["system"] == named[str(spool.system)])
    bare_snapshot = snapshot.model_copy(update={"pipe_systems": ()})
    bare = GraphIndex(bare_snapshot)
    c.check(
        "이름표가 없는 지도(엑셀 가져오기 등)는 계통 키를 그대로 보임",
        describe(bare, valve.part_id).attrs["system"] == valve.system,
    )
    config = load_config()
    partial = snapshot.model_copy(update={"pipe_systems": snapshot.pipe_systems[:1]})
    made = {
        label: make_ecns(config, source, EcnSplit.DEV, 200, config.seed)
        + list(nl_samples(source, NlSplit.SELECTION, 100, config.seed, config.scenario_date, load_nl_lexicon()))
        for label, source in (("없음", bare_snapshot), ("일부", partial))
    }
    reroutes = {
        label: [x.change.title for x in items if "배관 경로 변경" in x.change.title] for label, items in made.items()
    }
    c.check(
        "이름표가 없거나 일부만 있는 지도로도 설계변경·문장 사례를 끝까지 만듦(이름 없는 계통은 키)",
        all(reroutes.values()) and any(keys[0] in t or keys[1] in t for t in reroutes["없음"]),
        {k: v[:2] for k, v in reroutes.items()},
    )
