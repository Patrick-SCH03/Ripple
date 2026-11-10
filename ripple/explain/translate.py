"""현장 통보문 번역 초안(계약 1.36.0, docs/records.md(통보) 6절): 작업반 메일 초안 → 언어마다 MailTranslation.

외부 AI 없이 결정적이다(같은 입력 → 같은 출력, real 모드에서도 같다).
- 글 블록: 같은 템플릿 ID의 언어별 문장(Glossary.sentences)에 엔터티 이름을 끼운다.
  이름은 용어집으로 바꾸고 원문을 괄호에.
- 수치 블록: 언어별 라벨 + 결과 필드 값. 날짜는 YYYY-MM-DD(원문과 같은 숫자). 언어 문장이 없는 블록은 원문 그대로 둔다.
- 관련 건 줄의 변경 제목은 사용자가 쓴 자유 문장이라 한국어 그대로 두고 원문 표시를 붙인다.
- 끝에 '주요 용어' 문단: 원문에 나온 용어집 용어(한국어 – 번역).
한국어 원문 초안은 바꾸지 않는다(번역은 덧붙이기만).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from string import Formatter

from ripple.contracts.assistant import EmailDraft
from ripple.contracts.explain import RenderedBlock, RenderedText, TextPart
from ripple.contracts.result import AnalysisResult, ZeroLossDeadline
from ripple.contracts.translation import Glossary, MailTranslation

from .mail import CAUSE_LABELS
from .metrics import metric_value
from .templates import TEMPLATES
from .terms import TermTable, key_terms

CREW_TEMPLATES = (
    "mail.crew.intro",
    "mail.heading.activity",
    "mail.heading.part",
    "mail.heading.schedule",
    "mail.heading.request",
    "mail.item.activity",
    "mail.item.part",
    "mail.crew.status",
    "mail.crew.subcontract",
    "mail.crew.closing",
    "mail.thanks",
)
"""작업반 메일(ripple/explain/mail.py crew_mail)이 쓰는 템플릿 — 모든 언어에 문장이 있어야 한다."""
FRAME_SLOTS = {
    "frame.subject.crew": 2,  # 호선 · 기록 번호
    "frame.salutation": 1,  # 받는 쪽 이름
    "frame.reference": 0,
    "frame.hull": 1,
    "frame.source": 1,
    "frame.cause": 1,
    "frame.sign_off": 0,
    "frame.terms": 0,
}
"""메일 머리·끝 문장과 자리 수."""
CREW_METRICS = ("timing.deadline",)
KEY_TERMS_SHOWN = 12
TERMS_HEADING = "translation.terms"
TERMS_ITEM = "translation.term"


def glossary_problems(glossary: Glossary) -> list[str]:
    """작업반 메일 번역에 필요한 문장·라벨이 모두 있고 {0} 자리 수가 한국어 템플릿과 같은가(앱 시작·검사가 쓴다)."""
    problems: list[str] = []
    wanted = {**{t: len(TEMPLATES[t].slots) for t in CREW_TEMPLATES}, **FRAME_SLOTS}
    for key, slots in wanted.items():
        texts = glossary.sentences.get(key)
        if texts is None:
            problems.append(f"문장 없음: {key}")
            continue
        for code, text in texts.items():
            found = sorted({int(f) for _, f, _, _ in Formatter().parse(text) if f is not None and f.isdigit()})
            if found != list(range(slots)):
                problems.append(f"{key}.{code}: 자리 {found} · 필요 {list(range(slots))}")
    problems += [f"수치 라벨 없음: {key}" for key in CREW_METRICS if key not in glossary.metrics]
    return problems


def translate_mail(email: EmailDraft, result: AnalysisResult, glossary: Glossary, recipient: str) -> EmailDraft:
    """작업반 메일 초안에 언어마다 번역 초안을 덧붙인다(languages 순서)."""
    found = tuple(_Translator(glossary, code, result).mail(email, recipient) for code in glossary.languages)
    return email.model_copy(update={"translations": found})


class _Translator:
    def __init__(self, glossary: Glossary, code: str, result: AnalysisResult) -> None:
        self.glossary = glossary
        self.code = code
        self.result = result
        self.table = TermTable({ko: texts[code] for ko, texts in glossary.terms.items()})
        self.missing: list[str] = []

    def mail(self, email: EmailDraft, recipient: str) -> MailTranslation:
        change = self.result.request.change
        ships = "·".join(change.ship_ids)
        language = self.glossary.languages[self.code]
        paragraphs = [self._paragraph(p) for p in email.paragraphs]
        originals = [email.subject, email.reference, *(b.text for p in email.paragraphs for b in p.blocks)]
        terms = key_terms(originals, {ko: t[self.code] for ko, t in self.glossary.terms.items()}, KEY_TERMS_SHOWN)
        if terms:
            paragraphs.append(self._terms_paragraph(terms))
        organization = email.to[0].organization if email.to else recipient
        return MailTranslation(
            language=self.code,
            language_name=language.name,
            notice=language.notice,
            notice_ko=self.glossary.notice_ko,
            subject=self._frame("frame.subject.crew", ships, change.ecn_id),
            salutation=self._frame("frame.salutation", self._name(organization)),
            reference_label=self._frame("frame.reference"),
            reference=self._reference()[:600],
            paragraphs=tuple(paragraphs),
            sign_off=self._frame("frame.sign_off"),
            sender=self._name(email.sender) if email.sender else None,
            untranslated=tuple(dict.fromkeys(self.missing)),
        )

    def _frame(self, key: str, *values: str) -> str:
        return self.glossary.sentences[key][self.code].format(*values)

    def _name(self, korean: str) -> str:
        termed = self.table.name(korean)
        self.missing += termed.missing
        return termed.text

    def _reference(self) -> str:
        """관련 건 줄: 호선 · 기록 번호 + 변경 제목(자유 문장 — 원문 그대로, 표시) · 원문 번호 · 변경 원인(용어집)."""
        change = self.result.request.change
        mark = self.glossary.languages[self.code].original_mark
        title = f"{mark} {change.title}" if any("가" <= ch <= "힣" for ch in change.title) else change.title
        parts = [self._frame("frame.hull", "·".join(change.ship_ids)), f"{change.ecn_id} {title}"]
        source = change.source
        if source is not None and (source.ecn_ref or source.revision):
            ref = " ".join(p for p in (source.ecn_ref, f"Rev.{source.revision}" if source.revision else None) if p)
            parts.append(self._frame("frame.source", ref))
        if change.cause is not None:
            parts.append(self._frame("frame.cause", self._name(CAUSE_LABELS[change.cause])))
        return " · ".join(parts)

    def _paragraph(self, paragraph: RenderedText) -> RenderedText:
        return RenderedText(blocks=tuple(self._block(b) for b in paragraph.blocks), source=paragraph.source)

    def _block(self, block: RenderedBlock) -> RenderedBlock:
        if block.kind == "metric":
            return self._metric(block)
        texts = self.glossary.sentences.get(block.template_id or "")
        if texts is None:
            return self._kept(block)
        names = {p.entity_id: p.text for p in block.parts if p.entity_id}
        parts = _fill(texts[self.code], block.entity_ids, {e: self._name(names.get(e, e)) for e in block.entity_ids})
        return block.model_copy(update={"text": "".join(p.text for p in parts), "parts": parts})

    def _metric(self, block: RenderedBlock) -> RenderedBlock:
        """'- Decision deadline: 2026-10-31'. 언어 라벨이 없거나 날짜가 아닌 값이면 원문 그대로."""
        labels = self.glossary.metrics.get(block.metric or "")
        entity = block.entity_ids[0] if block.entity_ids else None
        value = metric_value(self.result, block.metric or "", entity)
        if isinstance(value, ZeroLossDeadline):
            value = value.last_day
        if labels is None or not isinstance(value, date):
            return self._kept(block)
        head = f"- {labels[self.code]}: "
        parts = (TextPart(text=head), TextPart(text=value.isoformat(), value=True))
        return block.model_copy(update={"text": head + value.isoformat(), "parts": parts})

    def _kept(self, block: RenderedBlock) -> RenderedBlock:
        """번역 문장이 없는 블록: 한국어 그대로 두고 번역 안 한 말로 남긴다."""
        self.missing.append(block.text)
        return block

    def _terms_paragraph(self, terms: Sequence[tuple[str, str]]) -> RenderedText:
        heading = RenderedBlock(kind="text", text=self._frame("frame.terms"), template_id=TERMS_HEADING)
        items = [
            RenderedBlock(kind="text", text=f"- {korean} – {translated}", template_id=TERMS_ITEM)
            for korean, translated in terms
        ]
        return RenderedText(blocks=(heading, *items), source="template")


def _fill(sentence: str, entities: Sequence[str], names: Mapping[str, str]) -> tuple[TextPart, ...]:
    """언어 문장을 자리({0} …)에서 나눠 글 조각과 엔터티 이름 조각으로(한국어 렌더러와 같은 조각 규칙)."""
    parts: list[TextPart] = []
    for literal, slot, _, _ in Formatter().parse(sentence):
        if literal:
            parts.append(TextPart(text=literal))
        if slot is None:
            continue
        entity = entities[int(slot)]
        parts.append(TextPart(text=names[entity] or entity, entity_id=entity))
    return tuple(parts)
