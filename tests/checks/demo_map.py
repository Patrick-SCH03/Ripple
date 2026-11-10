"""시연 합성 지도(generator/demo_map.yaml, docs/data.md(생성기) 12절 · docs/engine.md(비용·일정) 7절 R-S01 (라)).

- 기본 지도는 그대로: 기본 설정에는 관계 보강이 없고, 기본 지도의 ECN-D-0119에는 다른 블록 탑재 지연이 없다.
- 시연 지도는 기본 지도와 같은 선체·부재·발주·설계변경이고, 탑재 순서(블록 사이 선후행)만 더한다.
  같은 설정이면 같은 바이트.
- 시연 지도의 ECN-D-0119는 블록 사이 관계 두 단계 이상으로 번진다(근거 경로를 블록으로 접어 따로 센다 — 화면
  graph3d/relations.ts와 같은 접기). 비용 값은 기본 지도와 같고, 기본 지도의 영향은 모두 남는다.
- 설정: RIPPLE_SYNTHETIC_MAP 기본 base, demo면 생성기 설정·지도 파일·지도 이름이 시연 지도.
"""

from __future__ import annotations

import tempfile
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from harness import Checker

from ripple.api.deps import AppContext
from ripple.api.snapshot_info import DEFAULT_NAME, default_name
from ripple.api.workspace import Workspaces
from ripple.config.settings import DEMO_SNAPSHOT, Settings, parse_map
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.domain import ActivityKind, Relation
from ripple.contracts.result import AnalysisResult, Impact
from ripple.engine.analyze import analyze
from ripple.engine.cost import Demand
from ripple.engine.cost.onboard import OnboardBlock
from ripple.engine.index import GraphIndex
from ripple.engine.schedule.baseline import Baseline
from ripple.engine.timing.adjust import _onboard_lags, gate_targets
from ripple.generator.build import Generated, GeneratorError, generate
from ripple.generator.config import GeneratorConfig, RelationsConfig
from ripple.generator.io import DEFAULT_CONFIG_PATH, DEMO_CONFIG_PATH, load_config, write_outputs
from ripple.graph.memory import MemoryGraphStore
from ripple.store.snapshots import SnapshotStore

SHOWCASE = "ECN-D-0119"


def run(c: Checker) -> None:
    c.section("시연 합성 지도: 생성")
    base_cfg, demo_cfg = load_config(DEFAULT_CONFIG_PATH), load_config(DEMO_CONFIG_PATH)
    base, demo = generate(base_cfg), generate(demo_cfg)
    _generation(c, base_cfg, demo_cfg, base, demo)
    context = AppContext.load(Settings.from_env({}))
    c.section("시연 합성 지도: ECN-D-0119 블록 사이 관계")
    before, after = _analysis(context, base), _analysis(context, demo)
    _relations(c, base, demo, before, after)
    _exit_only(c, demo)
    c.section("시연 합성 지도: 설정·작업 공간")
    _settings(c, demo)


def _exit_only(c: Checker, demo: Generated) -> None:
    """6-3: 이미 탑재한 블록의 관문과 선상 설치 lag·자재 제약은 탑재의 후행 중 구역 출구에만 — 블록 사이 탑재
    선후행(시연 지도)의 다음 블록 탑재에는 걸지 않는다."""
    index = GraphIndex(demo.snapshot)
    erection = "S-001:B31P:erection"
    baseline = Baseline(index, demo.snapshot.ships[0].delivery_date - timedelta(days=3650))
    schedule = baseline.schedule_of(erection)
    assert schedule is not None
    net, base = schedule.network, schedule.base
    successors = {s for s, _ in net.succs.get(erection, ())}
    after = base.es[erection]  # 판정일 = 탑재 착수일(이미 탑재 시작)
    gated = set(gate_targets(net, base, "S-001:B31P", after))
    arrival = after + timedelta(days=30)
    demand = Demand(
        part_id="S-001:B31P-SP-001", line_id=None, qty=1.0, consumer="S-001:B31P:pre_outfitting", arrival=arrival
    )
    floor: dict[str, date] = {}
    lags = _onboard_lags(net, {"S-001:B31P": OnboardBlock(demands=(demand,), days=2, erection=erection)}, floor)
    c.check(
        "탑재 관문(이미 탑재)·선상 설치 lag·자재 제약은 구역 출구에만, 다음 블록 탑재(T31C·L31C·S31P)에는 걸지 않음",
        any(s not in net.exits for s in successors)
        and gated == successors & set(net.exits)
        and {s for _, s in lags} == successors & set(net.exits)
        and set(floor) == successors & set(net.exits),
        (sorted(successors), sorted(gated), sorted(lags), sorted(floor)),
    )


def _generation(
    c: Checker, base_cfg: GeneratorConfig, demo_cfg: GeneratorConfig, base: Generated, demo: Generated
) -> None:
    c.check("기본 설정에는 관계 보강이 없음(기본 지도·평가 관문 그대로)", base_cfg.relations is None)
    relations = demo_cfg.relations
    c.check(
        "시연 설정 = 기본 설정 + 관계 보강만(extends), 이름에 '합성'",
        relations is not None
        and "합성" in relations.name
        and demo_cfg.model_copy(update={"relations": None}) == base_cfg,
    )
    s0, s1 = base.snapshot, demo.snapshot
    c.check(
        "부재·연결·규격·발주·재고·도면·블록은 기본 지도와 같고, 설계변경 300건도 같음(시연 사례 번호 그대로)",
        (s0.parts, s0.connections, s0.specs, s0.purchase_orders, s0.po_lines, s0.stock, s0.drawings, s0.blocks)
        == (s1.parts, s1.connections, s1.specs, s1.purchase_orders, s1.po_lines, s1.stock, s1.drawings, s1.blocks)
        and [e.model_dump() for e in base.ecns] == [e.model_dump() for e in demo.ecns],
    )
    c.check("지도 ID는 다름(같은 선체 위 다른 지도)", s0.snapshot_id != s1.snapshot_id)
    c.check(
        "같은 설정·시드면 같은 바이트(결정적)",
        generate(load_config(DEMO_CONFIG_PATH)).snapshot.model_dump_json() == s1.model_dump_json(),
    )
    acts0 = {a.activity_id: a for a in s0.activities}
    acts1 = {a.activity_id: a for a in s1.activities}
    added = {
        (p.activity_id, a_id) for a_id, a in acts1.items() for p in a.predecessors if p not in acts0[a_id].predecessors
    }
    blocks = {a_id: a.block_id for a_id, a in acts1.items()}
    c.check(
        "더한 선후행은 모두 다른 블록 탑재 → 탑재(lag 0), 날짜·기간은 그대로",
        bool(added)
        and all(
            acts1[p].kind is ActivityKind.ERECTION and acts1[s].kind is ActivityKind.ERECTION and blocks[p] != blocks[s]
            for p, s in added
        )
        and all(
            (a.planned_start, a.duration_days, a.actual_start)
            == (acts0[i].planned_start, acts0[i].duration_days, acts0[i].actual_start)
            for i, a in acts1.items()
        ),
        sorted(added),
    )
    c.check(
        "탑재 순서가 계획 날짜와 맞음(후행 탑재 착수 계획 ≥ 선행 탑재 완료 계획)",
        all(
            acts1[s].planned_start >= acts1[p].planned_start + timedelta(days=acts1[p].duration_days) for p, s in added
        ),
    )
    c.check(
        "이중저 B31P가 횡격벽·종격벽·선측 좌보다 먼저, 갑판 D31C는 맨 뒤(화물창 링 탑재 순서)",
        {(p.split(":")[1], s.split(":")[1]) for p, s in added}
        >= {("B31P", "T31C"), ("B31P", "L31C"), ("B31P", "S31P"), ("L31C", "D31C")},
    )
    late = demo_cfg.model_copy(
        update={"relations": RelationsConfig(name="합성 시험", erection_after={"B31P": ("D31C",)})}
    )
    c.check("계획 날짜와 어긋나는 탑재 순서는 생성을 멈춤", Checker.raises(lambda: generate(late), GeneratorError))
    c.check(
        "탑재 순서 순환·이름에 '합성' 없음·없는 블록은 설정 오류",
        Checker.raises(lambda: RelationsConfig(name="합성", erection_after={"A": ("B",), "B": ("A",)}))
        and Checker.raises(lambda: RelationsConfig(name="시연 지도"))
        and Checker.raises(
            lambda: GeneratorConfig.model_validate(
                {**base_cfg.model_dump(), "relations": {"name": "합성", "erection_after": {"X99": ["B31P"]}}}
            )
        ),
    )


def _analysis(context: AppContext, generated: Generated) -> AnalysisResult:
    ecn = next(e for e in generated.ecns if e.change.ecn_id == SHOWCASE)
    request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of)
    return analyze(GraphIndex(generated.snapshot), request, context.rulebook, context.params, context.strength)


def _block_of(index: GraphIndex, entity: str) -> str | None:
    if entity in index.blocks:
        return entity
    if entity in index.parts:
        return index.parts[entity].block_id
    if entity in index.activities:
        return index.activities[entity].block_id
    return None  # 도면·발주 품목·재고는 블록이 없음


def _crossings(index: GraphIndex, impact: Impact) -> list[tuple[str, str, str]]:
    """근거 경로를 블록으로 접은 블록 경계 넘기(출발 블록, 도착 블록, 넘긴 연결 종류)."""
    if not impact.path:
        return []
    current = _block_of(index, impact.path[0].src)
    found: list[tuple[str, str, str]] = []
    first: Relation | None = None
    for hop in impact.path:
        first = first or hop.relation
        nxt = _block_of(index, hop.dst)
        if nxt is None:
            continue
        if current is not None and nxt != current:
            found.append((current.split(":")[1], nxt.split(":")[1], first.value))
        current, first = nxt, None
    return found


def _relations(c: Checker, base: Generated, demo: Generated, before: AnalysisResult, after: AnalysisResult) -> None:
    i0, i1 = GraphIndex(base.snapshot), GraphIndex(demo.snapshot)
    cross0 = {x for imp in before.impacts for x in _crossings(i0, imp)}
    cross1 = {x for imp in after.impacts for x in _crossings(i1, imp)}
    hops1 = max((len(_crossings(i1, imp)) for imp in after.impacts), default=0)
    c.check(
        "기본 지도: 블록 사이 관계는 B31P → L31C 맞대기 용접뿐(다른 블록 탑재 지연 없음 — 기본 지도 결과 그대로)",
        cross0 == {("B31P", "L31C", "butt_weld")}
        and not any(i.rule_id == "R-S01" and i.entity_id != "S-001:B31P:erection" for i in before.impacts),
        sorted(cross0),
    )
    c.check(
        "시연 지도: B31P → L31C 맞대기 용접 + B31P 탑재 → L31C·T31C·S31P 탑재 선행 + L31C 탑재 → D31C 탑재 선행",
        cross1
        >= {
            ("B31P", "L31C", "butt_weld"),
            ("B31P", "L31C", "precedes"),
            ("B31P", "T31C", "precedes"),
            ("B31P", "S31P", "precedes"),
            ("L31C", "D31C", "precedes"),
        },
        sorted(cross1),
    )
    c.check("시연 지도: 한 근거 경로가 블록 경계를 두 번 이상 넘음(2차 홉)", hops1 >= 2, hops1)
    c.check(
        "시연 지도: 실제로 블록을 건너는 관계만(같은 블록 안 '넘기' 없음 · 우현 S31S·B31S는 안 번짐)",
        all(a != b for a, b, _ in cross1) and not {b for _, b, _ in cross1} & {"S31S", "B31S"},
    )
    keys0 = {i.key for i in before.impacts}
    keys1 = {i.key for i in after.impacts}
    later = [i for i in after.impacts if i.key not in keys0]
    c.check(
        "기본 지도의 영향은 모두 남고, 더한 영향은 다른 블록 탑재의 일정 지연(R-S01, 메모에 늘어난 일수)",
        keys0 <= keys1
        and bool(later)
        and all(
            i.rule_id == "R-S01" and i.entity_id.endswith(":erection") and "늦어짐" in (i.note or "") for i in later
        ),
        [i.entity_id for i in later],
    )
    delays = after.schedule.added_days_by_activity
    c.check(
        "더한 영향의 탑재는 변경 일정에서 실제로 늦어진 탑재(added_days > 0)",
        all(delays.get(i.entity_id, 0) > 0 for i in later),
    )
    c.check(
        "비용 값·판정 수준·결정 기한은 기본 지도와 같음(탑재 순서는 일정 영향만 더함)",
        (before.total, before.verdict.level, before.timing.deadline, before.cost_lines)
        == (after.total, after.verdict.level, after.timing.deadline, after.cost_lines),
    )
    c.check(
        "구역 출구 지연은 기본 지도 이상(선행 탑재 지연이 갑판까지 이어짐)",
        after.schedule.max_exit_delay_days >= before.schedule.max_exit_delay_days,
        (before.schedule.max_exit_delay_days, after.schedule.max_exit_delay_days),
    )
    again = _analysis(AppContext.load(Settings.from_env({})), demo)
    c.check("시연 지도 분석도 같은 입력이면 같은 바이트", again.model_dump_json() == after.model_dump_json())


def _settings(c: Checker, demo: Generated) -> None:
    default = Settings.from_env({})
    chosen = Settings.from_env({"RIPPLE_SYNTHETIC_MAP": "Demo"})
    c.check(
        "RIPPLE_SYNTHETIC_MAP: 기본 base(배포는 기본 합성 지도), demo면 시연 설정·시연 지도 파일, 그 밖은 오류",
        default.synthetic_map == "base"
        and default.generator_config == DEFAULT_CONFIG_PATH
        and chosen.generator_config == DEMO_CONFIG_PATH
        and chosen.snapshot_path == DEMO_SNAPSHOT
        and Settings.from_env({"RIPPLE_SYNTHETIC_MAP": "demo", "RIPPLE_SNAPSHOT_PATH": "x.json"}).snapshot_path
        == Path("x.json")
        and Checker.raises(lambda: parse_map("real")),
    )
    c.check(
        "지도 이름: 기본 '기본 합성 지도', 시연 '시연 합성 지도'(둘 다 '합성')",
        default_name(DEFAULT_CONFIG_PATH) == DEFAULT_NAME and default_name(DEMO_CONFIG_PATH) == "시연 합성 지도",
    )
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        write_outputs(demo, root / "demo")
        settings = replace(
            Settings.from_env({"RIPPLE_AUTH": "off", "RIPPLE_SYNTHETIC_MAP": "demo"}),
            snapshot_path=root / "demo" / "snapshot.json",
            data_dir=root / "data",
        )
        holder = Workspaces(AppContext.load(settings), MemoryGraphStore(), None, SnapshotStore(settings.data_dir))
        start = holder.start()
        listing = holder.listing()
        item = next(i for i in listing.items if i.default)
        c.check(
            "시연 지도로 띄운 작업 공간: 기본 자리 = 시연 합성 지도(합성 데이터), 샘플에 ECN-D-0119",
            start.snapshot.snapshot_id == demo.snapshot.snapshot_id
            and item.name == "시연 합성 지도"
            and item.data_mode.value == "synthetic"
            and any(s.ecn_id == SHOWCASE for s in start.samples),
            (item.name, [s.ecn_id for s in start.samples][:3]),
        )
