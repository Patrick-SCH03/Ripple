"""식별자의 성질: 결과를 바꾸는 입력만 ID를 바꾼다."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from fixtures import THICKNESS_OP, VERSIONS, analysis_request, change_body, snapshot, snapshot_body
from harness import Checker

from ripple.contracts.domain import DataMode
from ripple.contracts.identity import LATER_FIELDS, analysis_id, canonical_json, snapshot_id
from ripple.graph.files import load_snapshot


def run(c: Checker) -> None:
    c.section("식별자: 분석 ID")
    base = analysis_id(VERSIONS, analysis_request())

    def with_change(**override: object) -> str:
        return analysis_id(VERSIONS, analysis_request(change=change_body(**override)))

    c.check(
        "원문·제목·ECN 번호·요청자가 달라도 같은 ID",
        base == with_change(ecn_id="E-99", title="다른 제목", raw_text="T31C 판 12T→14T", requested_by="설계팀"),
    )
    two_parts = {**THICKNESS_OP, "part_ids": ["p-a", "p-b"]}
    swapped = {**THICKNESS_OP, "part_ids": ["p-b", "p-a"]}
    c.check("대상 부재 순서가 달라도 같은 ID", with_change(ops=[two_parts]) == with_change(ops=[swapped]))
    reroute = {"op": "reroute_pipe", "removed_part_ids": ["s-b", "s-a"], "added_spool_spec_ids": ["DN100", "DN150"]}
    c.check(
        "경로 변경의 빼는 스풀 순서는 무관하지만 더하는 스풀 규격 순서는 다른 ID",
        with_change(ops=[reroute]) == with_change(ops=[{**reroute, "removed_part_ids": ["s-a", "s-b"]}])
        and with_change(ops=[reroute]) != with_change(ops=[{**reroute, "added_spool_spec_ids": ["DN150", "DN100"]}]),
    )
    other_op = {"op": "grade", "part_ids": ["p-a"], "from_grade": "AH32", "to_grade": "AH36"}
    c.check(
        "연산 순서가 달라도 같은 ID",
        with_change(ops=[THICKNESS_OP, other_op]) == with_change(ops=[other_op, THICKNESS_OP]),
    )
    c.check(
        "확정일을 비우면 기준일로 확정한 것과 같은 ID",
        base == analysis_id(VERSIONS, analysis_request(confirm_on="2026-10-20")),
    )
    c.check("바꾸는 두께가 다르면 다른 ID", base != with_change(ops=[{**THICKNESS_OP, "to_mm": 16}]))
    c.check(
        "변경 사유는 계산에 쓰지 않아 분석 ID를 바꾸지 않음(분석 뒤에 기록해도 같은 분석)",
        base == with_change(intent="weight") == with_change(intent=None),
    )
    c.check("확정일이 다르면 다른 ID", base != analysis_id(VERSIONS, analysis_request(confirm_on="2026-10-21")))
    c.check(
        "보류 행동이 있으면 다른 ID",
        base != analysis_id(VERSIONS, analysis_request(holds=[{"po_id": "PO-1", "hold_days": 7}])),
    )
    for field in ("contract", "snapshot_id", "rules", "params", "engine"):
        changed = VERSIONS.model_copy(update={field: "other"})
        c.check(f"버전 '{field}'가 다르면 다른 ID", base != analysis_id(changed, analysis_request()))
    c.check("분석 ID 형식은 A-16자리", base.startswith("A-") and len(base) == 18)

    c.section("식별자: 스냅샷 ID")
    first = snapshot_id(snapshot())
    c.check("snapshot_id 필드 값과 무관", first == snapshot_id(snapshot(snapshot_id="G-anything")))
    renamed = snapshot_body()
    renamed["blocks"][0]["name"] = "No.3 COT 횡격벽(개정)"
    c.check("내용이 바뀌면 다른 ID", first != snapshot_id(snapshot(blocks=renamed["blocks"])))
    c.check("스냅샷 ID 형식은 G-16자리", first.startswith("G-") and len(first) == 18)
    duplicated = snapshot_body()["parts"] * 2
    c.check("부재 ID가 겹치는 지도는 거부", c.raises(lambda: snapshot(parts=duplicated)))
    c.check("생성기 지도가 real 모드면 거부", c.raises(lambda: snapshot(data_mode="real")))

    c.section("식별자: 배관 계통 이름표(계약 1.8.0)")
    names = [{"system": "ballast", "name": "평형수"}]
    c.check("이름표가 있으면 내용 해시에 들어감", snapshot_id(snapshot(pipe_systems=names)) != first)
    c.check(
        "이름이 바뀌면 다른 지도",
        snapshot_id(snapshot(pipe_systems=names))
        != snapshot_id(snapshot(pipe_systems=[{**names[0], "name": "밸러스트"}])),
    )
    c.check("계통 키가 겹치는 이름표는 거부", c.raises(lambda: snapshot(pipe_systems=names * 2)))
    # 1.7.0 생성기가 쓴 지도 파일: pipe_systems 칸(과 그 뒤 판에 더한 칸)이 없고, ID는 그 칸이 없는 내용의 해시
    legacy = snapshot().model_dump(mode="json", exclude={"pipe_systems", "crews"})
    for collection, fields in LATER_FIELDS.items():
        for item in legacy[collection]:
            for name in fields:
                item.pop(name, None)
    legacy.pop("snapshot_id")
    legacy["snapshot_id"] = f"G-{hashlib.sha256(canonical_json(legacy)).hexdigest()[:16]}"
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "snapshot.json"
        path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        try:
            loaded = load_snapshot(path, DataMode.SYNTHETIC)
            problem = ""
        except ValueError as error:
            loaded, problem = None, str(error)
    c.check(
        "이름표 칸이 없던 지도 파일(1.7.0)도 ID가 맞아 그대로 읽힘(계통은 키로 보임)",
        loaded is not None and loaded.snapshot_id == legacy["snapshot_id"] and loaded.pipe_systems == (),
        problem,
    )
    _later_fields(c, first)


def _later_fields(c: Checker, first: str) -> None:
    """1.32.0 선택 필드(작업반·블록 난이도 입력·다른 분야 도면·수행 주체): 비면 ID에 넣지 않고, 채우면 ID가 바뀐다."""
    c.section("식별자: 1.32.0 선택 필드는 비면 지도 ID에서 뺌")
    body = snapshot_body()
    block = {**body["blocks"][0], "shape": None, "outfit_items": None, "electric_items": None}
    part = {**body["parts"][0], "secondary_drawing_ids": []}
    c.check(
        "새 필드를 비워 적은 지도(엑셀 가져오기 등)는 새 필드가 없던 지도와 같은 ID",
        snapshot_id(snapshot(blocks=[block], parts=[part], crews=[])) == first,
    )
    crews = [{"crew_id": "CRW-01", "name": "한빛 작업반", "processes": ["sub_assembly"]}]
    shaped = [{**body["blocks"][0], "shape": "curved"}]
    counted = [{**body["blocks"][0], "outfit_items": 12, "electric_items": 3}]
    drawn = [{**body["parts"][0], "secondary_drawing_ids": ["DWG-P11C-CS-P01@A"]}]
    changed = {
        "작업반": snapshot(crews=crews),
        "블록 형상": snapshot(blocks=shaped),
        "의장·전장품 수": snapshot(blocks=counted),
        "다른 분야 도면": snapshot(parts=drawn),
    }
    c.check(
        "작업반·블록 형상·의장·전장품 수·다른 분야 도면을 채우면 다른 ID",
        all(snapshot_id(s) != first for s in changed.values()),
        [name for name, s in changed.items() if snapshot_id(s) == first],
    )
    c.check(
        "작업반 ID로 'direct'(직영 표기)는 거부, 작업반 ID가 겹치면 거부",
        c.raises(lambda: snapshot(crews=[{**crews[0], "crew_id": "direct"}]))
        and c.raises(lambda: snapshot(crews=crews * 2)),
    )
