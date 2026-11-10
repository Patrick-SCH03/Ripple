"""E9 문서 접수 평가(docs/evaluation.md 3절): 합성 설계변경 문서와 정답, 확인표 채점.

문서 = 생성기 문장(정답 연산 포함, `ripple/generator/nl/`) 2~5개를 세 문체(ECN 양식 · 메일 · 변경 리스트 표)로
묶고 적대 변형을 섞은 것: 지원하지 않는 변경(각장·케이블 트레이·도장·덕트·난간), 같은 항목 두 번, 두 항목을 한 줄에,
한 항목을 두 줄로, 변경 아닌 참고 줄, 지도와 다른 '지금 값', 지도에 없는 도면 개정. 생성기 문장의 4%는 지도에 없는
번호를 쓴다.

채점은 사람이 확인표에서 보는 것 기준이다(자동 진행이 없으므로 '틀렸지만 경고가 있는 항목'은 사람이 고칠 수 있다).
정답 변경마다: 누락(어떤 항목에도 안 보임) / 정확(연산·대상·값이 정답과 같은 항목이 있음 — 막는 문제가 없으면 '맞음
한 번으로 확정') / 틀렸지만 막힘 / 틀렸지만 경고 / **틀렸는데 경고 없음**(사람이 그대로 맞음을 누를 위험). 지원 안 함은
덮는 항목이 모두 막혀 있어야 안전하다. 기대 문제(지금 값 다름·개정 다름·같은 변경)는 덮는 항목에 그 문제가 떴는지 본다.

순환성 주의: 문장 생성기와 해석기가 같은 용어 계열이라 이 점수는 실제 회사 문서의 정확도가 아니다(분할·대조·경고
동작 검증).
"""

from __future__ import annotations

import hashlib
import random
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from ripple.contracts.change import ChangeOp, ThicknessChange
from ripple.contracts.dataset import NlSample, NlSplit
from ripple.contracts.domain import GraphSnapshot
from ripple.contracts.identity import canonical_json, normalized_op
from ripple.contracts.intake import IntakeIssueCode, IntakeItem, IntakeProposal
from ripple.generator.nl import NlLexicon, nl_samples
from ripple.intake.checks import op_of

Style = Literal["form", "mail", "table"]
STYLES: tuple[Style, ...] = ("form", "mail", "table")
UNSUPPORTED = (
    "{block} 판 {n}번 용접 각장 6에서 7mm로 변경",
    "{block} 구역 케이블 트레이 경로 변경 바랍니다",
    "{block} 블록 도장 사양 변경(에폭시 → 징크)",
    "{block} 덕트 위치 50mm 이동",
    "{block} 난간 높이 1,100에서 1,200으로 변경",
)
NOTES = ("참고: 생산 일정은 별도 협의 예정", "※ 현장 확인 후 회신 바랍니다", "첨부 도면 참조")
_BEFORE = re.compile(r"^(\d+(?:\.\d+)?)(?=\s*(?:T에서|→|mm에서))")


@dataclass(frozen=True, slots=True)
class Truth:
    kind: Literal["change", "unsupported", "duplicate"]
    start: int
    end: int
    op: ChangeOp | None = None
    exists: bool = True  # 대상이 지도에 있음(없는 번호 문장이면 문제 표시가 정답)
    expect: frozenset[IntakeIssueCode] = frozenset()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IntakeDoc:
    doc_id: str
    style: Style
    text: str
    truths: tuple[Truth, ...]
    ecn_ref: str


@dataclass(slots=True)
class _Line:
    text: str
    kind: Literal["change", "unsupported", "duplicate", "note"]
    pieces: list[tuple[int, int, int]] = field(default_factory=list)  # (줄 안 시작, 끝, 정답 번호)


@dataclass(frozen=True, slots=True)
class _Pending:
    sample: NlSample
    text: str
    expect: frozenset[IntakeIssueCode]
    tags: tuple[str, ...]


def split_seed(seed: int, split: str) -> int:
    digest = hashlib.sha256(f"{seed}|intake|{split}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % (2**31)


def intake_docs(
    snapshot: GraphSnapshot, count: int, seed: int, as_of: date, lexicon: NlLexicon, split: str = "dev"
) -> list[IntakeDoc]:
    """문서 count개. 분할(dev·eval)마다 문장 시드가 달라 같은 문장이 겹치지 않는다."""
    base = split_seed(seed, split)
    pool = list(nl_samples(snapshot, NlSplit.SELECTION, count * 5, base, as_of, lexicon))
    blocks = sorted(b.block_id for b in snapshot.blocks)
    drawings = sorted({d.drawing_no for d in snapshot.drawings})
    docs = []
    for k in range(count):
        rng = random.Random(f"{base}|doc|{k}")
        n = rng.randint(2, 5)
        chosen = [pool.pop() for _ in range(n)]
        docs.append(_document(rng, f"E9-{split}-{k:04d}", STYLES[k % 3], chosen, blocks, drawings))
    return docs


def _document(
    rng: random.Random,
    doc_id: str,
    style: Style,
    samples: Sequence[NlSample],
    blocks: Sequence[str],
    drawings: Sequence[str],
) -> IntakeDoc:
    pending = [_variant(rng, s, drawings) for s in samples]
    truths: list[Truth] = []
    lines = _change_lines(rng, style, pending, truths)
    _insert_unsupported(rng, lines, truths, blocks)
    _insert_note(rng, lines)
    _append_duplicate(rng, lines, truths)
    ecn_ref = f"2026-{rng.randint(100, 999)}"
    return _render(doc_id, style, ecn_ref, rng, lines, truths)


def _change_line(items: Sequence[_Pending], truths: list[Truth]) -> _Line:
    """항목들을 한 줄로 잇고, 항목마다 정답을 truths에 더해 줄 안 위치를 단다."""
    line = _Line("", "change")
    for j, p in enumerate(items):
        if j:
            line.text += ", 그리고 "
        start = len(line.text)
        line.text += p.text
        truths.append(_truth("change", p))
        line.pieces.append((start, len(line.text), len(truths) - 1))
    return line


def _change_lines(rng: random.Random, style: Style, pending: Sequence[_Pending], truths: list[Truth]) -> list[_Line]:
    """변경 줄: 차례대로 한 줄에 하나씩, 가끔 두 항목을 한 줄에·한 항목을 두 줄로(표 문체는 줄 나눔 없음)."""
    lines: list[_Line] = []
    i = 0
    while i < len(pending):
        if i + 1 < len(pending) and rng.random() < 0.2:  # 두 항목을 한 줄에
            joined = [_tagged(pending[i], "joined"), _tagged(pending[i + 1], "joined")]
            lines.append(_change_line(joined, truths))
            i += 2
            continue
        current = pending[i]
        if style != "table" and rng.random() < 0.15 and " " in current.text.strip():  # 한 항목을 두 줄로
            current = _tagged(current, "wrapped")
            words = current.text.split(" ")
            cut = max(1, len(words) // 2)
            current = _Pending(
                current.sample, " ".join(words[:cut]) + "\n" + " ".join(words[cut:]), current.expect, current.tags
            )
        lines.append(_change_line([current], truths))
        i += 1
    return lines


def _insert_unsupported(rng: random.Random, lines: list[_Line], truths: list[Truth], blocks: Sequence[str]) -> None:
    if rng.random() < 0.5:  # 지원하지 않는 변경
        template = rng.choice(UNSUPPORTED)
        text = template.format(block=rng.choice(blocks), n=rng.randint(1, 12))
        line = _Line(text, "unsupported")
        truths.append(Truth("unsupported", 0, 0, tags=("unsupported",)))
        line.pieces.append((0, len(text), len(truths) - 1))
        lines.insert(rng.randint(0, len(lines)), line)


def _insert_note(rng: random.Random, lines: list[_Line]) -> None:
    if rng.random() < 0.3:  # 변경 아닌 참고 줄
        lines.insert(rng.randint(0, len(lines)), _Line(rng.choice(NOTES), "note"))


def _append_duplicate(rng: random.Random, lines: list[_Line], truths: list[Truth]) -> None:
    if rng.random() < 0.2:  # 같은 항목 두 번(뒤 항목에 '같은 변경')
        source = next((t for t in truths if t.kind == "change" and "joined" not in t.tags and t.exists), None)
        if source is not None:
            original = next(ln for ln in lines if any(truths[p[2]] is source for p in ln.pieces))
            text = original.text.replace("\n", " ")
            truths.append(
                Truth("duplicate", 0, 0, source.op, True, frozenset({IntakeIssueCode.DUPLICATE}), ("duplicate",))
            )
            line = _Line(text, "duplicate", [(0, len(text), len(truths) - 1)])
            lines.append(line)


def _variant(rng: random.Random, sample: NlSample, drawings: Sequence[str]) -> _Pending:
    text = sample.text
    expect: set[IntakeIssueCode] = set()
    tags: list[str] = list(sample.noise)
    op = sample.change.ops[0]
    if "stale_before" in sample.noise:
        expect.add(IntakeIssueCode.FROM_MISMATCH)
    elif isinstance(op, ThicknessChange) and rng.random() < 0.3:  # 지금 값을 지도와 다르게
        mention = next((m for m in sample.mentions if m.slot == "to_mm"), None)
        piece = text[mention.start : mention.end] if mention else ""
        found = _BEFORE.match(piece)
        if mention and found:
            wrong = float(found.group(1)) + 1
            shown = str(int(wrong)) if wrong.is_integer() else str(wrong)
            text = text[: mention.start] + shown + text[mention.start + found.end() :]
            expect.add(IntakeIssueCode.FROM_MISMATCH)
            tags.append("stale_before")
    if drawings and rng.random() < 0.15:  # 지도에 없는 개정
        text = f"{text} (도면 {rng.choice(drawings)} Rev.C)"
        expect.add(IntakeIssueCode.REVISION_MISMATCH)
        tags.append("revision")
    return _Pending(sample, text, frozenset(expect), tuple(tags))


def _tagged(p: _Pending, tag: str) -> _Pending:
    return _Pending(p.sample, p.text, p.expect, (*p.tags, tag))


def _truth(kind: Literal["change"], p: _Pending) -> Truth:
    exists = all(m.exists for m in p.sample.mentions)
    return Truth(kind, 0, 0, p.sample.change.ops[0], exists, p.expect, p.tags)


def _render(
    doc_id: str, style: Style, ecn_ref: str, rng: random.Random, lines: Sequence[_Line], truths: list[Truth]
) -> IntakeDoc:
    head: list[str]
    if style == "form":
        head = [f"ECN No. {ecn_ref}", "제목: 구조·의장 변경", "요청자: 설계팀", "사유: 선급 코멘트 반영", ""]
    elif style == "mail":
        head = ["안녕하세요, 설계팀입니다.", f"설계변경 {ecn_ref} 건 아래 내용 반영 부탁드립니다.", ""]
    else:
        head = [f"변경 리스트 (ECN {ecn_ref})", "No | 변경 내용 | 비고"]
    out = "\n".join(head) + "\n"
    number = 0
    spans: dict[int, tuple[int, int]] = {}
    for line in lines:
        if line.kind == "note":
            prefix, suffix = "", ""
        else:
            number += 1
            if style == "form":
                prefix, suffix = f"{number}. ", ""
            elif style == "mail":
                prefix, suffix = "- ", ""
            else:
                prefix, suffix = f"{number} | ", " | " + rng.choice(("", "긴급", "확인 요"))
        start = len(out) + len(prefix)
        for a, b, index in line.pieces:
            spans[index] = (start + a, start + b)
        out += prefix + line.text + suffix + "\n"
    tail = {"form": "", "mail": "\n감사합니다.\n설계팀 드림", "table": ""}[style]
    text = (out + tail).rstrip("\n")  # 접수는 앞뒤 빈 줄을 떼므로 생성 문서도 같은 꼴로
    placed = tuple(
        Truth(t.kind, *spans[i], op=t.op, exists=t.exists, expect=t.expect, tags=t.tags) for i, t in enumerate(truths)
    )
    return IntakeDoc(doc_id, style, text, placed, ecn_ref)


# ---------- 채점 ----------

Outcome = Literal[
    "lost", "exact_ready", "exact_flagged", "wrong_blocked", "wrong_warned", "wrong_silent", "safe", "silent"
]


@dataclass(frozen=True, slots=True)
class TruthScore:
    truth: Truth
    outcome: Outcome
    expected_hits: frozenset[IntakeIssueCode]
    codes: frozenset[str] = frozenset()  # 덮는 항목들의 문제 코드(막힌 이유 보기)


@dataclass(frozen=True, slots=True)
class DocScore:
    doc: IntakeDoc
    truths: tuple[TruthScore, ...]
    items: int
    stray_items: int  # 정답과 겹치지 않는 항목(머리·참고 줄을 항목으로 읽음)
    stray_blocking: int  # 그중 막는 문제가 있는 것(사람이 빼기 쉬움)


def _key(op: ChangeOp) -> bytes:
    return canonical_json(normalized_op(op))


def _overlaps(item: IntakeItem, truth: Truth) -> bool:
    return item.source.start < truth.end and truth.start < item.source.end


def score(doc: IntakeDoc, proposal: IntakeProposal) -> DocScore:
    """문서 하나의 확인표 채점. 항목 위치는 정규화한 원문 기준이고 생성 문서는 정규화가 바꾸지 않는 꼴이다."""
    if proposal.document != doc.text:
        raise ValueError(f"{doc.doc_id}: 정규화한 원문이 생성 문서와 달라 위치를 맞출 수 없어요")
    items = list(proposal.items)
    scores = [_score_truth(t, items) for t in doc.truths]
    stray = [i for i in items if not any(_overlaps(i, t) for t in doc.truths)]
    return DocScore(doc, tuple(scores), len(items), len(stray), sum(1 for i in stray if i.blocking))


def _score_truth(truth: Truth, items: Sequence[IntakeItem]) -> TruthScore:
    covering = [i for i in items if _overlaps(i, truth)]
    codes = {x.code for i in covering for x in i.issues}
    hits = frozenset(truth.expect & codes)
    names = frozenset(c.value for c in codes)

    def scored(outcome: Outcome) -> TruthScore:
        return TruthScore(truth, outcome, hits, names)

    if not covering:
        return scored("lost")
    if truth.kind == "unsupported" or not truth.exists:
        return scored("safe" if all(i.blocking for i in covering) else "silent")
    want = _key(truth.op) if truth.op is not None else b""
    exact = [i for i in covering if (op := op_of(i.draft)) is not None and _key(op) == want]
    if exact:
        return scored("exact_ready" if any(not i.blocking for i in exact) else "exact_flagged")
    if any(i.blocking for i in covering):
        return scored("wrong_blocked")
    return scored("wrong_warned" if any(i.issues for i in covering) else "wrong_silent")


@dataclass(frozen=True, slots=True)
class Summary:
    docs: int
    outcomes: dict[str, dict[str, int]]  # 정답 종류 → 결과 → 수
    expected: dict[str, tuple[int, int]]  # 기대 문제 코드 → (뜬 수, 기대 수)
    items: int
    stray_items: int
    stray_blocking: int
    by_tag: dict[str, dict[str, int]]
    by_style: dict[str, dict[str, int]]

    def rate(self, kind: str, *outcomes: str) -> float | None:
        counts = self.outcomes.get(kind, {})
        total = sum(counts.values())
        return sum(counts.get(o, 0) for o in outcomes) / total if total else None


def summarize(scores: Sequence[DocScore]) -> Summary:
    outcomes: dict[str, Counter[str]] = {}
    expected: dict[str, list[int]] = {}
    by_tag: dict[str, Counter[str]] = {}
    by_style: dict[str, Counter[str]] = {}
    for doc in scores:
        for s in doc.truths:
            kind = s.truth.kind if s.truth.kind != "change" or s.truth.exists else "missing_target"
            outcomes.setdefault(kind, Counter())[s.outcome] += 1
            for code in s.truth.expect:
                pair = expected.setdefault(code.value, [0, 0])
                pair[1] += 1
                pair[0] += code in s.expected_hits
            for tag in s.truth.tags or ("plain",):
                by_tag.setdefault(tag, Counter())[s.outcome] += 1
            by_style.setdefault(doc.doc.style, Counter())[s.outcome] += 1
    return Summary(
        docs=len(scores),
        outcomes={k: dict(v) for k, v in sorted(outcomes.items())},
        expected={k: (v[0], v[1]) for k, v in sorted(expected.items())},
        items=sum(d.items for d in scores),
        stray_items=sum(d.stray_items for d in scores),
        stray_blocking=sum(d.stray_blocking for d in scores),
        by_tag={k: dict(v) for k, v in sorted(by_tag.items())},
        by_style={k: dict(v) for k, v in sorted(by_style.items())},
    )
