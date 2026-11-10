"""설계변경 사전 점검(docs/engine.md(사전 점검), 1.32.0 안에서 추가): 규칙 6개의 성질.

- 규칙마다 '걸리는 작은 지도'와 '안 걸리는 대조 지도'를 손으로 만들어 본다(작은 지도는 엔진 분석 없이 사전 점검만 —
  분석 결과는 도면 개정 목록·재작업 블록만 읽으므로 그 영향만 손으로 넣는다). 지도에 정보가 없으면 '점검 불가'.
- 생성기 지도: 같은 입력 두 번 = 같은 항목, 사전 점검을 켜고 끈 결과는 사전 점검 말고 바이트 단위로 같음(판정·총액·결정
  기한·곡선·대안), 실데이터 결과에는 합성 NCR 건수가 없음, 빈 사전 점검은 직렬화에서 빠짐(기록 ID 그대로).
- 시연 고정점: ECN-D-0043(평형수 배관 경로)에서 P-02, ECN-D-0119(B31P 판 두께)에서 P-06.
- 결정 도우미: 사전 점검 항목이 서명 전 확인할 것 후보로 들어가고(확인 필요 먼저) 검사 함수를 통과한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from fixtures import VERSIONS, analysis_result
from harness import Checker

from ripple.brief import audit, build_brief
from ripple.brief.checks import check_options
from ripple.brief.facts import Facts
from ripple.config.loaders import load_params, load_rulebook, load_strength
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.change import (
    AddPart,
    ChangeOp,
    ChangeRequest,
    EquipmentSpecChange,
    ReroutePipe,
    ThicknessChange,
)
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.domain import DataMode, EntityType, GraphSnapshot, PartKind, Relation
from ripple.contracts.graphview import GraphNode, GraphView
from ripple.contracts.identity import snapshot_id
from ripple.contracts.records import RecordBody
from ripple.contracts.result import (
    AnalysisResult,
    Hop,
    Impact,
    ImpactType,
    PrecheckItem,
    PrecheckLevel,
    Severity,
)
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.precheck import precheck
from ripple.engine.schedule.baseline import Baseline
from ripple.generator.build import generate
from ripple.generator.io import load_config

AS_OF = date(2026, 10, 20)
SHIP = "S-001"
B1, B2 = f"{SHIP}:B1", f"{SHIP}:B2"
P1, P2, Q1 = f"{SHIP}:B1-PL-001", f"{SHIP}:B1-PL-002", f"{SHIP}:B2-PL-001"
S1, S2, S3, S4 = (f"{SHIP}:B1-SP-001", f"{SHIP}:B1-SP-002", f"{SHIP}:B1-SP-003", f"{SHIP}:B2-SP-101")
T1, C1, V1 = f"{SHIP}:B1-PS-001", f"{SHIP}:B1-CL-001", f"{SHIP}:B1-VL-001"
HULL1, PIPE1, HULL2 = "H-B1@A", "P-B1@A", "H-B2@A"
SPOOL = "SP-DN200-S40"
SAMPLE = 40  # 켜고 끈 비교에 쓰는 개발 분할 설계변경 수
COUNTS = {"P-01": 4, "P-02": 6, "P-03": 3, "P-04": 5, "P-05": 2, "P-06": 7}


# ---------- 작은 지도 ----------


def _part(part_id: str, kind: str, spec: str, drawing: str, **extra: Any) -> dict[str, Any]:
    block = B2 if ":B2-" in part_id else B1
    no, rev = drawing.split("@")
    return {
        "part_id": part_id,
        "ship_id": SHIP,
        "block_id": block,
        "kind": kind,
        "name": part_id.rsplit(":", 1)[-1],
        "spec_id": spec,
        "qty": 1.0,
        "drawing_no": no,
        "revision": rev,
        **extra,
    }


def _activity(
    block: str, kind: str, day: int, *, start: int | None = None, finish: int | None = None, by: str | None = None
) -> dict[str, Any]:
    planned = AS_OF + timedelta(days=day)
    return {
        "activity_id": f"{block}:{kind}",
        "ship_id": SHIP,
        "block_id": block,
        "kind": kind,
        "duration_days": 5,
        "planned_start": planned.isoformat(),
        "actual_start": None if start is None else (AS_OF + timedelta(days=start)).isoformat(),
        "actual_finish": None if finish is None else (AS_OF + timedelta(days=finish)).isoformat(),
        "performer": by,
    }


def _parts(secondary: bool = True) -> list[dict[str, Any]]:
    def sec(*ids: str) -> dict[str, Any]:
        return {"secondary_drawing_ids": list(ids)} if secondary else {}

    ballast = {"system": "ballast"}
    return [
        _part(P1, "plate", "PL-AH36-12.0", HULL1, thickness_mm=12.0, grade="AH36"),
        _part(P2, "plate", "PL-AH36-12.0", HULL1, thickness_mm=12.0, grade="AH36", **sec(PIPE1)),
        _part(Q1, "plate", "PL-AH36-12.0", HULL2, thickness_mm=12.0, grade="AH36"),
        _part(S1, "pipe_spool", SPOOL, PIPE1, **ballast),
        _part(S2, "pipe_spool", SPOOL, PIPE1, **ballast),
        _part(S3, "pipe_spool", SPOOL, PIPE1, **ballast),
        _part(S4, "pipe_spool", SPOOL, PIPE1, **ballast, **sec(HULL2)),
        _part(V1, "valve", "VL-GATE-DN200", PIPE1, **ballast),
        _part(T1, "pipe_support", "PS-DN200", PIPE1, **sec(HULL1)),
        _part(C1, "collar", "CL-DN200", HULL1, **sec(PIPE1)),
    ]


def _connections(joints: bool = True) -> list[dict[str, str]]:
    pipe = [(S1, S2), (S2, S3), (S3, S4), (V1, S1)] if joints else []
    rest = [(T1, S2, "support"), (C1, P2, "fillet_weld"), (C1, S1, "penetration"), (P2, S1, "penetration")]
    return [{"a": a, "b": b, "kind": "pipe_joint"} for a, b in pipe] + [{"a": a, "b": b, "kind": k} for a, b, k in rest]


def _activities(outfitting: str = "running") -> list[dict[str, Any]]:
    """B1: 소조립(한빛)·판넬조립·대조립(직영) 완료, 선행의장(해송) 진행 중 / B2: 착수 전."""
    found = [
        _activity(B1, "sub_assembly", -40, start=-40, finish=-30, by="CRW-01"),
        _activity(B1, "panel", -29, start=-29, finish=-20, by="direct"),
        _activity(B1, "assembly", -19, start=-19, finish=-5, by="direct"),
        _activity(B2, "sub_assembly", 30, by=None),
    ]
    if outfitting == "running":
        found.append(_activity(B1, "pre_outfitting", -4, start=-4, by="CRW-03"))
    elif outfitting == "planned":
        found.append(_activity(B1, "pre_outfitting", 10, by="CRW-03"))
    return found


def _map(*, parts: Sequence[dict[str, Any]] | None = None, **options: Any) -> GraphIndex:
    joints, outfitting = options.get("joints", True), options.get("outfitting", "running")
    chosen = list(parts if parts is not None else _parts())
    if options.get("no_collars"):
        chosen = [p for p in chosen if p["kind"] != "collar"]
    if options.get("no_supports"):
        chosen = [p for p in chosen if p["kind"] != "pipe_support"]
    kept = {p["part_id"] for p in chosen}
    body = {
        "snapshot_id": "G-pending",
        "origin": "generator",
        "data_mode": "synthetic",
        "ships": [
            {"ship_id": SHIP, "ship_type": "tanker", "dwt": 1, "contract_price_krw": 1, "delivery_date": "2027-12-15"}
        ],
        "zones": [{"zone_id": f"{SHIP}:Z1", "ship_id": SHIP, "name": "구역"}],
        "blocks": [
            {"block_id": b, "ship_id": SHIP, "zone_id": f"{SHIP}:Z1", "name": b[-2:], "steel_weight_t": 100.0}
            for b in (B1, B2)
        ],
        "specs": [
            {"spec_id": s, "category": c, "description": s, "unit": u, "unit_price_krw": 1}
            for s, c, u in (
                ("PL-AH36-12.0", "plate", "t"),
                (SPOOL, "pipe", "m"),
                ("VL-GATE-DN200", "valve", "ea"),
                ("VL-BALL-DN200", "valve", "ea"),
                ("PS-DN200", "fitting", "ea"),
                ("CL-DN200", "fitting", "ea"),
            )
        ],
        "parts": chosen,
        "connections": [c for c in _connections(joints) if c["a"] in kept and c["b"] in kept],
        "suppliers": [],
        "purchase_orders": [],
        "po_lines": [],
        "stock": [],
        "activities": _activities(outfitting),
        "drawings": [
            {"drawing_no": d.split("@")[0], "revision": "A", "discipline": disc, "title": d}
            for d, disc in ((HULL1, "hull"), (PIPE1, "piping"), (HULL2, "hull"))
        ],
        "crews": [
            {"crew_id": "CRW-01", "name": "한빛 작업반", "processes": ["sub_assembly", "panel"]},
            {"crew_id": "CRW-03", "name": "해송 작업반", "processes": ["pre_outfitting"]},
        ],
    }
    draft = GraphSnapshot.model_validate(body)
    return GraphIndex(draft.model_copy(update={"snapshot_id": snapshot_id(draft)}))


def _request(*ops: ChangeOp, confirm_on: date | None = None) -> AnalysisRequest:
    change = ChangeRequest(ecn_id="E-PRE", title="사전 점검 작은 지도", ship_ids=(SHIP,), ops=ops)
    return AnalysisRequest(change=change, as_of=AS_OF, confirm_on=confirm_on)


def _revisions(*pairs: tuple[str, str]) -> AnalysisResult:
    """도면 개정 영향(R-D01: 부재 → 도면)만 넣은 분석 결과(작은 지도는 엔진 분석 없이 사전 점검만 본다)."""
    impacts = sorted(
        (
            Impact(
                entity_type=EntityType.DRAWING,
                entity_id=drawing,
                ship_id=SHIP,
                impact_type=ImpactType.DRAWING_REVISION,
                severity=Severity.LOW,
                rule_id="R-D01",
                path=(Hop(src=part, dst=drawing, relation=Relation.DRAWN_IN, rule_id="R-D01"),),
            )
            for part, drawing in pairs
        ),
        key=lambda i: i.key,
    )
    ids = sorted({end for part, drawing in pairs for end in (part, drawing)})
    graph = GraphView(
        snapshot_id=VERSIONS.snapshot_id,
        nodes=tuple(GraphNode(id=i, type=EntityType.PART, label=i) for i in ids),
        edges=(),
    )
    return analysis_result(impacts=[i.model_dump(mode="json") for i in impacts], graph=graph.model_dump(mode="json"))


def _check(
    index: GraphIndex, *ops: ChangeOp, result: AnalysisResult | None = None, confirm_on: date | None = None
) -> tuple[PrecheckItem, ...]:
    return precheck(index, _request(*ops, confirm_on=confirm_on), result or analysis_result(), COUNTS)


def _keys(items: Sequence[PrecheckItem], rule: str) -> list[str]:
    return [i.key for i in items if i.rule_id == rule]


def run(c: Checker) -> None:
    _install(c)
    _penetration(c)
    _boundary_drawings(c)
    _support_sharing(c)
    generated = generate(load_config())
    _world(c, generated)


# ---------- 규칙별 작은 지도 ----------


def _reroute(removed: tuple[str, ...], crosses: tuple[str, ...] = ()) -> ReroutePipe:
    return ReroutePipe(removed_part_ids=removed, added_spool_spec_ids=(SPOOL,), crosses_part_ids=crosses)


def _install(c: Checker) -> None:
    c.section("사전 점검 P-01 설치 시점(작은 지도)")
    route = _reroute((S2,))
    running = _check(_map(), route)
    item = next((i for i in running if i.rule_id == "P-01"), None)
    c.check(
        "선행의장이 진행 중인 블록에 새 스풀 → 후행 설치 불가피(주의), 근거 = 새 부재 → 블록 · 선행의장 공정 → 블록",
        item is not None
        and item.level is PrecheckLevel.CAUTION
        and item.targets[0] == B1
        and f"{B1}:pre_outfitting" in item.targets
        and any(e.virtual and e.dst == B1 for e in item.evidence),
        item,
    )
    valve = _check(
        _map(), EquipmentSpecChange(part_ids=(V1,), from_spec_id="VL-GATE-DN200", to_spec_id="VL-BALL-DN200")
    )
    c.check("사양이 바뀌는 밸브(의장품)도 같은 규칙", bool(_keys(valve, "P-01")), _keys(valve, "P-01"))
    later = _map(outfitting="planned")
    es0 = Baseline(later, AS_OF).start(f"{B1}:pre_outfitting").expected  # 확정일 평가와 같은 공정 시계
    eve = _check(later, route, confirm_on=es0 - timedelta(days=1))
    day = _check(later, route, confirm_on=es0)
    plate = _check(_map(), ThicknessChange(part_ids=(P1,), from_mm=12.0, to_mm=14.0))
    c.check(
        f"경계(확정일 기준 예상 착수, 기준 일정 착수 {es0}): 확정일이 전날이면 안 걸리고 당일이면 걸림(글에 기준 일정)",
        es0 > AS_OF
        and not _keys(eve, "P-01")
        and _keys(day, "P-01") == [f"P-01:late_install:{B1}"]
        and "기준 일정" in next(i.text for i in day if i.rule_id == "P-01"),
        (_keys(eve, "P-01"), _keys(day, "P-01")),
    )
    c.check(
        "대조: 기준일 확정이면 착수 전 블록 · 의장품이 아닌 판은 걸리지 않음",
        not _keys(_check(later, route), "P-01") and not _keys(plate, "P-01"),
        _keys(plate, "P-01"),
    )
    missing = _check(_map(outfitting="none"), route)
    c.check(
        "지도에 그 블록의 선행의장 공정이 없으면 '점검 불가'(지어내지 않음)",
        [i.level for i in missing if i.rule_id == "P-01"] == [PrecheckLevel.UNCHECKED],
        _keys(missing, "P-01"),
    )


def _penetration(c: Checker) -> None:
    c.section("사전 점검 P-02 관통부 정합(작은 지도)")
    missing = _check(_map(), _reroute((S2,), crosses=(P1,)))
    c.check(
        "새 경로가 칼라 없는 판을 지남 → 관통부 누락 의심(확인 필요), 근거 = 새 스풀 → 판 관통(변경 후 보기)",
        _keys(missing, "P-02") == [f"P-02:missing:{P1}"]
        and next(i for i in missing if i.rule_id == "P-02").evidence[0].virtual,
        _keys(missing, "P-02"),
    )
    twice = _check(_map(), _reroute((S2,), crosses=(P1,)), _reroute((S3,), crosses=(P1,)))
    merged = next((i for i in twice if i.key == f"P-02:missing:{P1}"), None)
    c.check(
        "같은 판을 지나는 경로 변경 두 건은 판마다 항목 하나(키 중복 없음), 두 경로의 새 스풀을 모두 대상에",
        _keys(twice, "P-02") == [f"P-02:missing:{P1}"]
        and merged is not None
        and sum(1 for t in merged.targets if t.startswith("NEW:")) == 2,
        (_keys(twice, "P-02"), merged.targets if merged else None),
    )
    collar = _check(_map(), _reroute((S3,), crosses=(P2,)))
    added = _check(
        _map(),
        _reroute((S2,), crosses=(P1,)),
        AddPart(block_id=B1, kind=PartKind.COLLAR, spec_id="CL-DN200", qty=1.0, attach_to_part_id=P1),
    )
    c.check(
        "대조: 같은 계통 배관이 지나는 칼라가 있는 판 · 같은 요청에 칼라 추가가 있는 판은 걸리지 않음",
        not _keys(collar, "P-02") and not _keys(added, "P-02"),
        (_keys(collar, "P-02"), _keys(added, "P-02")),
    )
    blind = _check(_map(no_collars=True), _reroute((S2,), crosses=(P1,)))
    c.check(
        "지도에 칼라가 하나도 없으면 누락 쪽은 '점검 불가'",
        [i.level for i in blind if i.key.startswith("P-02:") and "hole" not in i.key] == [PrecheckLevel.UNCHECKED],
        _keys(blind, "P-02"),
    )
    hole = _check(_map(), _reroute((S1,)))
    reused = _check(_map(), _reroute((S1,), crosses=(P2,)))
    item = next((i for i in hole if i.key == f"P-02:hole:{P2}"), None)
    c.check(
        "빼는 스풀이 지나던 판(칼라 포함) → 구멍 막음 필요(주의), 근거 = 판·칼라 관통 + 칼라 필릿 용접",
        item is not None
        and item.level is PrecheckLevel.CAUTION
        and {e.relation for e in item.evidence} == {Relation.PENETRATION, Relation.FILLET_WELD}
        and C1 in item.targets,
        item,
    )
    c.check(
        "대조: 새 경로가 같은 판을 다시 지나면(관통부 다시 씀) 막음·누락 없음",
        not _keys(reused, "P-02"),
        _keys(reused, "P-02"),
    )


def _boundary_drawings(c: Checker) -> None:
    c.section("사전 점검 P-03 블록 경계 연결 · P-04 분야 간 도면(작은 지도)")
    route = _reroute((S3,))
    crossing = _check(_map(), route)
    item = next((i for i in crossing if i.rule_id == "P-03"), None)
    c.check(
        "경계 배관 연결(pipe_joint)의 상대 블록 B2가 범위 밖 → 상대 블록 확인(확인 필요), 근거 = 배관 연결 → 상대 블록",
        item is not None
        and item.targets[0] == B2
        and S4 in item.targets
        and Relation.PIPE_JOINT in {e.relation for e in item.evidence},
        item,
    )
    both = _check(_map(), route, ThicknessChange(part_ids=(Q1,), from_mm=12.0, to_mm=14.0))
    inside = _check(_map(), _reroute((S2,)))
    c.check(
        "대조: 같은 요청이 B2도 바꾸면 · 블록 안 연결뿐이면 걸리지 않음",
        not _keys(both, "P-03") and not _keys(inside, "P-03"),
        (_keys(both, "P-03"), _keys(inside, "P-03")),
    )
    jointless = _check(_map(joints=False), route)
    c.check(
        "지도에 배관 연결이 하나도 없으면 '점검 불가'",
        [i.level for i in jointless if i.rule_id == "P-03"] == [PrecheckLevel.UNCHECKED],
    )
    thick = ThicknessChange(part_ids=(P2,), from_mm=12.0, to_mm=14.0)
    own = _check(_map(), thick, result=_revisions((P2, HULL1)))
    item = next((i for i in own if i.rule_id == "P-04"), None)
    c.check(
        "바뀌는 판의 다른 분야 도면(배관도)이 개정 목록에 없음 → 다른 분야 도면 미반영, 근거 = 부재 → 다른 분야 도면",
        item is not None and item.targets[:2] == (PIPE1, P2) and item.evidence[0].relation == "secondary_drawing",
        item,
    )
    covered = _check(_map(), thick, result=_revisions((P2, HULL1), (S1, PIPE1)))
    plain = _check(_map(), ThicknessChange(part_ids=(P1,), from_mm=12.0, to_mm=14.0), result=_revisions((P1, HULL1)))
    c.check(
        "대조: 배관도도 개정 목록에 있으면 · 다른 분야 도면이 없는 판이면 걸리지 않음",
        not _keys(covered, "P-04") and not _keys(plain, "P-04"),
        (_keys(covered, "P-04"), _keys(plain, "P-04")),
    )
    bare = _check(_map(parts=_parts(secondary=False)), thick, result=_revisions((P2, HULL1)))
    c.check(
        "지도에 다른 분야 도면 정보가 하나도 없으면 '점검 불가'",
        [i.level for i in bare if i.rule_id == "P-04"] == [PrecheckLevel.UNCHECKED],
    )


def _support_sharing(c: Checker) -> None:
    c.section("사전 점검 P-05 새 스풀 서포트 · P-06 현장 공유(작은 지도)")
    route = _reroute((S2,))
    found = _check(_map(), route)
    item = next((i for i in found if i.rule_id == "P-05"), None)
    c.check(
        "새 스풀에 서포트 연결 없음(확인 필요), 근거에 빼는 스풀을 받치던 서포트",
        item is not None and item.level is PrecheckLevel.CHECK and T1 in item.targets and item.evidence[0].src == T1,
        item,
    )
    thick = _check(_map(), ThicknessChange(part_ids=(P1,), from_mm=12.0, to_mm=14.0))
    blind = _check(_map(no_supports=True), route)
    c.check(
        "대조: 새 스풀이 없으면 걸리지 않음 · 지도에 서포트가 하나도 없으면 '점검 불가'",
        not _keys(thick, "P-05") and [i.level for i in blind if i.rule_id == "P-05"] == [PrecheckLevel.UNCHECKED],
    )
    two = [i for i in _check(_map(no_supports=True), route, _reroute((S3,))) if i.rule_id == "P-05"]
    c.check(
        "지도에 서포트가 없으면 '점검 불가' 한 항목이 모든 연산의 새 스풀을 대상으로(경로 변경 2개 → 새 스풀 2개)",
        len(two) == 1
        and two[0].level is PrecheckLevel.UNCHECKED
        and len([t for t in two[0].targets if t.startswith("NEW:")]) == 2,
        two,
    )
    item = next((i for i in thick if i.rule_id == "P-06"), None)
    c.check(
        "이미 착수·완료한 공정이 있는 블록 → 현장 통보 필수, 수행 주체(작업반 이름·직영)와 공정 → 수행 주체 근거",
        item is not None
        and item.targets[0] == B1
        and all(name in item.text for name in ("한빛 작업반", "직영", "해송 작업반", "선행의장 진행 중"))
        and {e.dst for e in item.evidence if e.relation == "performed_by"} == {"CRW-01", "direct", "CRW-03"},
        item,
    )
    quiet = _check(_map(), ThicknessChange(part_ids=(Q1,), from_mm=12.0, to_mm=14.0))
    c.check("대조: 착수 전 블록(B2)만 바뀌면 걸리지 않음", not _keys(quiet, "P-06"), _keys(quiet, "P-06"))
    items = _check(_map(), _reroute((S2,), crosses=(P1,)))
    c.check(
        "항목은 규칙 ID → 키 순, 같은 입력 두 번 = 같은 항목, 합성 NCR 건수 = 넘긴 건수",
        list(items) == sorted(items, key=lambda i: (i.rule_id, i.key))
        and items == _check(_map(), _reroute((S2,), crosses=(P1,)))
        and all(i.ncr_count == COUNTS[i.rule_id] for i in items),
    )


# ---------- 생성기 지도 ----------


def _world(c: Checker, generated: Any) -> None:
    c.section("사전 점검: 생성기 지도(결정성 · 켜고 끈 비교 · 실데이터 · 시연 고정점 · 결정 도우미)")
    index = GraphIndex(generated.snapshot)
    book = load_rulebook(PROJECT_ROOT / "rules" / "propagation.yaml")
    params = load_params(PROJECT_ROOT / "params" / "cost_v1.yaml")
    strength = load_strength(PROJECT_ROOT / "rules" / "strength.yaml")
    dev = [AnalysisRequest(change=e.change, as_of=e.as_of) for e in generated.ecns if e.split is EcnSplit.DEV]
    changed, again, plain_ids = [], [], []
    seen = 0
    for request in dev[:SAMPLE]:
        on = analyze(index, request, book, params, ncr_counts=COUNTS)
        off = analyze(index, request, book, params, prechecks=False)
        seen += bool(on.prechecks)
        if on.model_dump(mode="json", exclude={"prechecks"}) != off.model_dump(mode="json"):
            changed.append(request.change.ecn_id)
        if analyze(index, request, book, params, ncr_counts=COUNTS).model_dump_json() != on.model_dump_json():
            again.append(request.change.ecn_id)
        if not off.prechecks and "prechecks" in off.model_dump(mode="json"):
            plain_ids.append(request.change.ecn_id)
    c.check(
        f"사전 점검을 켜고 끈 결과가 사전 점검 말고 같음(판정·총액·결정 기한·곡선, 개발 분할 {SAMPLE}건 중 "
        f"항목 있는 {seen}건)",
        not changed and seen > 0,
        changed[:4],
    )
    c.check("같은 입력 두 번 = 같은 결과(사전 점검 포함, 바이트 단위)", not again, again[:4])
    c.check("빈 사전 점검은 직렬화에서 빠짐(그 필드가 없던 기록 본문의 기록 ID 그대로)", not plain_ids, plain_ids[:4])
    _real(c, generated, book, params)
    _brief(c, _fixed_points(c, generated, index, book, params, strength))


def _real(c: Checker, generated: Any, book: Any, params: Any) -> None:
    snapshot = generated.snapshot.model_copy(update={"origin": "excel_import", "data_mode": DataMode.REAL})
    real = GraphIndex(snapshot.model_copy(update={"snapshot_id": snapshot_id(snapshot)}))
    ecn = next(e for e in generated.ecns if e.change.ecn_id == "ECN-D-0119")
    result = analyze(real, AnalysisRequest(change=ecn.change, as_of=ecn.as_of), book, params, ncr_counts=COUNTS)
    c.check(
        "실데이터 지도의 결과에는 합성 NCR 건수가 없음(넘겨도 None), 계약도 실데이터 결과의 건수를 거부",
        bool(result.prechecks)
        and all(i.ncr_count is None for i in result.prechecks)
        and c.raises(
            lambda: AnalysisResult.model_validate(
                {
                    **result.model_dump(mode="json"),
                    "prechecks": [{**result.prechecks[0].model_dump(mode="json"), "ncr_count": 3}],
                }
            )
        ),
    )


def _fixed_points(
    c: Checker, generated: Any, index: GraphIndex, book: Any, params: Any, strength: Any
) -> tuple[AnalysisResult, ...]:
    ecns = {e.change.ecn_id: e for e in generated.ecns}

    def run_one(ecn_id: str, confirm_on: date | None = None) -> AnalysisResult:
        ecn = ecns[ecn_id]
        request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of, confirm_on=confirm_on)
        return analyze(index, request, book, params, strength, ncr_counts=COUNTS)

    pipe, plate = run_one("ECN-D-0043"), run_one("ECN-D-0119")
    c.check(
        "시연 고정점 ECN-D-0043(평형수 배관 경로): 새 경로가 지나는 A11C 판의 관통부 누락 의심(P-02)",
        any(i.key == "P-02:missing:S-001:A11C-PL-001" for i in pipe.prechecks),
        [i.key for i in pipe.prechecks],
    )
    es0 = Baseline(index, ecns["ECN-D-0043"].as_of).start("S-001:E21C:pre_outfitting").expected
    eve, day = run_one("ECN-D-0043", es0 - timedelta(days=1)), run_one("ECN-D-0043", es0)
    late = "P-01:late_install:S-001:E21C"
    c.check(
        f"ECN-D-0043 경계: E21C 선행의장 기준 일정 착수({es0}) 전날 확정이면 P-01 없음, 당일 확정이면 P-01(주의) — "
        "기준일 확정에는 없음",
        late not in {i.key for i in pipe.prechecks}
        and late not in {i.key for i in eve.prechecks}
        and late in {i.key for i in day.prechecks},
        ([i.key for i in eve.prechecks], [i.key for i in day.prechecks]),
    )
    sharing = next((i for i in plate.prechecks if i.key == "P-06:notify:S-001:B31P"), None)
    c.check(
        "시연 고정점 ECN-D-0119(B31P 판 두께): 선행의장 진행 중인 B31P를 맡은 해송 작업반·직영 통보 필수(P-06)",
        sharing is not None and "해송 작업반" in sharing.text and "직영" in sharing.text,
        [i.key for i in plate.prechecks],
    )
    return pipe, plate


def _brief(c: Checker, results: Sequence[AnalysisResult]) -> None:
    c.section("사전 점검 → 결정 도우미(서명 전 확인할 것 후보)")
    for result in results:
        body = RecordBody(
            ecn_id=result.request.change.ecn_id,
            snapshot_id=result.versions.snapshot_id,
            data_mode=DataMode.SYNTHETIC,
            result=result,
        )
        options = check_options(Facts(body=body, today=result.request.as_of))
        pre = [o for o in options if o.key.startswith("precheck:")]
        brief = build_brief(body, record_id="R-00000000000000c1", revision=1, today=result.request.as_of)
        levels = [next(i.level for i in result.prechecks if o.key == f"precheck:{i.key}") for o in pre]
        c.check(
            f"결정 도우미({result.request.change.ecn_id}): 사전 점검이 확인할 것 후보(확인 필요 먼저), "
            "글에 '같은 유형 합성 NCR n건(합성 묶음(시연))', 검사 함수 통과",
            bool(pre)
            and levels == sorted(levels, key=lambda lv: list(PrecheckLevel).index(lv))
            and all("합성 묶음(시연)" in o.text and not o.computed for o in pre)
            and not audit(brief, body, result.request.as_of),
            ([o.key for o in pre], audit(brief, body, result.request.as_of)),
        )
