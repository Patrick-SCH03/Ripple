"""문서 접수의 성질(docs/input.md(문서 접수), 가짜 모델·키·네트워크 없이).

- 분할·머리: 위치가 원문과 맞고, 머리 줄·인사말은 항목이 아니다.
- AI 항목: 원문 인용·숫자 검증, AI가 빠뜨린 줄도 보인다, 대상·지금 값 칸은 AI가 채우지 않는다.
- 지원 안 함(용접 각장·케이블)은 연산 8종으로 들어가지 않는다. 접수 경로는 자동 진행이 없다.
- 확정: 서버 검증(정하지 않은 항목·남은 문제·지도에 없는 부재·겹치는 변경), 고친 대상의 지금 값은 지도에서.
- 실데이터 모드: 외부 호출 0회, 기록 원문은 확정 조각만, 수정 기록에 원문 없음.
- 원문 문서 정보(source)는 분석 ID에 들어가지 않는다. 비서 초안만 모드는 분석하지 않는다.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime

from harness import Checker

from ripple.agent.flow import Assistant
from ripple.agent.intake import Actor, IntakeError, IntakeProblems, IntakeService, rows_to_document
from ripple.agent.resources import AssistantResources
from ripple.config.loaders import load_decision_config, load_lexicon, load_params, load_rulebook
from ripple.config.settings import Settings
from ripple.contracts.assistant import (
    Answer,
    AssistantSeed,
    AssistantTurnRequest,
    ChangeDraft,
    FillMethod,
    SlotFill,
    TurnContext,
    TurnState,
)
from ripple.contracts.corrections import CorrectionAction, CorrectionEvent, CorrectionOrigin
from ripple.contracts.domain import DataMode
from ripple.contracts.identity import normalized_request
from ripple.contracts.intake import (
    BLOCKING,
    ExistingEcn,
    Extractor,
    IntakeConfirmation,
    IntakeHeader,
    IntakeIssueCode,
    IntakeProposal,
    IntakeResult,
    ItemAction,
    ItemDecision,
    ItemProblem,
)
from ripple.contracts.records import ECN_ID_PATTERN
from ripple.engine.index import GraphIndex
from ripple.eval import intake_docs as e9
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.generator.nl import load_nl_lexicon
from ripple.intake.build import RawAiItem, ai_pieces, merge
from ripple.intake.ecn_ref import ecn_id_for, same_ref
from ripple.intake.segment import read_header, segments
from ripple.llm.base import Guarded, Schema
from ripple.llm.quota import acting_as, current_actor
from ripple.store.corrections import summarize
from ripple.store.ttl import TtlStore

CONTEXT = TurnContext(ship_ids=("S-001",), as_of=date(2026, 10, 20))
DOC = """ECN No. 2026-034
제목: 3번 탱크 구조 보강
요청자: 설계팀
일자: 2026-10-18
사유: 좌굴 방지

1. 3번 화물탱크 더블바텀 좌현 판 2, 5, 7번 판 두께 17T에서 20T로 변경
2) T31C 판 7 용접 각장 6에서 7mm로 변경
- 케이블 트레이 경로 변경 바랍니다
감사합니다.
"""


class FakeExtract:
    """문서 접수 추출 요청에 미리 정한 항목을 돌려준다(받은 프롬프트를 남긴다)."""

    name = "fake-extract"

    def __init__(self, items: list[dict[str, str]]) -> None:
        self.items = items
        self.prompts: list[str] = []

    def generate_json(self, prompt: str, schema: Schema, timeout_s: float) -> object:
        self.prompts.append(prompt)
        return {"items": self.items}


def _ai(span: str, op: str, target: str = "", before: str = "", after: str = "") -> dict[str, str]:
    return {"source_span": span, "op": op, "target": target, "before": before, "after": after, "reason": ""}


def run(c: Checker) -> None:
    settings = Settings.from_env({})
    snapshot = generate(load_config()).snapshot

    def resources(mode: DataMode) -> AssistantResources:
        return AssistantResources.build(
            snapshot,
            GraphIndex(snapshot),
            load_lexicon(settings.lexicon_path),
            load_decision_config(settings.decision_path),
            load_rulebook(settings.rules_path),
            load_params(settings.params_path),
            mode,
        )

    synthetic, real = resources(DataMode.SYNTHETIC), resources(DataMode.REAL)
    _segments(c)
    _ecn_ids(c)
    _rule_path(c, synthetic)
    _ai_path(c, synthetic)
    _confirmations(c, synthetic)
    _real_mode(c, real)
    _corrections(c)
    _drafted(c, synthetic)
    _ttl(c)
    _e9(c, synthetic, snapshot)
    _counterexamples(c, synthetic)


def _segments(c: Checker) -> None:
    c.section("문서 접수: 분할·머리 정보")
    header, lines = read_header(DOC)
    pieces = segments(DOC, lines)
    c.check(
        "머리 정보: 번호만 있는 줄·라벨 줄(제목·요청자·일자·사유)",
        header.ecn_ref == "2026-034"
        and header.title == "3번 탱크 구조 보강"
        and header.requested_on == date(2026, 10, 18)
        and header.reason == "좌굴 방지",
        header,
    )
    c.check("조각 위치가 원문과 같음", all(DOC[p.start : p.end] == p.text for p in pieces))
    c.check(
        "머리 줄은 조각이 아니고 글머리표·번호는 떼어 냄",
        not any("ECN" in p.text or "제목" in p.text for p in pieces)
        and any(p.text.startswith("3번 화물탱크") for p in pieces)
        and any(p.text.startswith("T31C") for p in pieces),
        [p.text for p in pieces],
    )
    mail = (
        "설계변경 2026-681 건 아래 내용 반영 부탁드립니다.\n"
        "1. 좌굴 방지 때문에 엔진룸 이중저 스티프너\n012 A으로 변경 바랍니다\n"
        "2. B31P 판 7 두께 15에서 17로 변경, 그리고 T31C 판 9 삭제\n"
        "※ 현장 확인 후 회신 바랍니다"
    )
    header2, lines2 = read_header(mail)
    texts = [p.text for p in segments(mail, lines2)]
    c.check(
        "설계변경 번호만 담은 안내 줄은 머리(번호를 읽고 항목에서 뺌)",
        header2.ecn_ref == "2026-681" and not any("2026-681" in t for t in texts),
        texts,
    )
    c.check(
        "번호 목록 안 표시 없는 줄은 앞 항목에 이어짐(줄바꿈으로 갈린 한 항목), 참고 줄(※)은 따로",
        "좌굴 방지 때문에 엔진룸 이중저 스티프너\n012 A으로 변경 바랍니다" in texts and texts[-1].startswith("※"),
        texts,
    )
    c.check(
        "', 그리고'로 이은 두 변경은 두 조각",
        "B31P 판 7 두께 15에서 17로 변경" in texts and "T31C 판 9 삭제" in texts,
        texts,
    )
    decimal = segments("12.5mm로 B31P 판 7 두께 변경\n1. T31C 판 9 삭제")
    c.check(
        "줄 머리의 소수('12.5mm')는 번호 글머리표로 떼지 않음, '1. '은 뗌",
        [p.text for p in decimal] == ["12.5mm로 B31P 판 7 두께 변경", "T31C 판 9 삭제"],
        [p.text for p in decimal],
    )
    revisions = {
        text: read_header(text)[0].revision
        for text in (
            "Review 요청: B31P 판 7 두께 변경",
            "REVIEW 부탁",
            "Revision B 반영",
            "ECN 2026-034 Rev.B",
            "rev 2",
        )
    }
    c.check(
        "본문의 'Review'·'REVIEW'는 개정이 아님, 'Revision B'·'Rev.B'·'rev 2'는 개정",
        revisions
        == {
            "Review 요청: B31P 판 7 두께 변경": None,
            "REVIEW 부탁": None,
            "Revision B 반영": "B",
            "ECN 2026-034 Rev.B": "B",
            "rev 2": "2",
        },
        revisions,
    )
    plain = "B31P 판 7 두께 15에서 17로\nT31C 판 9 두께 25로"
    c.check("목록 표시가 없는 문서는 줄을 합치지 않음", len(segments(plain)) == 2, [p.text for p in segments(plain)])
    table = "No | 변경 내용 | 비고\n1 | B31P 판 7 두께 15에서 17로 변경 | 긴급"
    cells = segments(table)
    c.check(
        "표 행은 칸마다(번호 칸·숫자 없는 머리 행은 뺌), 위치는 원문 그대로",
        [p.text for p in cells] == ["B31P 판 7 두께 15에서 17로 변경", "긴급"]
        and all(table[p.start : p.end] == p.text for p in cells),
        [p.text for p in cells],
    )


def _ecn_ids(c: Checker) -> None:
    c.section("문서 접수: 원문 번호 → 기록 ID")
    refs = ["2026-034", "ECN-2026-034", "설변-2026/034", "설변-2026/035", "ECN 2026 034", "가" * 200]
    ids = [ecn_id_for(r, "doc") for r in refs]
    c.check("기록 ID 꼴(64자 이하·허용 문자)", all(re.fullmatch(ECN_ID_PATTERN, i) for i in ids), ids)
    c.check("다른 원문 번호는 다른 ID(해시 접미)", len(set(ids)) == len(ids))
    c.check(
        "같은 번호는 같은 ID, 번호가 없으면 문서 기준",
        ecn_id_for("2026-034", "x") == ids[0] and ecn_id_for(None, "a") != ecn_id_for(None, "b"),
    )
    upper = "ECN-2026-A34"
    cased = [ecn_id_for(r, "x") for r in (upper, "ecn-2026-a34", " Ecn-2026-A34 ")]
    c.check(
        "같은 번호로 보는 것(same_ref: 앞뒤 공백·대소문자만 다름)은 같은 ID, 대문자 번호의 ID는 전과 같음",
        same_ref(upper, "ecn-2026-a34")
        and len(set(cased)) == 1
        and cased[0] == f"ECN-2026-A34-{hashlib.sha256(upper.encode()).hexdigest()[:6]}",
        cased,
    )


def _service(resources: AssistantResources, model: object | None = None) -> tuple[IntakeService, Guarded]:
    guard = Guarded(model, resources.data_mode)  # type: ignore[arg-type]
    return IntakeService(resources, llm=guard), guard


def _rule_path(c: Checker, resources: AssistantResources) -> None:
    c.section("문서 접수: 규칙 경로")
    service, _ = _service(resources)
    proposal = service.propose(DOC, ("S-001",), lambda _: None)
    texts = [i.source.text for i in proposal.items]
    c.check("AI 없으면 규칙 경로", proposal.extractor == "rule")
    c.check(
        "항목 위치가 정규화한 원문과 같음",
        all(proposal.document[i.source.start : i.source.end] == i.source.text for i in proposal.items),
    )
    c.check("인사말은 항목이 아님", not any("감사" in t for t in texts), texts)
    unsupported = [i for i in proposal.items if any(x.code is IntakeIssueCode.UNSUPPORTED_OP for x in i.issues)]
    c.check(
        "용접 각장·케이블은 '지원 안 함'(초안 없음 — 판 두께로 들어가지 않음)",
        len(unsupported) == 2 and all(i.draft is None for i in unsupported),
        [(i.source.text, [x.code.value for x in i.issues]) for i in proposal.items],
    )
    main = next(i for i in proposal.items if i.source.text.startswith("3번 화물탱크"))
    c.check(
        "판 3장 두께 변경: 대상(판단)·지금 값(지도)·바꿀 값(규칙)",
        main.draft is not None
        and main.draft.slots["part_ids"].value == ("S-001:B31P-PL-002", "S-001:B31P-PL-005", "S-001:B31P-PL-007")
        and main.draft.slots["from_mm"].method is FillMethod.MAP
        and main.draft.slots["to_mm"].value == 20.0,
    )
    c.check(
        "후보는 최대 3개, 확률은 0~1(문턱 끈 보정 — 자동 진행 없음)",
        all(len(i.candidates) <= 3 for i in proposal.items)
        and all(x.probability is None or 0 <= x.probability <= 1 for i in proposal.items for x in i.candidates),
    )
    c.check("기록 ID는 원문 번호로", proposal.ecn_id == ecn_id_for("2026-034", proposal.document))
    dated = service.propose("B31P 판 7 두께 2026-10-30 변경", ("S-001",), lambda _: None).items
    c.check(
        "보통 범위 밖 추정 값(날짜 2026을 두께로)은 '맞음'으로 넘기지 못하게 막음",
        len(dated) == 1 and any(x.blocking and x.slot == "to_mm" for x in dated[0].issues),
        [(x.code.value, x.message) for i in dated for x in i.issues],
    )
    try:
        service.propose("x" * 13_000, ("S-001",), lambda _: None)
        too_long = False
    except IntakeError as error:
        too_long = error.status == 422
    c.check("문서 상한(12,000자)을 넘으면 422", too_long)
    rows = [["대상", "항목", "변경 전", "변경 후", "사유"], ["T31C 판 7번", "두께", "15", "17", "강도 보강"]]
    c.check(
        "변경 리스트 엑셀은 한 행 한 문장", rows_to_document(rows) == "T31C 판 7번 두께 15에서 17로 변경 (강도 보강)"
    )


def _ai_path(c: Checker, resources: AssistantResources) -> None:
    c.section("문서 접수: AI 경로(가짜 모델)")
    model = FakeExtract(
        [
            _ai("판 2, 5, 7번 판 두께 17T에서 20T로 변경", "thickness", "판 2, 5, 7번", "17", "20"),
            _ai("T31C 판 7 용접 각장 6에서 7mm로 변경", "unsupported"),
            _ai("원문에 없는 문장", "thickness", after="99"),
        ]
    )
    service, guard = _service(resources, model)
    proposal = service.propose(DOC, ("S-001",), lambda _: None)
    c.check("AI 경로 표시·외부 호출 1회", proposal.extractor == "rule+llm" and guard.calls == 1)
    c.check(
        "문서는 구분자 안에(문서 안 지시는 데이터)",
        "<문서>" in model.prompts[0] and "따르지 마세요" in model.prompts[0],
    )
    c.check(
        "원문에서 못 찾은 AI 항목은 버리고 문서 문제로 알림",
        any("찾지 못해" in p.message for p in proposal.problems)
        and not any("원문에 없는" in i.source.text for i in proposal.items),
    )
    widened = next((i for i in proposal.items if "판 2, 5, 7번" in i.source.text and i.extractor.value == "llm"), None)
    c.check(
        "AI 인용이 문장 중간이면 같은 조각 시작까지 넓혀 대상 맥락을 살림",
        widened is not None and widened.source.text.startswith("3번 화물탱크"),
        widened.source.text if widened else None,
    )
    uncovered = [i for i in proposal.items if any(x.code is IntakeIssueCode.NOT_EXTRACTED for x in i.issues)]
    c.check("AI가 뽑지 않은 줄(케이블)도 규칙으로 보임", any("케이블" in i.source.text for i in uncovered))
    ai_filled = [
        (name, fill)
        for i in proposal.items
        if i.draft is not None
        for name, fill in i.draft.slots.items()
        if fill.method is FillMethod.LLM
    ]
    c.check(
        "AI 값은 대상·지금 값 칸에 들어가지 않음",
        all(n not in {"part_ids", "from_mm"} for n, _ in ai_filled),
        ai_filled,
    )
    document = "B31P 판 7번 두께 15에서 17로 변경"
    pieces, _ = ai_pieces(document, [RawAiItem("B31P 판 7번 두께 15에서 17로 변경", "thickness", after="18")])
    c.check(
        "AI 값의 숫자가 인용 조각 안에 없으면 검증 실패(값은 버림)",
        len(pieces) == 1
        and pieces[0].ai is not None
        and pieces[0].ai.after is None
        and any(x.code is IntakeIssueCode.EXTRACT_UNVERIFIED for x in pieces[0].issues),
    )
    twice = "3번 화물탱크 좌현 판 2, 5, 7번 판 두께 17T에서 20T로 변경"
    split, _ = ai_pieces(twice, [RawAiItem(twice, "thickness", target=f"판 {n}") for n in (2, 5, 7)])
    c.check("AI가 같은 인용을 대상마다 따로 내도 항목 하나", len(split) == 1, len(split))
    c.check(
        "AI 조각이 없으면 규칙 조각에 'AI가 안 뽑음' 표시 없음",
        all(not p.issues for p in merge(segments(document), [])),
    )
    tail = "B31P 판 7번 두께 변경 15에서 17로 (도면 DWG-B31P-H01 Rev.C)"
    cut, _ = ai_pieces(tail, [RawAiItem("B31P 판 7번 두께 변경", "thickness", after="17")], segments(tail))
    c.check(
        "AI 인용 뒤 꼬리(도면 개정)도 같은 조각 끝까지 넓히고, 값 숫자는 넓힌 조각에서 확인",
        len(cut) == 1
        and cut[0].text == tail
        and not cut[0].issues
        and cut[0].ai is not None
        and cut[0].ai.after == "17",
        cut,
    )
    two = "B31P 판 7 두께 15에서 17로 변경함. T31C 밸브 V-1 삭제"
    spans, _ = ai_pieces(two, [RawAiItem(two, "thickness", after="17")], segments(two))
    merged = merge(segments(two), spans, two)
    c.check(
        "AI 인용이 변경 두 줄을 덮으면 제 줄에서 자르고 둘째 줄은 'AI가 뽑지 않은 줄'로 남김",
        [p.extractor for p in merged] == [Extractor.LLM, Extractor.RULE]
        and "밸브" not in merged[0].text
        and "밸브" in merged[1].text
        and any(x.code is IntakeIssueCode.NOT_EXTRACTED for x in merged[1].issues),
        [(p.extractor.value, p.text) for p in merged],
    )
    row = "| 1 | B31P 판 7번 판 두께 변경 | 15mm → 17mm |"
    quote = "B31P 판 7번 판 두께 변경 | 15mm → 17mm"
    cells, _ = ai_pieces(row, [RawAiItem(quote, "thickness", after="17")], segments(row))
    clause = "B31P 판 7 두께 변경; 15mm에서 17mm로 증후"
    valued, _ = ai_pieces(clause, [RawAiItem(clause, "thickness", after="17")], segments(clause))
    c.check(
        "대상 말 없는 다음 칸·절(값 칸 '15mm → 17mm', 값 절 '…로 증후')은 그대로 덮어 값을 확인",
        len(cells) == 1
        and "17mm" in cells[0].text
        and cells[0].ai is not None
        and cells[0].ai.after == "17"
        and len(valued) == 1
        and valued[0].text == clause
        and valued[0].ai is not None
        and valued[0].ai.after == "17",
        (cells, valued),
    )

    def disagree(text: str, after: str) -> bool:
        model = FakeExtract([_ai(text, "thickness", after=after)])
        found = _service(resources, model)[0].propose(text, ("S-001",), lambda _: None)
        return any(x.code is IntakeIssueCode.LLM_RULE_DISAGREE for i in found.items for x in i.issues)

    c.check(
        "증감 표현('1mm 감소')·규격을 AI가 값 칸에 내도 규칙 계산값과 견주지 않음(정확히 읽은 항목을 막지 않게)",
        not disagree("B31P 판 7번 두께 1mm 감소", "1mm") and not disagree("B31P 판 7번 두께 17로", "HP280x12-AH36"),
    )
    c.check(
        "증감 말 '올리기·내리기·키우기'도 '올려'처럼 견주지 않음(해석기 RELATIVE_WORDS와 같은 말)",
        not disagree("B31P 판 7번 두께 15에서 17로 2mm 올리기", "2mm")
        and not disagree("B31P 판 7번 두께 17에서 15로 2mm 내리기", "2mm"),
    )
    c.check(
        "적힌 값끼리 다르게 읽으면('15에서 17로'를 AI는 15) 불일치로 막음",
        disagree("B31P 판 7번 두께 15에서 17로", "15"),
    )


def _confirmations(c: Checker, resources: AssistantResources) -> None:
    c.section("문서 접수: 확정 검증")
    service, _ = _service(resources)
    actor = Actor(login_id="tester")
    doc = "B31P 판 7번 두께 17에서 20으로 변경\nB31P 판 7번 두께 17에서 20으로 변경\n판 9번 두께 25로"
    proposal = service.propose(doc, ("S-001",), lambda _: None)
    c.check(
        "같은 변경 두 번이면 뒤 항목에 '같은 변경' 문제",
        any(x.code is IntakeIssueCode.DUPLICATE for i in proposal.items for x in i.issues),
    )
    header = IntakeHeader()

    def attempt(decisions: list[ItemDecision]):  # type: ignore[no-untyped-def]
        try:
            return list(  # 성공은 [결과, 수정 기록], 실패는 문제 튜플
                service.confirm(
                    IntakeConfirmation(
                        proposal_id=proposal.proposal_id, context=CONTEXT, header=header, decisions=tuple(decisions)
                    ),
                    actor,
                )
            )
        except IntakeProblems as error:
            return error.problems

    missing = attempt([ItemDecision(item_id=proposal.items[0].item_id, action=ItemAction.ACCEPT)])
    c.check(
        "정하지 않은 항목이 있으면 확정 불가", isinstance(missing, tuple) and any(p.item_id == "I2" for p in missing)
    )
    blocked = next(
        i
        for i in proposal.items
        if i.blocking and any(x.code in BLOCKING - {IntakeIssueCode.DUPLICATE} for x in i.issues)
    )
    accepted_blocked = attempt(
        [
            ItemDecision(item_id=i.item_id, action=ItemAction.ACCEPT if i is blocked else ItemAction.DROP)
            for i in proposal.items
        ]
    )
    c.check("막는 문제가 남은 항목은 '맞음'으로 확정 불가", isinstance(accepted_blocked, tuple))
    third = proposal.items[2]
    same = resources.vocab.parts["S-001:T31C-PL-009"].part.thickness_mm
    unchanged = attempt(
        [
            ItemDecision(item_id="I1", action=ItemAction.DROP),
            ItemDecision(item_id="I2", action=ItemAction.DROP),
            ItemDecision(
                item_id=third.item_id,
                action=ItemAction.EDIT,
                part_ids=("S-001:T31C-PL-009",),
                values={"to_mm": float(same or 1)},
            ),
        ]
    )
    c.check(
        "고른 부재의 지금 값이 바꿀 값과 같으면 '빠진 칸'이 아니라 그 이유로 거절",
        isinstance(unchanged, tuple) and any("변경 전과 후가 같음" in p.message for p in unchanged),
        unchanged,
    )
    edited = attempt(
        [
            ItemDecision(item_id="I1", action=ItemAction.ACCEPT),
            ItemDecision(item_id="I2", action=ItemAction.DROP),
            ItemDecision(item_id=third.item_id, action=ItemAction.EDIT, part_ids=("S-001:T31C-PL-009",)),
        ]
    )
    ok = isinstance(edited, list)
    c.check("고친 대상(T31C 판 9)으로 확정·분석", ok, edited)
    proposal = service.propose(doc, ("S-001",), lambda _: None)  # 확정한 제안은 한 번만 쓴다
    if ok:
        result, events = edited
        thickness = result.request.change.ops[-1]
        part = resources.vocab.parts["S-001:T31C-PL-009"].part
        c.check(
            "고친 대상의 지금 두께는 지도 값",
            getattr(thickness, "from_mm", None) == part.thickness_mm and getattr(thickness, "to_mm", None) == 25.0,
            thickness,
        )
        c.check(
            "원문 문서 정보는 기록용(분석 ID 정규형에 없음)",
            result.request.change.source is not None
            and result.request.change.source.items == 2
            and result.request.change.source.dropped == 1
            and "source" not in normalized_request(result.request),
        )
        bare = result.request.model_copy(update={"change": result.request.change.model_copy(update={"source": None})})
        c.check("source가 있든 없든 정규형이 같음", normalized_request(bare) == normalized_request(result.request))
        c.check(
            "수정 기록: 항목마다 결정, 제안에 없던 대상을 고르면 ADD, 뺀 항목은 DROP, 합성 모드는 원문 조각",
            any(e.slot == "part_ids" and e.action in (CorrectionAction.ADD, CorrectionAction.EDIT) for e in events)
            and any(e.item == "I2" and e.action is CorrectionAction.DROP for e in events)
            and all(e.text for e in events),
        )
    unknown = attempt(
        [
            ItemDecision(item_id="I1", action=ItemAction.DROP),
            ItemDecision(item_id="I2", action=ItemAction.DROP),
            ItemDecision(item_id=third.item_id, action=ItemAction.EDIT, part_ids=("S-001:NOPE-PL-001",)),
        ]
    )
    c.check("지도에 없는 부재로 고치면 확정 불가", isinstance(unknown, tuple))
    try:
        service.confirm(
            IntakeConfirmation(
                proposal_id="IN-none",
                context=CONTEXT,
                header=header,
                decisions=(ItemDecision(item_id="I1", action=ItemAction.DROP),),
            ),
            actor,
        )
        gone = False
    except IntakeError as error:
        gone = error.status == 409
    c.check("없는(지도가 바뀐) 제안은 409", gone)


def _real_mode(c: Checker, resources: AssistantResources) -> None:
    c.section("문서 접수: 실데이터 모드")
    model = FakeExtract([_ai("B31P 판 7번 두께 17에서 20으로 변경", "thickness")])
    service, guard = _service(resources, model)
    proposal = service.propose("안녕하세요\nB31P 판 7번 두께 17에서 20으로 변경", ("S-001",), lambda _: None)
    c.check("외부 모델 호출 0회·규칙 경로", guard.calls == 0 and not model.prompts and proposal.extractor == "rule")
    item = proposal.items[0]
    result, events = service.confirm(
        IntakeConfirmation(
            proposal_id=proposal.proposal_id,
            context=CONTEXT,
            header=IntakeHeader(),
            decisions=(ItemDecision(item_id=item.item_id, action=ItemAction.ACCEPT),),
        ),
        Actor(login_id="tester"),
    )
    c.check("기록 원문은 확정한 조각만(문서 전문 아님)", result.request.change.raw_text == item.source.text)
    c.check("수정 기록에 원문 없음", bool(events) and all(e.text is None for e in events))


def _corrections(c: Checker) -> None:
    c.section("문서 접수: 수정 기록 집계")
    now = datetime.now(UTC)

    def event(action: CorrectionAction, demo: bool = False, slot: str = "to_mm") -> CorrectionEvent:
        return CorrectionEvent(
            at=now,
            actor="a",
            demo=demo,
            data_mode=DataMode.SYNTHETIC,
            origin=CorrectionOrigin.INTAKE,
            ref="IN-1",
            item="I1",
            slot=slot,
            action=action,
            method="rule",
        )

    summary = summarize(
        [event(CorrectionAction.ACCEPT), event(CorrectionAction.EDIT), event(CorrectionAction.EDIT, demo=True)]
    )
    rate = next(r for r in summary.rates if r.key == "slot:to_mm")
    c.check("체험·개발 행은 빼고 개수만", summary.excluded == 1 and summary.rows == 2)
    c.check("고친 비율 = 고침 ÷ (맞음 + 고침)", rate.edit_rate == 0.5)
    try:
        CorrectionEvent(
            at=now,
            actor="a",
            data_mode=DataMode.REAL,
            origin=CorrectionOrigin.INTAKE,
            ref="IN-1",
            slot="item",
            action=CorrectionAction.ACCEPT,
            text="원문",
        )
        allowed = True
    except ValueError:
        allowed = False
    c.check("실데이터 수정 기록에 원문을 넣으면 계약이 거부", not allowed)


def _drafted(c: Checker, resources: AssistantResources) -> None:
    c.section("문서 접수: 비서 초안만 모드")
    assistant = Assistant(resources)
    seed = AssistantSeed(
        fixed_op="thickness",
        overrides={"part_ids": SlotFill(value=("S-001:B31P-PL-007",), method=FillMethod.USER)},
    )
    turn = assistant.turn(
        AssistantTurnRequest(context=CONTEXT, message="B31P 판 7번 두께 20으로", draft_only=True, seed=seed)
    )
    for _ in range(4):
        if turn.state is not TurnState.ASKING:
            break
        question = turn.questions[0]
        option = question.options[0].option_id if question.options else None
        turn = assistant.turn(
            AssistantTurnRequest(
                conversation_id=turn.conversation_id,
                context=CONTEXT,
                answer=Answer(question_id=question.question_id, option_id=option)
                if option
                else Answer(question_id=question.question_id, text="20"),
            )
        )
    c.check(
        "초안만: 분석하지 않고 다 채운 초안(대상은 넘긴 값)",
        turn.state is TurnState.DRAFTED
        and turn.result is None
        and turn.draft is not None
        and turn.draft.slots["part_ids"].value == ("S-001:B31P-PL-007",),
        (turn.state, turn.questions),
    )
    try:
        AssistantTurnRequest(context=CONTEXT, conversation_id="C-1", message="x", draft_only=True)
        allowed = True
    except ValueError:
        allowed = False
    c.check("초안만은 새 대화에만", not allowed)

    def seeded(message: str, parts: tuple[str, ...]) -> object:
        seed = AssistantSeed(
            fixed_op="thickness", overrides={"part_ids": SlotFill(value=parts, method=FillMethod.USER)}
        )
        request = AssistantTurnRequest(context=CONTEXT, message=message, draft_only=True, seed=seed)
        return Assistant(resources).turn(request)

    moved = seeded("B31P 판 7번 두께 20으로", ("S-001:T31C-PL-009",))
    t31c = resources.vocab.parts["S-001:T31C-PL-009"].part.thickness_mm
    c.check(
        "씨앗 대상이 문장과 다르면 지금 값은 씨앗 대상의 지도 값(옛 대상 값으로 초안을 마치지 않음)",
        moved.state is not TurnState.DRAFTED  # type: ignore[attr-defined]
        or (
            moved.draft is not None  # type: ignore[attr-defined]
            and moved.draft.slots["from_mm"].value == t31c  # type: ignore[attr-defined]
            and moved.draft.slots["to_mm"].value == 20.0  # type: ignore[attr-defined]
        ),
        moved,
    )
    relative = seeded("B31P 판 7번 두께 3mm 증가", ("S-001:T31C-PL-009",))
    c.check(
        "씨앗 대상을 바꾸면 옛 대상 기준 증감 값('3mm 증가')으로 초안을 마치지 않고 다시 물음",
        relative.state is TurnState.ASKING  # type: ignore[attr-defined]
        or (
            relative.draft is not None  # type: ignore[attr-defined]
            and relative.draft.slots.get("to_mm") is not None  # type: ignore[attr-defined]
            and relative.draft.slots["to_mm"].value == (t31c or 0) + 3  # type: ignore[attr-defined]
        ),
        relative,
    )


def _ttl(c: Checker) -> None:
    c.section("문서 접수: 제안 보관")
    clock = [0.0]
    store: TtlStore[int] = TtlStore(ttl_s=10, limit=2, clock=lambda: clock[0])
    store.put("a", 1)
    store.put("b", 2)
    store.put("c", 3)
    c.check("상한을 넘으면 오래된 것부터", store.get("a") is None and store.get("c") == 3)
    clock[0] = 11
    c.check("시간이 지나면 사라짐", store.get("c") is None and len(store) == 0)


def _e9(c: Checker, resources: AssistantResources, snapshot) -> None:  # type: ignore[no-untyped-def]
    c.section("문서 접수: E9 합성 문서 생성기·채점기")
    docs = e9.intake_docs(snapshot, 9, 20261020, date(2026, 10, 20), load_nl_lexicon(), "dev")
    again = e9.intake_docs(snapshot, 9, 20261020, date(2026, 10, 20), load_nl_lexicon(), "dev")
    other = e9.intake_docs(snapshot, 9, 20261020, date(2026, 10, 20), load_nl_lexicon(), "eval")
    c.check(
        "같은 시드·분할이면 같은 문서, 분할이 다르면 다른 문서",
        [d.text for d in docs] == [d.text for d in again]
        and not set(d.text for d in docs) & set(d.text for d in other),
    )
    c.check(
        "정답 위치가 문서 안이고 세 문체가 다 나옴",
        all(0 <= t.start < t.end <= len(d.text) for d in docs for t in d.truths)
        and {d.style for d in docs} == {"form", "mail", "table"},
    )
    service, _ = _service(resources)
    scores = [e9.score(d, service.propose(d.text, ("S-001",), lambda _: None)) for d in docs]
    summary = e9.summarize(scores)
    lost = sum(counts.get("lost", 0) for counts in summary.outcomes.values())
    silent = summary.outcomes.get("unsupported", {}).get("silent", 0)
    c.check(
        "규칙 경로: 사람에게 안 보인 정답 0건·지원 안 함이 경고 없이 통과 0건",
        lost == 0 and silent == 0,
        summary.outcomes,
    )


class RoutedFake:
    """경로 모델 흉내: 부른 스레드에서 본 로그인 계정을 남긴다."""

    name = "routed-fake"

    def __init__(self) -> None:
        self.actors: list[str] = []

    def generate_json(self, prompt: str, schema: Schema, timeout_s: float) -> object:
        return {"items": []}

    def generate_routed(self, task: str, prompt: str, schema: Schema, accept: object) -> object:
        self.actors.append(current_actor())
        return {"items": []}


def _counterexamples(c: Checker, resources: AssistantResources) -> None:  # 반례별 회귀
    c.section("문서 접수: 반례 회귀")
    service, _ = _service(resources)
    actor = Actor(login_id="tester")

    def confirm_with(
        proposal: IntakeProposal,
        decisions: list[ItemDecision],
        header: IntakeHeader | None = None,
        context: TurnContext = CONTEXT,
        cont: bool = False,
    ) -> tuple[IntakeResult, list[CorrectionEvent]] | list[ItemProblem] | IntakeError:
        """성공은 (결과, 수정 기록), 확정 불가는 이유 목록, 제안 없음 등은 IntakeError."""
        conf = IntakeConfirmation(
            proposal_id=proposal.proposal_id,
            context=context,
            header=header or proposal.header,
            decisions=tuple(decisions),
            continue_ecn=cont,
        )
        try:
            return service.confirm(conf, actor)
        except IntakeProblems as error:
            return list(error.problems)
        except IntakeError as error:
            return error

    proposal = service.propose(DOC, ("S-001",), lambda _: None)
    unsupported = next(i for i in proposal.items if any(x.code is IntakeIssueCode.UNSUPPORTED_OP for x in i.issues))
    fake = ChangeDraft(
        text=unsupported.source.text,
        ship_ids=("S-001",),
        op=SlotFill(value="thickness", method=FillMethod.USER),
        slots={
            "part_ids": SlotFill(value=("S-001:T31C-PL-007",), method=FillMethod.USER),
            "from_mm": SlotFill(
                value=float(resources.vocab.parts["S-001:T31C-PL-007"].part.thickness_mm or 1), method=FillMethod.MAP
            ),
            "to_mm": SlotFill(value=7.0, method=FillMethod.USER),
        },
    )
    decisions = [
        ItemDecision(item_id=i.item_id, action=ItemAction.DROP)
        if i is not unsupported
        else ItemDecision(item_id=i.item_id, action=ItemAction.EDIT, draft=fake)
        for i in proposal.items
    ]
    got = confirm_with(proposal, decisions)
    c.check(
        "지원 안 함 항목은 비서로 마친 초안이어도 확정 불가(각장 → 판 두께 방지)",
        isinstance(got, list) and any("지원하지 않는" in p.message for p in got),
        got,
    )

    relative = service.propose("B31P 판 7번 두께 3mm 증가", ("S-001",), lambda _: None)
    item = relative.items[0]
    moved = [ItemDecision(item_id=item.item_id, action=ItemAction.EDIT, part_ids=("S-001:T31C-PL-009",))]
    got = confirm_with(relative, moved)
    c.check(
        "대상을 바꾸면 옛 대상 기준 증감 값은 쓰지 않고 바꿀 값을 직접 넣게 함",
        isinstance(got, list) and any("직접 입력" in p.message for p in got),
        got,
    )
    t31c = float(resources.vocab.parts["S-001:T31C-PL-009"].part.thickness_mm or 0)
    with_value = [
        ItemDecision(
            item_id=item.item_id, action=ItemAction.EDIT, part_ids=("S-001:T31C-PL-009",), values={"to_mm": t31c + 3}
        )
    ]
    got = confirm_with(relative, with_value)
    ok = isinstance(got, tuple)
    op = got[0].request.change.ops[0] if isinstance(got, tuple) else None
    c.check(
        "실패한 확정 뒤에도 제안이 남아 고쳐서 확정(지금 값 = 새 대상 지도 값)",
        ok and getattr(op, "from_mm", None) == t31c and getattr(op, "to_mm", None) == t31c + 3,
        got,
    )
    again = confirm_with(relative, with_value)
    c.check(
        "같은 제안은 한 번만 확정(두 번째는 409 — 수정 기록이 두 번 쌓이지 않게)",
        isinstance(again, IntakeError) and again.status == 409,
    )

    plain = service.propose("B31P 판 7번 두께 20으로", ("S-001",), lambda _: None)
    got = confirm_with(
        plain, [ItemDecision(item_id=plain.items[0].item_id, action=ItemAction.EDIT, values={"from_mm": 5.0})]
    )
    c.check(
        "지도에서 읽는 지금 값 칸은 표에서 고칠 수 없음",
        isinstance(got, list) and any("고칠 수 없는 칸" in p.message for p in got),
        got,
    )
    twice = TurnContext(ship_ids=("S-001", "S-001"), as_of=date(2026, 10, 20))
    got = confirm_with(plain, [ItemDecision(item_id=plain.items[0].item_id, action=ItemAction.ACCEPT)], context=twice)
    c.check("같은 호선이 두 번 와도 서버 오류 없이 하나로", isinstance(got, tuple), got)

    existing = ExistingEcn(ecn_id="ECN-OLD", title="옛 설계변경", state="draft", can_continue=True)
    numbered = service.propose("ECN No. 2026-034\nB31P 판 7번 두께 20으로", ("S-001",), lambda _: existing)
    edited = numbered.header.model_copy(update={"ecn_ref": "2026-999"})
    got = confirm_with(
        numbered, [ItemDecision(item_id=numbered.items[0].item_id, action=ItemAction.ACCEPT)], header=edited, cont=True
    )
    c.check(
        "원문 번호를 고치면 기존 설계변경·이어 가기 답보다 고친 번호가 먼저",
        isinstance(got, tuple) and got[0].ecn_id == ecn_id_for("2026-999", numbered.document),
        got,
    )

    routed = RoutedFake()
    routed_service = IntakeService(resources, llm=Guarded(routed, resources.data_mode))
    with acting_as("alice"):
        routed_service.propose(DOC, ("S-001",), lambda _: None)
    c.check(
        "AI 항목 뽑기 호출은 작업 스레드에서도 로그인 계정 몫(사용량 한도)",
        bool(routed.actors) and set(routed.actors) == {"alice"},
        routed.actors,
    )

    notice = "안녕하세요.\n설계변경 2026-034 건으로 엔진룸 펌프 P-A 사양 변경 부탁드립니다\n감사합니다."
    header, lines = read_header(notice)
    texts = [s.text for s in segments(notice, lines)]
    c.check(
        "번호가 든 줄이라도 변경 단서 말이 있으면 항목(안내 줄로 버리지 않음)",
        header.ecn_ref == "2026-034" and any("사양 변경" in x for x in texts),
        texts,
    )
    ahead = "설계변경 12건 정리해서 보냅니다\nECN No: 2026-034\nB31P 판 7 두께 15에서 17로 변경"
    tailed = "설계변경 12건 정리해서 보냅니다\nECN No. 2026-034 Rev.B\nB31P 판 7 두께 15에서 17로 변경"
    counted = "설계변경 12건 정리해서 보냅니다\nB31P 판 7 두께 15에서 17로 변경"
    refs = [read_header(d)[0].ecn_ref for d in (ahead, tailed, counted)]
    c.check(
        "'설계변경 12건'의 12는 번호가 아님, 번호만 있는 줄은 'Rev.B' 꼬리가 있어도 번호",
        refs == ["2026-034", "2026-034", None] and read_header(tailed)[0].revision == "B",
        refs,
    )
    wordy = "ECN process 개선에 따라 B31P 판 7 두께 15에서 17로 변경"
    c.check("본문 속 'ECN 낱말'은 숫자가 없으면 번호로 읽지 않음", read_header(wordy)[0].ecn_ref is None)
    c.check(
        "원문 번호 비교는 앞뒤 공백·대소문자를 무시하고, 둘 다 비었으면 같음",
        same_ref(" ecn-7 ", "ECN-7") and same_ref(None, " ") and not same_ref("ECN-7", None),
    )
    columns = "No | 대상 | 항목 | 전 | 후\n1 | B31P 판 7 | 두께 | 15 | 17\n2 | 엔진룸 펌프 P-A | 사양 | 기존 | 신규"
    rows = [s.text for s in segments(columns)]
    c.check(
        "열로 나눈 표는 행 전체가 한 조각(값 칸을 버리지 않음), 숫자 없는 둘째 행도 남음",
        any("15" in r and "17" in r for r in rows) and any("펌프" in r for r in rows),
        rows,
    )
    closed = "1. B31P 판 7 두께 15에서 17로 변경 (긴급)\nT31C 판 9 두께 25로 변경"
    c.check("괄호로 끝난 항목 뒤 줄은 이어 붙이지 않음", len(segments(closed)) == 2, [s.text for s in segments(closed)])
    item_header = rows_to_document([["No", "Item", "부재", "변경 전", "변경 후"], [1, "두께", "B31P 판 7", 15, 17]])
    c.check("엑셀 머리글 Item은 항목(속성) 열", "B31P 판 7" in item_header, item_header)
