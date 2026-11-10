"""ECN 상태 기계(순수 계산, docs/records.md(기록·결재) 3·14절).

저장소(ripple/store/records/)가 트랜잭션 안에서 지금 투영을 읽어 이 함수에 넘기고, 돌려받은 다음 투영과 감사 세부를
같은 트랜잭션으로 쓴다. 여기서는 I/O 없이 '받을 수 있는가 · 다음 상태 · 감사 줄에 남길 것'만 정한다.

검사 순서(먼저 걸린 이유로 거절): 기대값 대조(버전·개정·기록·검토 순번) → 전이표(무비용 담당자 처리는 무비용 개정만) →
권한·결재 단계·자기 결정 → 사유·확인 목록 → 지도 → 계산 판 → 개발 모드 승인. 지도 대조 결과(same_map)는 호출자가 지도
전환 잠금 안에서 구해 넘긴다(커밋 시점의 지도).
계산 판 대조 결과(same_version)는 그 개정 본문의 판이 그 요청을 지금 분석할 때의 판과 같은가(ripple/api/records.py).

결재선(14절): 검토 요청이 결재선(line)을 그 검토에 고정하고, 단계 승인은 다음 단계로 넘기며(검토 상태 그대로, 버전 +1)
마지막 단계 승인이 승인이다. 반려는 어느 단계에서든 검토를 끝내고, 보류는 그 단계에서 이어진다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date

from ripple.contracts.records import (
    DECISIONS,
    ApprovalStep,
    AuditDetail,
    AuditEntry,
    EcnAction,
    EcnState,
    NoticeLog,
)

from .approval import APPROVAL_LINE, STEP_LABEL, line_or_legacy

# 행동 → (받는 상태들, 다음 상태). 기록 저장(RECORD)은 record(), 통보 기록(NOTICE)은 notice()가 따로 다룬다.
# 승인의 다음 상태는 마지막 단계일 때이고, 앞 단계 승인은 검토 그대로 다음 단계로 간다(_check_transition).
TRANSITIONS: dict[EcnAction, tuple[frozenset[EcnState], EcnState]] = {
    EcnAction.REQUEST_REVIEW: (frozenset({EcnState.ANALYZED, EcnState.APPROVED}), EcnState.IN_REVIEW),
    EcnAction.WITHDRAW: (frozenset({EcnState.IN_REVIEW}), EcnState.ANALYZED),
    EcnAction.APPROVE: (frozenset({EcnState.IN_REVIEW, EcnState.ON_HOLD}), EcnState.APPROVED),
    EcnAction.REJECT: (frozenset({EcnState.IN_REVIEW, EcnState.ON_HOLD}), EcnState.REJECTED),
    EcnAction.HOLD: (frozenset({EcnState.IN_REVIEW}), EcnState.ON_HOLD),
    EcnAction.START: (frozenset({EcnState.APPROVED}), EcnState.IN_PROGRESS),
    EcnAction.CLOSE: (frozenset({EcnState.IN_PROGRESS}), EcnState.CLOSED),
    EcnAction.SETTLE: (frozenset({EcnState.ANALYZED}), EcnState.APPROVED),  # 무비용 개정만
}
LOCKED = frozenset({EcnState.IN_PROGRESS, EcnState.CLOSED})  # 새 개정을 받지 않는 상태
REASON_REQUIRED = frozenset({EcnAction.REJECT, EcnAction.HOLD})
CHECKED = frozenset({EcnAction.APPROVE, EcnAction.SETTLE})  # 확인 목록을 체크해 보내는 행동(승인 · 무비용 담당자 처리)
SAME_MAP_AND_VERSION = frozenset({EcnAction.REQUEST_REVIEW, EcnAction.APPROVE, EcnAction.SETTLE})


class FlowError(Exception):
    """받을 수 없는 요청. status·code·message는 API가 그대로 내보낸다(RecordProblem)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class Projection:
    """ECN 상태 투영(감사 줄을 처음부터 다시 돌리면 같은 값이 나와야 한다).

    진행 중 검토가 있으면 review_steps(그 검토에 고정한 결재선)와 review_step(지금 단계, 1부터)이 함께 있다."""

    state: EcnState
    version: int
    revision: int
    record_id: str
    review_seq: int | None = None
    review_revision: int | None = None
    review_by: str | None = None  # 검토를 요청한 계정 아이디
    approved_revision: int | None = None
    approval_dev: bool = False
    review_steps: tuple[ApprovalStep, ...] = ()
    review_step: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Who:
    """행동한 사람: 아이디 · 기록 권한 · 결정할 수 있는 결재 단계(자기 단계 · 전결) · 관리자(팀장) · 개발 모드."""

    login_id: str
    can_record: bool
    admin: bool = False
    dev: bool = False
    steps: frozenset[ApprovalStep] = frozenset()  # 자기 단계로 결정
    proxy: frozenset[ApprovalStep] = frozenset()  # 전결로 결정(팀장 → 파트장·본부장)

    @property
    def can_approve(self) -> bool:
        return bool(self.steps or self.proxy)


@dataclass(frozen=True, slots=True)
class Ask:
    """행동 요청(계약 ActionRequest에서 옮긴 값)."""

    action: EcnAction
    expected_version: int
    revision: int
    record_id: str
    review_seq: int | None = None
    reason: str | None = None
    acknowledged: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Outcome:
    projection: Projection
    detail: AuditDetail


def _changed() -> FlowError:
    return FlowError(409, "ecn_changed", "설계변경 상태 변경됨 — 다시 불러온 뒤 재시도")


def current_step(current: Projection) -> ApprovalStep:
    """진행 중 검토의 지금 단계(검토·보류 상태에서만 부른다)."""
    if not current.review_steps or current.review_step is None:
        raise ValueError("진행 중 검토에 결재선 없음")
    return current.review_steps[current.review_step - 1]


def check_record(current: Projection | None, who: Who) -> None:
    """기록 저장 자격: 권한과 잠김. 최신 개정과 같은 본문(새 개정 없음)도 같은 답을 받는다 — 잠긴 설계변경에
    같은 본문을 다시 보내도 200으로 지나가지 않게."""
    if not who.can_record:
        raise FlowError(403, "forbidden", "권한 없음 — 이 계정은 기록 불가")
    if current is not None and current.state in LOCKED:
        raise FlowError(409, "locked", "실행·종료된 설계변경 — 새 개정 불가")


def record(current: Projection | None, revision: int, record_id: str, who: Who) -> Outcome:
    """새 개정 저장(본문이 최신 개정과 다를 때만 호출). 실행·종료 뒤에는 잠김."""
    check_record(current, who)
    expected = 1 if current is None else current.revision + 1
    if revision != expected:
        raise _changed()
    from_state = EcnState.REQUESTED if current is None else current.state
    superseded = current.review_seq if current is not None else None
    nxt = Projection(
        state=EcnState.ANALYZED,
        version=1 if current is None else current.version + 1,
        revision=revision,
        record_id=record_id,
    )
    return Outcome(
        nxt, AuditDetail(from_state=from_state, to_state=EcnState.ANALYZED, superseded_review_seq=superseded)
    )


def notice(current: Projection, record_id: str, log: NoticeLog, who: Who, today: date) -> AuditDetail:
    """통보 기록(1.28.0): 기록 권한, 화면이 본 최신 개정, 앞날이 아닌 날짜. 상태·버전은 바꾸지 않는다 — 결재 중인
    다른 사람의 화면을 '그사이 바뀜'으로 막지 않게. 실행·종료 뒤에도 받는다(늦은 회신도 남겨야 하므로)."""
    if not who.can_record:
        raise FlowError(403, "forbidden", "권한 없음 — 이 계정은 통보 기록 불가")
    if record_id != current.record_id:
        raise _changed()
    if log.on > today:
        raise FlowError(422, "invalid_transition", "통보 날짜가 오늘보다 뒤")
    return AuditDetail(from_state=current.state, to_state=current.state, notice=log)


def act(
    current: Projection,
    ask: Ask,
    who: Who,
    *,
    checklist: frozenset[str],
    same_map: bool,
    same_version: bool,
    login_mode: bool,
    seq: int,
    no_cost: bool = False,
    line: tuple[ApprovalStep, ...] = APPROVAL_LINE,
) -> Outcome:
    """검토 요청·취소·결정·무비용 담당자 처리·실행·종료. seq = 이번에 남길 감사 줄 순번(검토 요청이면 그 줄이 진행 중
    검토가 된다). no_cost = 그 개정이 무비용인가(records.approval.no_cost), line = 검토 요청이 고정할 결재선.

    검사는 모듈 설명의 순서대로 하고, 먼저 걸린 이유로 거절한다.
    """
    action = ask.action
    if action is EcnAction.RECORD:
        raise FlowError(422, "invalid_transition", "기록 저장은 POST /api/records 사용")
    if action is EcnAction.NOTICE:
        raise FlowError(422, "invalid_transition", "통보 기록은 POST /api/ecns/{ecn_id}/notices 사용")
    _check_expected(current, ask)
    to_state = _check_transition(current, action, login_mode, no_cost)
    proxy = _check_actor(current, action, who)
    _check_reason(ask, checklist)
    _check_map_and_version(action, same_map, same_version)
    if action is EcnAction.START and current.approval_dev and login_mode:
        raise FlowError(409, "dev_approval", "개발 모드 승인 — 업무 계정으로 재검토·승인 필요")
    decision = action in DECISIONS
    detail = AuditDetail(
        from_state=current.state,
        to_state=to_state,
        reason=ask.reason,
        acknowledged=tuple(sorted(ask.acknowledged)),
        review_seq=current.review_seq if decision or action is EcnAction.WITHDRAW else None,
        other_map=action is EcnAction.START and not same_map,
        other_version=action in (EcnAction.REJECT, EcnAction.HOLD) and not same_version,
        self_decision=decision and who.login_id == current.review_by,
        steps=line if action is EcnAction.REQUEST_REVIEW else (),
        step=current_step(current) if decision else None,
        proxy=proxy,
        no_cost=action is EcnAction.SETTLE,
    )
    return Outcome(_next_projection(current, action, to_state, seq, who, line), detail)


def _check_expected(current: Projection, ask: Ask) -> None:
    """1) 기대값: 화면이 본 상태와 지금이 같은가."""
    if (
        ask.expected_version != current.version
        or ask.revision != current.revision
        or ask.record_id != current.record_id
    ):
        raise _changed()
    reviewed = ask.action in DECISIONS or ask.action is EcnAction.WITHDRAW
    if reviewed and ask.review_seq != current.review_seq:  # 검토가 없는 상태끼리는 같음 → 아래 전이표가 거절
        raise _changed()


def _check_transition(current: Projection, action: EcnAction, login_mode: bool, no_cost: bool) -> EcnState:
    """2) 전이표. 승인 뒤 다시 검토 요청은 '개발 모드 승인을 업무 계정으로 다시 받는' 길만. 무비용 담당자 처리는 무비용
    개정만. 승인은 마지막 단계일 때만 승인 상태로, 앞 단계면 검토 그대로(다음 단계)."""
    allowed, to_state = TRANSITIONS[action]
    if current.state not in allowed:
        raise FlowError(409, "invalid_transition", "지금 상태에서 불가")
    rereview = action is EcnAction.REQUEST_REVIEW and current.state is EcnState.APPROVED
    if rereview and not (current.approval_dev and login_mode):
        raise FlowError(409, "invalid_transition", "이미 승인된 개정")
    if action is EcnAction.SETTLE and not no_cost:
        raise FlowError(
            409,
            "invalid_transition",
            "추가 비용 있는 개정 — 결재선(파트장 → 팀장 → 본부장)으로 검토 요청 필요",
        )
    if action is EcnAction.APPROVE and (current.review_step or 1) < len(current.review_steps):
        return EcnState.IN_REVIEW
    return to_state


def _check_actor(current: Projection, action: EcnAction, who: Who) -> bool:
    """3) 권한·결재 단계·자기 결정. 결정이면 전결인가를 돌려준다(팀장이 다른 단계를 결정)."""
    if action in DECISIONS:
        step = current_step(current)
        if step in who.steps:
            proxy = False
        elif step in who.proxy:
            proxy = True
        elif not who.can_approve:
            raise FlowError(403, "forbidden", "권한 없음 — 승인·반려·보류는 결재선 결재자(파트장·팀장·본부장)만 가능")
        else:
            name = STEP_LABEL[step]
            raise FlowError(403, "forbidden", f"지금은 {name} 결재 단계 — {name} 또는 팀장 전결로 결정")
        if who.login_id == current.review_by and not who.dev:
            raise FlowError(403, "self_decision", "본인이 검토 요청한 건 — 결재선의 다른 사람이 결정")
        return proxy
    if action is EcnAction.WITHDRAW:
        if not (who.admin or who.login_id == current.review_by):
            raise FlowError(403, "forbidden", "권한 없음 — 검토 취소는 요청자·팀장만 가능")
    elif not who.can_record:
        raise FlowError(403, "forbidden", "권한 없음")
    return False


def _check_reason(ask: Ask, checklist: frozenset[str]) -> None:
    """4) 사유·확인 목록(승인과 무비용 담당자 처리는 확인 목록이 있으면 전부 체크 + 사유)."""
    if ask.action in REASON_REQUIRED and not ask.reason:
        raise FlowError(422, "reason_required", "사유 입력 필요")
    if ask.action in CHECKED and checklist:
        if ask.acknowledged != checklist:
            raise FlowError(422, "checklist_required", "확인 필요 항목 모두 체크 필요")
        if not ask.reason:
            raise FlowError(422, "reason_required", "확인 필요 항목이 남은 채 승인하는 사유 입력 필요")
    if ask.action not in CHECKED and ask.acknowledged:
        raise FlowError(422, "invalid_transition", "확인 목록 체크는 승인·담당자 처리에만 사용")
    if ask.acknowledged - checklist:  # 확인 목록이 비었어도 목록 밖 체크는 거절
        raise FlowError(422, "checklist_required", "확인 필요 항목에 없는 체크 있음 — 다시 불러온 뒤 재시도")


def _check_map_and_version(action: EcnAction, same_map: bool, same_version: bool) -> None:
    """5) 지도·계산 판: 검토 요청·승인(단계마다)·무비용 담당자 처리는 지금 지도·지금 판으로 기록한 개정만.

    이전 판 개정은 반려·보류만 받는다.
    """
    if action not in SAME_MAP_AND_VERSION:
        return
    if not same_map:
        raise FlowError(
            409,
            "map_changed",
            "지도 바뀜 — 이 개정은 지금 지도와 다름 · 지금 지도로 다시 분석해 새 개정 기록",
        )
    if not same_version:
        raise FlowError(
            409,
            "version_changed",
            "계산 판 바뀜 — 이 개정은 지금 계산과 다름 · 지금 판으로 다시 기록 후 검토 요청",
        )


def _closed(nxt: Projection) -> Projection:
    """진행 중 검토를 닫은 투영."""
    return replace(nxt, review_seq=None, review_revision=None, review_by=None, review_steps=(), review_step=None)


def _next_projection(
    current: Projection, action: EcnAction, to_state: EcnState, seq: int, who: Who, line: tuple[ApprovalStep, ...]
) -> Projection:
    """행동 뒤 투영. 검토 요청은 진행 중 검토(결재선 고정, 1단계)를 새로 열고, 앞 단계 승인은 다음 단계로, 마지막 단계
    승인·무비용 담당자 처리는 승인 개정을 남기고, 반려·취소는 검토를 닫는다.

    replay()는 감사 줄에서 같은 규칙을 따로 적용한다(서로 대조하는 검사가 독립이도록 일부러 공유하지 않는다).
    """
    nxt = replace(current, state=to_state, version=current.version + 1)
    if action is EcnAction.REQUEST_REVIEW:
        return replace(
            nxt,
            review_seq=seq,
            review_revision=current.revision,
            review_by=who.login_id,
            review_steps=line,
            review_step=1,
            approved_revision=None,
            approval_dev=False,
        )
    if action is EcnAction.APPROVE and to_state is EcnState.IN_REVIEW:
        return replace(nxt, review_step=(current.review_step or 1) + 1)
    if action in (EcnAction.APPROVE, EcnAction.SETTLE):
        return replace(_closed(nxt), approved_revision=current.revision, approval_dev=who.dev)
    if action in (EcnAction.REJECT, EcnAction.WITHDRAW):
        return _closed(nxt)
    return nxt  # 보류: 같은 검토·같은 단계가 이어진다(보류 뒤 결정도 그 순번으로) · 실행·종료


def replay(entries: Iterable[AuditEntry]) -> Projection | None:
    """한 ECN의 감사 줄(순번 순)을 처음부터 다시 돌린 투영. 저장소의 투영과 같아야 한다(검증·검사).

    옛 검토 요청 줄(결재선 없음)은 팀장 한 단계로 읽는다."""
    current: Projection | None = None
    for entry in entries:
        to_state = entry.detail.to_state
        if entry.action is EcnAction.RECORD:
            assert entry.revision is not None and entry.record_id is not None
            current = Projection(
                state=to_state,
                version=1 if current is None else current.version + 1,
                revision=entry.revision,
                record_id=entry.record_id,
            )
            continue
        if current is None:
            raise ValueError(f"기록 없이 시작한 감사 줄(순번 {entry.seq})")
        if entry.action is EcnAction.NOTICE:  # 통보 기록은 상태·버전을 바꾸지 않는다
            if to_state is not current.state or entry.detail.notice is None:
                raise ValueError(f"통보 기록 줄이 상태를 바꾸거나 내용 없음(순번 {entry.seq})")
            continue
        nxt = replace(current, state=to_state, version=current.version + 1)
        if entry.action is EcnAction.REQUEST_REVIEW:
            nxt = replace(
                nxt,
                review_seq=entry.seq,
                review_revision=entry.revision,
                review_by=entry.actor.login_id,
                review_steps=line_or_legacy(entry.detail.steps),
                review_step=1,
                approved_revision=None,
                approval_dev=False,
            )
        elif entry.action is EcnAction.APPROVE and to_state is EcnState.IN_REVIEW:
            nxt = replace(nxt, review_step=(current.review_step or 1) + 1)
        elif entry.action in (EcnAction.APPROVE, EcnAction.SETTLE):
            nxt = replace(
                nxt,
                review_seq=None,
                review_revision=None,
                review_by=None,
                review_steps=(),
                review_step=None,
                approved_revision=entry.revision,
                approval_dev=entry.actor.dev,
            )
        elif entry.action in (EcnAction.REJECT, EcnAction.WITHDRAW):
            nxt = replace(nxt, review_seq=None, review_revision=None, review_by=None, review_steps=(), review_step=None)
        current = nxt
    return current
