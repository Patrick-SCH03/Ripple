"""기록·승인 흐름 서비스(docs/records.md): 다시 계산 → 확인 목록 → 전환 잠금 안에서 저장소 커밋.

- 기록 저장: 화면이 본 결과 숫자 대신 요청을 받아, 요청이 시작될 때 잡은 작업 공간 세대로 다시 분석한다.
  분석 ID가 화면이 본 것과 다르면 409(analysis_changed). 저장소 커밋은 지도 전환 잠금 안에서 그 세대가
  아직 지금 세대인지 확인한 뒤에 한다.
- 검토 요청·결정·실행·종료도 같은 잠금 안에서 커밋한다(검토 요청·승인은 그 개정의 지도 = 커밋 시점의 활성 지도여야 함).
- 계산 판 대조: 개정 본문의 판(지도를 뺀 버전 묶음)이 그 요청을 지금 분석할 때의 판과 다르면 다시 계산한 분석 ID가
  기록과 달라진다 — 검토 요청·승인은 받지 않고 반려·보류는 받는다. 저장된 모델은 바꾸지 않고
  읽을 때·행동할 때 본문에서 계산한다(옛 저장소도 그대로 읽힘).
- 확인 목록 = 분석이 계산하지 못한 항목(unresolved) + 가져온 지도 품질 리포트의 경고. 기록할 때 고정한다.
  같은 종류(같은 이유의 미계산 · 같은 시트의 같은 경고)가 GROUP_AT개를 넘으면 한 항목으로 묶는다 — 사람이 하나씩
  체크할 수 있는 크기로, 승인 요청의 체크 한도(ActionRequest.acknowledged) 안에 들게.
- 합성 시연 기록 시드(demo_seed.py)도 같은 함수(record_body · commit_record · commit_action · outcome_entry)로 쓴다.
  다른 것은 작업 공간 전환 잠금이 없다는 것뿐이다(서버가 요청을 받기 전, 시작할 때 돈다).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from pydantic import ValidationError

from ripple.auth import Principal
from ripple.contracts.auth import Permission, Role
from ripple.contracts.domain import DataMode, GraphSnapshot
from ripple.contracts.ingest import ImportIssue, IssueSeverity
from ripple.contracts.outcomes import OutcomeEntry, OutcomeInput
from ripple.contracts.records import (
    ActionRequest,
    Actor,
    ApprovalPlan,
    ApprovalStep,
    ChecklistItem,
    EcnState,
    EcnStatus,
    RecordBody,
    RecordRequest,
    RecordSaved,
    ReviewInfo,
)
from ripple.contracts.result import AnalysisResult, Unresolved
from ripple.contracts.workspace import SnapshotInfo
from ripple.engine.analyze import analysis_versions, analyze
from ripple.engine.index import GraphIndex
from ripple.records.approval import approval_plan, steps_of
from ripple.records.flow import Ask, FlowError, Who
from ripple.records.metrics import business_today, kst_date
from ripple.store.records import PlanOf, RecordStore

from .deps import AppContext
from .ncr import ncr_counts
from .workspace import Workspace, Workspaces

EXECUTED = (EcnState.IN_PROGRESS, EcnState.CLOSED)  # 실적을 넣을 수 있는 상태
TEXT_MAX = 500
GROUP_AT = 4  # 같은 종류가 이보다 많으면 한 항목으로 묶는다
SHOWN = 5  # 묶은 항목에 이름을 적는 개수(나머지는 '외 n건')
UNRESOLVED_LABEL = {
    "delivery": "인도 조건",
    "po_state": "발주 상태",
    "block_stage": "블록 단계",
    "connection": "연결 정보",
    "strength_inputs": "강도 검토 입력",
}


def actor_of(principal: Principal, *, login_mode: bool) -> Actor:
    return Actor(login_id=principal.login_id, name=principal.name, role=principal.role, dev=not login_mode)


def who_of(principal: Principal, *, login_mode: bool) -> Who:
    """결재 규칙이 보는 사람: 승인 권한이 있으면 역할 → 결재 단계(팀장은 파트장·본부장 전결), 개발 모드는 모든 단계."""
    own, proxy = steps_of(principal.role, dev=not login_mode)
    approver = principal.can(Permission.APPROVE)
    return Who(
        login_id=principal.login_id,
        can_record=principal.can(Permission.RECORD),
        steps=own if approver else frozenset(),
        proxy=proxy if approver else frozenset(),
        admin=principal.role is Role.ADMIN,
        dev=not login_mode,
    )


def inbox_steps(principal: Principal, *, login_mode: bool) -> frozenset[ApprovalStep] | None:
    """결재함에 싣는 단계: 보는 사람의 자기 단계(팀장 = 팀장 단계). 개발 모드는 모두(None)."""
    if not login_mode:
        return None
    own, _proxy = steps_of(principal.role)
    return own


def proxy_steps(principal: Principal, *, login_mode: bool) -> frozenset[ApprovalStep]:
    """결재함 전결 묶음에 싣는 단계: 팀장 = 파트장·본부장. 파트장·본부장·개발 모드(결재함에 모든 단계)는 없음."""
    if not login_mode or not principal.can(Permission.APPROVE):
        return frozenset()
    _own, proxy = steps_of(principal.role)
    return proxy


def plan_of(context: AppContext, now: datetime) -> PlanOf:
    """상세·기록 조회의 결재 계획: 그 개정 본문과 진행 중 검토(저장소가 상태 행에서 고름 — 최신 개정이 아니면 없음)로,
    그 기록의 업무상 오늘(실데이터·실시간 시연 = KST 오늘)에서 센다. 같은 기록이면 상세와 기록 조회가 같은 값이다."""
    today = kst_date(now)
    live = context.settings.live_world

    def plan(body: RecordBody, review: ReviewInfo | None) -> ApprovalPlan:
        return approval_plan(body.result, business_today(body, today, live=live), review)

    return plan


def with_plan(context: AppContext, result: AnalysisResult, *, real: bool, now: datetime) -> AnalysisResult:
    """분석 응답에 결재 계획을 덧붙인다(1.33.0, 엔진 결과·분석 ID는 그대로). 업무상 오늘은 기록과 같은 기준 —
    실데이터·실시간 시연 세계 = KST 오늘, 날짜에 멈춘 합성 = 분석 기준일. 결재선은 검토 전(무비용이면 없음)."""
    live = context.settings.live_world
    today = kst_date(now) if live or real else result.request.as_of
    plan = approval_plan(result, today, None)
    return result.model_copy(update={"approval_plan": plan})


def _clip(text: str) -> str:
    return text if len(text) <= TEXT_MAX else text[: TEXT_MAX - 1] + "…"


def _unresolved_text(item: Unresolved) -> str:
    label = UNRESOLVED_LABEL.get(item.kind.value, item.kind.value)
    where = f" · {item.entity_id}" if item.entity_id else ""
    return _clip(f"{label}{where}: {item.reason}")


def _issue_text(issue: ImportIssue) -> str:
    place = " · ".join(
        part
        for part in (
            issue.sheet,
            f"{issue.row}행" if issue.row is not None else None,
            issue.file_column or issue.column,
        )
        if part
    )
    return _clip(f"{issue.message}" + (f" ({place})" if place else ""))


def _more(names: list[str]) -> str:
    shown = ", ".join(names[:SHOWN])
    return shown + (f" 외 {len(names) - SHOWN}건" if len(names) > SHOWN else "")


def _grouped[T](items: list[T], key: Callable[[T], tuple[str, ...]]) -> list[list[T]]:
    """처음 나온 순서대로 같은 키끼리 묶는다."""
    groups: dict[tuple[str, ...], list[T]] = {}
    for item in items:
        groups.setdefault(key(item), []).append(item)
    return list(groups.values())


def _analysis_items(unresolved: list[Unresolved]) -> list[ChecklistItem]:
    items: list[ChecklistItem] = []
    for group in _grouped(unresolved, lambda u: (u.kind.value, u.reason)):
        if len(group) <= GROUP_AT:
            for u in group:
                key = f"analysis:{len(items) + 1}:{u.kind.value}"
                items.append(ChecklistItem(key=key, source="analysis", text=_unresolved_text(u)))
            continue
        first = group[0]
        label = UNRESOLVED_LABEL.get(first.kind.value, first.kind.value)
        names = [u.entity_id for u in group if u.entity_id]
        where = f" — {_more(names)}" if names else ""
        text = _clip(f"{label} {len(group)}건: {first.reason}{where}")
        items.append(ChecklistItem(key=f"analysis:{len(items) + 1}:{first.kind.value}", source="analysis", text=text))
    return items


def _import_items(warnings: list[ImportIssue]) -> list[ChecklistItem]:
    items: list[ChecklistItem] = []
    for group in _grouped(warnings, lambda i: (i.code.value, i.sheet or "")):
        if len(group) <= GROUP_AT:
            for issue in group:
                key = f"import:{len(items) + 1}:{issue.code.value}"
                items.append(ChecklistItem(key=key, source="import", text=_issue_text(issue)))
            continue
        first = group[0]
        rows = [f"{i.row}행" for i in group if i.row is not None]
        place = f"{first.sheet} · " if first.sheet else ""
        more = f" ({place}{_more(rows)})" if rows else (f" ({first.sheet})" if first.sheet else "")
        text = _clip(f"같은 확인 {len(group)}건: {first.message}{more}")
        items.append(ChecklistItem(key=f"import:{len(items) + 1}:{first.code.value}", source="import", text=text))
    return items


def checklist_of(result: AnalysisResult, info: SnapshotInfo) -> tuple[ChecklistItem, ...]:
    """승인 전에 사람이 확인할 항목. 키는 기록 안에서 고유하고 같은 결과면 같다(승인 때 체크가 이 키를 보낸다)."""
    items = _analysis_items(list(result.unresolved))
    if info.origin == "excel_import" and info.summary is not None:
        warnings = [issue for issue in info.summary.issues if issue.severity is IssueSeverity.WARNING]
        items += _import_items(warnings)
    return tuple(items)


def same_version_of(context: AppContext) -> Callable[[RecordBody], bool]:
    """개정 본문의 계산 판 = 그 요청을 지금 분석할 때의 판(지도는 따로 대조하므로 본문의 지도로 맞춘다)."""

    def same(body: RecordBody) -> bool:
        recorded = body.result.versions
        now = analysis_versions(
            recorded.snapshot_id, body.result.request, context.rulebook, context.params, context.strength
        )
        return now == recorded

    return same


class Desk(Protocol):
    """기록을 계산하는 지도 한 벌: 작업 공간 세대(Workspace), 시연 기록 시드는 그날의 시연 세계(demo_seed)."""

    @property
    def index(self) -> GraphIndex: ...

    @property
    def snapshot(self) -> GraphSnapshot: ...

    @property
    def info(self) -> SnapshotInfo: ...

    @property
    def data_mode(self) -> DataMode: ...


def record_body(context: AppContext, desk: Desk, body: RecordRequest) -> RecordBody:
    """요청을 그 지도로 다시 계산해 화면이 본 분석 ID와 대조하고 기록 본문(확인 목록 고정)을 만든다(잠금 밖).
    RequestError(지도와 안 맞는 요청)는 호출자가 422로. 사전 점검의 합성 NCR 건수는 분석 경로와 같게(합성 지도만)."""
    counts = ncr_counts(desk.data_mode)
    result = analyze(desk.index, body.request, context.rulebook, context.params, context.strength, ncr_counts=counts)
    if result.analysis_id != body.analysis_id:
        raise FlowError(409, "analysis_changed", "다시 계산한 결과가 화면과 다름 — 다시 분석 후 기록")
    try:
        return RecordBody(
            ecn_id=body.request.change.ecn_id,
            snapshot_id=desk.snapshot.snapshot_id,
            data_mode=desk.data_mode,
            result=result,
            checklist=checklist_of(result, desk.info),
        )
    except ValidationError:
        raise FlowError(
            422, "invalid_transition", "ECN 번호 형식 오류 — 영문·숫자로 시작하는 64자 이내(. _ - 가능)만 기록 가능"
        ) from None


def commit_record(
    store: RecordStore, record: RecordBody, principal: Principal, body: RecordRequest, *, login_mode: bool
) -> RecordSaved:
    """저장소 한 트랜잭션(상태 버전 대조 · 개정 · 감사 줄). 작업 공간 경로는 전환 잠금 안에서 부른다."""
    return store.save(
        record,
        actor_of(principal, login_mode=login_mode),
        who_of(principal, login_mode=login_mode),
        request_id=body.request_id,
        analysis_id=body.analysis_id,
        expected_version=body.expected_version,
    )


def save_record(
    context: AppContext,
    workspaces: Workspaces,
    workspace: Workspace,
    store: RecordStore,
    principal: Principal,
    body: RecordRequest,
    *,
    login_mode: bool,
) -> RecordSaved:
    """다시 계산해 대조하고(잠금 밖), 전환 잠금 안에서 커밋한다. RequestError(지도와 안 맞는 요청)는 호출자가 422로."""
    # 같은 저장 요청의 재시도는 다시 계산하기 전에 처음 결과로 — 계산 판이 바뀐 배포 뒤에도
    # (docs/records.md(기록·결재) 2절 1)
    prior = store.prior_save(body.request_id, ecn_id=body.request.change.ecn_id, analysis_id=body.analysis_id)
    if prior is not None:
        return prior
    record = record_body(context, workspace, body)
    with workspaces.pinned(workspace.token):
        return commit_record(store, record, principal, body, login_mode=login_mode)


def commit_action(
    context: AppContext,
    store: RecordStore,
    principal: Principal,
    ecn_id: str,
    body: ActionRequest,
    *,
    active_snapshot_id: str,
    login_mode: bool,
) -> EcnStatus:
    """검토 요청·취소·결정·실행·종료를 저장소 한 트랜잭션으로(결재 규칙은 records.flow). active_snapshot_id = 커밋
    시점의 활성 지도(작업 공간 경로는 전환 잠금 안에서 잡은 세대의 지도)."""
    ask = Ask(
        action=body.action,
        expected_version=body.expected_version,
        revision=body.revision,
        record_id=body.record_id,
        review_seq=body.review_seq,
        reason=body.reason,
        acknowledged=frozenset(body.acknowledged),
    )
    return store.act(
        ecn_id,
        ask,
        actor_of(principal, login_mode=login_mode),
        who_of(principal, login_mode=login_mode),
        active_snapshot_id=active_snapshot_id,
        same_version=same_version_of(context),
        login_mode=login_mode,
    )


def act_on(
    context: AppContext,
    workspaces: Workspaces,
    workspace: Workspace,
    store: RecordStore,
    principal: Principal,
    ecn_id: str,
    body: ActionRequest,
    *,
    login_mode: bool,
) -> EcnStatus:
    with workspaces.pinned(workspace.token) as pinned:
        return commit_action(
            context,
            store,
            principal,
            ecn_id,
            body,
            active_snapshot_id=pinned.snapshot.snapshot_id,
            login_mode=login_mode,
        )


def outcome_entry(store: RecordStore, ecn_id: str, body: OutcomeInput, actor: Actor, at: datetime) -> OutcomeEntry:
    """실적 한 줄(docs/records.md(기록·결재) 11절): 실행을 시작했거나 끝낸 ECN의 승인 개정에 붙인다. 아니면 FlowError
    (기록 없음 404 · 실행 전 409 · 승인 개정 없음 404)."""
    status = next((item.status for item in store.listing(include_real=True).ecns if item.status.ecn_id == ecn_id), None)
    if status is None:
        raise FlowError(404, "not_found", "기록 없는 설계변경")
    if status.state not in EXECUTED or status.approved_revision is None:
        raise FlowError(409, "invalid_transition", "실적 입력 불가 — 실행 중·종료된 설계변경만 가능")
    detail = store.detail(ecn_id, include_real=True, same_version=lambda _body: True)
    approved = next((r for r in detail.revisions if r.revision == status.approved_revision), None) if detail else None
    if approved is None:
        raise FlowError(404, "not_found", "승인한 개정 없음")
    return OutcomeEntry(
        ecn_id=ecn_id,
        revision=approved.revision,
        record_id=approved.record_id,
        cost_krw=body.cost_krw,
        exit_delay_days=body.exit_delay_days,
        note=body.note.strip(),
        entered_by=actor,
        entered_at=at,
    )
