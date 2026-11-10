"""상태 올리기(바뀌는 시트만, docs/input.md(엑셀 양식) 5절): 상태 시트만 읽고, 미리보기로 바뀌는 것·거부를 보이고,
확정하면 지금 지도에 덮어쓴다. 같은 모양 파일은 매핑을 기억한다. 로그인은 끈다(권한은 auth_api 표)."""

from __future__ import annotations

import io
import tempfile
import threading
import time
import warnings
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any
from unittest import mock

from harness import Checker
from openpyxl import Workbook

from ripple.api.app import create_app
from ripple.api.pending_imports import PENDING_TTL_S
from ripple.api.workspace import Workspaces
from ripple.api.workspace_errors import NotFound
from ripple.config.settings import Settings
from ripple.contracts.auth import Role
from ripple.contracts.domain import PO_STATUS_ORDER, GraphSnapshot, POStatus
from ripple.contracts.ingest import MappingProposal, MappingSubmission
from ripple.contracts.records import Actor
from ripple.contracts.workspace import WORKSPACE_HEADER
from ripple.engine.updates import highest_status
from ripple.generator.build import generate
from ripple.generator.io import load_config, write_outputs
from ripple.ingest.proposal import mapping_of
from ripple.ingest.template import PO_STATUSES

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

FILE = "발주현황_1020.xlsx"
OCTET = {"Content-Type": "application/octet-stream"}


def _targets(snapshot: GraphSnapshot, today: date) -> tuple[str, POStatus, str, str]:
    """(다음 단계로 올릴 발주, 그 단계, 리드타임을 바꿀 발주, 실적을 넣을 공정)."""
    movable = []
    for po in snapshot.purchase_orders:
        reached = highest_status(po)
        seen = [o.observed_on for o in po.observations] + list(po.entered_on.values())
        if reached in (POStatus.ORDERED, POStatus.MATERIAL_SECURED) and all(day <= today for day in seen):
            movable.append((po.po_id, PO_STATUS_ORDER[PO_STATUS_ORDER.index(reached) + 1]))
    first, second = movable[0], movable[1]
    activity = next(a.activity_id for a in snapshot.activities if a.actual_start is None and a.block_id)
    return first[0], first[1], second[0], activity


def _advance(snapshot: GraphSnapshot, today: date, skip: set[str]) -> tuple[str, POStatus]:
    """다음 단계로 올릴 수 있는 다른 발주(지도를 실제로 바꾸는 갱신)."""
    for po in snapshot.purchase_orders:
        reached = highest_status(po)
        seen = [o.observed_on for o in po.observations] + list(po.entered_on.values())
        if (
            po.po_id not in skip
            and reached in (POStatus.ORDERED, POStatus.MATERIAL_SECURED)
            and all(d <= today for d in seen)
        ):
            return po.po_id, PO_STATUS_ORDER[PO_STATUS_ORDER.index(reached) + 1]
    raise AssertionError("시험할 발주가 없어요")


def _workbook(po_id: str, step: POStatus, lead_po: str, lead: int, activity: str, today: date) -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "발주 관측"
    sheet.append(["발주번호", "상태", "관측일"])
    sheet.append([po_id, PO_STATUSES[step.value], today])
    orders = book.create_sheet("발주")
    orders.append(["발주번호", "입고까지(일)"])
    orders.append([lead_po, lead])
    works = book.create_sheet("공정")
    works.append(["공정ID", "실적 착수일"])
    works.append([activity, today])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _stage(client: TestClient, data: bytes) -> MappingProposal:
    response = client.post(f"/api/status-imports?file_name={FILE}", content=data, headers=OCTET)
    assert response.status_code == 200, response.text[:300]
    return MappingProposal.model_validate(response.json())


def _submit(client: TestClient, proposal: MappingProposal) -> dict[str, Any]:
    body = {"version": proposal.version, "mapping": mapping_of(proposal).model_dump(mode="json")}
    return dict(client.post(f"/api/status-imports/{proposal.import_id}/mapping", json=body).json())


def _overlap(
    holder: Workspaces, first: Callable[[], object], second: Callable[[], object]
) -> tuple[object, object, int]:
    """first가 지도에 적용하는 도중(apply_update 안에서 멈춤)에 second를 부른다. 두 결과(값 또는 예외)와 적용 횟수."""
    entered, release = threading.Event(), threading.Event()
    calls: list[int] = []
    original = holder.apply_update

    def slow(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        entered.set()
        release.wait(5)
        return original(*args, **kwargs)

    def run(fn: Callable[[], object]) -> object:
        try:
            return fn()
        except Exception as error:  # 어느 쪽이 무엇을 던졌는지 검사에서 본다
            return error

    with mock.patch.object(holder, "apply_update", side_effect=slow), ThreadPoolExecutor(2) as pool:
        one = pool.submit(run, first)
        entered.wait(5)
        two = pool.submit(run, second)
        time.sleep(0.3)  # 잠금이 나뉘어 있으면 이 사이에 둘째가 끼어든다
        release.set()
        return one.result(10), two.result(10), len(calls)


def _concurrent(c: Checker, client: TestClient, data: bytes) -> None:
    c.section("상태 올리기: 동시 확정(찾기 → 적용 → 기억을 잠금 하나 안에서)")
    state = client.app.state  # type: ignore[attr-defined]
    holder, imports, log = state.workspaces, state.status_imports, state.updates
    actor = Actor(login_id="dev", name="개발", role=Role.ADMIN, dev=True)

    proposal = _stage(client, data)
    staged = _submit(client, proposal)
    token = client.get("/api/snapshots").json()["workspace"]
    before = len(log.recent(200))

    def confirm() -> object:
        return imports.confirm(staged["import_id"], staged["version"], token, actor, log)

    one, two, calls = _overlap(holder, confirm, confirm)
    same = isinstance(one, tuple) and isinstance(two, tuple) and one[1].event_id == two[1].event_id
    c.check(
        "같은 확정이 동시에 두 번 와도 지도 적용·갱신 기록은 한 번, 늦은 쪽은 그 기록을 그대로 받음",
        same and calls == 1 and len(log.recent(200)) == before + 1,
        (type(one).__name__, type(two).__name__, calls, len(log.recent(200)) - before),
    )

    proposal = _stage(client, data)
    staged = _submit(client, proposal)
    token = client.get("/api/snapshots").json()["workspace"]
    submission = MappingSubmission(version=staged["version"], mapping=mapping_of(proposal))

    def resubmit() -> object:
        return imports.submit(staged["import_id"], submission)

    one, two, _ = _overlap(holder, confirm, resubmit)
    c.check(
        "확정이 적용하는 도중에 끼어든 다시 읽기는 받아 놓고 버리지 않고, 확정이 끝난 뒤 '없는 상태 올리기'(404)",
        isinstance(one, tuple) and isinstance(two, NotFound),
        (type(one).__name__, type(two).__name__),
    )


def run(c: Checker) -> None:
    generated = generate(load_config())
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        write_outputs(generated, root / "synthetic")
        settings = replace(
            Settings.from_env({"RIPPLE_AUTH": "off"}),
            snapshot_path=root / "synthetic" / "snapshot.json",
            data_dir=root / "data",
        )
        with TestClient(create_app(settings)) as client:
            _flow(c, client, generated.snapshot)


def _flow(c: Checker, client: TestClient, snapshot: GraphSnapshot) -> None:
    c.section("상태 올리기: 상태 시트만 읽기 → 미리보기 → 확정")
    first = client.get("/api/snapshots").json()
    today = date.fromisoformat(first["today"])
    po_id, step, lead_po, activity = _targets(snapshot, today)
    lead = next(po.lead_time_days for po in snapshot.purchase_orders if po.po_id == lead_po) + 7
    data = _workbook(po_id, step, lead_po, lead, activity, today)
    proposal = _stage(client, data)
    c.check(
        "고를 수 있는 양식 시트는 상태 시트 4개뿐, 필수는 ID·관측 값만",
        [t.key for t in proposal.template] == ["purchase_orders", "observations", "activities", "activity_checks"]
        and {f.key for t in proposal.template for f in t.columns if f.required}
        == {"po_id", "status", "observed_on", "activity_id", "state", "confirmed_on"},
    )
    result = _submit(client, proposal)
    diff = (result.get("preview") or {}).get("diff", {})
    c.check(
        "미리보기: 단계 변화·납기(리드타임) 전후·공정 실적, 거부 없음이면 확정 가능",
        result.get("import_id") is not None
        and [s["po_id"] for s in diff.get("status_changed", [])] == [po_id]
        and [(p["po_id"], p["after"]) for p in diff.get("plan_changed", [])] == [(lead_po, lead)]
        and [a["activity_id"] for a in diff.get("activities", [])] == [activity],
        str(result)[:400],
    )
    c.check("미리보기만으로는 지도가 그대로", client.get("/api/snapshots").json()["workspace"] == first["workspace"])
    # 미리보기 뒤에 다른 사람이 지도를 바꿈(화면 확인) → 옛 미리보기 확정은 최신 토큰으로 보내도 409
    other, other_status = _advance(snapshot, today, skip={po_id, lead_po})
    meanwhile = client.post(
        "/api/updates",
        json={
            "origin": "confirm",
            "items": [{"kind": "po_status", "po_id": other, "status": other_status, "observed_on": today.isoformat()}],
        },
        headers={WORKSPACE_HEADER: first["workspace"]},
    )
    latest = client.get("/api/snapshots").json()["workspace"]
    stale = client.post(
        f"/api/status-imports/{proposal.import_id}/confirm",
        json={"version": result["version"]},
        headers={WORKSPACE_HEADER: latest},
    )
    c.check(
        "미리보기 뒤 지도가 바뀌면 최신 토큰으로 확정해도 409(모르는 변경을 덮어쓰지 않음)",
        meanwhile.status_code == 200 and stale.status_code == 409,
        stale.text[:200],
    )
    result = _submit(client, _stage(client, data))
    confirmed = client.post(
        f"/api/status-imports/{result['import_id']}/confirm",
        json={"version": result["version"]},
        headers={WORKSPACE_HEADER: latest},
    )
    applied = confirmed.json()
    c.check(
        "다시 읽어 확정하면 지금 지도에 덮어쓴 새 지도·새 세대, 갱신 기록의 출처는 엑셀",
        confirmed.status_code == 200
        and applied["snapshots"]["workspace"] != latest
        and applied["event"]["origin"] == "excel"
        and applied["event"]["file_name"] == FILE,
        confirmed.text[:300],
    )
    c.check(
        "합성 지도에 엑셀 상태를 올리면 실제 데이터로 다뤄 외부 AI 호출이 꺼짐(신뢰 경계)",
        applied["snapshots"]["data_mode"] == "real" and applied["snapshots"]["llm_external"] is False,
    )
    retry = client.post(
        f"/api/status-imports/{result['import_id']}/confirm",
        json={"version": result["version"]},
        headers={WORKSPACE_HEADER: latest},
    )
    c.check(
        "응답을 잃고 같은 확정을 다시 보내도 같은 결과(새 갱신 없이 그 기록과 지금 지도)",
        retry.status_code == 200 and retry.json()["event"]["event_id"] == applied["event"]["event_id"],
        retry.text[:200],
    )
    imports = client.app.state.status_imports  # type: ignore[attr-defined]
    later = time.monotonic() + PENDING_TTL_S + 1
    imports._monotonic = lambda: later
    forgotten = client.post(
        f"/api/status-imports/{result['import_id']}/confirm",
        json={"version": result["version"]},
        headers={WORKSPACE_HEADER: applied["snapshots"]["workspace"]},
    )
    imports._monotonic = time.monotonic
    c.check(
        "확정한 상태 올리기도 30분이 지나면 잊음(404, 엑셀 가져오기와 같은 규칙)",
        forgotten.status_code == 404,
        forgotten.text[:200],
    )
    again = _stage(client, data)
    c.check("같은 모양 파일은 확정한 매핑을 기억(상태 올리기 종류)", again.remembered is not None)
    _concurrent(c, client, data)

    c.section("상태 올리기: 거부·권한 밖 시트")
    bad = _workbook("PO-9999", step, lead_po, lead, activity, today)
    rejected = _submit(client, _stage(client, bad))
    problems = (rejected.get("preview") or {}).get("problems", [])
    c.check(
        "지도에 없는 발주가 있으면 확정할 수 없고(import_id 없음) 그 항목·이유를 보임",
        rejected.get("import_id") is None and any(p["entity_id"] == "PO-9999" for p in problems),
    )
    mixed = Workbook()
    parts = mixed.active
    assert parts is not None
    parts.title = "부재"
    parts.append(["부재ID", "호선번호"])
    parts.append(["S-001:X-1", "S-001"])
    out = io.BytesIO()
    mixed.save(out)
    only_parts = _stage(client, out.getvalue())
    c.check(
        "부재처럼 구조 시트는 읽지 않음(읽지 않는 이유와 함께)",
        all(s.template is None for s in only_parts.sheets)
        and any("상태 올리기에서는" in r for s in only_parts.sheets for r in s.reasons),
    )
