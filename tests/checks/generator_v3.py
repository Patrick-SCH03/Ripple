"""생성기 v3(docs/data.md(생성기) 10절)와 시연 고정점.

- PE 순서: 블록 공정 사슬 소조립 → 판넬조립 → 대조립 → 선행의장 → 선행도장 → PE → 탑재, 이정표 진수 → 시운전 → 인도.
- v3 지도: 블록 경계 배관 연결 · 관통 칼라 · 계통 장비 · 사내 협력사 작업반(공정 수행 주체) · 사외 협력사(단품) ·
  다른 분야 도면(secondary) · 블록 형상·의장·전장품 수.
- 설계변경 이력은 v2 그대로라 v3 부재(이웃 블록 스풀·칼라·장비)를 대상으로 삼지 않는다.
- 시연 고정점: ECN-D-0043(평형수 배관 경로 · 후행 설치 선택지) · ECN-D-0119(B31P 판 두께 · 더 저렴한 충족 대안,
  출구 지연 없음) · ECN-D-0067(결재함 더 저렴한 대안) · ECN-D-0173(같은 블록을 더 두껍게 올렸다 반려된 건)이
  엔진 결과로 성립한다.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from itertools import pairwise

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook, load_strength
from ripple.config.settings import Settings
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.change import ReroutePipe, ThicknessChange
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.domain import (
    BLOCK_ACTIVITY_ORDER,
    DIRECT_PERFORMER,
    ActivityKind,
    ConnectionKind,
    GraphSnapshot,
    PartKind,
    SupplierKind,
)
from ripple.contracts.result import REQUEST_ALT, AnalysisResult, Eligibility, OnboardDirection
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.generator.build import Generated, generate
from ripple.generator.io import load_config


def run(c: Checker) -> None:
    config = load_config()
    generated = generate(config)
    snapshot = generated.snapshot
    _pe_order(c, snapshot)
    _structure(c, snapshot)
    _crews(c, snapshot)
    _organizations(c, snapshot)
    _ecn_targets(c, generated)
    _fixed_points(c, generated)


# ---------- PE 순서 ----------


def _pe_order(c: Checker, snapshot: GraphSnapshot) -> None:
    c.section("생성기 v3: PE 순서(블록 공정 사슬 · 이정표)")
    by_block: dict[str, list[ActivityKind]] = {}
    chained = True
    dated = True
    by_id = {a.activity_id: a for a in snapshot.activities}
    for block in snapshot.blocks:
        chain = [a for a in snapshot.activities if a.block_id == block.block_id]
        by_block[block.block_id] = [a.kind for a in chain]
        for before, after in pairwise(chain):
            chained &= tuple(p.activity_id for p in after.predecessors) == (before.activity_id,)
            dated &= after.planned_start >= before.planned_start + timedelta(days=before.duration_days)
    order = list(BLOCK_ACTIVITY_ORDER)
    c.check(
        "블록마다 공정 일곱 개가 소조립 → … → 선행도장 → PE → 탑재 순(PE는 선행도장 뒤·탑재 앞)",
        all(kinds == order for kinds in by_block.values()) and order.index(ActivityKind.PRE_ERECTION) == 5,
        {b: k for b, k in by_block.items() if k != order},
    )
    c.check("공정마다 선행은 바로 앞 공정 하나이고 계획 착수일은 앞 공정 계획 완료 뒤", chained and dated)
    ship = snapshot.ships[0].ship_id
    launch, trial, delivery = (by_id[f"{ship}:{tail}"] for tail in ("launch", "sea_trial", "delivery"))
    c.check(
        "이정표: 진수 → 시운전 → 인도(시운전은 진수와 인도 사이)",
        [p.activity_id for p in trial.predecessors] == [launch.activity_id]
        and [p.activity_id for p in delivery.predecessors] == [trial.activity_id]
        and launch.planned_start <= trial.planned_start <= delivery.planned_start,
    )
    exits = [a for a in snapshot.activities if a.activity_id.endswith(":exit")]
    c.check(
        "구역 출구는 그 구역 블록의 탑재 뒤(PE가 아니라 탑재가 출구의 선행)",
        all(all(p.activity_id.endswith(":erection") for p in e.predecessors) for e in exits),
    )
    early = [
        a.activity_id
        for a in snapshot.activities
        if a.kind in (ActivityKind.PRE_ERECTION, ActivityKind.ERECTION) and a.actual_start is not None
    ]
    c.check("기준일에 PE·탑재를 착수한 블록이 없음(v2와 같은 블록 단계)", not early, early)


# ---------- 지도 구조 ----------


def _structure(c: Checker, snapshot: GraphSnapshot) -> None:
    c.section("생성기 v3: 블록 경계 배관 · 관통 칼라 · 계통 장비 · 다른 분야 도면")
    parts = {p.part_id: p for p in snapshot.parts}
    crossing = [
        x
        for x in snapshot.connections
        if x.kind is ConnectionKind.PIPE_JOINT
        and parts[x.a].block_id != parts[x.b].block_id
        and parts[x.a].system == parts[x.b].system
    ]
    systems = {parts[x.a].system for x in crossing}
    c.check(
        "배관 계통마다 블록 경계를 넘는 배관 연결이 있음(같은 계통, 다른 블록)",
        systems == {s.system for s in snapshot.pipe_systems},
        sorted(str(s) for s in systems),
    )
    penetrations = [x for x in snapshot.connections if x.kind is ConnectionKind.PENETRATION]
    plate_pipe = [(x.a, x.b) for x in penetrations if parts[x.a].kind is PartKind.PLATE]
    collars = {p.part_id: p for p in snapshot.parts if p.kind is PartKind.COLLAR}
    fillet = {frozenset((x.a, x.b)) for x in snapshot.connections if x.kind is ConnectionKind.FILLET_WELD}
    through = {(x.a if x.a in collars else x.b, x.b if x.a in collars else x.a) for x in penetrations}
    covered = [
        (plate, pipe)
        for plate, pipe in plate_pipe
        if any(
            (cid, pipe) in through
            and frozenset((cid, plate)) in fillet
            and collars[cid].block_id == parts[plate].block_id
            for cid in collars
        )
    ]
    c.check(
        "판 관통마다 칼라 부재(판의 블록, 판에 필릿 용접 · 배관과 관통)",
        bool(plate_pipe) and covered == plate_pipe and len(collars) == len(plate_pipe),
        (len(plate_pipe), len(covered), len(collars)),
    )
    pumps = [p for p in snapshot.parts if p.kind is PartKind.EQUIPMENT]
    joined = {x.a for x in snapshot.connections if x.kind is ConnectionKind.PIPE_JOINT} | {
        x.b for x in snapshot.connections if x.kind is ConnectionKind.PIPE_JOINT
    }
    c.check(
        "배관 계통마다 장비 부재 하나(계통 주 블록, 배관과 연결)",
        sorted(str(p.system) for p in pumps) == sorted(s.system for s in snapshot.pipe_systems)
        and all(p.part_id in joined for p in pumps),
        [p.part_id for p in pumps],
    )
    drawings = {d.drawing_id for d in snapshot.drawings}
    secondary = [p for p in snapshot.parts if p.secondary_drawing_ids]
    kinds = Counter(p.kind for p in secondary)
    c.check(
        "다른 분야 도면(secondary)은 지도의 도면이고 자기 도면과 다름 — 관통 판·칼라·서포트·장비·경계 스풀에 붙음",
        all(
            set(p.secondary_drawing_ids) <= drawings and f"{p.drawing_no}@{p.revision}" not in p.secondary_drawing_ids
            for p in secondary
        )
        and {PartKind.PLATE, PartKind.COLLAR, PartKind.PIPE_SUPPORT, PartKind.EQUIPMENT, PartKind.PIPE_SPOOL}
        <= set(kinds),
        dict(kinds),
    )
    blocks = snapshot.blocks
    c.check(
        "블록마다 형상·의장품 수·전장품 수(난이도 계수 입력)가 있음",
        all(b.shape is not None and b.outfit_items is not None and b.electric_items is not None for b in blocks),
        [b.block_id for b in blocks if b.shape is None],
    )


def _crews(c: Checker, snapshot: GraphSnapshot) -> None:
    c.section("생성기 v3: 사내 협력사 작업반(공정 수행 주체)")
    crews = {crew.crew_id: crew for crew in snapshot.crews}
    block_work = [a for a in snapshot.activities if a.kind is not ActivityKind.MILESTONE]
    by_crew = [a for a in block_work if a.performer not in (None, DIRECT_PERFORMER)]
    c.check("작업반 3~4곳", 3 <= len(crews) <= 4, sorted(crews))
    c.check(
        "블록 공정마다 수행 주체가 있고(직영 또는 작업반), 탑재는 직영, 작업반은 자기가 맡는 공정만",
        all(a.performer is not None for a in block_work)
        and all(a.performer == DIRECT_PERFORMER for a in block_work if a.kind is ActivityKind.ERECTION)
        and all(a.performer in crews and a.kind in crews[str(a.performer)].processes for a in by_crew),
    )
    share = len(by_crew) / len(block_work)
    c.check(
        f"블록 공정의 약 절반을 작업반이 맡음({len(by_crew)}/{len(block_work)} = {share:.0%}, 35~65%)",
        0.35 <= share <= 0.65 and {a.performer for a in by_crew} == set(crews),
        share,
    )
    c.check(
        "작업반 연락처는 가상('.example')",
        all(crew.contact and crew.contact.endswith(".example") for crew in crews.values()),
    )


def _organizations(c: Checker, snapshot: GraphSnapshot) -> None:
    c.section("생성기 v3: 협력사 구분(기자재 공급사 · 사외 협력사 단품)")
    kinds = {s.supplier_id: s.kind for s in snapshot.suppliers}
    parts = {p.part_id: p for p in snapshot.parts}
    supplier_of = {}
    for line in snapshot.po_lines:
        order = next(po for po in snapshot.purchase_orders if po.po_id == line.po_id)
        for part_id in line.part_ids:
            supplier_of[part_id] = kinds[order.supplier_id]
    single = [p for p in parts.values() if p.kind in (PartKind.BRACKET, PartKind.PIPE_SUPPORT, PartKind.COLLAR)]
    c.check(
        "브라켓·서포트·칼라 단품은 사외 협력사(단품 제작)에, 장비는 기자재 공급사(장비)에 발주",
        bool(single)
        and all(supplier_of[p.part_id] is SupplierKind.PARTS for p in single)
        and all(
            supplier_of[p.part_id] is SupplierKind.EQUIPMENT for p in parts.values() if p.kind is PartKind.EQUIPMENT
        ),
    )


def _ecn_targets(c: Checker, generated: Generated) -> None:
    c.section("생성기 v3: 설계변경 이력은 v2 그대로(v3 부재를 대상으로 삼지 않음)")
    parts = {p.part_id: p for p in generated.snapshot.parts}
    home = {s.name: f"{s.block}" for s in load_config().piping.systems}
    added = {
        p.part_id
        for p in parts.values()
        if p.kind in (PartKind.COLLAR, PartKind.EQUIPMENT)
        or (p.system in home and not p.block_id.endswith(f":{home[str(p.system)]}"))
    }
    targets = {
        target
        for ecn in generated.ecns
        for op in ecn.change.ops
        for target in (
            *getattr(op, "part_ids", ()),
            *getattr(op, "removed_part_ids", ()),
            *getattr(op, "crosses_part_ids", ()),
            *(x for x in (getattr(op, "plate_part_id", None), getattr(op, "pipe_part_id", None)) if x),
        )
    }
    c.check(
        f"설계변경 300건의 대상에 v3 부재({len(added)}개: 이웃 블록 스풀·칼라·장비)가 없음",
        bool(added) and not targets & added,
        sorted(targets & added)[:3],
    )


# ---------- 시연 고정점 ----------


def _analysis(generated: Generated, ecn_id: str, alternatives: bool) -> AnalysisResult:
    settings = Settings.from_env({})
    ecn = next(e for e in generated.ecns if e.change.ecn_id == ecn_id and e.split is EcnSplit.DEV)
    request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of, include_alternatives=alternatives)
    book, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    return analyze(GraphIndex(generated.snapshot), request, book, params, load_strength(settings.strength_path))


def _cheaper(result: AnalysisResult) -> bool:
    """더 저렴한 충족 대안이 권고됨(결재함 '더 저렴한 대안'·시연 '같은 목적의 더 저렴한 대안')."""
    request = next(a for a in result.alternatives if a.alt_id == REQUEST_ALT)
    rec = result.recommendation
    chosen = next((a for a in result.alternatives if rec is not None and a.alt_id == rec.alt_id), None)
    return (
        chosen is not None
        and chosen.alt_id != REQUEST_ALT
        and chosen.eligibility.status is Eligibility.MEETS
        and chosen.total.value < request.total.value
    )


def _fixed_points(c: Checker, generated: Generated) -> None:
    c.section("시연 고정점: 같은 번호·이야기가 v3 지도·엔진 0.10.0에서도 성립")
    parts = {p.part_id: p for p in generated.snapshot.parts}
    ecns = {e.change.ecn_id: e.change for e in generated.ecns}
    pipe = ecns["ECN-D-0043"].ops[0]
    pipe_result = _analysis(generated, "ECN-D-0043", alternatives=False)
    c.check(
        "ECN-D-0043: 평형수 배관 경로 변경이고 후행 설치(선상 설치) 선택지가 있음(기다리는 방식 → 후행 설치)",
        isinstance(pipe, ReroutePipe)
        and all(parts[p].system == "ballast" for p in pipe.removed_part_ids)
        and pipe_result.onboard is not None
        and pipe_result.onboard.direction is OnboardDirection.TO_ON_BOARD,
        pipe_result.onboard,
    )
    plate = ecns["ECN-D-0119"].ops[0]
    plate_result = _analysis(generated, "ECN-D-0119", alternatives=True)
    stiffener = next((a for a in plate_result.alternatives if a.alt_id == "ALT-T1"), None)
    c.check(
        "ECN-D-0119: B31P 판 두께 증가 — 보강재 추가안(ALT-T1)이 충족·권고·더 쌈, 그 대안은 구역 출구 지연 없음",
        isinstance(plate, ThicknessChange)
        and all(p.startswith("S-001:B31P-PL-") for p in plate.part_ids)
        and plate.to_mm > plate.from_mm
        and _cheaper(plate_result)
        and stiffener is not None
        and plate_result.recommendation is not None
        and plate_result.recommendation.alt_id == "ALT-T1"
        and stiffener.max_exit_delay_days == 0,
        [
            (a.alt_id, a.eligibility.status.value, a.total.value, a.max_exit_delay_days)
            for a in plate_result.alternatives
        ],
    )
    inbox = _analysis(generated, "ECN-D-0067", alternatives=True)
    c.check(
        "ECN-D-0067: 결재함의 '더 저렴한 대안'(충족 대안이 요청안보다 쌈)",
        _cheaper(inbox),
        [(a.alt_id, a.eligibility.status.value, a.total.value) for a in inbox.alternatives],
    )
    thinner, rejected = ecns["ECN-D-0067"].ops[0], ecns["ECN-D-0173"].ops[0]
    c.check(
        "ECN-D-0173(반려) → ECN-D-0067: 같은 블록 판을 더 얇게 다시 올림",
        isinstance(thinner, ThicknessChange)
        and isinstance(rejected, ThicknessChange)
        and {parts[p].block_id for p in thinner.part_ids} == {parts[p].block_id for p in rejected.part_ids}
        and thinner.to_mm < rejected.to_mm,
    )
