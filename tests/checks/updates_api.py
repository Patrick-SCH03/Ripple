"""상태 갱신 API(docs/domain.md 12절): 적용 → 새 지도·새 세대·기록, 옛 토큰 409, 날짜 규칙 422, 재확인,
다시 켜도 그대로.

로그인은 끈다(권한은 tests/checks/auth.py의 역할 표). 지도 파일·데이터 폴더는 임시 폴더.
"""

from __future__ import annotations

import sqlite3
import tempfile
import warnings
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from harness import Checker

from ripple.api.app import create_app
from ripple.config.settings import Settings
from ripple.contracts.domain import PO_STATUS_ORDER, GraphSnapshot, POStatus
from ripple.contracts.workspace import WORKSPACE_HEADER
from ripple.engine.updates import highest_status
from ripple.generator.build import generate
from ripple.generator.io import load_config, write_outputs
from ripple.store import updates as updates_store
from ripple.store.append_log import connect

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient


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
        new_map = _flow(c, settings, generated.snapshot)
        _rollback(c, settings, generated.snapshot)
        with TestClient(create_app(settings)) as client:
            listing = client.get("/api/snapshots").json()
            c.check(
                "다시 켜도 갱신한 지도로 시작하고 샘플 목록이 그대로",
                listing["active_snapshot_id"] == new_map and len(client.get("/api/samples").json()) > 0,
            )


def _po(snapshot: GraphSnapshot, today: date, skip: str | None = None) -> tuple[str, POStatus]:
    """아직 입고 전이고 오늘(업무상) 뒤 근거가 없는 발주와 그 다음 단계(skip은 건너뜀)."""
    for po in snapshot.purchase_orders:
        if po.po_id == skip:
            continue
        reached = highest_status(po)
        seen = [o.observed_on for o in po.observations] + list(po.entered_on.values())
        early = reached is not None and reached not in (POStatus.RECEIVED, POStatus.PROCESSED)
        if early and reached is not None and all(day <= today for day in seen):
            return po.po_id, PO_STATUS_ORDER[PO_STATUS_ORDER.index(reached) + 1]
    raise AssertionError("시험할 발주가 없어요")


def _body(po_id: str, status: POStatus, day: str, origin: str = "confirm") -> dict[str, Any]:
    return {"origin": origin, "items": [{"kind": "po_status", "po_id": po_id, "status": status, "observed_on": day}]}


def _flow(c: Checker, settings: Settings, snapshot: GraphSnapshot) -> str:
    c.section("상태 갱신 API: 적용·충돌·날짜 규칙·재확인")
    with TestClient(create_app(settings)) as client:
        first = client.get("/api/snapshots").json()
        today = date.fromisoformat(first["today"])
        c.check(
            "합성 지도의 업무상 오늘 = 지도 자료 기준일",
            first["today"] == first["items"][0]["status_date"],
        )
        po_id, nxt = _po(snapshot, today)
        token = first["workspace"]
        body = _body(po_id, nxt, today.isoformat())
        c.check("기대 작업 공간 토큰 없이 보내면 거절(422)", client.post("/api/updates", json=body).status_code == 422)
        preview = client.post("/api/updates/preview", json=body).json()
        c.check(
            "미리보기는 지도를 바꾸지 않고 바뀔 것을 보여 줌",
            preview["snapshot_id"] is not None
            and client.get("/api/snapshots").json()["workspace"] == token
            and [s["po_id"] for s in preview["diff"]["status_changed"]] == [po_id],
        )
        applied = client.post("/api/updates", json=body, headers={WORKSPACE_HEADER: token})
        result = applied.json()
        listing = result.get("snapshots", {})
        active: dict[str, Any] = next(
            (i for i in listing.get("items", []) if i["snapshot_id"] == listing.get("active_snapshot_id")), {}
        )
        c.check(
            "적용하면 새 지도·새 세대, 지도 이름·표시에 상태 갱신",
            applied.status_code == 200
            and listing["workspace"] != token
            and listing["active_snapshot_id"] != first["active_snapshot_id"]
            and "상태 갱신" in active.get("name", "")
            and active.get("update", {}).get("status_changed") == 1
            and active["update"]["lineage_root"] == first["active_snapshot_id"],
            applied.text[:300],
        )
        c.check("갱신한 지도에서도 샘플 목록(같은 구조)", len(client.get("/api/samples").json()) > 0)
        stale = client.post("/api/updates", json=body, headers={WORKSPACE_HEADER: token})
        c.check("옛 토큰으로 보내면 409(다른 사람이 먼저 바꿈)", stale.status_code == 409)
        new_token = listing["workspace"]
        yesterday = (today - timedelta(days=1)).isoformat()
        past = client.post("/api/updates", json=_body(po_id, nxt, yesterday), headers={WORKSPACE_HEADER: new_token})
        c.check(
            "화면 확인은 오늘 날짜만(어제 날짜는 422, 아무것도 바꾸지 않음)",
            past.status_code == 422 and client.get("/api/snapshots").json()["workspace"] == new_token,
        )
        tomorrow = (today + timedelta(days=1)).isoformat()
        future = client.post(
            "/api/updates", json=_body(po_id, nxt, tomorrow, "excel"), headers={WORKSPACE_HEADER: new_token}
        )
        c.check("엑셀 올리기도 오늘 뒤 날짜의 사실은 422", future.status_code == 422)
        again = client.post("/api/updates", json=body, headers={WORKSPACE_HEADER: new_token})
        c.check(
            "같은 확인을 다시 하면 지도·세대 그대로, 기록은 남음(재확인)",
            again.status_code == 200
            and again.json()["snapshots"]["workspace"] == new_token
            and again.json()["event"]["diff"]["confirmed_only"] == 1,
        )
        based = {**body, "base_snapshot_id": first["active_snapshot_id"]}
        moved = client.post("/api/updates", json=based, headers={WORKSPACE_HEADER: new_token})
        c.check("화면이 본 지도(base)가 지금 지도와 다르면 409(모르는 변경을 덮어쓰지 않음)", moved.status_code == 409)
        events = client.get("/api/updates").json()
        c.check(
            "갱신 기록: 최근 것부터 2건, 누가·언제·바뀐 것",
            len(events) == 2
            and events[0]["event_id"] == again.json()["event"]["event_id"]
            and events[1]["diff"]["status_changed"][0]["po_id"] == po_id
            and events[1]["actor"]["name"],
        )
        other, step = _po(snapshot, today, skip=po_id)
        more = client.post(
            "/api/updates", json=_body(other, step, today.isoformat()), headers={WORKSPACE_HEADER: new_token}
        )
        latest = more.json()["snapshots"]
        updated = [i for i in latest["items"] if i.get("update")]
        c.check(
            "같은 계보의 갱신 지도는 목록에 가장 최근 것 하나만(확인할 때마다 늘지 않음)",
            more.status_code == 200 and [i["snapshot_id"] for i in updated] == [latest["active_snapshot_id"]],
        )
        return str(latest["active_snapshot_id"])


def _rollback(c: Checker, settings: Settings, snapshot: GraphSnapshot) -> None:
    c.section("상태 갱신 API: 전환이 실패하면 기록도 되돌림")
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        listing = client.get("/api/snapshots").json()
        today = date.fromisoformat(listing["today"])
        activity = next(a.activity_id for a in snapshot.activities if a.actual_start is None and a.block_id)
        check = {
            "kind": "activity_check",
            "activity_id": activity,
            "state": "not_started",
            "confirmed_on": today.isoformat(),
        }
        holder = client.app.state.workspaces  # type: ignore[attr-defined]
        before = len(client.get("/api/updates").json())
        original = holder._install

        def broken(*args: Any, **kwargs: Any) -> Any:
            raise OSError("디스크가 가득 참")

        holder._install = broken
        try:
            failed = client.post(
                "/api/updates",
                json={"origin": "confirm", "items": [check]},
                headers={WORKSPACE_HEADER: listing["workspace"]},
            )
        finally:
            holder._install = original
        after = client.get("/api/snapshots").json()
        c.check(
            "활성 전환이 실패하면 갱신 기록이 남지 않고, 저장만 된 그 지도는 목록·전환에서 숨김",
            failed.status_code == 500
            and len(client.get("/api/updates").json()) == before
            and after["workspace"] == listing["workspace"]
            and len(after["items"]) == len(listing["items"]),
            (failed.status_code, failed.text[:200]),
        )
        _commit_failure(c, client, check)


class _CommitFails:
    """기록 확정(commit)만 실패하는 연결(나머지는 진짜 연결에 맡김)."""

    def __init__(self, inner: sqlite3.Connection) -> None:
        self._inner = inner

    def commit(self) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _commit_failure(c: Checker, client: TestClient, check: dict[str, Any]) -> None:
    """활성 전환은 됐는데 갱신 기록 확정이 실패: 새 지도만 활성으로 남지 않고 그 전 지도·세대로 되돌림."""
    listing = client.get("/api/snapshots").json()
    before = len(client.get("/api/updates").json())
    setattr(updates_store, "connect", lambda *a, **k: _CommitFails(connect(*a, **k)))  # noqa: B010
    try:
        failed = client.post(
            "/api/updates",
            json={"origin": "confirm", "items": [check]},
            headers={WORKSPACE_HEADER: listing["workspace"]},
        )
    finally:
        setattr(updates_store, "connect", connect)  # noqa: B010
    after = client.get("/api/snapshots").json()
    c.check(
        "기록 확정이 실패하면 활성 지도·작업 공간 토큰·목록·기록이 모두 그 전 그대로(503)",
        failed.status_code == 503
        and len(client.get("/api/updates").json()) == before
        and after["workspace"] == listing["workspace"]
        and after["active_snapshot_id"] == listing["active_snapshot_id"]
        and len(after["items"]) == len(listing["items"]),
        (failed.status_code, failed.text[:200], after["active_snapshot_id"] == listing["active_snapshot_id"]),
    )
