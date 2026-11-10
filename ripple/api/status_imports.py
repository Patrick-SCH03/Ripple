"""상태 올리기(바뀌는 시트만, docs/input.md(엑셀 양식) 5절).

올리기 → 매핑 제안(열 확인) → 읽기(품질 리포트 + 적용 미리보기) → 확정(지금 지도에 상태 갱신, 새 작업 공간 세대).

엑셀 가져오기와 같은 읽기·열 확인·상태 버전 규칙(ripple/api/pending_imports.py PendingImports)을 쓰되 양식은 상태
시트만이고, 확정은 지도를 새로 만드는 대신 지금 지도에 덮어쓴다(Workspaces.apply_update — 기대 토큰 대조·갱신 기록·
거부 규칙이 화면 확인과 같다). 담당자도 할 수 있다.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from ripple.contracts.ingest import ConfirmedMapping, MappingOverrides, MappingProposal, MappingSubmission
from ripple.contracts.records import Actor
from ripple.contracts.updates import StatusImportPreview, StatusUpdate, UpdateEvent
from ripple.engine.updates import date_problems
from ripple.ingest.proposal import plan_file, to_contract
from ripple.ingest.status import build_update, status_proposal
from ripple.ingest.workbook import read_workbook
from ripple.store.updates import UpdateLog

from .generation import Workspace
from .pending_imports import STATUS_WORDING, Claim, Confirmed, PendingImports
from .workspace import Workspaces
from .workspace_errors import ImportChanged


@dataclass(frozen=True, slots=True)
class _Built:
    version: int
    update: StatusUpdate
    mapping: ConfirmedMapping


class StatusImports:
    def __init__(self, holder: Workspaces, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._holder = holder
        self._monotonic = monotonic
        # 확정을 마친 상태 올리기는 갱신 기록을 기억한다(응답을 잃은 화면이 다시 확정해도 같은 결과, 30분).
        # 시계는 부를 때마다 self._monotonic(검사가 바꿔 끼운다)
        self._imports: PendingImports[_Built, UpdateEvent] = PendingImports(STATUS_WORDING, lambda: self._monotonic())

    def stage(self, file_name: str, data: bytes) -> MappingProposal:
        context = self._holder.context
        with self._holder.reading():
            raw = read_workbook(data)
            plan = plan_file(raw, context.columns, context.fields)
        import_id = self._imports.add(file_name, raw)
        proposal = status_proposal(to_contract(plan, raw, import_id, file_name, 1, context.columns))
        return self._holder.with_remembered(proposal, raw, "status")

    def propose(self, import_id: str, overrides: MappingOverrides) -> MappingProposal:
        context = self._holder.context
        with self._holder.reading():
            draft = self._imports.override(import_id, overrides)
            plan = plan_file(draft.raw, context.columns, context.fields, draft.overrides)
        return status_proposal(to_contract(plan, draft.raw, import_id, draft.file_name, draft.version, context.columns))

    def submit(self, import_id: str, submission: MappingSubmission) -> StatusImportPreview:
        """확정 매핑으로 읽고 지금 지도에 적용했을 때를 미리 본다.

        읽기 오류·거부 항목·날짜 규칙 위반이 없을 때만 확정할 수 있게 둔다(그사이 지도가 바뀌면 확정 때 다시 본다).
        """
        with self._holder.reading():
            draft = self._imports.advance(import_id, submission.version)
            update, summary = build_update(draft.raw, draft.file_name, submission.mapping)
        version = draft.version
        if update is None:
            return StatusImportPreview(summary=summary, version=version)
        preview = self._holder.preview_update(update)
        dated = date_problems(update, self._holder.today())
        if dated:
            preview = preview.model_copy(update={"snapshot_id": None, "problems": (*dated, *preview.problems)})
        if preview.problems:
            return StatusImportPreview(summary=summary, version=version, preview=preview)
        # 확정은 이 미리보기의 지도에만(그사이 다른 사람이 지도를 바꿨으면 409 — 모르는 변경을 덮어쓰지 않게)
        update = update.model_copy(update={"base_snapshot_id": preview.base_snapshot_id})
        self._imports.keep(draft, _Built(version, update, submission.mapping))
        return StatusImportPreview(import_id=import_id, version=version, summary=summary, preview=preview)

    def confirm(
        self, import_id: str, version: int, expected: str, actor: Actor, log: UpdateLog
    ) -> tuple[Workspace, UpdateEvent]:
        """그 버전의 읽기 결과를 지금 지도에 적용한다. 기대 토큰이 다르면 StaleWorkspace, 그사이 지도가 바뀌어 거부
        항목이 생기면 UpdateRejected(둘 다 아무것도 바꾸지 않음). 성공하면 매핑을 기억한다.

        찾기 → 적용 → 기억을 가져오기 확정과 같이 잠금 하나 안에서 한다(PendingImports.confirm): 같은 확정이 동시에 와도
        적용·갱신 기록은 한 번이고, 적용 중에 끼어든 열 확인·제출은 확정이 끝난 뒤 '없는 상태 올리기'가 된다(받아 놓고
        버리지 않게). 잠금 순서는 이 잠금 → 작업 공간 전환 잠금(가져오기 확정은 다른 인스턴스라 엇갈리지 않음)."""

        def again(confirmed: Confirmed[UpdateEvent]) -> tuple[Workspace, UpdateEvent]:
            # 응답을 잃은 화면의 다시 보내기: 같은 결과(새 갱신 없음)
            current = self._holder.current
            assert current is not None
            return current, confirmed.result

        def apply(claim: Claim[_Built]) -> tuple[tuple[Workspace, UpdateEvent], UpdateEvent]:
            pending, built = claim.pending, claim.built
            dated = date_problems(built.update, self._holder.today())
            if dated:
                raise ImportChanged("날짜 기준 변경됨 · 다시 읽기 필요", pending.version)
            workspace, event = self._holder.apply_update(built.update, expected, actor, log)
            self._holder.remember_mapping(pending.raw, built.mapping, "status", pending.file_name)
            return (workspace, event), event

        return self._imports.confirm(import_id, version, again=again, apply=apply)
