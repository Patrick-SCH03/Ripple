"""AI 비서 계약의 성질: 슬롯 표 = 변경 연산 필드, 초안 조립·자격, 대화 차례·문장 사례·사전의 모순 거부."""

from __future__ import annotations

from datetime import date
from typing import Any

from fixtures import AS_OF
from harness import Checker
from pydantic import TypeAdapter

from checks.contracts import MINIMAL_OPS
from ripple.contracts.assistant import (
    ANY_OF,
    OP_LABELS,
    OP_SLOTS,
    Answer,
    AssistantTurn,
    AssistantTurnRequest,
    ChangeDraft,
    FillMethod,
    Question,
    QuestionKind,
    SlotFill,
    SlotKind,
    SourceSpan,
    TurnContext,
    TurnState,
    op_types,
)
from ripple.contracts.change import CHANGE_OP_TYPES, ChangeOp
from ripple.contracts.dataset import MentionTruth, NlSample, NlSplit
from ripple.contracts.lexicon import Lexicon

OP_ADAPTER: TypeAdapter[Any] = TypeAdapter(ChangeOp)
TEXT = "T31C 판 7번 두께 15에서 17로 올려 주세요"


def run(c: Checker) -> None:
    _slot_table(c)
    _drafts(c)
    _turns(c)
    _samples(c)
    _lexicon(c)


def _slot_table(c: Checker) -> None:
    c.section("계약: 비서 슬롯 표")
    c.check("슬롯 표는 변경 연산 8종을 계약 순서대로 덮음", tuple(OP_SLOTS) == op_types() == tuple(OP_LABELS))
    for op_type in CHANGE_OP_TYPES:
        name = str(op_type.model_fields["op"].default)
        fields = {k: f for k, f in op_type.model_fields.items() if k != "op"}
        specs = {s.name: s for s in OP_SLOTS[name]}
        c.check(f"'{name}': 슬롯 이름 = 연산 필드", set(specs) == set(fields), set(specs) ^ set(fields))
        c.check(
            f"'{name}': 필수 슬롯 = 기본값 없는 필드",
            all(specs[k].required == f.is_required() for k, f in fields.items() if k in specs),
        )
    calibrated = {(op, s.name) for op, specs in OP_SLOTS.items() for s in specs if s.calibrated}
    c.check(
        "보정 슬롯은 대상 부재(part_ids)뿐",
        all(name == "part_ids" for _, name in calibrated)
        and {op for op, _ in calibrated} == {"thickness", "grade", "dimension", "remove_part", "equipment_spec"},
        sorted(calibrated),
    )
    from_map = {(op, s.name) for op, specs in OP_SLOTS.items() for s in specs if s.from_map}
    c.check(
        "지도 현재값으로 채우는 슬롯은 변경 전 두께·강종·규격",
        from_map == {("thickness", "from_mm"), ("grade", "from_grade"), ("equipment_spec", "from_spec_id")},
        sorted(from_map),
    )
    c.check(
        "하나 이상 묶음의 슬롯은 모두 선택 슬롯",
        all(not s.required for op, group in ANY_OF.items() for s in OP_SLOTS[op] if s.name in group),
    )


def _fill(value: Any, kind: SlotKind) -> Any:
    if kind in (SlotKind.PARTS, SlotKind.SPECS):
        return tuple(value)
    if kind in (SlotKind.MILLIMETER, SlotKind.QUANTITY):
        return float(value)
    return value


def _draft(name: str, method: FillMethod = FillMethod.RULE, **overrides: Any) -> ChangeDraft:
    specs = {s.name: s for s in OP_SLOTS[name]}
    slots = {k: SlotFill(value=_fill(v, specs[k].kind), method=method) for k, v in MINIMAL_OPS[name].items()}
    body: dict[str, Any] = {
        "text": TEXT,
        "ship_ids": ("S-001",),
        "op": SlotFill(value=name, method=FillMethod.DECISION),
        "intent": SlotFill(value="strength", method=FillMethod.DECISION),
        "slots": slots,
    }
    body.update(overrides)
    return ChangeDraft(**body)


def _drafts(c: Checker) -> None:
    c.section("계약: 변경 초안")
    for op, body in MINIMAL_OPS.items():
        change = _draft(op).to_change(ecn_id="ECN-AI-1", title="시험")
        expected = OP_ADAPTER.validate_python({"op": op, **body})
        c.check(f"'{op}': 채운 슬롯으로 조립하면 같은 연산", change.ops == (expected,) and change.raw_text == TEXT)
    empty = ChangeDraft(text=TEXT, ship_ids=("S-001",))
    c.check(
        "아무것도 없으면 연산이 빠짐(변경 사유는 분석 뒤에 정하므로 필수가 아님)",
        empty.missing() == ("op",) and not empty.ready,
    )
    bare = _draft("thickness", slots={})
    c.check("연산만 있으면 필수 슬롯이 모두 빠짐", bare.missing() == ("part_ids", "from_mm", "to_mm"))
    crosses = _draft("reroute_pipe", slots={"crosses_part_ids": SlotFill(value=("p1",), method=FillMethod.RULE)})
    c.check("경로 변경에 빼는·더하는 스풀이 모두 없으면 빠짐", crosses.missing() == ("removed_part_ids",))
    c.check("모두 결정적으로 채우면 자동 진행 자격", _draft("thickness").ready)
    guessed = _draft("thickness")
    guessed = guessed.model_copy(
        update={"slots": {**guessed.slots, "to_mm": SlotFill(value=14.0, method=FillMethod.GUESS)}}
    )
    c.check("추정한 값이 있으면 자격 없음", not guessed.ready and guessed.unconfirmed() == ("to_mm",))
    llm_op = _draft("thickness", op=SlotFill(value="thickness", method=FillMethod.LLM))
    c.check("LLM이 고른 연산이면 자격 없음", not llm_op.ready and llm_op.unconfirmed() == ("op",))
    c.check("사용자가 확인한 값은 자격 있음", _draft("thickness", method=FillMethod.USER).ready)
    c.check("빠진 슬롯이 있으면 조립 거부", c.raises(lambda: bare.to_change(ecn_id="E", title="t")))
    same = _draft("thickness")
    same = same.model_copy(update={"slots": {**same.slots, "to_mm": SlotFill(value=12.0, method=FillMethod.RULE)}})
    c.check("조립한 연산이 계약에 어긋나면(전·후 같음) 거부", c.raises(lambda: same.to_change(ecn_id="E", title="t")))
    c.check(
        "연산에 없는 슬롯은 거부",
        c.raises(lambda: _draft("thickness", slots={"to_grade": SlotFill(value="EH36", method=FillMethod.RULE)})),
    )
    c.check(
        "연산 없이 슬롯을 채우면 거부",
        c.raises(lambda: _draft("thickness", op=None)),
    )
    c.check(
        "부재 묶음 슬롯에 글자 하나를 넣으면 거부",
        c.raises(lambda: _draft("thickness", slots={"part_ids": SlotFill(value="p1", method=FillMethod.RULE)})),
    )
    c.check(
        "mm 슬롯에 0 이하 값은 거부",
        c.raises(lambda: _draft("thickness", slots={"to_mm": SlotFill(value=0.0, method=FillMethod.RULE)})),
    )
    c.check(
        "없는 연산은 거부", c.raises(lambda: _draft("thickness", op=SlotFill(value="paint", method=FillMethod.RULE)))
    )
    c.check(
        "없는 의도는 거부", c.raises(lambda: _draft("thickness", intent=SlotFill(value="cost", method=FillMethod.RULE)))
    )
    c.check("원문 위치와 조각 길이가 다르면 거부", c.raises(lambda: SourceSpan(start=0, end=3, text="T31C")))


def _question() -> Question:
    return Question(question_id="q1", kind=QuestionKind.CONFIRM, target="part_ids#0", prompt="이 판이 맞나요?")


def _turns(c: Checker) -> None:
    c.section("계약: 대화 차례")
    context = TurnContext(ship_ids=("S-001",), as_of=AS_OF)
    c.check("답은 선택지와 입력 중 하나", c.raises(lambda: Answer(question_id="q1")))
    c.check("답에 선택지와 입력을 함께 쓰면 거부", c.raises(lambda: Answer(question_id="q1", option_id="a", text="b")))
    c.check("새 문장도 답도 없으면 거부", c.raises(lambda: AssistantTurnRequest(context=context)))
    answer = Answer(question_id="q1", option_id="__yes__")
    c.check(
        "새 대화에 답만 보내면 거부",
        c.raises(lambda: AssistantTurnRequest(context=context, answer=answer)),
    )
    c.check(
        "확정일이 기준일보다 앞서면 거부",
        c.raises(lambda: TurnContext(ship_ids=("S-001",), as_of=AS_OF, confirm_on=date(2026, 1, 1))),
    )
    asking = {"conversation_id": "C-1", "turn": 1, "message": "확인해 주세요", "interpreter": "rule"}
    c.check("묻는 차례에 질문이 없으면 거부", c.raises(lambda: AssistantTurn(**asking, state=TurnState.ASKING)))
    c.check(
        "묻는 차례에 질문이 있으면 받음",
        AssistantTurn(**asking, state=TurnState.ASKING, questions=(_question(),)).state is TurnState.ASKING,
    )
    c.check(
        "분석을 마쳤다면서 결과가 없으면 거부",
        c.raises(lambda: AssistantTurn(**asking, state=TurnState.ANALYZED)),
    )


def _sample(**overrides: Any) -> NlSample:
    change = _draft("thickness").to_change(ecn_id="ECN-NL-1", title="t")
    body: dict[str, Any] = {
        "sample_id": "NL-train-0001",
        "split": NlSplit.TRAIN,
        "text": TEXT,
        "ship_id": "S-001",
        "as_of": AS_OF,
        "change": change,
        "mentions": (MentionTruth(slot="part_ids", start=7, end=9, value="p1"),),
        "value_form": "from_to",
        "intent_stated": False,
    }
    body.update(overrides)
    return NlSample(**body)


def _samples(c: Checker) -> None:
    c.section("계약: 문장 사례")
    c.check("정답 연산 하나·조각이 문장 안이면 받음", _sample().split is NlSplit.TRAIN)
    change = _sample().change
    two = change.model_copy(
        update={"ops": (*change.ops, OP_ADAPTER.validate_python({"op": "remove_part", "part_ids": ["p9"]}))}
    )
    c.check("연산이 둘인 사례는 거부", c.raises(lambda: _sample(change=two)))
    outside = (MentionTruth(slot="part_ids", start=7, end=len(TEXT) + 1, value="p1"),)
    c.check("조각이 문장 밖이면 거부", c.raises(lambda: _sample(mentions=outside)))
    c.check("조각의 끝이 시작보다 앞이면 거부", c.raises(lambda: MentionTruth(slot="op", start=5, end=5, value="x")))


def _lexicon(c: Checker) -> None:
    c.section("계약: 해석기 사전")
    body: dict[str, Any] = {
        "version": "lexicon-v1",
        "part_kinds": {"plate": ["판"]},
        "block_words": {"횡격벽": ["T.BHD"]},
        "systems": {"ballast": ["평형수"]},
        "valve_types": {"gate": ["게이트"]},
        "ops": {"thickness": ["두께"]},
        "intents": {"strength": ["보강"]},
        "increase": ["올려"],
        "decrease": ["줄여"],
        "dimensions": {"length_mm": ["길이"]},
        "grades": ["AH36"],
        "roles": {"crosses": ["관통"]},
    }
    c.check("최소 사전은 받음", Lexicon.model_validate(body).version == "lexicon-v1")
    c.check("없는 연산의 단서는 거부", c.raises(lambda: Lexicon.model_validate({**body, "ops": {"paint": ["도장"]}})))
    c.check("빈 별칭 묶음은 거부", c.raises(lambda: Lexicon.model_validate({**body, "increase": []})))
    c.check("빈 글자 별칭은 거부", c.raises(lambda: Lexicon.model_validate({**body, "grades": [" "]})))
