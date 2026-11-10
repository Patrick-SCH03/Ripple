"""규칙 기반 해석의 성질: 값 정규화 동치·모호·지도 불일치, 참조 추출, 초안 채우기(LLM 없이)."""

from __future__ import annotations

import random

from harness import Checker

from ripple.config.loaders import load_lexicon
from ripple.config.settings import Settings
from ripple.contracts.assistant import FillMethod, SlotValue
from ripple.contracts.change import OP_NAMES
from ripple.contracts.dataset import NlSplit
from ripple.contracts.decision import NONE_OPTION, DecisionTopic
from ripple.contracts.domain import GraphSnapshot, PartKind
from ripple.contracts.lexicon import Lexicon
from ripple.eval.nl_labels import read_and_label, same_change, training_examples
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.generator.nl import load_nl_lexicon, nl_samples
from ripple.nl.fill_ops import FILLERS
from ripple.nl.fill_types import TEXT_ISSUE
from ripple.nl.pipeline import Fixed, Models, read
from ripple.nl.refs import find_references
from ripple.nl.resolve import deterministic_part
from ripple.nl.text import normalize
from ripple.nl.value_exprs import extract_values
from ripple.nl.values import Certainty, find_grades, normalize_grade, normalize_measure
from ripple.nl.vocab import MapVocabulary

SHIP = ("S-001",)
HAND_MODELS = Models(
    op={"cue": 2.0, "none:bias": 0.5, "other_cued": -1.0},
    intent={"cue": 2.0, "none:bias": 0.5},
    target={
        "number": 3.0,
        "number_miss": -1.0,
        "block_in": 2.0,
        "block_unique": 1.0,
        "block_out": -2.0,
        "kind": 1.0,
        "kind_miss": -1.0,
        "code": 5.0,
        "det": 2.0,
        "sim": 1.0,
        "system": 1.0,
        "vtype": 1.0,
        "none:bias": 3.0,
    },
)
"""손으로 정한 가중치(학습 전). 규칙 기반 경로가 끝까지 도는지 보는 용도이지 정확도 기준이 아니다."""


def run(c: Checker) -> None:
    lexicon = load_lexicon(Settings.from_env({}).lexicon_path)
    config = load_config()
    snapshot = generate(config).snapshot
    vocab = MapVocabulary(snapshot)
    _text(c)
    _values(c, lexicon)
    _grades(c, lexicon)
    _references(c, lexicon, vocab)
    _drafts(c, lexicon, vocab, snapshot)
    _labels(c, lexicon, vocab, snapshot, config.seed, config.scenario_date)


def _measure(
    lexicon: Lexicon, text: str, measure: str, current: float | None
) -> tuple[float | None, float | None, Certainty | None]:
    clean = normalize(text)
    result = normalize_measure(extract_values(clean, lexicon.increase, lexicon.decrease), measure, current)  # type: ignore[arg-type]
    return result.before, result.after, result.certainty


def _text(c: Checker) -> None:
    c.section("해석: 문장 정규화")
    raw = "Ｔ３１Ｃ　판７ → ＥＨ３６ ～ 4―5번 ・ ㆍ"
    c.check("정규화는 길이를 바꾸지 않음(원문 위치 그대로)", len(normalize(raw)) == len(raw))
    c.check("전각 글자·대시·화살표를 반각으로", normalize("Ｔ３１Ｃ－ＰＬ⟶") == "T31C-PL→")


def _values(c: Checker, lexicon: Lexicon) -> None:
    c.section("해석: 값 정규화(결정적)")
    same = ("15에서 16.5로", "1.5 올림", "16.5mm로", "+1.5", "15T→16.5T", "1.5mm 두껍게", "15mm를 16.5mm로")
    results = {text: _measure(lexicon, text, "thickness", 15.0) for text in same}
    c.check(
        "두께 표현 동치: '15에서 16.5로' ≡ '1.5 올림' ≡ '16.5mm로' ≡ '+1.5' …(지도 15mm)",
        set(results.values()) == {(15.0, 16.5, Certainty.RULE)},
        results,
    )
    rng = random.Random(7)
    mismatches = []
    for _ in range(200):
        current = rng.randrange(16, 50) / 2
        delta = rng.choice((0.5, 1.0, 1.5, 2.0, 3.0, 4.0)) * rng.choice((1, -1))
        after = current + delta
        word = "올림" if delta > 0 else "내림"
        forms = (f"{current:g}에서 {after:g}로", f"{abs(delta):g} {word}", f"{after:g}mm로", f"{delta:+g}")
        got = {_measure(lexicon, form, "thickness", current) for form in forms}
        if got != {(current, after, Certainty.RULE)}:
            mismatches.append((current, delta, got))
    c.check("무작위 두께·증감 200건에서 네 표현의 결과가 같음", not mismatches, mismatches[:3])
    stale = _measure(lexicon, "15에서 16.5로", "thickness", 14.5)
    c.check(
        "문장의 변경 전 값이 지도와 다르면 지도 값을 쓰고 추정으로",
        stale == (14.5, 16.5, Certainty.GUESS),
        stale,
    )
    guesses = {
        "두께 2": "증감인지 절대값인지 모호",
        "2로 바꿔": "범위 밖",
        "17로 줄여": "방향 단어와 값이 반대",
        "16 또는 17로": "값 표현이 여럿",
        "15로": "변경 전과 후가 같음",
    }
    wrong = {t: _measure(lexicon, t, "thickness", 15.0) for t in guesses}
    c.check(
        "모호한 두께 표현은 모두 추정(자동 진행 자격 없음)",
        all(r[2] is Certainty.GUESS for r in wrong.values()),
        wrong,
    )
    c.check("값이 없으면 바꿀 값을 비움", _measure(lexicon, "두께 올려 주세요", "thickness", 15.0)[1] is None)
    lengths = {
        t: _measure(lexicon, t, "length", None)
        for t in ("길이 3,200에서 2,800으로", "3200에서 400 줄여", "3.2m에서 2.8m로")
    }
    c.check(
        "치수 표현 동치(지도에 없는 값은 문장의 변경 전 값)",
        set(lengths.values()) == {(3200.0, 2800.0, Certainty.RULE)},
        lengths,
    )
    c.check(
        "치수에 바꿀 값만 있으면 변경 전 값은 비움",
        _measure(lexicon, "2800으로", "length", None) == (None, 2800.0, Certainty.RULE),
    )
    c.check(
        "치수 증감만 있고 지금 값을 모르면 바꿀 값을 정하지 않음",
        _measure(lexicon, "400 줄여", "length", None)[1] is None,
    )
    masses = {t: _measure(lexicon, t, "mass", None)[1] for t in ("0.2t", "200kg", "0.2톤")}
    c.check("수량 표현 동치(t·kg·톤)", set(masses.values()) == {0.2}, masses)
    c.check("비율 증감은 지금 값 기준", _measure(lexicon, "10% 늘려", "length", 3000.0)[1] == 3300.0)
    c.check(
        "변경 전 + 비율('3200에서 10% 줄여')은 문장의 변경 전 값 기준",
        _measure(lexicon, "3200에서 10% 줄여", "length", None) == (3200.0, 2880.0, Certainty.RULE),
    )
    c.check(
        "변경 전·어림 비율·바꿀 값을 다 적으면 비율이 1% 안일 때 결정적",
        _measure(lexicon, "1900mm에서 약 18.9% 늘려 2260mm로", "length", None) == (1900.0, 2260.0, Certainty.RULE),
    )
    c.check(
        "비율과 바꿀 값이 맞지 않으면 추정",
        _measure(lexicon, "1900mm에서 약 30% 늘려 2260mm로", "length", None)[2] is Certainty.GUESS,
    )
    c.check(
        "서로 다른 비율('10% 올려 또는 20% 올려')은 하나를 고르지 않고 추정",
        _measure(lexicon, "10% 올려 또는 20% 올려", "thickness", 15.0)[2] is Certainty.GUESS,
    )
    c.check(
        "줄인 결과가 0 이하면 바꿀 값을 정하지 않음('20mm 줄여', 지금 15mm)",
        _measure(lexicon, "20mm 줄여", "thickness", 15.0)[1] is None,
    )


def _grades(c: Checker, lexicon: Lexicon) -> None:
    c.section("해석: 강종")

    def grade(text: str, current: str | None) -> tuple[str | None, Certainty | None]:
        clean = normalize(text)
        result = normalize_grade(clean, find_grades(clean, lexicon.grades), current)
        return result.after, result.certainty

    c.check("전후 표기는 결정적", grade("AH36→EH36", "AH36") == ("EH36", Certainty.RULE))
    c.check("표기 변형(소문자·하이픈)", grade("eh-36으로", "AH36") == ("EH36", Certainty.RULE))
    c.check("한 글자 강종은 '급'이 붙을 때만", grade("A급으로", "AH36") == ("A", Certainty.RULE))
    c.check("변경 전 강종이 지도와 다르면 추정", grade("AH32에서 EH36으로", "AH36") == ("EH36", Certainty.GUESS))
    c.check("지금 강종만 적혀 있으면 바꿀 강종 없음", grade("AH36 유지", "AH36") == (None, None))
    c.check("바꿀 강종 후보가 여럿이면 추정", grade("DH36, EH36", "AH36")[1] is Certainty.GUESS)
    c.check("화살표 뒤 한 글자 강종('AH36→A')", grade("AH36→A 검토", "AH36") == ("A", Certainty.RULE))


def _references(c: Checker, lexicon: Lexicon, vocab: MapVocabulary) -> None:
    c.section("해석: 참조 추출")

    def mentions(text: str) -> list[tuple[str | None, int | None, tuple[str, ...]]]:
        refs = find_references(normalize(text), vocab, lexicon, SHIP)
        return [
            (m.kind.value if m.kind else None, m.number, tuple(sorted(b.split(":")[1] for b in m.block_ids)))
            for m in refs.mentions
        ]

    c.check(
        "화물탱크 번호·블록 이름 별칭·번호 → 블록·종류·번호",
        mentions("3번 탱크 횡격벽 7번 판 두께 15에서 17로") == [("plate", 7, ("T31C",))],
    )
    c.check(
        "약어 블록 이름(T.BHD)과 붙여 쓴 번호 목록",
        mentions("No.3 COT T.BHD 판7, 판9")
        == [
            ("plate", 7, ("T31C",)),
            ("plate", 9, ("T31C",)),
        ],
    )
    c.check(
        "번호 목록은 번호마다 표현 하나, 문맥은 이어짐",
        mentions("기관실 이중저 브라켓 3, 4 삭제") == [("bracket", 3, ("E11C",)), ("bracket", 4, ("E11C",))],
    )
    c.check(
        "좌우 단서로 블록 하나",
        mentions("3번 탱크 이중저 좌 판 4번 강종 변경") == [("plate", 4, ("B31P",))],
    )
    c.check(
        "범위 '4~5번'은 두 표현, 계통 단서로 배관 블록",
        mentions("평형수 스풀 4~5번 경로 변경")[:2] == [("pipe_spool", 4, ("E21C",)), ("pipe_spool", 5, ("E21C",))],
    )
    c.check(
        "계통 약어 'C/S'의 'S'를 우현으로 읽지 않음(긴 별칭이 먼저 자리를 잡음), 홀로 쓴 'S'는 우현",
        mentions("펌프룸 C/S 파이프 5, 6번 리라우팅") == [("pipe_spool", 5, ("P11C",)), ("pipe_spool", 6, ("P11C",))]
        and mentions("P/R C/S 파이프 005") == [("pipe_spool", 5, ("P11C",))]
        and mentions("No.3 COT 선측 S 강판 002") == [("plate", 2, ("S31S",))],
    )
    c.check(
        "종류 '서포트'의 '포트'를 좌현(port)으로 읽지 않음(종류 표도 같은 맞춤), 홀로 쓴 '포트'는 좌현",
        mentions("평형수 서포트 2번 삭제") == [("pipe_support", 2, ("E21C",))]
        and mentions("포트 판 3번") == [("plate", 3, ("B31P", "S31P"))],
    )
    code = find_references(normalize("T31C PL-007 15T→17T"), vocab, lexicon, SHIP).mentions
    c.check("부재 코드는 지도 부재 하나", [m.part_id for m in code] == ["S-001:T31C-PL-007"])
    spec = find_references(normalize("P11C VLCS-001 사양 VL-BALL-DN100-16K로 변경"), vocab, lexicon, SHIP)
    c.check(
        "규격 ID 안의 글자는 밸브 종류·번호로 읽지 않음",
        [m.part_id for m in spec.mentions] == ["S-001:P11C-VLCS-001"]
        and [t.spec_id for t in spec.specs] == ["VL-BALL-DN100-16K"],
    )
    valve = find_references(normalize("펌프룸 스트리핑 글로브 밸브 1번 볼 밸브로 사양 변경"), vocab, lexicon, SHIP)
    c.check(
        "'볼 밸브로'는 대상 표현이 아니라 바꿀 규격 설명",
        len(valve.mentions) == 1 and [t.valve_type for t in valve.targets] == ["ball"],
    )
    c.check("'판단'·'좌굴'·'우회'는 판·좌현·우현이 아님", mentions("판단이 필요해요 좌굴 우회") == [])
    c.check(
        "'PL 1, 5, 7번'은 코드가 아니라 종류 단어 + 번호 목록",
        mentions("선수루 갑판 PL 1, 5, 7번 재질 변경")
        == [
            ("plate", 1, ("F31C",)),
            ("plate", 5, ("F31C",)),
            ("plate", 7, ("F31C",)),
        ],
    )
    stiffener = find_references(normalize("E/R 측부·플랫 STF (E21C-PL-010에 부착) 신설"), vocab, lexicon, SHIP)
    c.check(
        "다른 종류의 코드 옆 종류 단어는 새 부재 종류로 남김",
        [(m.kind, m.number) for m in stiffener.mentions] == [(PartKind.STIFFENER, None), (PartKind.PLATE, 10)],
    )
    typos = {
        "No.3 COT 이중저 현좌 강판 1번": ("plate", 1, ("B31P",)),
        "No.3 COT 선측 P 판강 14번": ("plate", 14, ("S31P",)),
        "T31C 레이트 013": ("plate", 13, ("T31C",)),
        "3번 탱크 횡격볍 7번 판": ("plate", 7, ("T31C",)),
    }
    got = {t: mentions(t) for t in typos}
    c.check(
        "오타 허용 일치: 뒤바뀜(현좌·판강)·빠짐(레이트)·바뀜(횡격볍)을 사전 별칭으로 찾고 더 긴 별칭을 고름",
        all(got[t] == [expected] for t, expected in typos.items()),
        got,
    )
    fuzzy = find_references(normalize("3번 탱크 횡격볍 7번 판"), vocab, lexicon, SHIP).mentions
    c.check(
        "오타 허용으로 찾은 표현은 결정적 일치가 아님(역할 슬롯은 확인)",
        all(m.fuzzy for m in fuzzy) and deterministic_part(fuzzy[0], vocab, SHIP) is None,
    )
    c.check(
        "의도 단서('보강 위해')는 보강재의 오타로 보지 않음",
        mentions("강도 보강 위해 T31C 판 7") == [("plate", 7, ("T31C",))]
        and not find_references(normalize("강도 보강 위해 T31C 판 7"), vocab, lexicon, SHIP).mentions[0].fuzzy,
    )
    profile = find_references(normalize("E11C 판 5에 HP200x10 보강재 0.2t 추가"), vocab, lexicon, SHIP)
    c.check(
        "형강 표기의 숫자는 부재 번호가 아님",
        [(m.kind, m.number) for m in profile.mentions] == [(PartKind.PLATE, 5), (PartKind.STIFFENER, None)],
    )

    def numbered(text: str) -> tuple[list[int | None], int]:
        refs = find_references(normalize(text), vocab, lexicon, SHIP)
        return [m.number for m in refs.mentions], len(refs.unread)

    spans = {t: numbered(t) for t in ("T31C 보강재 1~12번 삭제", "T31C 1~12번 보강재 삭제", "T31C 보강재 3~4번 삭제")}
    c.check(
        "범위는 사이 번호까지 모두 펼침(오른쪽 '보강재 1~12번'·왼쪽 '1~12번 보강재'·두 개 '3~4번')",
        spans
        == {
            "T31C 보강재 1~12번 삭제": (list(range(1, 13)), 0),
            "T31C 1~12번 보강재 삭제": (list(range(1, 13)), 0),
            "T31C 보강재 3~4번 삭제": ([3, 4], 0),
        },
        spans,
    )
    broken = {t: numbered(t) for t in ("T31C 보강재 12~1번 삭제", "T31C 판 1~40번 두께 변경")}
    c.check(
        "거꾸로이거나 너무 긴 범위는 양 끝으로 줄이지 않고 읽지 못한 표현으로 남김(끝 번호는 표현으로 만들지 않음)",
        broken == {"T31C 보강재 12~1번 삭제": ([12], 1), "T31C 판 1~40번 두께 변경": ([1], 1)},
        broken,
    )
    values = {t: numbered(t)[0] for t in ("T31C 판 12T로", "T31C 판 1500으로", "T31C 판 3, 1500")}
    c.check(
        "값 숫자('12T'·'1500') 안으로 되짚어 앞자리를 부재 번호로 읽지 않음",
        values == {"T31C 판 12T로": [None], "T31C 판 1500으로": [None], "T31C 판 3, 1500": [3]},
        values,
    )


def _drafts(c: Checker, lexicon: Lexicon, vocab: MapVocabulary, snapshot: GraphSnapshot) -> None:
    c.section("해석: 초안 채우기(손 가중치)")
    c.check(
        "연산별 채우기 표가 변경 연산 8종과 같음(빠진 연산이 조용히 실패하지 않게)",
        set(FILLERS) == OP_NAMES,
        sorted(FILLERS),
    )
    demo2 = read("3번 탱크 횡격벽 7번 판 두께 15에서 17로 올려 주세요 (강도 보강)", SHIP, vocab, lexicon, HAND_MODELS)
    draft = demo2.proposal.draft
    c.check("데모 2 문장: 대상·변경 전(지도)·바꿀 값·의도를 채우고 자동 진행 자격", draft.ready, draft.missing())
    c.check(
        "데모 2 슬롯 값과 채움 방법",
        draft.slots["part_ids"].value == ("S-001:T31C-PL-007",)
        and (draft.slots["from_mm"].value, draft.slots["from_mm"].method) == (15.0, FillMethod.MAP)
        and (draft.slots["to_mm"].value, draft.slots["to_mm"].method) == (17.0, FillMethod.RULE),
    )
    demo1 = read("펌프룸 스트리핑 글로브 밸브 1번 볼 밸브로 사양 변경 (선주 요청)", SHIP, vocab, lexicon, HAND_MODELS)
    slots = demo1.proposal.draft.slots
    c.check(
        "데모 1 문장: 지금 규격은 지도, 바꿀 규격은 지금 규격 + 바뀐 속성으로 지도에서 하나",
        slots.get("from_spec_id") is not None
        and slots["from_spec_id"].method is FillMethod.MAP
        and slots.get("to_spec_id") is not None
        and slots["to_spec_id"].value == "VL-BALL-DN100-16K",
        {k: v.value for k, v in slots.items()},
    )
    change = draft.to_change(ecn_id="ECN-AI-T", title="t")
    c.check("자격 있는 초안은 변경 요청으로 조립됨", change.ops[0].op == "thickness" and change.raw_text is not None)
    vague_reading = read("횡격벽 판 두께 2 올려", SHIP, vocab, lexicon, HAND_MODELS)
    candidates = [o for o in vague_reading.targets[0].posed.question.option_ids if o != NONE_OPTION]
    part_fill = vague_reading.proposal.draft.slots.get("part_ids")
    c.check(
        "블록이 여럿이거나 번호가 없으면 대상 후보가 여럿이고 결정적 일치가 아님(판단 계층이 되묻기)",
        len({vocab.parts[o].part.block_id for o in candidates}) > 1
        and (part_fill is None or part_fill.method is FillMethod.DECISION),
        (len(candidates), None if part_fill is None else part_fill.method.value),
    )
    stale = read("T31C PL-007 두께 14에서 17로 (선급)", SHIP, vocab, lexicon, HAND_MODELS).proposal
    c.check(
        "지도와 다른 변경 전 값은 추정 → 자격 없음, 확인할 것에 이유",
        not stale.draft.ready and any(i.slot == "to_mm" and "지도" in i.reason for i in stale.issues),
        [i.reason for i in stale.issues],
    )
    c.check("지도 부재 수만큼 어휘가 있음", len(vocab.parts) == len(snapshot.parts))
    lost = read("SP-DN100-S40 3개 P/R 스풀풀 9, 10번 재배치 간섭 해소", SHIP, vocab, lexicon, HAND_MODELS).proposal
    c.check(
        "어느 슬롯에도 쓰지 않은 부재 표현·숫자가 있으면 자격 없음(조용히 버리지 않음)",
        not lost.ready and any(i.slot == TEXT_ISSUE for i in lost.issues),
        [i.reason for i in lost.issues],
    )

    def proposal_of(text: str, op: str) -> tuple[bool, dict[str, SlotValue], list[tuple[str, str]]]:
        found = read(text, SHIP, vocab, lexicon, HAND_MODELS, Fixed(op=op)).proposal
        slots = {k: v.value for k, v in found.draft.slots.items()}
        return found.ready, slots, [(i.slot, i.reason) for i in found.issues]

    valve = "펌프룸 스트리핑 글로브 밸브 1번 {} 사양 변경 (선주 요청)"
    agreed = [
        proposal_of(valve.format(v), "equipment_spec") for v in ("VL-BALL-DN100-16K로", "DN100 VL-BALL-DN100-16K로")
    ]
    c.check(
        "규격 ID와 맞는 속성(지금 규격의 DN100)은 그대로 결정적",
        all(ready and slots.get("to_spec_id") == "VL-BALL-DN100-16K" for ready, slots, _ in agreed),
        agreed,
    )
    clashes = [
        proposal_of(valve.format(v), "equipment_spec")
        for v in ("VL-BALL-DN100-16K로, 구경 DN200으로", "VL-BALL-DN100-16K 체크 밸브로")
    ]
    c.check(
        "규격 ID와 어긋나는 구경·밸브 종류를 함께 적으면 규격을 정하지 않고 확인(ID만 믿지 않음)",
        all(
            not ready and "to_spec_id" not in slots and any(slot == "to_spec_id" for slot, _ in issues)
            for ready, slots, issues in clashes
        ),
        clashes,
    )
    roles = {
        "부재 앞 DN100 = 지금 규격": proposal_of(
            "펌프룸 스트리핑 DN100 글로브 밸브 1번 VL-GATE-DN200-10K로 사양 변경 (선주 요청)", "equipment_spec"
        ),
        "부재 앞 DN200 ≠ 지금 규격": proposal_of(
            "펌프룸 스트리핑 DN200 글로브 밸브 1번 VL-BALL-DN100-16K로 사양 변경 (선주 요청)", "equipment_spec"
        ),
        "규격 ID 뒤 'DN100 유지'": proposal_of(
            valve.format("VL-GATE-DN200-10K로, 구경은 DN100 유지"), "equipment_spec"
        ),
        "부재보다 앞의 바꿀 속성": proposal_of(
            "DN200 10K 체크 밸브로 펌프룸 스트리핑 글로브 밸브 1번 사양 변경 (선주 요청)", "equipment_spec"
        ),
    }
    c.check(
        "구경·압력 등급: 부재 구절 안은 지금 규격 설명, 밖은 어순과 상관없이 바꿀 규격 조건(어긋나면 확인)",
        roles["부재 앞 DN100 = 지금 규격"][0]
        and roles["부재 앞 DN100 = 지금 규격"][1].get("to_spec_id") == "VL-GATE-DN200-10K"
        and not roles["부재 앞 DN200 ≠ 지금 규격"][0]
        and not roles["규격 ID 뒤 'DN100 유지'"][0]
        and roles["부재보다 앞의 바꿀 속성"][1].get("to_spec_id") == "VL-CHECK-DN200-10K",
        roles,
    )
    shrink = proposal_of("T31C 판 7번 두께 20mm 줄여 (강도 보강)", "thickness")
    c.check(
        "줄인 결과가 0 이하인 문장은 오류 없이 바꿀 값을 묻기",
        not shrink[0] and "to_mm" not in shrink[1] and any(slot == "to_mm" for slot, _ in shrink[2]),
        shrink,
    )
    unused = {
        "규격": proposal_of("T31C 판 7번 두께 15에서 17로 VL-BALL-DN100-16K (강도 보강)", "thickness"),
        "강종": proposal_of("T31C 판 7번 두께 15에서 17로, 강종 AH36 (강도 보강)", "thickness"),
        "범위": proposal_of("T31C 보강재 1~40번 삭제 (선주 요청)", "remove_part"),
    }
    c.check(
        "어느 슬롯에도 쓰지 않은 규격·강종 표기와 읽지 못한 범위는 확인할 것(조용히 버리지 않음)",
        all(not ready and any(slot == TEXT_ISSUE for slot, _ in issues) for ready, _, issues in unused.values()),
        unused,
    )
    crossing = read(
        "펌프룸 스트리핑 스풀 4번 경로 변경 SP-DN100-S40 1개, T31C 판 99 관통",
        SHIP,
        vocab,
        lexicon,
        HAND_MODELS,
        Fixed(op="reroute_pipe", intent="interference"),
    ).proposal
    c.check(
        "적었는데 못 정한 선택 슬롯(관통 판)이 있으면 초안이 차 있어도 자격 없음",
        crossing.draft.ready is True and not crossing.ready,
        [i.reason for i in crossing.issues],
    )


def _labels(
    c: Checker, lexicon: Lexicon, vocab: MapVocabulary, snapshot: GraphSnapshot, seed: int, as_of: object
) -> None:
    c.section("해석: 평가 라벨(생성 문장 정답과 맞추기)")
    samples = nl_samples(snapshot, NlSplit.SELECTION, 80, seed, as_of, load_nl_lexicon())  # type: ignore[arg-type]
    labeled = read_and_label(samples, vocab, lexicon, HAND_MODELS)
    teacher = read_and_label(samples, vocab, lexicon, HAND_MODELS, teacher=True)
    c.check("대상 질문마다 라벨 하나", all(len(x.target_labels) == len(x.reading.targets) for x in labeled))
    c.check(
        "대상 라벨은 그 질문의 선택지 안(없으면 해당 없음)",
        all(
            label == NONE_OPTION or label in t.scores
            for x in labeled
            for t, label in zip(x.reading.targets, x.target_labels, strict=True)
        ),
    )
    c.check(
        "정답으로 센 해석은 자격이 있고 조립한 요청이 정답 요청과 같음(변경 사유는 분석 뒤라 빼고)",
        all(
            x.reading.proposal.ready
            and same_change(x.reading.proposal.draft.to_change(ecn_id="X", title="x"), x.sample.change, intent=False)
            for x in labeled
            if x.correct
        ),
    )
    c.check(
        "단위의 자격·정답은 초안 자격·라벨과 같음",
        all(x.unit().ready == x.reading.proposal.ready for x in labeled)
        and all(x.unit().sound for x in labeled if not x.reading.proposal.ready),
    )
    c.check("후보에 든 정답 대상 ≤ 지도에 있는 정답 대상", all(x.candidate_hits <= x.candidate_total for x in labeled))
    c.check(
        "학습 자료(정답 연산으로 질문)는 연산을 정답으로 고정",
        all(
            x.reading.proposal.draft.op is not None and x.reading.proposal.draft.op.value == x.op_label for x in teacher
        ),
    )
    examples = training_examples(teacher)
    c.check(
        "학습 사례는 연산·의도는 문장마다 하나, 대상은 대상 질문마다 하나",
        len(examples[DecisionTopic.CHANGE_OP]) == len(teacher) == len(examples[DecisionTopic.CHANGE_INTENT])
        and len(examples[DecisionTopic.TARGET_PART]) == sum(len(x.reading.targets) for x in teacher),
    )
