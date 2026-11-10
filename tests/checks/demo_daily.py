"""시연 기록 날마다 새로 채우기(RIPPLE_DEMO_SEED + 실시간 시연 세계, docs/operations.md(서비스) 7절) — 서버·키 없이.

- KST 날이 바뀌어 작업 공간이 새 날로 넘어가면(roll_day의 새 날 훅) 옛 기록을 자동 보관하고 그날 기준으로 다시 채움:
  결재함 D-n이 새 날 기준(첫날과 같은 값) · 오늘 검토 요청한 건의 지도 = 새 날 지도라 결재선 승인이 409 없이 됨.
- 같은 날 다시 시작하면 그대로 · 시드 판이 다르면 같은 날이어도 다시 채움 · 날짜에 멈춘 세계 · 시드 끔 · 기본 지도가
  아닌 지도면 안 함.
- 자동 보관은 최근 14개만(사람이 표지로 만든 보관은 그대로).
- 채우는 동안 다른 요청은 반쯤 찬 기록을 보지 않음(읽는 스레드가 본 설계변경·실적 수가 늘 온전한 수).
- 바꿔 끼우다 n번째 파일에서 실패하면(가짜 replace_file) 데이터 폴더 원복 · 준비 폴더 제거 · 문 풀림, 되돌리기마저
  실패하면 남은 파일도 되돌리고 로그 · 원래 예외(__cause__ = 되돌리기 실패).
"""

from __future__ import annotations

import json
import logging
import tempfile
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from harness import Checker

from ripple.api.demo_daily import MARK_FILE, DemoSeeder, read_mark, seed_demo
from ripple.api.demo_plan import APPROVERS, PLAN
from ripple.api.deps import AppContext
from ripple.api.live_world import live_world
from ripple.api.records import commit_action
from ripple.api.workspace import Workspaces
from ripple.auth import Principal
from ripple.config.files import replace_file
from ripple.config.settings import Settings
from ripple.contracts.auth import Role
from ripple.contracts.domain import ActivityCheck, DataMode
from ripple.contracts.records import ActionRequest, Actor, ApprovalStep, EcnAction, EcnState
from ripple.contracts.updates import ActivityCheckItem, StatusUpdate, UpdateOrigin
from ripple.generator.build import generate
from ripple.generator.io import load_config, write_outputs
from ripple.graph.memory import MemoryGraphStore
from ripple.records.flow import FlowError
from ripple.records.metrics import Inputs, overview
from ripple.store import reset
from ripple.store.accounts import AccountStore
from ripple.store.gate import gate_of
from ripple.store.outcomes import OutcomeLog
from ripple.store.records import RecordStore
from ripple.store.reset import AUTO_KEEP, DONE, STAGING, TARGETS, prune_auto, staging_folder, swap_records
from ripple.store.snapshots import SnapshotStore
from ripple.store.updates import UpdateLog

DAY = date(2026, 11, 9)
NOW = datetime(2026, 11, 9, 6, 0, tzinfo=UTC)  # KST 15:00
LIVE_ON = {"RIPPLE_SYNTHETIC_CLOCK": "live", "RIPPLE_DEMO_SEED": "on"}
VERSION = "검사 판 1"


def run(c: Checker) -> None:
    c.section("시연 기록 날마다 새로 채우기: 새 날 · 같은 날 · 시드 판")
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        _rolls(c, root)
        _version(c, root)
        _not_here(c, root)
    _prune(c)
    _swap_undo(c)


# ---------- 준비 ----------


class _Desk:
    """실시간 세계 작업 공간 + 시드 입구(날짜·시각을 함께 옮긴다)."""

    def __init__(self, settings: Settings, *, version: str = VERSION) -> None:
        self.settings = settings
        self.day = [DAY]
        self.now = [NOW]
        self.context = AppContext.load(settings)
        self.holder = Workspaces(
            self.context, MemoryGraphStore(), None, SnapshotStore(settings.data_dir), today=lambda: self.day[0]
        )
        self.holder.start()
        self.accounts = AccountStore(settings.data_dir)
        self.accounts.load()
        RecordStore(settings.data_dir).start()
        self.seeder = DemoSeeder(self.context, self.holder, self.accounts, clock=lambda: self.now[0], version=version)
        self.holder.on_new_day(self.seeder.new_day)

    def advance(self, days: int = 1) -> None:
        self.day[0] += timedelta(days=days)
        self.now[0] += timedelta(days=days)


def _settings(root: Path, data: str, env: dict[str, str]) -> Settings:
    return replace(Settings.from_env(env), data_dir=root / data)


def _counts(data_dir: Path) -> tuple[int, int, int]:
    store = RecordStore(data_dir)
    return len(store.listing(include_real=True).ecns), store.verify().entries, len(OutcomeLog(data_dir).latest())


def _archives(data_dir: Path) -> list[str]:
    return sorted(p.name for p in (data_dir / "archive").glob("records-auto-*"))


def _inbox(data_dir: Path, now: datetime) -> list[tuple[str, int]]:
    store = RecordStore(data_dir)
    items, audit, bodies = store.overview_inputs(include_real=True)
    found = overview(Inputs(items=items, audit=audit, bodies=bodies, now=now, days=30, live=True))
    return sorted((i.ecn_id, i.days_left) for i in found.inbox)


def _approve_part_lead(desk: _Desk, snapshot_id: str) -> str:
    """파트장 단계에서 기다리는 건을 파트장(이파트장)이 그 지도(커밋 때의 활성 지도)로 승인해 본다. 결과: 'ok' 또는
    오류 상태·코드."""
    store = RecordStore(desk.settings.data_dir)
    waiting = [
        item.status
        for item in store.listing(include_real=True).ecns
        if item.status.state is EcnState.IN_REVIEW
        and item.status.review is not None
        and item.status.review.current is ApprovalStep.PART_LEAD
    ]
    if not waiting:
        return "파트장 대기 없음"
    status = waiting[0]
    found = store.record(status.record_id, include_real=True)
    assert found is not None and status.review is not None
    part_lead = next(p for p in APPROVERS if p.role is Role.PART_LEAD)
    body = ActionRequest(
        action=EcnAction.APPROVE,
        expected_version=status.version,
        revision=status.revision,
        record_id=status.record_id,
        review_seq=status.review.seq,
        reason="확인 필요 항목 모두 확인",
        acknowledged=tuple(item.key for item in found.body.checklist),
    )
    try:
        commit_action(
            desk.context,
            store,
            Principal(login_id=part_lead.login_id, name=part_lead.name, role=part_lead.role),
            status.ecn_id,
            body,
            active_snapshot_id=snapshot_id,
            login_mode=True,
        )
    except FlowError as error:
        return f"{error.status} {error.code}"
    return "ok"


# ---------- 새 날 ----------


def _rolls(c: Checker, root: Path) -> None:
    desk = _Desk(_settings(root, "roll", LIVE_ON))
    data_dir = desk.settings.data_dir
    first = desk.seeder.start()
    counts = _counts(data_dir)
    inbox = _inbox(data_dir, NOW)
    mark = read_mark(data_dir)
    c.check(
        "시작: 빈 폴더에 채우고 표시(채운 날 · 시드 판)를 남김, 빈 기록은 보관하지 않음",
        first is not None
        and counts[0] == len(PLAN)
        and mark is not None
        and mark.day == DAY
        and mark.version == VERSION
        and _archives(data_dir) == [],
        (counts, mark, _archives(data_dir)),
    )
    desk.advance()
    stale = _approve_part_lead(desk, live_world(desk.day[0]).snapshot.snapshot_id)  # 채우기 전 = 전날 기록
    reads = _reading(data_dir, desk.holder.roll_day)
    after = _counts(data_dir)
    c.check(
        "날이 바뀌면(작업 공간 새 날) 옛 기록을 자동 보관하고 그날 기준으로 다시 채움(같은 수 · 표시 = 새 날)",
        after == counts
        and len(_archives(data_dir)) == 1
        and getattr(read_mark(data_dir), "day", None) == desk.day[0]
        and not (data_dir / ".seed-staging").exists(),
        (after, _archives(data_dir)),
    )
    c.check(
        "결재함 D-n이 새 날 기준(첫날 시드의 첫날 D-n과 같음)",
        _inbox(data_dir, desk.now[0]) == inbox,
        (_inbox(data_dir, desk.now[0]), inbox),
    )
    c.check(
        "전제: 새로 채우지 않았으면 전날 지도 기록이라 파트장 승인이 409(map_changed)",
        stale.startswith("409"),
        stale,
    )
    c.check(
        "새로 채운 뒤 파트장 승인 409 없음(오늘 검토 요청한 건의 지도 = 새 날 지도)",
        _approve_part_lead(desk, _active(desk)) == "ok",
    )
    c.check(
        "채우는 동안 읽는 스레드가 본 설계변경·실적 수는 늘 온전한 수(반쯤 찬 기록 없음)",
        bool(reads) and all(seen == (len(PLAN), counts[2]) for seen in reads),
        sorted(set(reads)),
    )
    archived = json.loads((data_dir / "archive" / _archives(data_dir)[0] / DONE).read_text(encoding="utf-8"))
    c.check(
        "자동 보관 폴더: 기록·실적 파일 · DONE에 auto · 새 날 · 이유(날 바뀜)",
        archived.get("auto") is True
        and "records.sqlite3" in archived.get("moved", [])
        and "outcomes.sqlite3" in archived.get("moved", [])
        and archived.get("day") == desk.day[0].isoformat()
        and "날 바뀜" in str(archived.get("why")),
        archived,
    )
    again = _Desk(desk.settings)
    again.day[0], again.now[0] = desk.day[0], desk.now[0]
    restarted = again.seeder.start(desk.now[0] + timedelta(hours=1))
    c.check(
        "같은 날 다시 시작하면 그대로(안 채움 · 보관 늘지 않음)",
        restarted is None and len(_archives(data_dir)) == 1,
        _archives(data_dir),
    )


def _active(desk: _Desk) -> str:
    current = desk.holder.current
    assert current is not None
    return current.snapshot.snapshot_id


def _reading(data_dir: Path, action: Callable[[], None]) -> list[tuple[int, int]]:
    """action을 하는 동안 다른 스레드가 설계변경 수 · 실적 수를 계속 읽어 본 값을 모은다."""
    seen: list[tuple[int, int]] = []
    stop = threading.Event()

    def read() -> None:
        store = RecordStore(data_dir)
        outcomes = OutcomeLog(data_dir)
        while not stop.is_set():
            seen.append((len(store.listing(include_real=True).ecns), len(outcomes.latest())))

    thread = threading.Thread(target=read)
    thread.start()
    try:
        action()
    finally:
        stop.set()
        thread.join()
    return seen


# ---------- 시드 판 ----------


def _version(c: Checker, root: Path) -> None:
    settings = _settings(root, "version", LIVE_ON)
    desk = _Desk(settings)
    desk.seeder.start()
    before = _counts(settings.data_dir)
    changed = _Desk(settings, version="검사 판 2")
    result = changed.seeder.start(NOW + timedelta(hours=1))
    mark = read_mark(settings.data_dir)
    c.check(
        "시드 판이 다르면 같은 날이어도 다시 채움(보관 1 · 같은 수 · 표시 = 새 판)",
        result is not None
        and _counts(settings.data_dir) == before
        and len(_archives(settings.data_dir)) == 1
        and mark is not None
        and mark.version == "검사 판 2",
        (mark, _archives(settings.data_dir)),
    )
    (settings.data_dir / MARK_FILE).write_text("{깨진", encoding="utf-8")
    broken = _Desk(settings, version="검사 판 2").seeder.start(NOW + timedelta(hours=2))
    c.check(
        "표시 파일이 깨졌으면 모르는 기록으로 보고 다시 채움",
        broken is not None and len(_archives(settings.data_dir)) == 2,
    )


# ---------- 안 하는 경우 ----------


def _not_here(c: Checker, root: Path) -> None:
    c.section("시연 기록 날마다 새로 채우기: 안 하는 경우")
    off = _Desk(_settings(root, "off", {"RIPPLE_SYNTHETIC_CLOCK": "live"}))
    off.advance()
    off.holder.roll_day()
    off.seeder.new_day()
    c.check("시드 끔: 새 날에도 아무것도 안 함", _counts(off.settings.data_dir) == (0, 0, 0))

    desk = _Desk(_settings(root, "derived", LIVE_ON))
    desk.seeder.start()
    before = _counts(desk.settings.data_dir)
    current = desk.holder.current
    assert current is not None
    idle = next(a.activity_id for a in current.snapshot.activities if a.actual_start is None)
    check = StatusUpdate(
        origin=UpdateOrigin.CONFIRM,
        items=(ActivityCheckItem(activity_id=idle, state=ActivityCheck.NOT_STARTED, confirmed_on=DAY),),
    )
    actor = Actor(login_id="dev", name="개발", role=Role.ADMIN, dev=True)
    desk.holder.apply_update(check, current.token, actor, UpdateLog(desk.settings.data_dir))
    skipped = desk.seeder.refresh(NOW + timedelta(hours=1), startup=False)
    c.check(
        "지금 지도가 기본 지도가 아니면(가져온 지도 · 상태만 바꾼 지도) 안 채움",
        skipped is None and _counts(desk.settings.data_dir) == before and _archives(desk.settings.data_dir) == [],
    )

    real = _Desk(_settings(root, "real", LIVE_ON))
    real.seeder = DemoSeeder(
        AppContext.load(replace(real.settings, data_mode=DataMode.REAL)), real.holder, real.accounts, version=VERSION
    )
    c.check("실데이터 모드: 안 채움", real.seeder.start(NOW) is None and _counts(real.settings.data_dir) == (0, 0, 0))

    fixed_settings = _settings(root, "fixed", {"RIPPLE_DEMO_SEED": "on"})
    _fixed(c, fixed_settings)


def _fixed(c: Checker, settings: Settings) -> None:
    folder = settings.data_dir.parent / "fixed-map"
    write_outputs(generate(load_config()), folder)
    settings = replace(settings, snapshot_path=folder / "snapshot.json")
    context = AppContext.load(settings)
    holder = Workspaces(context, MemoryGraphStore(), None, SnapshotStore(settings.data_dir), today=lambda: DAY)
    holder.start()
    accounts = AccountStore(settings.data_dir)
    accounts.load()
    RecordStore(settings.data_dir).start()
    first = seed_demo(context, holder, accounts, now=NOW, version=VERSION)
    before = _counts(settings.data_dir)
    later = seed_demo(context, holder, accounts, now=NOW + timedelta(days=1), version="검사 판 2")
    c.check(
        "날짜에 멈춘 세계(fixed): 빈 폴더에 한 번 · 다음 날 · 다른 판이어도 다시 채우지 않음 · 표시 없음",
        first is not None
        and later is None
        and _counts(settings.data_dir) == before
        and _archives(settings.data_dir) == []
        and not (settings.data_dir / MARK_FILE).exists(),
    )


# ---------- 보관 14개 ----------


def _prune(c: Checker) -> None:
    with tempfile.TemporaryDirectory() as folder:
        data_dir = Path(folder)
        archive = data_dir / "archive"
        for n in range(AUTO_KEEP + 3):
            made = archive / f"records-auto-202610{n + 1:02d}-090000"
            made.mkdir(parents=True)
            (made / DONE).write_text(json.dumps({"auto": True}), encoding="utf-8")
        human = archive / "records-auto-manual"  # 사람이 RIPPLE_RESET_RECORDS=auto-manual로 만든 보관
        human.mkdir()
        (human / DONE).write_text(json.dumps({"label": "auto-manual", "scope": "records"}), encoding="utf-8")
        labeled = archive / "records-20261012"
        labeled.mkdir()
        removed = prune_auto(data_dir)
        left = sorted(p.name for p in archive.iterdir())
    c.check(
        "자동 보관은 최근 14개만(오래된 3개 지움) · 사람이 표지로 만든 보관은 이름이 비슷해도 그대로",
        removed == [f"records-auto-202610{n:02d}-090000" for n in (1, 2, 3)]
        and len([n for n in left if n.startswith("records-auto-2026")]) == AUTO_KEEP
        and "records-auto-manual" in left
        and "records-20261012" in left,
        (removed, left),
    )


# ---------- 바꿔 끼우기 실패 되돌리기 ----------


class _Boom(OSError):
    """가짜 replace_file이 내는 실패."""


def _failing_at(*failures: int) -> tuple[Callable[..., None], list[int]]:
    """n번째(1부터) 부름에서 실패하는 replace_file. 나머지는 진짜로 옮긴다. 부른 횟수 목록을 함께 돌려준다."""
    calls: list[int] = []

    def fake(source: Path, target: Path) -> None:
        calls.append(len(calls) + 1)
        if len(calls) in failures:
            raise _Boom(f"{len(calls)}번째 옮기기 실패")
        replace_file(source, target)

    return fake, calls


def _swap_case(data_dir: Path, fake: Callable[..., None], *, keep: bool) -> BaseException | None:
    """지금 기록(old)과 준비 폴더 기록(new) 파일을 두고 가짜 replace_file로 바꿔 끼운다. 낸 예외를 돌려준다."""
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in TARGETS[:2]:
        (data_dir / name).write_text(f"old {name}", encoding="utf-8")
    staged = staging_folder(data_dir)
    for name in TARGETS[:2]:
        (staged / name).write_text(f"new {name}", encoding="utf-8")
    try:
        with patch.object(reset, "replace_file", fake):
            swap_records(data_dir, staged, keep=keep, note={}, now=NOW)
    except BaseException as error:  # 낸 예외를 그대로 살펴본다
        return error
    return None


def _restored(data_dir: Path) -> bool:
    """데이터 폴더 = 바꾸기 전 그대로(지금 기록) · 준비 폴더 없음 · 빈 자동 보관 폴더 없음 · 문이 풀림."""
    old = all((data_dir / n).read_text(encoding="utf-8") == f"old {n}" for n in TARGETS[:2])
    return old and not (data_dir / STAGING).exists() and not _archives(data_dir) and _free(data_dir)


def _swap_undo(c: Checker) -> None:
    c.section("시연 기록 바꿔 끼우기: 중간 실패 되돌리기")
    total = 2 * 2  # 지금 파일 2개 → 보관, 준비 파일 2개 → 데이터 폴더
    wrong: list[str] = []
    with tempfile.TemporaryDirectory() as folder:
        for keep in (True, False):
            for n in range(1, total + 1):
                data_dir = Path(folder) / f"swap-{keep}-{n}"
                fake, _calls = _failing_at(n)
                error = _swap_case(data_dir, fake, keep=keep)
                if not isinstance(error, _Boom) or error.__cause__ is not None or not _restored(data_dir):
                    wrong.append(f"keep={keep} n={n}: {error!r}")
        c.check(
            "n번째 파일(1~4, 두 번째 포함) 실패: 원래 예외 · 데이터 폴더 원복 · 준비 폴더 제거 · 문 풀림(보관·버림)",
            not wrong,
            wrong[:3],
        )
        # 3번째(준비 파일 첫째)에서 실패 → 되돌리기 첫 부름(4번째 = 둘째 지금 파일 되돌리기)도 실패, 5번째는 성공
        data_dir = Path(folder) / "swap-undo-fails"
        fake, calls = _failing_at(3, 4)
        logs: list[logging.LogRecord] = []
        handler = _Collect(logs)
        logger = logging.getLogger(reset.__name__)
        logger.addHandler(handler)
        try:
            error = _swap_case(data_dir, fake, keep=True)
        finally:
            logger.removeHandler(handler)
        first = TARGETS[0]
        c.check(
            "되돌리기마저 실패: 남은 파일 계속 되돌림 · log.exception 1건 · 원래 예외(cause = 되돌리기 실패) · 문 풀림",
            isinstance(error, _Boom)
            and "3번째" in str(error)
            and isinstance(error.__cause__, _Boom)
            and "4번째" in str(error.__cause__)
            and len(calls) == 5
            and (data_dir / first).read_text(encoding="utf-8") == f"old {first}"
            and not (data_dir / STAGING).exists()
            and len([r for r in logs if r.levelno == logging.ERROR and r.exc_info]) == 1
            and _free(data_dir),
            (repr(error), repr(getattr(error, "__cause__", None)), calls, [r.getMessage() for r in logs]),
        )


class _Collect(logging.Handler):
    def __init__(self, into: list[logging.LogRecord]) -> None:
        super().__init__(logging.DEBUG)
        self.into = into

    def emit(self, record: logging.LogRecord) -> None:
        self.into.append(record)


def _free(data_dir: Path) -> bool:
    try:
        with gate_of(data_dir).exclusive(wait_s=0.5):
            return True
    except TimeoutError:
        return False
