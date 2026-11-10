"""문서 접수 조율(docs/input.md(문서 접수)): AI 추출(합성 모드) + 규칙 분할 → 확인표 제안 → 사람 확정 → 분석 + 수정
기록.

순수 계산은 ripple.intake가 한다. 여기서는 외부 모델 호출(데이터 모드 경계 Guarded 뒤 — intake_extract), 제안 보관(지도
세대마다 새로 — 지도가 바뀌면 이전 제안은 찾을 수 없다), 엑셀 변경 리스트를 문서로 바꾸기, 수정 기록 줄 만들기
(intake_records)를 맡는다. 요청자 신원(Actor)은 intake_types에 있다(서버·검사는 여기서 import한다).
"""

from __future__ import annotations

import re
import secrets
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.assistant import OP_LABELS, ChangeDraft
from ripple.contracts.change import ChangeOp, ChangeRequest, SourceDocument, SourceKind
from ripple.contracts.corrections import CorrectionEvent, DecisionTrace
from ripple.contracts.domain import DataMode
from ripple.contracts.intake import (
    MAX_DOCUMENT_CHARS,
    ExistingEcn,
    IntakeConfirmation,
    IntakeProposal,
    IntakeResult,
    ItemProblem,
)
from ripple.engine.analyze import analyze
from ripple.engine.validate import RequestError, validate_request
from ripple.intake.assemble import CALIBRATION_NOTE, ReadContext
from ripple.intake.build import ai_pieces, build_items, merge
from ripple.intake.confirm import confirm
from ripple.intake.ecn_ref import ecn_id_for, same_ref
from ripple.intake.segment import normalize_document, read_header, segments
from ripple.llm.base import Guarded
from ripple.store.ttl import TtlStore

from .intake_extract import extract_items
from .intake_records import correction_events
from .intake_types import Actor
from .resources import AssistantResources

__all__ = [
    "Actor",
    "ExistingLookup",
    "IntakeError",
    "IntakeProblems",
    "IntakeService",
    "rows_to_document",
]


class IntakeError(ValueError):
    """접수를 이어 갈 수 없음(없는 제안·지도 바뀜·문서 형식). status는 HTTP 상태."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class IntakeProblems(ValueError):
    """확정할 수 없음: 항목별 이유(422)."""

    def __init__(self, problems: Sequence[ItemProblem]) -> None:
        super().__init__("; ".join(p.message for p in problems))
        self.problems = tuple(problems)


@dataclass(slots=True)
class Stored:
    proposal: IntakeProposal
    traces: dict[str, tuple[DecisionTrace, ...]]
    model: str | None
    existing: ExistingEcn | None = None
    created: datetime = field(default_factory=lambda: datetime.now(UTC))


ExistingLookup = Callable[[str], ExistingEcn | None]


class IntakeService:
    def __init__(
        self, resources: AssistantResources, llm: Guarded | None, store: TtlStore[Stored] | None = None
    ) -> None:
        self.resources = resources
        self.llm = llm
        self.store: TtlStore[Stored] = store or TtlStore()
        drawings: dict[str, set[str]] = defaultdict(set)
        for drawing in resources.snapshot.drawings:
            drawings[drawing.drawing_no].add(drawing.revision)
        self._drawings = {k: frozenset(v) for k, v in drawings.items()}

    # ---------- 제안 ----------

    def propose(
        self, text: str, ship_ids: tuple[str, ...], existing: ExistingLookup, kind: SourceKind = SourceKind.TEXT
    ) -> IntakeProposal:
        document = normalize_document(text).strip("\n")
        if not document.strip():
            raise IntakeError(422, "빈 문서")
        if len(document) > MAX_DOCUMENT_CHARS:
            raise IntakeError(422, f"문서 {MAX_DOCUMENT_CHARS:,}자 초과 — 나눠서 입력")
        unknown = sorted(set(ship_ids) - set(self.resources.vocab.ship_ids))
        if unknown:
            raise IntakeError(422, f"지도에 없는 호선 · {', '.join(unknown)}")
        header, header_lines = read_header(document)
        rule = segments(document, header_lines)
        raw, problems, model = extract_items(self.llm, document, rule, self.resources)
        pieces, ai_problems = ai_pieces(document, raw, rule) if raw else ([], [])
        ctx = ReadContext(
            ship_ids=ship_ids,
            vocab=self.resources.vocab,
            lexicon=self.resources.lexicon,
            models=self.resources.models,
            decision=self.resources.decision,
            drawings=self._drawings,
        )
        items, item_problems, traces = build_items(merge(rule, pieces, document), ctx)
        proposal_id = f"IN-{secrets.token_hex(6)}"
        ecn_id = ecn_id_for(header.ecn_ref, document)
        found = existing(ecn_id) if header.ecn_ref else None
        proposal = IntakeProposal(
            proposal_id=proposal_id,
            snapshot_id=self.resources.snapshot.snapshot_id,
            data_mode=self.resources.data_mode,
            kind=kind,
            document=document,
            header=header,
            items=items,
            extractor="rule+llm" if pieces else "rule",
            problems=(*problems, *ai_problems, *item_problems),
            ecn_id=ecn_id,
            existing=found,
            calibration_note=CALIBRATION_NOTE,
        )
        self.store.put(proposal_id, Stored(proposal, traces, model if pieces else None, found))
        return proposal

    def propose_rows(
        self, rows: Sequence[Sequence[object]], ship_ids: tuple[str, ...], existing: ExistingLookup
    ) -> IntakeProposal:
        """변경 리스트 엑셀(첫 행 = 머리글) → 한 행 한 줄 문서 → propose."""
        return self.propose(rows_to_document(rows), ship_ids, existing, SourceKind.XLSX)

    # ---------- 확정 ----------

    def confirm(self, confirmation: IntakeConfirmation, actor: Actor) -> tuple[IntakeResult, list[CorrectionEvent]]:
        """확정은 제안마다 한 번: 꺼내서 처리하고, 확정하지 못하면 되돌려 둔다(다시 고쳐 확정할 수 있게). 같은 제안을
        두 번 확정해 수정 기록이 두 번 쌓이던 것을 막는다."""
        stored = self.store.pop(confirmation.proposal_id)
        if stored is None:
            raise IntakeError(409, "제안 없음(이미 확정됨, 지도 바뀜 또는 2시간 지남) · 문서 다시 입력")
        try:
            return self._confirm(stored, confirmation, actor)
        except BaseException:
            self.store.put(confirmation.proposal_id, stored)
            raise

    def _confirm(
        self, stored: Stored, confirmation: IntakeConfirmation, actor: Actor
    ) -> tuple[IntakeResult, list[CorrectionEvent]]:
        proposal = stored.proposal
        confirmed = confirm(proposal, confirmation.decisions, self.resources.vocab)
        if confirmed.problems:
            raise IntakeProblems(confirmed.problems)
        header = confirmation.header
        ecn_id = self._ecn_id(proposal, stored.existing, confirmation)
        ops = tuple(op for _, op in confirmed.entries)
        title = (header.title or _default_title(confirmed.drafts.values()))[:200]
        context = confirmation.context
        try:
            change = ChangeRequest(
                ecn_id=ecn_id,
                title=title,
                ship_ids=tuple(dict.fromkeys(context.ship_ids)),  # 같은 호선 두 번은 하나로
                ops=ops,
                raw_text=self._raw_text(proposal, [i for i, _ in confirmed.entries]),
                requested_by=header.requested_by,
                requested_on=header.requested_on,
                source=SourceDocument(
                    kind=proposal.kind,
                    ecn_ref=header.ecn_ref,
                    revision=header.revision,
                    items=len(ops),
                    dropped=confirmed.dropped,
                ),
            )
            request = AnalysisRequest(
                change=change, as_of=context.as_of, confirm_on=context.confirm_on, horizon_days=context.horizon_days
            )
        except ValueError as error:  # 계약이 거절한 요청은 서버 오류(500)가 아니라 이유와 함께 422
            raise IntakeError(422, f"요청 생성 불가 · {error}"[:300]) from None
        problems = validate_request(self.resources.index, request)
        if problems:
            raise IntakeProblems(_attribute(self.resources, request, confirmed.entries, problems))
        try:
            result = analyze(self.resources.index, request, self.resources.rulebook, self.resources.params)
        except RequestError as error:
            raise IntakeProblems([ItemProblem(item_id=None, message=p) for p in error.problems]) from None
        outcome = IntakeResult(ecn_id=ecn_id, request=request, result=result, kept=len(ops), dropped=confirmed.dropped)
        events = correction_events(proposal, stored.traces, stored.model, confirmation, confirmed.drafts, actor)
        return outcome, events

    def _ecn_id(self, proposal: IntakeProposal, existing: ExistingEcn | None, confirmation: IntakeConfirmation) -> str:
        """사람이 원문 번호를 고쳤으면 언제나 그 번호로(제안 때 찾은 기존 설계변경·이어 가기 답은 옛 번호의 것이라 쓰지
        않는다). 앞뒤 공백·대소문자만 다르면 고친 것이 아니다.
        아니면 기존 설계변경을 이어 가거나 새 ID."""
        if not same_ref(confirmation.header.ecn_ref, proposal.header.ecn_ref):
            return ecn_id_for(confirmation.header.ecn_ref, proposal.document)
        if existing is None:
            return proposal.ecn_id
        if confirmation.continue_ecn:
            if not existing.can_continue:
                raise IntakeError(409, "실행·종료된 설계변경은 이어 가기 불가 — 새 설계변경으로 확정")
            return existing.ecn_id
        return f"{proposal.ecn_id[:55]}-{proposal.proposal_id[-6:]}"

    def _raw_text(self, proposal: IntakeProposal, kept: Sequence[str]) -> str:
        """합성 모드는 문서 원문, 실데이터 모드는 확정한 항목 조각만(문서 전문을 기록에 남기지 않는다)."""
        if proposal.data_mode is DataMode.SYNTHETIC:
            return proposal.document
        texts = {i.item_id: i.source.text for i in proposal.items}
        return "\n".join(texts[i] for i in kept)


_HEADER_SYNONYMS: dict[str, re.Pattern[str]] = {
    "target": re.compile(r"대상|부재|품번|위치|Part", re.I),
    "attribute": re.compile(r"항목|속성|구분|변경\s*내용|Attribute|Item", re.I),  # Item = 항목
    "before": re.compile(r"변경\s*전|현재|기존|Before|From|AS[\s-]?IS", re.I),
    "after": re.compile(r"변경\s*후|변경값|To\b|After|TO[\s-]?BE", re.I),
    "reason": re.compile(r"사유|이유|Reason", re.I),
}


def rows_to_document(rows: Sequence[Sequence[object]]) -> str:
    """변경 리스트 엑셀 → 문서. 머리글이 대상·항목·변경 전·변경 후를 알아보면 한 행을 한 문장으로, 아니면 칸을 이어
    붙인다(해석은 같은 접수 길을 탄다)."""
    if len(rows) < 2:
        raise IntakeError(422, "변경 리스트에 머리글과 행 필요")
    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    columns: dict[str, int] = {}
    for key, pattern in _HEADER_SYNONYMS.items():
        index = next((i for i, h in enumerate(header) if h and pattern.search(h) and i not in columns.values()), None)
        if index is not None:
            columns[key] = index
    lines = []
    for row in rows[1:]:
        cells = [str(c).strip() if c is not None else "" for c in row]

        def cell(key: str, cells: list[str] = cells) -> str:
            index = columns.get(key)
            return cells[index] if index is not None and index < len(cells) else ""

        target, after = cell("target"), cell("after")
        if target and after:
            before = cell("before")
            change = f"{before}에서 {after}로" if before else f"{after}로"
            line = f"{target} {cell('attribute')} {change} 변경".replace("  ", " ")
            if cell("reason"):
                line += f" ({cell('reason')})"
        else:
            line = " / ".join(c for c in cells if c)
        if line.strip():
            lines.append(line.strip())
    document = "\n".join(lines)
    if len(document) > MAX_DOCUMENT_CHARS:
        raise IntakeError(422, f"변경 리스트 {MAX_DOCUMENT_CHARS:,}자 초과 — 나눠서 올리기")
    return document


def _attribute(
    resources: AssistantResources,
    request: AnalysisRequest,
    entries: Sequence[tuple[str, ChangeOp]],
    problems: list[str],
) -> list[ItemProblem]:
    """문서 전체 검증 문제를 항목에 붙인다(그 연산 하나로 다시 검증해 같은 문제가 나오면 그 항목)."""
    out: list[ItemProblem] = []
    remaining = list(problems)
    for item_id, op in entries:
        single = request.model_copy(update={"change": request.change.model_copy(update={"ops": (op,)})})
        mine = set(validate_request(resources.index, single))
        for problem in [p for p in remaining if p in mine]:
            out.append(ItemProblem(item_id=item_id, message=problem))
            remaining.remove(problem)
    out.extend(ItemProblem(item_id=None, message=p) for p in remaining)
    return out


def _default_title(drafts: Iterable[ChangeDraft]) -> str:
    labels = []
    for draft in drafts:
        if draft.op is not None:
            labels.append(OP_LABELS.get(str(draft.op.value), str(draft.op.value)))
    unique = list(dict.fromkeys(labels))
    return f"문서 접수: {', '.join(unique[:3])}" + (" 등" if len(unique) > 3 else "") if unique else "문서 접수"
