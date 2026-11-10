"""시연 기록 시드를 언제 채우나(설정 RIPPLE_DEMO_SEED, docs/operations.md(서비스) 7절): 실시간 시연 세계에서는 KST
날마다 · 시드 판이 바뀐 배포 뒤 자동으로 새로 채운다.

- 합성 데이터 모드 · 지금 지도가 기본 합성 지도일 때만. 실데이터 모드 · 실데이터 지도 · 가져온 지도면 안 함(경고).
- 실시간 시연 세계(RIPPLE_SYNTHETIC_CLOCK=live): 데이터 폴더의 표시(demo_seed.json — 채운 날(KST)과 시드 판)가 오늘 ·
  지금 판과 다르거나 기록이 비어 있으면, 서버가 시작할 때와 날이 바뀌어 작업 공간이 새 날로 넘어갈 때
  (Workspaces.roll_day의 새 날 훅 — 전환 잠금 안이라 다른 요청은 다 채운 뒤의 새 세대를 본다) 새로 채운다.
  같은 날 · 같은 판이면 그대로.
- 날짜에 멈춘 세계(fixed): 지금처럼 기록이 비어 있을 때 시작하면서 한 번만.
- 새로 채우기 = 준비 폴더(.seed-staging)의 새 저장소에 각본대로 채운 뒤(demo_seed.fill — 지금 기록은 그대로) 데이터
  폴더 문을 혼자 잡고 바꿔 끼운다(store.reset.swap_records). 옛 기록·실적·수정 기록은 자동 보관 폴더
  (archive/records-auto-<KST 시각>)로 옮기고 최근 14개만 남긴다. 채우거나 바꿔 끼우다 실패하면 지금 기록 그대로
  두고 이유를 로그에 남긴다(서버는 계속 — 다음 날 · 다음 시작에 다시).
- 시드 판 = 앱·엔진·계약 판 + 백엔드 코드(ripple/**.py)·규칙표·파라미터·생성기 설정 내용의 해시: 문구·계산이 바뀐
  배포를 알아본다(같은 날이어도 다시 채움). 계정(빠른 로그인 고정 계정 · 가상 담당자)은 건드리지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import cache
from pathlib import Path

import ripple
from ripple import __version__
from ripple.config.files import write_atomic
from ripple.contracts.base import CONTRACT_VERSION
from ripple.contracts.domain import DataMode
from ripple.engine import ENGINE_VERSION
from ripple.generator.io import DEFAULT_CONFIG_PATH
from ripple.store.accounts import AccountStore
from ripple.store.corrections import CorrectionLog
from ripple.store.outcomes import OutcomeLog
from ripple.store.records import RecordStore
from ripple.store.reset import staging_folder, swap_records

from .demo_plan import APPROVERS
from .demo_seed import KST, SeedResult, Worlds, fill, sync_approvers
from .deps import AppContext
from .workspace import Workspaces

log = logging.getLogger("ripple.seed")
MARK_FILE = "demo_seed.json"


@dataclass(frozen=True, slots=True)
class SeedMark:
    """데이터 폴더의 지금 시연 기록을 채운 날(KST)과 시드 판."""

    day: date
    version: str


def read_mark(data_dir: Path) -> SeedMark | None:
    try:
        data = json.loads((data_dir / MARK_FILE).read_text(encoding="utf-8"))
        return SeedMark(day=date.fromisoformat(data["day"]), version=str(data["version"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None  # 없음 · 깨짐 = 모르는 기록(새로 채운다)


def write_mark(data_dir: Path, mark: SeedMark, result: SeedResult, at: datetime) -> None:
    data = {"day": mark.day.isoformat(), "version": mark.version, "at": at.isoformat(), "ecns": result.ecns}
    write_atomic(data_dir / MARK_FILE, json.dumps(data, ensure_ascii=False))


@cache
def _digest(paths: tuple[Path, ...]) -> str:
    sha = hashlib.sha256()
    for path in paths:
        sha.update(path.as_posix().encode())
        try:
            sha.update(path.read_bytes().replace(b"\r\n", b"\n"))
        except OSError:
            sha.update(b"-")
    return sha.hexdigest()[:16]


def seed_version(context: AppContext) -> str:
    """시드 판: 기록 본문의 계산·문구를 정하는 것(앱·엔진·계약 판 + 백엔드 코드·규칙표·파라미터·생성기 설정)."""
    settings = context.settings
    package = Path(ripple.__file__).parent
    code = sorted(package.rglob("*.py"))
    configs = (
        settings.rules_path,
        settings.params_path,
        settings.decision_path,
        settings.lexicon_path,
        settings.strength_path,
        settings.contacts_path,
        DEFAULT_CONFIG_PATH,
        settings.generator_config,  # 시연 합성 지도(RIPPLE_SYNTHETIC_MAP=demo)면 그 설정도
    )
    digest = _digest(tuple(path.resolve() for path in (*code, *configs)))
    return f"{__version__}/엔진 {ENGINE_VERSION}/계약 {CONTRACT_VERSION}/{digest}"


def _empty(data_dir: Path) -> bool:
    """기록·실적·수정 기록이 모두 비어 있나(비어 있으면 바꿔 끼울 때 보관하지 않고 버린다)."""
    records = RecordStore(data_dir)
    listed = records.path.exists() and records.listing(include_real=True).ecns
    return not (listed or OutcomeLog(data_dir).latest() or CorrectionLog(data_dir).events())


class DemoSeeder:
    """시연 기록 시드 입구: 시작할 때(start)와 실시간 세계의 새 날(new_day — Workspaces 새 날 훅)."""

    def __init__(
        self,
        context: AppContext,
        workspaces: Workspaces,
        accounts: AccountStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        version: str | None = None,
    ) -> None:
        self._context = context
        self._workspaces = workspaces
        self._accounts = accounts
        self._clock = clock
        self._version = version

    @property
    def version(self) -> str:
        if self._version is None:
            self._version = seed_version(self._context)
        return self._version

    def start(self, now: datetime | None = None) -> SeedResult | None:
        """시작할 때: 결재선 가상 계정을 맞추고(합성 모드면 늘), 채울 때면 채운다."""
        settings = self._context.settings
        if not settings.demo_seed:
            return None
        at = now or self._clock()
        if settings.data_mode is not DataMode.REAL and sync_approvers(self._accounts, at):
            how = (
                "빠른 로그인 '파트장으로'·'본부장으로' 단추로 접속"
                if settings.quick_login and settings.auth_required
                else "빠른 로그인 꺼짐 — 접속 불가(팀장 전결)"
            )
            log.warning("시연 기록 시드: 결재선 가상 계정(%s) — %s", "·".join(p.login_id for p in APPROVERS), how)
        return self.refresh(at, startup=True)

    def new_day(self) -> None:
        """실시간 세계가 새 날로 넘어간 뒤(전환 잠금 안): 그날 기준으로 새로 채운다. 무슨 일이 있어도 예외를 내지 않는다
        (날 넘기기는 그대로)."""
        if not self._context.settings.demo_seed:
            return
        try:
            self.refresh(self._clock(), startup=False)
        except Exception:
            log.exception("시연 기록 새 날 채우기 실패 — 지금 기록 그대로 · 다음 날·다음 시작에 다시 시도")

    def refresh(self, now: datetime, *, startup: bool) -> SeedResult | None:
        """채울 때면(아래) 준비 폴더에 채워 바꿔 끼운다. 안 채웠거나 실패했으면 None(이유는 로그)."""
        context = self._context
        reason = self._skip()
        if reason is not None:
            log.warning("RIPPLE_DEMO_SEED=on: %s", reason)
            return None
        today = now.astimezone(KST).date()
        worlds = Worlds(context)
        current = self._workspaces.current
        if current is None or current.snapshot.snapshot_id != worlds.of(today).snapshot.snapshot_id:
            log.warning("RIPPLE_DEMO_SEED=on: 지금 지도가 기본 합성 지도 아님 — 시연 기록 안 채움")
            return None
        data_dir = context.settings.data_dir
        empty = _empty(data_dir)
        why = self._why(data_dir, today, empty=empty)
        if why is None:
            return None
        folder = staging_folder(data_dir)
        try:
            result = fill(context, folder, self._accounts, worlds, now)
            # 시작할 때는 요청 전이라 빈 기록은 버리고, 새 날에는 그사이 들어온 줄이 있을 수 있어 늘 보관
            note: dict[str, object] = {"day": today.isoformat(), "version": self.version, "why": why}
            archive = swap_records(data_dir, folder, keep=not (startup and empty), note=note, now=now)
        except Exception:  # 시연 데이터 때문에 서버가 멈추면 안 된다 — 지금 기록 그대로
            shutil.rmtree(folder, ignore_errors=True)
            log.exception("시연 기록 채우기 중단(%s) — 지금 기록 그대로 · 다음 날·다음 시작에 다시 시도", why)
            return None
        self._mark(data_dir, today, result, now)
        kept = f"옛 기록 보관 {archive.relative_to(data_dir).as_posix()}" if archive else "옛 기록 없음"
        log.warning(
            "시연 기록 채움(RIPPLE_DEMO_SEED=on · %s · %s 기준): 설계변경 %d건 · 감사 줄 %d줄 · 실적 %d건 · "
            "가상 담당자 %d명 · %s",
            why,
            today.isoformat(),
            result.ecns,
            result.audit,
            result.outcomes,
            result.people,
            kept,
        )
        return result

    def _skip(self) -> str | None:
        if self._context.settings.data_mode is DataMode.REAL:
            return "실데이터 모드 — 시연 기록 안 채움(RIPPLE_DEMO_SEED는 합성 데이터에서만)"
        current = self._workspaces.current
        if current is None or current.data_mode is DataMode.REAL:
            return "지금 지도가 실데이터 — 시연 기록 안 채움"
        return None

    def _why(self, data_dir: Path, today: date, *, empty: bool) -> str | None:
        """새로 채우는 이유. 채우지 않으면 None(그 이유는 로그)."""
        if empty:
            return "기록 없음"
        if not self._context.settings.live_world:
            log.warning(
                "RIPPLE_DEMO_SEED=on: 기록이 이미 있어 안 채움(날짜에 멈춘 세계 — 다시 채우려면 RIPPLE_RESET_RECORDS에 "
                "새 표지)"
            )
            return None
        mark = read_mark(data_dir)
        if mark is None:
            return "채운 날 표시 없음"
        if mark.day != today:
            return f"날 바뀜 {mark.day.isoformat()} → {today.isoformat()}"
        if mark.version != self.version:
            return "시드 판 바뀜"
        log.info("시연 기록 그대로(같은 날 %s · 같은 시드 판)", today.isoformat())
        return None

    def _mark(self, data_dir: Path, today: date, result: SeedResult, now: datetime) -> None:
        if not self._context.settings.live_world:
            return
        try:
            write_mark(data_dir, SeedMark(today, self.version), result, now)
        except OSError as error:  # 다음 시작에 한 번 더 채울 뿐
            log.warning("시연 기록 표시(%s) 저장 실패: %s", MARK_FILE, error)


def seed_demo(
    context: AppContext,
    workspaces: Workspaces,
    accounts: AccountStore,
    *,
    now: datetime | None = None,
    version: str | None = None,
) -> SeedResult | None:
    """시작할 때 한 번(DemoSeeder.start). 채우지 않았거나 멈췄으면 None(이유는 로그)."""
    return DemoSeeder(context, workspaces, accounts, version=version).start(now)
