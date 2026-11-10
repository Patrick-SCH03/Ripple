"""합성 시연 기록 시드(설정 RIPPLE_DEMO_SEED, docs/operations.md(서비스) 7절): 팀장 화면(결재함·현황·성과)을 채우는
지난 기록을 실제 기록 흐름으로 만든다.

- 여기는 채우는 법(fill: 준비 폴더의 새 저장소에 각본대로)과 결재선 가상 계정 맞추기(sync_approvers)다. 언제 채우고
  지금 기록과 어떻게 바꿔 끼우는지(시작할 때 · 실시간 세계에서 KST 날이 바뀔 때 · 시드 판이 바뀐 배포 뒤)는
  demo_daily.py.
- 각본(demo_plan.py)의 행동을 업무 경로와 같은 함수로 한다: 그날의 시연 세계로 다시 계산해 대조한 기록 본문
  (records.record_body) → 저장소 한 트랜잭션(commit_record · commit_action — 결재 규칙은 records.flow, 감사 사슬은
  store.records 그대로) → 실적(outcome_entry). 다른 것은 시각뿐이다(기록 저장소의 시계 주입 · 실적 줄의 입력 시각).
- 그날의 세계: 실시간 시연 세계(RIPPLE_SYNTHETIC_CLOCK=live)면 그 날짜를 기준일로 만든 생성기 세계(지도 ID가 날마다
  다르다 — 작업 공간이 그날 쓰던 지도와 같다), 날짜에 멈춘 세계면 기본 지도 하나.
- 실적 = 그 개정을 계산한 세계의 숨긴 모델(generator.actuals.HiddenModel.outcome, 생성기 시드 고정)의 실제 비용과 구역
  출구 최대 지연 — 합성 과거 사례와 같은 근거다.
- 오늘 행동은 오늘 업무 시작(08:30, 그 전이면 자정)부터 지금 조금 전 사이에 각본 순서대로 놓는다
  (앞날 시각이 생기지 않게).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path

from ripple.auth import Principal
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.change import ChangeRequest
from ripple.contracts.dataset import EcnSplit, GeneratedEcn
from ripple.contracts.domain import DataMode, GraphSnapshot
from ripple.contracts.identity import analysis_id
from ripple.contracts.outcomes import OutcomeInput
from ripple.contracts.records import ActionRequest, EcnAction, EcnStatus, RecordBody, RecordRequest
from ripple.contracts.workspace import SnapshotInfo
from ripple.engine.analyze import analysis_versions
from ripple.engine.index import GraphIndex
from ripple.generator.actuals import HiddenModel
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.store.accounts import AccountStore, RetiredIdError, StoredAccount
from ripple.store.outcomes import OutcomeLog
from ripple.store.records import RecordStore

from .demo_plan import (
    APPROVERS,
    CAUSE_OF_INTENT,
    PLAN,
    SEED_PEOPLE,
    WORK_MINUTES,
    WORK_START_MINUTES,
    Case,
    Person,
    Step,
)
from .deps import AppContext
from .generation import effective_mode
from .records import actor_of, commit_action, commit_record, outcome_entry, record_body
from .snapshot_info import default_info, default_name

log = logging.getLogger("ripple.seed")
KST = timezone(timedelta(hours=9))  # 서머타임 없음
UNUSABLE_PASSWORD = "!demo-seed"  # 해시 형식이 아니라 어떤 비밀번호로도 맞지 않는다(auth.passwords.verify_password)
EARLY = timedelta(hours=1)  # 업무 시작 뒤 이만큼도 안 지났으면 오늘 행동을 자정부터 놓는다
MARGIN = timedelta(minutes=5)  # 오늘 마지막 행동과 지금 사이


class SeedError(RuntimeError):
    """각본대로 할 수 없음(세계에 없는 설계변경 · 새 개정이 생기지 않음 · 음수 실적)."""


@dataclass(frozen=True, slots=True)
class SeedResult:
    ecns: int
    audit: int
    outcomes: int
    people: int


@dataclass(frozen=True, slots=True)
class World:
    """그날의 시연 세계: 지도·색인·지도 정보·유효 데이터 모드(records.Desk) + 그 세계의 설계변경과 숨긴 모델."""

    snapshot: GraphSnapshot
    index: GraphIndex
    info: SnapshotInfo
    data_mode: DataMode
    ecns: Mapping[str, GeneratedEcn]
    hidden: HiddenModel


class Worlds:
    """날짜 → 시연 세계(만든 것은 기억). 날짜에 멈춘 세계면 늘 기본 세계 하나."""

    def __init__(self, context: AppContext) -> None:
        self._context = context
        self._live = context.settings.live_world
        self._made: dict[date | None, World] = {}

    def of(self, day: date) -> World:
        key = day if self._live else None
        if key not in self._made:
            config = load_config(self._context.settings.generator_config)
            generated = generate(config.model_copy(update={"scenario_date": day}) if self._live else config)
            snapshot = generated.snapshot
            self._made[key] = World(
                snapshot=snapshot,
                index=GraphIndex(snapshot),
                info=default_info(snapshot, default_name(self._context.settings.generator_config)),
                data_mode=effective_mode(self._context.settings.data_mode, snapshot),
                ecns={e.change.ecn_id: e for e in generated.ecns if e.split is EcnSplit.DEV},
                hidden=HiddenModel(generated, self._context.settings.params_path),
            )
        return self._made[key]

    def by_snapshot(self, snapshot_id: str) -> World:
        found = next((w for w in self._made.values() if w.snapshot.snapshot_id == snapshot_id), None)
        if found is None:
            raise SeedError(f"기록한 지도의 세계 없음: {snapshot_id}")
        return found


def moment(now: datetime, day: int, minute: int) -> datetime:
    """각본의 (며칠 전, 업무 시작 뒤 분) → 시각(UTC). 오늘은 업무 시작부터 지금 조금 전까지를 하루로 줄여 놓는다."""
    today = now.astimezone(KST).date()
    start = datetime.combine(today + timedelta(days=day), time(), KST) + timedelta(minutes=WORK_START_MINUTES)
    if day < 0:
        return (start + timedelta(minutes=minute)).astimezone(UTC)
    if now - start < EARLY:
        start = datetime.combine(today, time(), KST)
    end = max(start, now - MARGIN)
    return (start + (end - start) * (minute / WORK_MINUTES)).astimezone(UTC)


@dataclass
class _Clock:
    """기록 저장소가 쓸 때마다 부르는 시계: 지금 하는 각본 행동의 시각."""

    at: datetime

    def __call__(self) -> datetime:
        return self.at


def _principal(person: Person) -> Principal:
    return Principal(login_id=person.login_id, name=person.name, role=person.role)


def _change(ecn: GeneratedEcn, step: Step) -> ChangeRequest:
    """담당자가 화면에서 적는 요청 값(변경 원인 · 설계 승인 상태)을 얹은 그 세계의 설계변경."""
    update: dict[str, object] = {}
    if ecn.change.cause is None and ecn.change.intent is not None:
        update["cause"] = CAUSE_OF_INTENT.get(ecn.change.intent)
    if step.design is not None:
        update["design_status"] = step.design
    return ChangeRequest.model_validate({**ecn.change.model_dump(), **update})


@dataclass
class _Run:
    """각본을 차례로 한다. 상태 판·기록 본문은 저장소가 돌려준 것을 이어 쓴다(화면이 다시 읽은 것과 같은 값)."""

    context: AppContext
    store: RecordStore
    outcomes: OutcomeLog
    worlds: Worlds
    clock: _Clock
    status: dict[str, EcnStatus] = field(default_factory=dict)
    bodies: dict[tuple[str, int], RecordBody] = field(default_factory=dict)
    entered: int = 0

    def step(self, case: Case, step: Step, at: datetime) -> None:
        self.clock.at = at
        world = self.worlds.of(at.astimezone(KST).date())
        if step.action is EcnAction.RECORD:
            self._record(case, step, world)
        elif step.action is None:
            self._outcome(case.ecn_id, step, at)
        else:
            self._act(case.ecn_id, step, step.action, world)

    def _record(self, case: Case, step: Step, world: World) -> None:
        ecn = world.ecns.get(case.ecn_id)
        if ecn is None:
            raise SeedError(f"그날 세계에 없는 설계변경: {case.ecn_id}")
        request = AnalysisRequest(change=_change(ecn, step), as_of=ecn.as_of, include_alternatives=case.alternatives)
        context = self.context
        snapshot_id = world.snapshot.snapshot_id
        versions = analysis_versions(snapshot_id, request, context.rulebook, context.params, context.strength)
        current = self.status.get(case.ecn_id)
        body = RecordRequest(
            request=request,
            analysis_id=analysis_id(versions, request),  # 화면이 본 분석(같은 요청 · 같은 판)
            request_id=str(uuid.uuid4()),
            expected_version=current.version if current else 0,
        )
        record = record_body(context, world, body)
        saved = commit_record(self.store, record, _principal(step.who), body, login_mode=True)
        if not saved.created:
            raise SeedError(f"새 개정 미생성: {case.ecn_id}")
        self.status[case.ecn_id] = saved.status
        self.bodies[(case.ecn_id, saved.revision.revision)] = record

    def _act(self, ecn_id: str, step: Step, action: EcnAction, world: World) -> None:
        current = self.status[ecn_id]
        checklist = self.bodies[(ecn_id, current.revision)].checklist
        checks = action in (EcnAction.APPROVE, EcnAction.SETTLE)  # 승인·무비용 담당자 처리는 확인 목록을 체크해 보낸다
        acknowledged = tuple(item.key for item in checklist) if checks else ()
        reason = step.reason or ("확인 필요 항목 모두 확인" if acknowledged else None)
        body = ActionRequest(
            action=action,
            expected_version=current.version,
            revision=current.revision,
            record_id=current.record_id,
            review_seq=current.review.seq if current.review else None,
            reason=reason,
            acknowledged=acknowledged,
        )
        self.status[ecn_id] = commit_action(
            self.context,
            self.store,
            _principal(step.who),
            ecn_id,
            body,
            active_snapshot_id=world.snapshot.snapshot_id,  # 그날 작업 공간이 쓰던 지도
            login_mode=True,
        )

    def _outcome(self, ecn_id: str, step: Step, at: datetime) -> None:
        status = self.status[ecn_id]
        if status.approved_revision is None:
            raise SeedError(f"승인 개정 없음 — 실적 입력 불가: {ecn_id}")
        approved = self.bodies[(ecn_id, status.approved_revision)]
        request = approved.result.request
        truth = self.worlds.by_snapshot(approved.snapshot_id).hidden.outcome(
            request.change,
            request.as_of,
            request.effective_confirm_on,
            {hold.po_id: hold.hold_days for hold in request.holds},
        )
        if truth.total_krw < 0:
            raise SeedError(f"숨긴 모델 실제 비용이 음수 — 실적 입력 불가: {ecn_id}")
        data = OutcomeInput(
            cost_krw=truth.total_krw,
            exit_delay_days=truth.max_exit_delay_days if step.delay else None,
            note=step.note,
        )
        actor = actor_of(_principal(step.who), login_mode=True)
        self.outcomes.append(outcome_entry(self.store, ecn_id, data, actor, at))
        self.entered += 1


def _add_people(accounts: AccountStore, created: datetime) -> int:
    """가상 담당자를 계정 파일에(이미 있으면 그대로): 비밀번호를 쓸 수 없는 계정 — 구성원 관리에서 초기화할 수 있다."""
    added: list[str] = []

    def add(stored: dict[str, StoredAccount]) -> None:
        for person in SEED_PEOPLE:
            if person.login_id not in stored:
                stored[person.login_id] = StoredAccount(
                    login_id=person.login_id,
                    name=person.name,
                    role=person.role,
                    password_hash=UNUSABLE_PASSWORD,
                    created_at=created,
                )
                added.append(person.login_id)

    try:
        accounts.change(add)
    except RuntimeError as error:  # 계정 파일을 읽지 못한 개발 모드
        log.warning("시연 기록 시드: 가상 담당자 계정 추가 실패(%s)", error)
        return 0
    return len(added)


def sync_approvers(accounts: AccountStore, now: datetime) -> bool:
    """결재선 가상 계정(이파트장·최본부장)을 계정 파일에 맞춘다(시작할 때마다 — 시드가 이미 채워졌어도).

    두 계정은 빠른 로그인 고정 계정(ripple/auth/quick.py — '파트장으로'·'본부장으로' 단추)과 같은 아이디라 아이디·
    비밀번호로는 들어갈 수 없다. 이름·역할·사용 중은 각본 값으로 되돌리고, 비밀번호 해시는 어떤 비밀번호로도 맞지 않는
    값으로 둔다 — 예전 시드가 RIPPLE_DEMO_PASSWORD로 만든 해시가 남아 있으면 지우고 세션 판을 올린다(그 비밀번호로 만든
    세션 무효, 그 뒤 빠른 로그인 세션은 새 판). 계정 파일을 쓰면 True, 못 쓰면 False."""

    def put(stored: dict[str, StoredAccount]) -> None:
        for person in APPROVERS:
            current = stored.get(person.login_id)
            if current is None:
                current = StoredAccount(
                    login_id=person.login_id,
                    name=person.name,
                    role=person.role,
                    password_hash=UNUSABLE_PASSWORD,
                    created_at=now,
                )
            bump = current.password_hash != UNUSABLE_PASSWORD or current.role is not person.role or current.disabled
            stored[person.login_id] = current.model_copy(
                update={
                    "name": person.name,
                    "role": person.role,
                    "password_hash": UNUSABLE_PASSWORD,
                    "disabled": False,
                    "must_change_password": False,
                    "session_version": current.session_version + (1 if bump else 0),
                }
            )

    try:
        accounts.change(put)
    except (RuntimeError, RetiredIdError) as error:  # 계정 파일을 읽지 못한 개발 모드 · 지운 아이디
        log.warning("시연 기록 시드: 결재선 가상 계정 추가 실패(%s)", error)
        return False
    return True


def fill(context: AppContext, folder: Path, accounts: AccountStore, worlds: Worlds, now: datetime) -> SeedResult:
    """각본대로 folder(준비 폴더)의 새 기록·실적 저장소에 채운다. 가상 담당자는 계정 파일에(이미 있으면 그대로).
    각본대로 할 수 없으면 예외(SeedError 등) — 부른 쪽이 준비 폴더를 버린다."""
    clock = _Clock(now)
    store = RecordStore(folder, clock=clock)
    store.start()
    outcomes = OutcomeLog(folder)
    run = _Run(context, store, outcomes, worlds, clock)
    events = sorted(
        ((moment(now, s.day, s.minute), i, j) for i, case in enumerate(PLAN) for j, s in enumerate(case.steps)),
    )
    first = min(e[0] for e in events)
    people = _add_people(accounts, first - timedelta(days=3))
    for at, i, j in events:
        run.step(PLAN[i], PLAN[i].steps[j], at)
    return SeedResult(ecns=len(run.status), audit=store.verify().entries, outcomes=run.entered, people=people)
