"""기록·승인 흐름 계약(docs/records.md).

ECN마다 분석 결과를 불변 기록(개정)으로 남기고, 상태는 요청 → 분석 → 검토 → 승인·반려·보류 → 실행 → 종료로 바뀐다.
모든 상태 변화는 덧붙이기만 하는 감사 줄(앞 줄 해시로 이음, ripple/records/chain.py)로 남는다.

- 기록 ID = 본문(RecordBody) 전체의 정규 JSON 해시: 유효 데이터 모드까지 들어가고 시각·기록한 사람은 빠진다.
- 기록 저장은 화면이 본 결과 숫자가 아니라 요청을 받아 서버가 그 작업 공간 세대로 다시 계산한 결과를 남긴다.
- 상태를 바꾸는 요청은 기대 상태 버전(EcnStatus.version)을 보내고, 결정은 진행 중 검토의 순번(review_seq)도 보낸다.
  다르면 409(ecn_changed)이고 아무것도 바뀌지 않는다. 기록 저장은 저장 요청 ID로 재시도를 알아본다.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from .analysis import AnalysisRequest, HoldAction

# 결재선 타입은 contracts/approval.py(분석 결과도 쓰므로 순환 없이 둔다) — 기록 계약에서 이어 쓰던 이름 그대로
# 다시 내보낸다
from .approval import LEGACY_LINE as LEGACY_LINE
from .approval import ApprovalPlan as ApprovalPlan
from .approval import ApprovalStep as ApprovalStep
from .approval import HoldApproval as HoldApproval
from .assistant import NotificationTarget
from .auth import Role
from .base import Frozen
from .change import ChangeCause, ChangeIntent, DesignStatus, Effectivity
from .domain import DataMode
from .result import Amount, AnalysisResult, VerdictLevel, ZeroLossDeadline
from .workspace import SnapshotId

RECORD_ID_PATTERN = r"^R-[0-9a-f]{16}$"
ECN_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"  # 영문·숫자로 시작, 64자 이내(경로·저장 키로 씀)
REQUEST_ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"  # 화면이 만든 UUID
HASH_PATTERN = r"^[0-9a-f]{64}$"
REASON_MAX = 500

RecordId = Annotated[str, StringConstraints(pattern=RECORD_ID_PATTERN)]
EcnId = Annotated[str, StringConstraints(pattern=ECN_ID_PATTERN)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=REASON_MAX)]


class EcnState(StrEnum):
    REQUESTED = "requested"  # 요청: 기록이 아직 없음(목록에서만 — 저장소에는 기록이 생긴 ECN만 있다)
    ANALYZED = "analyzed"  # 분석: 기록이 있고 검토 전
    IN_REVIEW = "in_review"  # 검토
    APPROVED = "approved"  # 승인
    REJECTED = "rejected"  # 반려
    ON_HOLD = "on_hold"  # 보류(결정을 미룸)
    IN_PROGRESS = "in_progress"  # 실행
    CLOSED = "closed"  # 종료


class EcnAction(StrEnum):
    RECORD = "record"  # 기록 저장(새 개정) — POST /api/records로만
    REQUEST_REVIEW = "request_review"
    WITHDRAW = "withdraw"  # 검토 취소
    APPROVE = "approve"
    REJECT = "reject"
    HOLD = "hold"
    START = "start"  # 실행 시작
    CLOSE = "close"  # 종료
    NOTICE = "notice"  # 1.28.0 통보 기록(보냄·수령 확인·회신) — POST /api/ecns/{ecn_id}/notices로만, 상태·버전 그대로
    # 무비용 담당자 처리(결재선 없음): 비용 줄이 도면 개정뿐이고 판정이 승인 가능인 개정을 담당자가
    # 분석 → 승인으로(감사 세부 no_cost).
    # 결재자의 승인(APPROVE)과 다른 행동이라 '담당자 자기 승인 금지'는 그대로다(docs/records.md(기록·결재) 14절)
    SETTLE = "settle"


DECISIONS = frozenset({EcnAction.APPROVE, EcnAction.REJECT, EcnAction.HOLD})
"""결재선 결재자만 하는 결정(지금 단계의 결재자 또는 팀장 전결). 그 검토를 요청한 계정은 결정할 수 없다(자기 승인 금지,
개발 모드만 예외·표시)."""


class Actor(Frozen):
    """기록·결정을 한 사람(그때의 이름·역할). dev = 로그인을 끈 개발 모드의 주체(업무 기록 아님)."""

    login_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    role: Role
    dev: bool = False


class ChecklistItem(Frozen):
    """승인 전에 사람이 확인할 항목: 분석이 계산하지 못했거나 가정한 것, 가져온 지도의 품질 경고. 기록할 때 고정한다."""

    key: str = Field(min_length=1, max_length=200)  # 기록 안에서 고유(승인 때 '확인했음' 체크가 이 키를 보낸다)
    source: Literal["analysis", "import"]
    text: str = Field(min_length=1, max_length=500)


class RecordBody(Frozen):
    """불변 기록 본문. 기록 ID = 이 본문 전체(정규 JSON)의 해시."""

    ecn_id: EcnId
    snapshot_id: SnapshotId
    data_mode: DataMode  # 기록할 때의 유효 데이터 모드(설정·지도 중 하나라도 real이면 real)
    result: AnalysisResult
    checklist: tuple[ChecklistItem, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> RecordBody:
        if self.result.request.change.ecn_id != self.ecn_id:
            raise ValueError("기록의 ECN 번호가 분석 요청과 다름")
        if self.result.versions.snapshot_id != self.snapshot_id:
            raise ValueError("기록의 지도가 분석한 지도와 다름")
        if self.result.data_mode is DataMode.REAL and self.data_mode is not DataMode.REAL:
            raise ValueError("실제 데이터 분석은 실제 데이터 기록으로만 저장 가능")
        keys = [item.key for item in self.checklist]
        if len(set(keys)) != len(keys):
            raise ValueError("확인 목록 키 중복")
        return self


class EcnRecord(Frozen):
    """GET /api/records/{record_id}: 불변 기록 전체(서버가 읽을 때 본문 해시를 ID와 대조한다).

    approval_plan(1.33.0)은 읽을 때 그 본문으로 계산한 결재 계획(보류 권고의 결재 기간 문구 포함 — 판단 리포트가 쓴다).
    본문 밖이라 기록 ID와 무관하다."""

    record_id: RecordId
    body: RecordBody
    approval_plan: ApprovalPlan | None = None


class RevisionSummary(Frozen):
    """개정 한 줄(이력 탭): 본문에서 뽑은 요약 + 기록한 사람·시각."""

    revision: int = Field(ge=1)
    record_id: RecordId
    analysis_id: str
    recorded_at: AwareDatetime
    recorded_by: Actor
    snapshot_id: SnapshotId
    data_mode: DataMode
    title: str
    intent: ChangeIntent | None = None  # 변경 사유(분석 ID에는 없어 '화면 = 기록' 판단에 함께 본다)
    verdict: VerdictLevel
    total: Amount
    deadline: ZeroLossDeadline
    as_of: date
    confirm_on: date
    holds: tuple[HoldAction, ...] = ()
    alternatives: bool = False
    checklist: int = Field(ge=0)  # 확인 목록 항목 수


class ReviewInfo(Frozen):
    """진행 중 검토(검토·보류 상태): 결정은 이 순번을 함께 보내야 받는다.

    결재선(steps)은 검토 요청 때 고정하고 step은 지금 결정할 단계(1부터). 단계 승인은 다음 단계로 넘기고 마지막
    단계 승인이 승인이다. 형식 판 3까지의 검토는 두 칸이 없어 기본값(팀장 한 단계, 1/1단계)으로 읽힌다."""

    seq: int = Field(ge=1)  # 검토 요청 감사 줄 순번
    revision: int = Field(ge=1)
    requested_by: Actor
    requested_at: AwareDatetime
    steps: tuple[ApprovalStep, ...] = Field(default=LEGACY_LINE, min_length=1)
    step: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _step(self) -> ReviewInfo:
        if self.step > len(self.steps) or len(set(self.steps)) != len(self.steps):
            raise ValueError("지금 결재 단계가 결재선 밖이거나 결재선 단계 중복")
        return self

    @property
    def current(self) -> ApprovalStep:
        """지금 결정할 단계."""
        return self.steps[self.step - 1]


class EcnStatus(Frozen):
    """ECN 상태(목록 칩·상세 결재 띠). version은 상태가 바뀔 때마다 1씩 오른다."""

    ecn_id: EcnId
    title: str
    state: EcnState
    version: int = Field(ge=1)
    revision: int = Field(ge=1)  # 최신 개정
    record_id: RecordId  # 최신 개정의 기록
    snapshot_id: SnapshotId  # 최신 기록의 지도
    review: ReviewInfo | None = None
    approved_revision: int | None = Field(default=None, ge=1)  # 승인·실행·종료 상태의 승인 개정
    approval_dev: bool = False  # 그 승인이 개발 모드였는가(로그인 모드에서는 실행 불가 → 다시 검토·승인)
    real: bool = False  # 실데이터 기록이 하나라도 있는가(체험에게 안 보임)
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def _consistent(self) -> EcnStatus:
        reviewing = self.state in (EcnState.IN_REVIEW, EcnState.ON_HOLD)
        if reviewing != (self.review is not None):
            raise ValueError("진행 중 검토는 검토·보류 상태에만 허용")
        approved = self.state in (EcnState.APPROVED, EcnState.IN_PROGRESS, EcnState.CLOSED)
        if approved != (self.approved_revision is not None):
            raise ValueError("승인 개정은 승인·실행·종료 상태에만 허용")
        if self.state is EcnState.REQUESTED:
            raise ValueError("저장된 ECN은 요청 상태 불가(기록 있음)")
        return self


class EcnListItem(Frozen):
    """목록 한 줄: 상태 + 최신 개정 요약(판정·총액·마감일 — 샘플에 없는 기록된 ECN도 목록에 그린다)."""

    status: EcnStatus
    latest: RevisionSummary

    @model_validator(mode="after")
    def _same(self) -> EcnListItem:
        if self.latest.revision != self.status.revision or self.latest.record_id != self.status.record_id:
            raise ValueError("목록 줄의 요약이 최신 개정이 아님")
        return self


class EcnList(Frozen):
    ecns: tuple[EcnListItem, ...] = ()


class NoticeStep(StrEnum):
    """통보 단계(1.28.0). 앱은 메일을 보내지 않으므로 사람이 한 일을 적는다."""

    SENT = "sent"  # 보냄
    ACKNOWLEDGED = "acknowledged"  # 받는 쪽이 받았다고 확인함
    REPLIED = "replied"  # 회신(진행 상황·견적·이의)을 받음


class NoticeLog(Frozen):
    """통보 기록 한 줄(1.28.0): 누구에게(알림 대상·받는 쪽 ID) · 무엇을 했나 · 언제(사람이 적은 날) · 메모.

    분쟁에서 '언제 알렸고 언제 확인받았나'를 증명할 당시 기록이 없던 문제(docs/records.md(기록·결재) 7절). 감사 사슬에
    남아
    고칠 수 없고, 잘못 적었으면 새 줄로 바로잡는다.
    """

    target: NotificationTarget
    # 알림의 받는 쪽 ID(협력사·블록·도면 분야). 공백뿐인 값은 받지 않는다
    recipient_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    step: NoticeStep
    on: date
    note: str | None = Field(default=None, max_length=200)


class NoticeRequest(Frozen):
    """POST /api/ecns/{ecn_id}/notices: 통보 기록 남기기. 화면이 본 최신 개정(기록 ID)이 지금과 다르면 409."""

    record_id: RecordId
    notice: NoticeLog


class AuditDetail(Frozen):
    """감사 줄 세부. 행동마다 쓰는 필드만 채운다."""

    from_state: EcnState
    to_state: EcnState
    reason: str | None = None
    acknowledged: tuple[str, ...] = ()  # 승인 때 '확인했음'으로 체크한 확인 목록 키
    review_seq: int | None = Field(default=None, ge=1)  # 결정·취소가 묶인 검토 요청 줄
    superseded_review_seq: int | None = Field(default=None, ge=1)  # 새 개정 저장이 끝낸 진행 중 검토
    other_map: bool = False  # 실행 시작 때 승인한 기록의 지도가 활성 지도와 다름(허용)
    other_version: bool = False  # 이전 계산 판으로 기록한 개정을 반려·보류함(허용)
    self_decision: bool = False  # 개발 모드에서 요청자가 직접 결정함(업무 승인 아님)
    note: str | None = None
    notice: NoticeLog | None = None  # 1.28.0 통보 기록 줄(action = notice)일 때만
    # 결재선(형식 판 4). 옛 줄에는 없어 기본값으로 읽힌다 — 검토 요청의 빈 결재선 = 팀장 한 단계, 결정의 빈 단계 = 팀장
    steps: tuple[ApprovalStep, ...] = ()  # 검토 요청: 이 검토에 고정한 결재선
    step: ApprovalStep | None = None  # 결정: 결정한 결재 단계(전결이면 원래 단계)
    proxy: bool = False  # 결정: 팀장이 다른 단계(파트장·본부장)를 대신 결정함(전결)
    no_cost: bool = False  # 담당자 처리: 비용 줄이 도면 개정뿐 + 승인 가능이라 결재선 없이 승인으로


class StepSign(Frozen):
    """결재선 한 단계의 승인(결재함·상세의 진행 표시): 단계 · 결정한 사람 · 시각 · 전결 여부."""

    step: ApprovalStep
    actor: Actor
    at: AwareDatetime
    proxy: bool = False


class AuditEntry(Frozen):
    """감사 줄(덧붙이기만). digest = SHA-256(정규 JSON {prev, entry}), entry = 이 모델에서 seq·prev·digest를 뺀 값."""

    seq: int = Field(ge=1)
    at: AwareDatetime
    actor: Actor
    action: EcnAction
    ecn_id: EcnId
    revision: int | None = Field(default=None, ge=1)
    record_id: RecordId | None = None
    detail: AuditDetail
    prev: str = Field(pattern=HASH_PATTERN)
    digest: str = Field(pattern=HASH_PATTERN)


class EcnDetail(Frozen):
    """GET /api/ecns/{ecn_id}: 상태 · 개정(오래된 순) · 이 ECN의 감사 줄(순번 순) · 최신 개정의 확인 목록.

    same_version은 저장하지 않고 읽을 때 계산한다: 최신 개정의 계산 판(지도를 뺀 버전 묶음 — 계약·규칙표·파라미터·엔진·
    대안 분석의 강도 규칙)이 그 요청을 지금 분석할 때의 판과 같은가. 다르면 다시 계산한 분석 ID가 기록과 달라
    검토 요청·승인을 받지 않는다(지도가 바뀐 개정과 같은 원칙, 반려·보류는 됨).
    """

    status: EcnStatus
    revisions: tuple[RevisionSummary, ...] = Field(min_length=1)
    audit: tuple[AuditEntry, ...] = Field(min_length=1)
    checklist: tuple[ChecklistItem, ...] = ()
    same_version: bool
    # 1.23.0 최신 개정 요청의 설계 승인 상태·적용 범위. 분석 ID에 다 들어가지 않아(미입력↔승인, 적용 시작일)
    # 화면이 '지금 분석 = 기록'을 가를 때 함께 본다.
    # 읽을 때 본문에서 계산하고, 재시도 응답(RecordSaved)에는 넣지 않는다.
    latest_design_status: DesignStatus = DesignStatus.UNKNOWN
    latest_effectivity: Effectivity | None = None
    # 1.28.0 최신 개정 요청의 변경 원인(선주 요청 말고는 분석 ID에 안 들어가 함께 비교)
    latest_cause: ChangeCause | None = None
    # 결재선: 최신 개정의 결재 소요·결재 올릴 기한(읽을 때 계산, 14절). 진행 중 검토면 남은 단계로
    approval_plan: ApprovalPlan | None = None


class RecordRequest(Frozen):
    """POST /api/records: 화면이 본 분석을 기록으로 남긴다(서버가 같은 요청을 다시 계산해 대조)."""

    request: AnalysisRequest
    analysis_id: str = Field(min_length=1, max_length=64)  # 화면이 본 분석 ID(다시 계산한 값과 다르면 409)
    request_id: str = Field(pattern=REQUEST_ID_PATTERN)  # 같은 ID의 재시도는 처음 결과를 그대로 받는다
    expected_version: int = Field(ge=0)  # 화면이 아는 상태 버전(새 ECN이면 0)


class RecordSaved(Frozen):
    status: EcnStatus
    revision: RevisionSummary
    created: bool  # 새 개정을 만들었는가(최신 개정과 같은 본문이면 False)


class ActionRequest(Frozen):
    """POST /api/ecns/{ecn_id}/actions: 검토 요청·취소·결정·실행·종료(기록 저장은 /api/records)."""

    action: EcnAction
    expected_version: int = Field(ge=1)
    revision: int = Field(ge=1)
    record_id: RecordId
    review_seq: int | None = Field(default=None, ge=1)  # 결정·취소: 화면이 본 진행 중 검토
    reason: Reason | None = None
    acknowledged: tuple[str, ...] = Field(default=(), max_length=1000)  # 확인 목록은 묶어서 이보다 훨씬 작다

    @model_validator(mode="after")
    def _shape(self) -> ActionRequest:
        if self.action is EcnAction.RECORD:
            raise ValueError("기록 저장은 POST /api/records 사용")
        if self.action is EcnAction.NOTICE:
            raise ValueError("통보 기록은 POST /api/ecns/{ecn_id}/notices 사용")
        if (self.action in DECISIONS or self.action is EcnAction.WITHDRAW) and self.review_seq is None:
            raise ValueError("결정·검토 취소에는 진행 중 검토 순번(review_seq) 필요")
        return self


class AuditCheck(Frozen):
    """GET /api/audit/verify(승인(결재자)): 사슬 + 참조 무결성(기록 본문 해시·개정 연결·투영 = 재생)."""

    ok: bool
    entries: int = Field(ge=0)
    records: int = Field(ge=0)
    broken_at: int | None = Field(default=None, ge=1)  # 사슬이 처음 어긋난 순번
    head: str = Field(pattern=HASH_PATTERN)
    problems: tuple[str, ...] = ()  # 명사형 이유(참조 무결성 포함)


class RecordProblem(Frozen):
    """기록·결정 거절 이유(detail). code로 화면이 문구·다음 행동을 고른다."""

    code: Literal[
        "ecn_changed",  # 기대 버전·개정·기록·검토 순번이 지금과 다름(다시 불러오기)
        "analysis_changed",  # 다시 계산한 분석 ID가 화면이 본 것과 다름
        "invalid_transition",  # 지금 상태에서 할 수 없는 행동
        "locked",  # 실행·종료 뒤 새 개정
        "self_decision",  # 내가 요청한 검토를 결정
        "checklist_required",  # 확인 목록 미체크
        "reason_required",  # 사유 없음
        "map_changed",  # 기록의 지도가 활성 지도와 다름(검토 요청·승인)
        "version_changed",  # 기록의 계산 판이 지금 판과 다름(검토 요청·승인)
        "dev_approval",  # 개발 모드 승인으로 로그인 모드 실행
        "not_found",
        "forbidden",  # 역할 권한 밖(결정은 관리자, 검토 취소는 요청자·관리자)
        "request_reused",  # 같은 저장 요청 ID를 다른 기록에 씀
        "integrity",  # 저장된 본문 해시가 ID와 다름 · 사슬 머리가 맞지 않음
    ]
    message: str
