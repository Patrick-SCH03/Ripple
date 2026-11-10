"""항목 조각 → 확인표 항목(순수 계산): 기존 해석기로 다시 읽고, 판단 계층 확률을 강조용으로 붙이고, 문제를 단다.

AI 추출 항목도 같은 길을 탄다 — 대상·규격·블록·종류는 해석기(지도 일치·판단 계층)만 채우고, AI 값은 해석기가 못
읽은 수치·강종·치수 종류 칸에만 'AI 추정'(FillMethod.LLM)으로 넣는다. 접수 경로의 문턱은 늘 꺼 두어(자동 진행 없음)
확률은 칸 강조에만 쓴다. AI 값 맞추기는 ai_values, 문제 달기는 item_issues에 있다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace

from ripple.contracts.assistant import OP_LABELS, OP_SLOTS, FillMethod, SlotFill, SourceSpan
from ripple.contracts.corrections import DecisionTrace
from ripple.contracts.decision import GATE_TOPICS, NONE_OPTION, DecisionConfig, Gate, GateKind
from ripple.contracts.domain import Part
from ripple.contracts.intake import (
    CANDIDATES_SHOWN,
    MAX_FRAGMENT_CHARS,
    AiReading,
    Extractor,
    IntakeIssue,
    IntakeIssueCode,
    IntakeItem,
    TargetCandidate,
)
from ripple.contracts.lexicon import Lexicon
from ripple.decide.router import decide_unit
from ripple.nl.draft import Proposal
from ripple.nl.pipeline import Fixed, Models, Reading, read
from ripple.nl.vocab import MapVocabulary

from .ai_values import with_ai
from .item_issues import dedupe, issue, revision_issues, slot_issues

CALIBRATION_NOTE = "합성 문장 기준 보정(실제 회사 문서로는 확인 전) — 확률은 강조에만 사용"
UNSUPPORTED_OP = "unsupported"
"""AI가 연산 8종 밖이라고 판단한 항목의 연산 이름."""

UNSUPPORTED = re.compile(
    r"각장|용접\s*(?:사이즈|크기|치수)|케이블|전선|배선|트레이|(?<!선행)(?<!블록)도장|페인트|도료|코팅|덕트|조명|"
    r"단열|보온|난간|사다리"
)
"""연산 8종(두께·강종·치수·부재 추가·삭제·배관 경로·장비 사양·관통부)으로 나타낼 수 없는 변경의 단서. 이 단서가
있으면 해석기가 억지로 8종 중 하나로 읽어도 '지원 안 함'으로 둔다(용접 각장을 판 두께로 읽는 오류를 막는다)."""


@dataclass(frozen=True, slots=True)
class Piece:
    """항목 후보 조각(문서 위치)과 그 조각을 낸 쪽."""

    start: int
    end: int
    text: str
    extractor: Extractor
    ai: AiReading | None = None
    issues: tuple[IntakeIssue, ...] = ()  # 조각을 만들 때 생긴 문제(AI 검증 실패, AI가 안 뽑은 줄)


@dataclass(frozen=True, slots=True)
class ReadContext:
    ship_ids: tuple[str, ...]
    vocab: MapVocabulary
    lexicon: Lexicon
    models: Models
    decision: DecisionConfig
    drawings: Mapping[str, frozenset[str]]  # 도면 번호 → 지도에 있는 개정들


@dataclass(frozen=True, slots=True)
class ReadOutcome:
    """항목과 그 항목 판단의 재보정 자료(서버에만 둔다 — 화면 응답에는 안 보낸다)."""

    item: IntakeItem
    traces: tuple[DecisionTrace, ...] = ()


def read_piece(piece: Piece, item_id: str, ctx: ReadContext) -> ReadOutcome | None:
    """조각 하나를 항목으로. 변경 단서가 없는 규칙 조각(인사말·서명 등)은 None."""
    text, issues = _clipped(piece)
    source = SourceSpan(start=piece.start, end=piece.start + len(text), text=text)

    def bare(problem: IntakeIssue, traces: tuple[DecisionTrace, ...] = ()) -> ReadOutcome:
        """초안 없는 항목(지원 안 함·읽지 못함): 문제만 달고 빼거나 비서로 넘기게 한다."""
        item = IntakeItem(
            item_id=item_id, source=source, extractor=piece.extractor, issues=(*issues, problem), ai=piece.ai
        )
        return ReadOutcome(item, traces)

    unsupported = _unsupported_issue(text, piece.ai)
    if unsupported is not None:
        return bare(unsupported)
    try:
        reading, rule_op = _read(text, ctx, piece.ai)
    except ValueError as error:  # 해석기 계약 위반(예: 너무 긴 조각) — 버리지 않고 읽지 못함으로
        return bare(issue(IntakeIssueCode.UNREADABLE, f"이 조각 읽기 실패 · {error}"[:300]))
    if piece.extractor is Extractor.RULE and not _substantive(reading):
        return None
    proposal = reading.proposal
    draft = proposal.draft
    if draft.op is None:
        unreadable = issue(IntakeIssueCode.UNREADABLE, "변경 종류 읽기 실패 — 빼거나 비서로 넘기기")
        return bare(unreadable, _traces(reading, {}, proposal.ready))
    probabilities = _probabilities(reading, ctx)
    candidates = _candidates(reading, ctx, probabilities, str(draft.op.value))
    if rule_op is not None:
        issues.append(
            issue(
                IntakeIssueCode.VALUE_UNCERTAIN,
                f"변경 종류는 AI 판단(규칙은 '{OP_LABELS.get(rule_op, rule_op)}'로 해석) — 맞는지 확인 필요",
                "op",
            )
        )
    if piece.ai is not None:
        draft, ai_issues = with_ai(draft, piece.ai)
        issues.extend(ai_issues)
    issues.extend(slot_issues(proposal, draft, candidates))
    issues.extend(revision_issues(text, ctx.drawings))
    item = IntakeItem(
        item_id=item_id,
        source=source,
        extractor=piece.extractor,
        draft=draft,
        slots=draft.specs(),
        candidates=candidates,
        issues=dedupe(issues),
        ai=piece.ai,
    )
    return ReadOutcome(item, _traces(reading, probabilities, proposal.ready))


def _clipped(piece: Piece) -> tuple[str, list[IntakeIssue]]:
    """조각 글(상한을 넘으면 앞부분만)과 조각에 이미 붙은 문제(+잘림)."""
    issues = list(piece.issues)
    if len(piece.text) <= MAX_FRAGMENT_CHARS:
        return piece.text, issues
    message = f"조각이 길어 앞 {MAX_FRAGMENT_CHARS}자까지만 반영 · 나머지는 원문에서 확인"
    return piece.text[:MAX_FRAGMENT_CHARS], [*issues, issue(IntakeIssueCode.TRUNCATED, message)]


def _unsupported_issue(text: str, ai: AiReading | None) -> IntakeIssue | None:
    """연산 8종 밖(규칙 단서나 AI 판단)이면 '지원 안 함' 문제."""
    unsupported = UNSUPPORTED.search(text)
    if not unsupported and (ai is None or ai.op != UNSUPPORTED_OP):
        return None
    cue = f"('{unsupported.group(0)}')" if unsupported else "(AI 판단)"
    return issue(
        IntakeIssueCode.UNSUPPORTED_OP,
        f"지원하지 않는 변경{cue} · 계산 대상은 두께·강종·치수·부재 추가·삭제·배관 경로·장비 사양·관통부 — "
        "빼기 필요(지원하는 변경을 잘못 읽었으면 AI 비서에 따로 입력)",
    )


def _read(text: str, ctx: ReadContext, ai: AiReading | None) -> tuple[Reading, str | None]:
    """해석기로 읽는다. AI가 연산 8종 중 하나로 읽었는데 규칙과 다르면(한 조각에 두 변경이 섞인 경우 등) AI 연산으로
    다시 읽고 연산 칸을 'AI 추정'으로 표시한다. 두 번째 값은 규칙이 읽은 연산(달랐을 때만)."""
    reading = read(text, ctx.ship_ids, ctx.vocab, ctx.lexicon, ctx.models)
    rule_op = reading.proposal.draft.op
    if ai is None or ai.op not in OP_SLOTS or (rule_op is not None and rule_op.value == ai.op):
        return reading, None
    reading = read(text, ctx.ship_ids, ctx.vocab, ctx.lexicon, ctx.models, Fixed(op=ai.op))
    draft = reading.proposal.draft
    if draft.op is not None:
        relabeled = draft.model_copy(update={"op": SlotFill(value=draft.op.value, method=FillMethod.LLM)})
        reading = replace(reading, proposal=Proposal(draft=relabeled, issues=reading.proposal.issues))
    return reading, None if rule_op is None else str(rule_op.value)


def _substantive(reading: Reading) -> bool:
    interp = reading.interp
    return bool(interp.op_cues or interp.refs.mentions or interp.values or interp.grades or interp.refs.specs)


def _candidates(
    reading: Reading, ctx: ReadContext, calibrated: Mapping[str, Mapping[str, float]], op: str | None = None
) -> tuple[TargetCandidate, ...]:
    """첫 대상 질문의 상위 후보(확률 순). 보정 산출물이 없으면 점수 순·확률 없이."""
    if not reading.targets:
        return ()
    target = reading.targets[0]
    probabilities = calibrated.get(target.posed.question.question_id)
    ranking = probabilities if probabilities is not None else target.scores
    ordered = sorted((k for k in ranking if k != NONE_OPTION), key=lambda k: (-ranking[k], k))
    out = []
    for part_id in ordered[:CANDIDATES_SHOWN]:
        entry = ctx.vocab.parts.get(part_id)
        if entry is None:
            continue
        code = entry.block_code or entry.part.block_id.split(":")[-1]
        probability = None if probabilities is None else round(probabilities[part_id], 4)
        label = f"{code} {entry.part.name}{_now(entry.part, op)}"
        out.append(TargetCandidate(part_id=part_id, label=label, probability=probability))
    return tuple(out)


def _now(part: Part, op: str | None) -> str:
    """후보 이름 뒤 지도의 지금 값(문서에 적은 지금 값과 사람이 견줘 보게 — 대상을 못 정하면 '지금 값 다름'을 낼 수
    없어서). 이 연산에 지금 값 칸이 없으면 빈 글."""
    if op == "thickness" and part.thickness_mm is not None:
        return f" · 지금 {part.thickness_mm:g}mm"
    if op == "grade" and part.grade:
        return f" · 지금 {part.grade}"
    if op == "equipment_spec" and part.spec_id:
        return f" · 지금 {part.spec_id}"
    return ""


def _probabilities(reading: Reading, ctx: ReadContext) -> dict[str, dict[str, float]]:
    """요청 문 판단의 보정 확률(문턱 끔 — 자동 진행 없음). 보정 산출물이 없으면 빈 사전."""
    decision = ctx.decision
    calibrations = {t.topic: t for t in decision.topics if t.topic in GATE_TOPICS[GateKind.REQUEST]}
    if len(calibrations) < len(GATE_TOPICS[GateKind.REQUEST]):
        return {}
    gate = Gate(kind=GateKind.REQUEST, auto_threshold=None, n_units=0, split="-")
    items = [(d.posed.question, d.scores) for d in reading.decisions()]
    answers = decide_unit(items, calibrations, gate, decision.targets.max_choices, decision.version, ready=False)
    return {a.question_id: dict(a.probabilities) for a in answers}


def _traces(
    reading: Reading, probabilities: Mapping[str, Mapping[str, float]], ready: bool
) -> tuple[DecisionTrace, ...]:
    """요청 문 판단(연산·대상 부재)마다 선택지·특징 값·보정 확률 — 사람이 고른 값과 함께 수정 기록에 남긴다."""
    out = []
    for scored in reading.decisions():
        question = scored.posed.question
        features = {o: dict(scored.posed.features[o]) for o in question.option_ids}
        out.append(
            DecisionTrace(
                topic=question.topic.value,
                question_id=question.question_id,
                options=question.option_ids,
                features=features,
                probabilities=dict(probabilities.get(question.question_id, {})),
                ready=ready,
            )
        )
    return tuple(out)
