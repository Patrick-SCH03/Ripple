"""읽기: 저장 요청 재시도·목록·상세·결재 지표 재료·기록 한 건(읽기 한 트랜잭션 = 한 시점, 잠금 없음)."""

from __future__ import annotations

from collections.abc import Callable

from ripple.contracts.domain import DataMode
from ripple.contracts.records import (
    ApprovalPlan,
    AuditEntry,
    EcnAction,
    EcnDetail,
    EcnList,
    EcnListItem,
    EcnRecord,
    EcnStatus,
    RecordBody,
    RecordSaved,
    ReviewInfo,
    RevisionSummary,
)
from ripple.records.flow import FlowError

from .connection import Transaction
from .identity import checked
from .rows import StatusRead, entry_of, prior, read_body, read_summary

LATEST = (
    "SELECT e.status, r.summary FROM ecns e JOIN revisions r "
    "ON r.ecn_id = e.ecn_id AND r.revision = json_extract(e.status, '$.revision') ORDER BY e.ecn_id"
)  # ECN마다 상태 + 최신 개정 요약
PlanOf = Callable[[RecordBody, ReviewInfo | None], ApprovalPlan]  # 본문·진행 중 검토 → 결재 계획(ripple/api/records.py)


class RecordReader:
    """읽기 트랜잭션·상태 행 함수를 받아 읽는다. 보기 범위(include_real)는 ECN 단위."""

    def __init__(self, read: Transaction, read_status: StatusRead) -> None:
        self._read = read
        self._read_status = read_status

    def prior_save(self, request_id: str, *, ecn_id: str, analysis_id: str) -> RecordSaved | None:
        """이미 처리한 저장 요청이면 그 처음 응답(다른 ECN·분석에 쓴 요청 ID면 request_reused). 서비스가 다시 계산하기
        전에 본다 — 계산 판이 바뀐 뒤 같은 요청을 다시 보내도 처음 결과를 받게(docs/records.md(기록·결재) 2절 1)."""
        with self._read() as db:
            return prior(db, request_id, ecn_id, analysis_id)

    def listing(self, *, include_real: bool) -> EcnList:
        """상태 + 최신 개정 요약(저장한 요약을 읽는다 — 본문을 펼치지 않아 빠르다. 요약 = 본문은 검증이 본다)."""
        with self._read() as db:
            rows = db.execute(LATEST).fetchall()
        items = (
            EcnListItem(status=EcnStatus.model_validate_json(s), latest=RevisionSummary.model_validate_json(r))
            for s, r in rows
        )
        return EcnList(ecns=tuple(item for item in items if include_real or not item.status.real))

    def detail(
        self,
        ecn_id: str,
        *,
        include_real: bool,
        same_version: Callable[[RecordBody], bool],
        plan: PlanOf | None = None,
    ) -> EcnDetail | None:
        """상태·개정·감사 줄·확인 목록 + 최신 개정의 계산 판 대조·결재 계획(저장하지 않고 같은 읽기 시점의 본문으로
        계산 — 결재 계획은 받은 함수가 업무상 오늘로 계산한다)."""
        with self._read() as db:
            status = self._read_status(db, ecn_id)
            if status is None or (status.real and not include_real):
                return None
            rows = db.execute("SELECT revision FROM revisions WHERE ecn_id = ? ORDER BY revision", (ecn_id,)).fetchall()
            revisions = tuple(read_summary(db, ecn_id, row[0]) for row in rows)
            audit = tuple(
                entry_of(row)
                for row in db.execute(
                    "SELECT seq, entry, prev, digest FROM audit WHERE ecn_id = ? ORDER BY seq", (ecn_id,)
                )
            )
            if any(entry.ecn_id != ecn_id for entry in audit):
                raise FlowError(500, "integrity", "감사 줄의 ECN이 색인과 다름 — 감사 로그 확인 필요")
            latest = read_body(db, status.record_id)
        return EcnDetail(
            status=status,
            revisions=revisions,
            audit=audit,
            checklist=latest.checklist,
            same_version=same_version(latest),
            latest_design_status=latest.result.request.change.design_status,
            latest_effectivity=latest.result.request.change.effectivity,
            latest_cause=latest.result.request.change.cause,
            approval_plan=plan(latest, status.review) if plan is not None else None,
        )

    def overview_inputs(
        self, *, include_real: bool
    ) -> tuple[tuple[EcnListItem, ...], tuple[AuditEntry, ...], dict[str, RecordBody]]:
        """결재·현황 지표의 재료(같은 읽기 시점): 목록 · 전체 감사 줄 · 본문(최신 개정 + 승인한 개정)."""
        with self._read() as db:
            rows = db.execute(LATEST).fetchall()
            items = tuple(
                item
                for item in (
                    EcnListItem(status=EcnStatus.model_validate_json(s), latest=RevisionSummary.model_validate_json(r))
                    for s, r in rows
                )
                if include_real or not item.status.real
            )
            shown = {item.status.ecn_id for item in items}
            audit = tuple(
                entry
                for entry in (
                    entry_of(row) for row in db.execute("SELECT seq, entry, prev, digest FROM audit ORDER BY seq")
                )
                if entry.ecn_id in shown
            )
            wanted = {item.status.record_id for item in items} | {
                entry.record_id for entry in audit if entry.action is EcnAction.APPROVE and entry.record_id
            }
            bodies = {record_id: read_body(db, record_id) for record_id in sorted(wanted)}
        return items, audit, bodies

    def record(self, record_id: str, *, include_real: bool, plan: PlanOf | None = None) -> EcnRecord | None:
        """기록 한 건 + 결재 계획(plan을 받으면): 그 기록이 상태 행의 최신 개정이면 진행 중 검토의 남은 단계로(상세와
        같은 값), 아니면 검토 전 결재선으로 — 같은 읽기 시점의 상태로 고른다."""
        with self._read() as db:
            row = db.execute("SELECT body FROM records WHERE record_id = ?", (record_id,)).fetchone()
            if row is None:
                return None
            body = checked(record_id, row[0])
            status = self._read_status(db, body.ecn_id)
        # 보기 범위는 그 ECN 단위(실데이터 개정이 하나라도 있으면 뒤의 합성 개정도 체험에게 없음 — 목록·상세와 같게)
        real = body.data_mode is DataMode.REAL or (status is not None and status.real)
        if real and not include_real:
            return None
        review = status.review if status is not None and status.record_id == record_id else None
        approval = plan(body, review) if plan is not None else None
        return EcnRecord(record_id=record_id, body=body, approval_plan=approval)
