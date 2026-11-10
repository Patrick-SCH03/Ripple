"""AI 값과 규칙 값 맞추기(순수 계산, docs/input.md(문서 접수)): 규칙이 못 채운 수치·강종·치수 종류 칸만 AI 값으로
채우고('AI 추정'), 견줄 수 있을 때만 서로 다른 값을 불일치로 알린다. 지도 ID 칸(대상·규격·블록·종류)은 채우지 않는다."""

from __future__ import annotations

import math
import re

from ripple.contracts.assistant import NUMBER_KINDS, ChangeDraft, FillMethod, SlotFill, SlotKind, SlotSpec
from ripple.contracts.intake import AiReading, IntakeIssue, IntakeIssueCode
from ripple.nl.draft import RELATIVE_WORDS

from .item_issues import issue

NUMBER = re.compile(r"\d+(?:\.\d+)?")
"""글에 적힌 숫자(소수 포함, 부호·천 단위 쉼표 없음). AI 값의 숫자를 원문과 견줄 때 쓴다(값 맞추기·build 인용 검증)."""
_AI_FILLABLE = frozenset({SlotKind.MILLIMETER, SlotKind.QUANTITY, SlotKind.GRADE, SlotKind.DIMENSION})
"""AI 값이 들어갈 수 있는 칸 종류. 대상·규격·블록·종류 칸은 지도 ID라 해석기 후보나 비서로만 정한다."""


def with_ai(draft: ChangeDraft, ai: AiReading) -> tuple[ChangeDraft, list[IntakeIssue]]:
    """AI 값과 규칙 값을 맞춰 본다: 규칙이 못 채운 수치·강종 칸은 AI 값으로(AI 추정), 서로 다르면 불일치."""
    issues: list[IntakeIssue] = []
    slots = dict(draft.slots)
    for spec, raw in _ai_values(draft, ai):
        if spec.kind not in _AI_FILLABLE:
            continue
        if spec.kind in NUMBER_KINDS and not _PLAIN_VALUE.match(raw):
            continue
        value = _ai_value(spec, raw)
        if value is None:
            continue
        current = slots.get(spec.name)
        if current is None:
            slots[spec.name] = SlotFill(value=value, method=FillMethod.LLM)
        elif (
            current.method is not FillMethod.MAP
            and current.value != value
            and _comparable(current.value, raw, draft.text)
        ):
            message = (
                f"{spec.label}: 규칙은 {current.value:g}, AI는 {value:g}로 해석"
                if isinstance(value, float) and isinstance(current.value, float)
                else f"{spec.label}: 규칙과 AI 해석이 다름"
            )
            issues.append(issue(IntakeIssueCode.LLM_RULE_DISAGREE, message, spec.name))
    if slots != draft.slots:
        draft = ChangeDraft.model_validate({**draft.model_dump(), "slots": slots})
    return draft, issues


_PLAIN_VALUE = re.compile(r"^\s*\d+(?:\.\d+)?\s*(?:mm|MM|T|t|톤|kg|KG|ea|EA|개|m)?\s*(?:으로|로)?\s*$")
"""AI 값이 그대로 쓸 수 있는 값 꼴(숫자 + 단위). 규격·증감 표현은 값 칸에 넣지도 견주지도 않는다."""


def _comparable(rule_value: str | float | tuple[str, ...], raw: str, text: str) -> bool:
    """규칙 값과 AI 값을 견줄 수 있는가: AI 값이 '숫자(+단위)' 꼴이고, 조각에 증감·비율 표현이 없고, 규칙 값이 원문에
    그대로 적힌 값일 때만. 증감·비율·단위 환산으로 계산한 값('3mm 증가' → 20mm, '295kg' → 0.295t)이나 AI가 규격
    ('HP280x12-AH36')을 값 칸에 낸 경우는 다르게 보일 뿐이라 견주지 않는다(견주면 정확히 읽은 항목도
    이 불일치로 막힌다). 증감 말은 해석기(RELATIVE_WORDS)와 같은 목록을 쓴다 — 따로 두면 '올리기'처럼 한쪽에만 있는
    말에서 해석기는 증감으로 계산하고 여기서는 견주게 된다."""
    if isinstance(rule_value, float):
        if not _PLAIN_VALUE.match(raw) or RELATIVE_WORDS.search(text):
            return False
        return any(math.isclose(float(n), rule_value) for n in NUMBER.findall(text.replace(",", "")))
    if isinstance(rule_value, str):
        return rule_value.upper() in text.upper()
    return False


def _ai_values(draft: ChangeDraft, ai: AiReading) -> list[tuple[SlotSpec, str]]:
    """AI의 전·후 값을 이 연산의 슬롯에 맞춘다. 지도에서 오는 지금 값 칸은 AI 값으로 채우지 않는다(지도가 기준)."""
    specs = draft.specs()
    befores = [s for s in specs if not s.from_map and s.name.startswith("from")]
    afters = [s for s in specs if s.name.startswith("to") or s.name in {"qty", "diameter_mm"}]
    pairs: list[tuple[SlotSpec, str]] = []
    if ai.before and befores:
        pairs.append((befores[0], ai.before))
    if ai.after and afters:
        pairs.append((afters[0], ai.after))
    return pairs


def _ai_value(spec: SlotSpec, raw: str) -> str | float | None:
    if spec.kind in NUMBER_KINDS:
        match = NUMBER.search(raw)
        if match is None:
            return None
        value = float(match.group(0))
        return value if value > 0 else None
    text = raw.strip().upper()
    return text or None
