"""문장 해석 라벨(판단 계층 보정·평가용): 읽은 결과(Reading)를 문장 정답(NlSample)과 맞춘다.

- 연산·의도 라벨은 정답 요청의 연산·의도다.
- 대상 질문의 라벨은 그 표현과 겹치는 정답 대상 조각의 부재(지도에 있고 후보 안에 있으면), 아니면 '해당 없음'.
  후보 재현율은 이 라벨과 따로, 정답 대상이 지도에 있는 표현 중 후보 안에 든 비율로 센다.
- 단위 정답(sound)은 초안이 자격을 갖췄을 때 조립한 요청의 연산·의도가 정답과 같은지다(빠진 대상 표현·
  잘못 채운 결정적 슬롯도 오답). 자격이 없는 단위는 자동 진행하지 않으므로 판단 밖 부분을 따지지 않는다.
학습 자료는 정답 연산으로 의도·대상 질문을 만든다(teacher forcing). 평가는 예측한 연산을 쓴다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ripple.contracts.change import ChangeRequest
from ripple.contracts.dataset import MentionTruth, NlSample
from ripple.contracts.decision import NONE_OPTION, DecisionTopic
from ripple.contracts.identity import canonical_json, normalized_op
from ripple.contracts.lexicon import Lexicon
from ripple.decide.policy import Decision, ScoredCase, Unit
from ripple.decide.scorer import Example
from ripple.nl.pipeline import Fixed, Models, Reading, Scored, read
from ripple.nl.vocab import MapVocabulary

TARGET_SLOT = "part_ids"


@dataclass(frozen=True, slots=True)
class Labeled:
    sample: NlSample
    reading: Reading
    op_label: str
    intent_label: str
    target_labels: tuple[str, ...]  # 대상 질문 순서대로
    covered: bool  # 정답 대상 조각마다 겹치는 대상 질문이 있음
    candidate_hits: int  # 지도에 있는 정답 대상 중 후보 안에 든 수
    candidate_total: int  # 지도에 있는 정답 대상 수

    @property
    def decisions_correct(self) -> bool:
        """요청 문 판단(연산·대상)이 모두 정답. 변경 사유는 사유 문(intent_unit)으로 따로 본다."""
        tops = [self.reading.op.top, *(t.top for t in self.reading.targets)]
        labels = [self.op_label, *self.target_labels]
        return tops == labels

    @property
    def sound(self) -> bool:
        if not self.reading.proposal.ready:
            return True
        draft = self.reading.proposal.draft
        return same_change(draft.to_change(ecn_id="X", title="x"), self.sample.change, intent=False)

    @property
    def correct(self) -> bool:
        """자동 진행 자격이 있고 조립한 요청이 정답과 같음(자동 진행해도 되는 해석)."""
        return self.reading.proposal.ready and self.decisions_correct and self.sound

    def unit(self) -> Unit:
        """요청 문 단위: 연산·대상 판단 + 판단 밖 자격(초안)."""
        decisions = [
            Decision(DecisionTopic.CHANGE_OP, _case(self.reading.op, self.op_label)),
            *(
                Decision(DecisionTopic.TARGET_PART, _case(t, label))
                for t, label in zip(self.reading.targets, self.target_labels, strict=True)
            ),
        ]
        return Unit(tuple(decisions), ready=self.reading.proposal.ready, sound=self.sound)

    def intent_unit(self) -> Unit:
        """사유 문 단위: 의도 판단 하나(분석 뒤 기록이라 초안 자격과 무관)."""
        return Unit((Decision(DecisionTopic.CHANGE_INTENT, _case(self.reading.intent, self.intent_label)),))


def same_change(a: ChangeRequest, b: ChangeRequest, intent: bool = True) -> bool:
    """연산·호선(intent면 변경 사유까지)이 같은지(제목·번호·원문은 보지 않음)."""
    return (
        (not intent or a.intent is b.intent)
        and sorted(a.ship_ids) == sorted(b.ship_ids)
        and sorted(canonical_json(normalized_op(op)) for op in a.ops)
        == sorted(canonical_json(normalized_op(op)) for op in b.ops)
    )


def label(sample: NlSample, reading: Reading) -> Labeled:
    truths = [m for m in sample.mentions if m.slot == TARGET_SLOT]
    labels = []
    aligned: set[int] = set()
    hits = 0
    for scored in reading.targets:
        mention = scored.posed.mention
        assert mention is not None
        index, truth = _overlap(truths, (mention.start, mention.end))
        value = NONE_OPTION
        if truth is not None:
            aligned.add(index)
            if truth.exists and str(truth.value) in scored.scores:
                value = str(truth.value)
        labels.append(value)
    for truth in truths:
        if not truth.exists:
            continue
        options = [
            s.scores
            for s in reading.targets
            if s.posed.mention is not None and _overlaps((s.posed.mention.start, s.posed.mention.end), truth)
        ]
        hits += any(str(truth.value) in o for o in options)
    if sample.change.intent is None:
        raise ValueError(f"{sample.sample_id}: 문장 사례의 정답에는 변경 사유가 있어야 해요")
    return Labeled(
        sample=sample,
        reading=reading,
        op_label=sample.change.ops[0].op,
        intent_label=sample.change.intent.value,
        target_labels=tuple(labels),
        covered=len(aligned) == len(truths),
        candidate_hits=hits,
        candidate_total=sum(t.exists for t in truths),
    )


def read_and_label(
    samples: Sequence[NlSample], vocab: MapVocabulary, lexicon: Lexicon, models: Models, teacher: bool = False
) -> list[Labeled]:
    """teacher=True면 정답 연산으로 의도·대상 질문을 만든다(학습 자료용)."""
    found = []
    for sample in samples:
        fixed = Fixed(op=sample.change.ops[0].op) if teacher else None
        reading = read(sample.text, (sample.ship_id,), vocab, lexicon, models, fixed)
        found.append(label(sample, reading))
    return found


def training_examples(labeled: Sequence[Labeled]) -> dict[DecisionTopic, list[Example]]:
    examples: dict[DecisionTopic, list[Example]] = {topic: [] for topic in _TOPICS}
    for item in labeled:
        reading = item.reading
        examples[DecisionTopic.CHANGE_OP].append(_example(reading.op, item.op_label))
        examples[DecisionTopic.CHANGE_INTENT].append(_example(reading.intent, item.intent_label))
        for scored, value in zip(reading.targets, item.target_labels, strict=True):
            examples[DecisionTopic.TARGET_PART].append(_example(scored, value))
    return examples


_TOPICS = (DecisionTopic.CHANGE_OP, DecisionTopic.CHANGE_INTENT, DecisionTopic.TARGET_PART)


def _example(scored: Scored, value: str) -> Example:
    options = scored.posed.question.option_ids
    return Example(options=options, features=tuple(scored.posed.features[o] for o in options), label=value)


def _case(scored: Scored, value: str) -> ScoredCase:
    options = scored.posed.question.option_ids
    return ScoredCase(option_ids=options, scores=tuple(scored.scores[o] for o in options), label=value)


def _overlap(truths: Sequence[MentionTruth], span: tuple[int, int]) -> tuple[int, MentionTruth | None]:
    for index, truth in enumerate(truths):
        if _overlaps(span, truth):
            return index, truth
    return -1, None


def _overlaps(span: tuple[int, int], truth: MentionTruth) -> bool:
    return span[0] < truth.end and truth.start < span[1]
