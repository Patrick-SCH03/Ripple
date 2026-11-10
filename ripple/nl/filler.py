"""슬롯 채우기 도구: 슬롯 값과 근거 자리·채움 방법, 확인할 것을 모으고, 어느 슬롯에도 쓰지 않은 표현을
확인할 것으로 남긴다. 연산마다 무엇을 채우는지는 fill_ops에 있다."""

from __future__ import annotations

from collections.abc import Sequence

from ripple.contracts.assistant import FillMethod, SlotFill, SlotValue, SourceSpan
from ripple.contracts.decision import NONE_OPTION
from ripple.contracts.domain import PartKind

from .fill_types import NUMERIC_SLOTS, TEXT_ISSUE, SlotIssue, TargetPick
from .interpret import Interpretation
from .ref_types import Mention
from .resolve import deterministic_part
from .specs import SpecChoice
from .values import Certainty, Measure, Normalized, NormalizedText, normalize_measure, split_usable
from .vocab import MapVocabulary


class Filler:
    def __init__(
        self,
        interp: Interpretation,
        original: str,
        ship_ids: tuple[str, ...],
        vocab: MapVocabulary,
        slots: dict[str, SlotFill],
        issues: list[SlotIssue],
    ) -> None:
        self.interp = interp
        self.original = original
        self.ship_ids = ship_ids
        self.vocab = vocab
        self.slots = slots
        self.issues = issues
        self.used: set[tuple[int, int]] = set()  # 슬롯에 쓴 부재 표현
        self.used_specs: set[tuple[int, int]] = set()  # 슬롯에 쓴 규격 표기
        self.used_grades: set[tuple[int, int]] = set()  # 슬롯에 쓴 강종 표기

    def span(self, span: tuple[int, int] | None) -> SourceSpan | None:
        if span is None or span[1] <= span[0]:
            return None
        return SourceSpan(start=span[0], end=span[1], text=self.original[span[0] : span[1]])

    def put(self, slot: str, value: SlotValue, method: FillMethod, span: tuple[int, int] | None = None) -> None:
        self.slots[slot] = SlotFill(value=value, method=method, span=self.span(span))

    def issue(self, slot: str, reason: str, **extra: object) -> None:
        self.issues.append(SlotIssue(slot=slot, reason=reason, **extra))  # type: ignore[arg-type]

    def leftovers(self, op: str) -> None:
        """문장에 있는데 어느 슬롯에도 쓰지 않은 부재 표현·숫자·규격·강종과 읽지 못한 번호 범위는
        조용히 버리지 않고 확인할 것으로 둔다."""
        text = self.interp.text
        for mention in self.interp.refs.mentions:
            if mention.span not in self.used:
                piece = text[mention.phrase[0] : mention.phrase[1]] or mention.text
                self.issue(TEXT_ISSUE, f"쓰이지 않은 표현 '{piece}'", span=mention.span)
        for span, reason in self.interp.refs.unread:
            self.issue(TEXT_ISSUE, f"'{text[span[0] : span[1]]}': {reason}", span=span)
        for token in self.interp.refs.specs:
            if token.span not in self.used_specs:
                piece = text[token.start : token.end]
                self.issue(TEXT_ISSUE, f"쓰이지 않은 규격 '{piece}'", span=token.span)
        for grade in self.interp.grades:
            if (grade.start, grade.end) not in self.used_grades:
                piece = text[grade.start : grade.end]
                self.issue(TEXT_ISSUE, f"쓰이지 않은 강종 '{piece}'", span=(grade.start, grade.end))
        measure = NUMERIC_SLOTS.get(op)
        _, unusable = split_usable(self.interp.values, measure) if measure else ((), self.interp.values)
        for expr in unusable:
            piece = text[expr.span[0] : expr.span[1]]
            self.issue(TEXT_ISSUE, f"쓰이지 않은 숫자 '{piece}'", span=expr.span)

    def targets(self, targets: Sequence[TargetPick], label: str) -> list[str] | None:
        """보정 슬롯(part_ids). 대상이 없거나 '해당 없음'이 있으면 None(다시 묻기)."""
        if not targets:
            self.issue("part_ids", f"문장에 {label} 없음")
            return None
        if any(t.part_id is None or t.part_id == NONE_OPTION for t in targets):
            return None  # 판단 계층 질문(다시 설명)으로 묻는다
        ids = sorted({str(t.part_id) for t in targets})
        method = FillMethod.USER if all(t.method is FillMethod.USER for t in targets) else FillMethod.DECISION
        start = min(t.mention.start for t in targets)
        end = max(t.mention.end for t in targets)
        self.put("part_ids", tuple(ids), method, (start, end))
        return ids

    def current(self, part_ids: Sequence[str], attribute: str, label: str, slot: str) -> object | None:
        values: set[object] = {getattr(self.vocab.parts[p].part, attribute) for p in part_ids if p in self.vocab.parts}
        if len(values) == 1:
            value = next(iter(values))
            if isinstance(value, str | float):
                self.put(slot, value, FillMethod.MAP)
                return value
        if len(values) > 1:
            self.issue(slot, f"고른 부재들의 지금 {label} 서로 다름")
        return None

    def measure(self, slot: str, measure: Measure, current: float | None, before_slot: str | None = None) -> None:
        result = normalize_measure(self.interp.values, measure, current)
        self._apply_measure(slot, result, before_slot)

    def _apply_measure(self, slot: str, result: Normalized, before_slot: str | None) -> None:
        if before_slot is not None and result.before is not None and before_slot not in self.slots:
            method = FillMethod.MAP if result.before_from_map else FillMethod.RULE
            self.put(before_slot, float(result.before), method, None if result.before_from_map else result.span)
        if result.after is None:
            self.issue(slot, result.reason or "값 없음", span=result.span)
            return
        method = FillMethod.RULE if result.certainty is Certainty.RULE else FillMethod.GUESS
        self.put(slot, float(result.after), method, result.span)
        if method is FillMethod.GUESS:
            self.issue(
                slot,
                result.reason or "값 확인 필요",
                proposal=float(result.after),
                span=result.span,
                map_mismatch=result.map_mismatch,
            )

    def text_value(self, slot: str, result: NormalizedText) -> None:
        if result.after is None:
            self.issue(slot, result.reason or "값 없음", span=result.span)
            return
        method = FillMethod.RULE if result.certainty is Certainty.RULE else FillMethod.GUESS
        self.put(slot, result.after, method, result.span)
        if method is FillMethod.GUESS:
            self.issue(
                slot,
                result.reason or "값 확인 필요",
                proposal=result.after,
                span=result.span,
                map_mismatch=result.map_mismatch,
            )

    def spec_value(self, slot: str, choice: SpecChoice, guessed: bool = False) -> None:
        if choice.spec_id is None:
            self.issue(slot, choice.reason or "규격 미정", options=choice.candidates, span=choice.span)
            return
        method = FillMethod.GUESS if guessed else FillMethod.RULE
        self.put(slot, choice.spec_id, method, choice.span)
        if guessed:
            self.issue(
                slot,
                "같은 강종으로 선택 · 맞는지 확인 필요",
                proposal=choice.spec_id,
                options=choice.candidates,
                span=choice.span,
            )

    def role_parts(
        self, slot: str, mentions: Sequence[Mention], label: str, kinds: Sequence[PartKind]
    ) -> list[str] | None:
        """역할 부재를 결정적 일치로만 정한다. 하나라도 못 정하면 확인할 것으로 돌리고 None."""
        self.used.update(m.span for m in mentions)
        found: list[str] = []
        for mention in mentions:
            part_id = deterministic_part(mention, self.vocab, self.ship_ids)
            if part_id is None or (kinds and self.vocab.parts[part_id].part.kind not in kinds):
                self.issue(slot, f"{label} 하나로 특정 불가", span=mention.span)
                return None
            found.append(part_id)
        return list(dict.fromkeys(found))

    def role_part(self, slot: str, mention: Mention | None, label: str, kinds: Sequence[PartKind]) -> str | None:
        if mention is None:
            self.issue(slot, f"문장에 {label} 없음")
            return None
        found = self.role_parts(slot, [mention], label, kinds)
        if not found:
            return None
        self.put(slot, found[0], FillMethod.RULE, mention.span)
        return found[0]
