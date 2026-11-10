"""실시간 시연 세계(docs/operations.md(서비스) 6절): 생성기 기준일을 옮기면 날짜만 옮겨진 같은 세계이고, 작업 공간은
한국 시간 오늘로 기본 지도를 만들어 날이 바뀌면 새 날의 세계로 넘어간다. 시계는 바꿔 끼운다(서버·키 없이)."""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from harness import Checker

from ripple.api.deps import AppContext
from ripple.api.live_world import LiveWorld, live_world
from ripple.api.snapshot_info import status_date
from ripple.api.workspace import Workspaces
from ripple.config.settings import Settings, parse_clock
from ripple.contracts.auth import Role
from ripple.contracts.domain import ActivityCheck, DataMode
from ripple.contracts.records import Actor
from ripple.contracts.updates import ActivityCheckItem, StatusUpdate, UpdateOrigin
from ripple.graph.memory import MemoryGraphStore
from ripple.store.snapshots import SnapshotStore
from ripple.store.updates import UpdateLog

DAY = date(2026, 10, 25)
_DATE = re.compile(r"\"(\d{4}-\d{2}-\d{2})\"")


def _back(world: LiveWorld, days: int) -> str:
    """세계의 지도(ID 빼고)·설계변경을 JSON으로, 날짜는 days만큼 앞으로 당겨서."""
    snapshot = json.loads(world.snapshot.model_dump_json())
    snapshot.pop("snapshot_id")
    text = json.dumps([snapshot, [json.loads(e.model_dump_json()) for e in world.ecns]], sort_keys=True)
    return _DATE.sub(lambda m: f'"{(date.fromisoformat(m.group(1)) - timedelta(days=days)).isoformat()}"', text)


def run(c: Checker) -> None:
    c.section("실시간 시연 세계")
    first, later = live_world(DAY), live_world(DAY + timedelta(days=3))
    c.check(
        "기준일만 사흘 옮긴 세계는 날짜만 사흘 옮겨진 같은 세계(지도·설계변경 — 시연 사례가 날마다 그대로 성립)",
        _back(later, 3) == _back(first, 0),
    )
    c.check(
        "세계의 자료 기준일과 설계변경 기준일 = 그날",
        status_date(first.snapshot) == DAY and bool(first.ecns) and all(e.as_of == DAY for e in first.ecns),
    )
    c.check(
        "설정: 시계 기본 fixed, live·fixed 말고는 오류, 실데이터 모드면 실시간 세계를 만들지 않음",
        Settings.from_env({}).synthetic_clock == "fixed"
        and Settings.from_env({"RIPPLE_SYNTHETIC_CLOCK": "LIVE"}).live_world
        and not Settings.from_env({"RIPPLE_SYNTHETIC_CLOCK": "live", "RIPPLE_DATA_MODE": "real"}).live_world
        and Checker.raises(lambda: parse_clock("now")),
    )
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        base = Settings.from_env({"RIPPLE_AUTH": "off", "RIPPLE_SYNTHETIC_CLOCK": "live"})
        settings = replace(base, snapshot_path=root / "없는-지도.json", data_dir=root / "data")
        day = [DAY]
        holder = Workspaces(
            AppContext.load(settings), MemoryGraphStore(), None, SnapshotStore(settings.data_dir), today=lambda: day[0]
        )
        start = holder.start()
        listing = holder.listing()
        c.check(
            "지도 파일 없이 시작: 기본 지도가 오늘의 합성 세계, 업무상 오늘·목록 오늘 = 오늘",
            start.data_mode is DataMode.SYNTHETIC
            and status_date(start.snapshot) == DAY
            and holder.today() == DAY
            and listing.today == DAY,
        )
        c.check(
            "샘플 설계변경의 기준일 = 오늘(목록 D-n이 오늘부터)",
            bool(start.samples) and all(s.request.as_of == DAY for s in start.samples),
        )
        holder.roll_day()
        c.check("같은 날 다시 물으면 그대로(새 세대 없음)", holder.current is start)
        day[0] = DAY + timedelta(days=1)
        holder.roll_day()
        moved = holder.current
        assert moved is not None
        c.check(
            "날이 바뀌면 새 날의 기본 지도로 새 세대(토큰이 바뀌어 화면이 다시 읽음), 샘플·오늘도 새 날",
            moved.generation == start.generation + 1
            and moved.token != start.token
            and status_date(moved.snapshot) == day[0]
            and holder.default_snapshot().snapshot_id == moved.snapshot.snapshot_id
            and holder.today() == day[0]
            and bool(moved.samples)
            and all(s.request.as_of == day[0] for s in moved.samples),
        )
        c.check(
            "목록의 기본 지도도 새 날의 지도(옛 지도는 목록에 남지 않음)",
            [i.snapshot_id for i in holder.listing().items if i.default] == [moved.snapshot.snapshot_id],
        )
        day[0] = DAY + timedelta(days=2)
        with mock.patch.object(holder, "_install", side_effect=RuntimeError("설치 실패")):
            failed = Checker.raises(holder.roll_day, RuntimeError)
        kept = holder.current is moved and holder.default_snapshot().snapshot_id == moved.snapshot.snapshot_id
        holder.roll_day()
        again = holder.current
        c.check(
            "새 날 설치가 실패하면 전날 상태로 되돌려(기본 지도·샘플·날짜) 다음 요청이 다시 시도함",
            failed and kept and again is not None and status_date(again.snapshot) == day[0],
        )
        _updated_map(c, settings, holder, day)


def _updated_map(c: Checker, settings: Settings, holder: Workspaces, day: list[date]) -> None:
    """그날 기본 지도에서 상태만 바꾼 지도(현장 확인)를 쓰다가 날이 바뀌거나 서버를 다시 켜면 오늘 기본 지도로."""
    today_map = holder.current
    assert today_map is not None
    idle = next(a.activity_id for a in today_map.snapshot.activities if a.actual_start is None)
    check = StatusUpdate(
        origin=UpdateOrigin.CONFIRM,
        items=(ActivityCheckItem(activity_id=idle, state=ActivityCheck.NOT_STARTED, confirmed_on=day[0]),),
    )
    actor = Actor(login_id="dev", name="개발", role=Role.ADMIN, dev=True)
    derived, _ = holder.apply_update(check, today_map.token, actor, UpdateLog(settings.data_dir))
    c.check(
        "전제: 현장 확인으로 상태만 바꾼 지도가 활성(계보 시작 = 그날 기본 지도, 샘플 그대로)",
        derived.info.update is not None
        and derived.info.update.lineage_root == today_map.snapshot.snapshot_id
        and bool(derived.samples),
    )
    day[0] += timedelta(days=1)
    holder.roll_day()
    rolled = holder.current
    assert rolled is not None
    c.check(
        "상태만 바꾼 지도를 쓰다가 날이 바뀌어도 새 날의 기본 지도로(샘플 있음, 갱신 지도는 목록에 남음)",
        status_date(rolled.snapshot) == day[0]
        and rolled.info.update is None
        and bool(rolled.samples)
        and derived.snapshot.snapshot_id in {i.snapshot_id for i in holder.listing().items},
    )
    fresh = Workspaces(
        AppContext.load(settings), MemoryGraphStore(), None, SnapshotStore(settings.data_dir), today=lambda: day[0]
    )
    restarted = fresh.start()
    c.check(
        "다시 켤 때 활성 기록이 다른 날 세계의 상태 갱신 지도면 오늘 기본 지도로 시작하고 목록에 이유를 남김",
        status_date(restarted.snapshot) == day[0]
        and restarted.info.update is None
        and bool(restarted.samples)
        and "다른 날짜 시연 데이터" in (fresh.restore_problem or ""),
        fresh.restore_problem,
    )
