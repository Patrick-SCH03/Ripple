"""외부 생성 모델에 맡기는 일 가운데 비서의 두 가지(합성 모드만, ripple.llm.Guarded 경계 뒤). 셋째인 문서 항목
뽑기(1.27.0)는 문서 접수 조율(ripple/agent/intake.py)에 있다(docs/input.md(문서 접수)).

1. 설명 블록 고르기(B8): 서버 글 템플릿 ID와 이 분석에서 값이 있는 수치 키만 고른다. 자유 글은 받지 않는다.
   고른 블록은 렌더러 검사(사실 조건 포함, ripple.explain.render.check)를 통과한 것만 쓰고, 판정·이유·총비용·마감일은
   엔진 결과로 채운다. 판정·이유 말고 통과한 블록이 둘 미만이면 기본 순서를 쓴다.
2. 해석 보조(B4): 규칙 기반이 못 읽은 요청을 정규 문장으로 다시 쓰게 하고, 그 문장을 다시 결정적으로 읽는다.
   다시 쓴 문장에는 원문에 없는 숫자가 있으면 안 된다(지도 코드·규격 ID 안의 숫자는 지도와 대조).
   다시 쓴 해석은 LLM이 채운 것으로 보고 항상 확인받는다(자동 진행 없음).
"""

from __future__ import annotations

import re

from ripple.contracts.assistant import INTENT_LABELS, OP_LABELS
from ripple.contracts.decision import NONE_OPTION
from ripple.contracts.explain import METRICS, Explanation, ExplanationBlock, MetricBlock, TemplateBlock
from ripple.contracts.result import AnalysisResult
from ripple.explain.metrics import available_metrics
from ripple.explain.render import Directory, check, name_of, result_entities
from ripple.explain.templates import REASONS, TEMPLATES, VERDICT_TEMPLATES, Use
from ripple.llm.base import Guarded, LlmBlocked, LlmUnavailable
from ripple.nl.fill_types import TEXT_ISSUE
from ripple.nl.pipeline import Reading
from ripple.nl.vocab import MapVocabulary

EXPLAIN_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["template", "metric"]},
                    "id": {"type": "string"},
                    "entities": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["kind", "id"],
            },
        }
    },
    "required": ["blocks"],
}

REWRITE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "understood": {"type": "boolean"},
        "request": {"type": "string"},
    },
    "required": ["understood", "request"],
}

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


ESSENTIAL_METRICS = ("cost.total", "timing.deadline")
"""설명 앞머리에 늘 들어가는 수치(기본 설명과 같은 핵심 정보)."""


def pick_explanation(llm: Guarded, result: AnalysisResult, directory: Directory) -> Explanation | None:
    """LLM이 고른 설명 블록. 앞머리는 엔진 결과로 고정하고 LLM은 그 뒤만 고른다.

    앞머리 = 엔진 판정 → 판정 이유 → 총비용 → 마감일(LLM이 고른 판정 블록·앞머리 수치는 버림). 뒤는 검사(사실 조건
    포함)를 통과한 블록만, 같은 블록은 한 번만. 뒤에 남는 블록이 둘 미만이면 None(기본 순서).
    """
    if not llm.usable:
        return None
    try:
        data = llm.generate_json(
            _explain_prompt(result, directory),
            EXPLAIN_SCHEMA,
            timeout_s=10.0,
            task="explain",
            accept=lambda answer: bool(_parse_blocks(answer)),
        )
    except (LlmBlocked, LlmUnavailable):
        return None
    blocks = _parse_blocks(data)
    if not blocks:
        return None
    explanation = Explanation(blocks=tuple(blocks[:12]), source="llm")
    bad = {int(problem.split(":", 1)[0]) for problem in check(explanation, result)}
    head: list[ExplanationBlock] = [
        TemplateBlock(template_id=VERDICT_TEMPLATES[result.verdict.level]),
        TemplateBlock(template_id=REASONS),
        *(MetricBlock(metric=m) for m in ESSENTIAL_METRICS),
    ]
    seen = {_block_key(block) for block in head}
    rest: list[ExplanationBlock] = []
    for index, block in enumerate(explanation.blocks):
        key = _block_key(block)
        verdict = isinstance(block, TemplateBlock) and block.template_id.startswith("verdict.")
        if index in bad or key in seen or verdict:
            continue
        seen.add(key)
        rest.append(block)
    if len(rest) < 2:
        return None
    return Explanation(blocks=(*head, *rest), source="llm")


def _block_key(block: ExplanationBlock) -> tuple[str, ...]:
    if isinstance(block, MetricBlock):
        return ("m", block.metric, block.entity_id or "")
    return ("t", block.template_id, *block.entities)


def _explain_prompt(result: AnalysisResult, directory: Directory) -> str:
    """앞머리(판정·이유·총비용·마감일)는 서버가 넣으므로 목록에서 빼고, 그 뒤에 올 블록만 고르게 한다.

    수치는 검사를 통과하는 것만 보인다(지연 0일처럼 버릴 수치를 고르지 않게).
    """
    templates = []
    for template_id, template in TEMPLATES.items():
        if template.use is Use.EXPLANATION and not template_id.startswith("verdict."):
            slots = ", ".join(slot.value for slot in template.slots)
            templates.append(f"- {template_id}: {template.text}" + (f" (엔터티: {slots})" if slots else ""))
    metrics = [
        f"- {m.metric}" + (f" [{m.entity_id}]" if m.entity_id else "") + f": {METRICS[m.metric].label}"
        for m in available_metrics(result)
        if m.metric != "cost.line"
        and not (m.metric in ESSENTIAL_METRICS and m.entity_id is None)
        and not check(Explanation(blocks=(m,), source="llm"), result)
    ]
    entities = []
    for slot, ids in result_entities(result).items():
        for entity in sorted(ids)[:12]:
            entities.append(f"- {slot.value} {entity}: {name_of(entity, result, directory)}")
    facts = [
        f"판정: {result.verdict.level.value} — " + " / ".join(result.verdict.reasons),
        f"영향 종류: {', '.join(sorted({i.impact_type.value for i in result.impacts}))}",
        f"보류 권고 발주: {', '.join(h.po_id for h in result.timing.holds) or '없음'}",
        f"판단 불가 항목: {len(result.unresolved)}",
    ]
    return "\n".join(
        [
            "조선소 설계변경 분석 결과를 담당자에게 설명할 블록을 고르세요. "
            "글을 직접 쓰지 말고 아래 목록의 ID만 고릅니다.",
            "수치는 수치 키로만 넣고(값은 서버가 씁니다), 템플릿의 엔터티 자리에는 아래 엔터티 ID만 넣으세요.",
            "판정·판정 이유·총비용·마감일은 서버가 맨 앞에 넣습니다. 그 뒤에 이어질 블록을 "
            "일정 지연 → 해야 할 일(보류·재작업) → 확인할 것 순으로 3~8개 고르세요. "
            "사실이 아닌 문장은 서버가 버립니다.",
            "",
            "[분석 요약]",
            *facts,
            "",
            "[글 템플릿]",
            *templates,
            "",
            "[수치 키]",
            *metrics,
            "",
            "[엔터티]",
            *entities,
            "",
            '응답 형식: {"blocks": [{"kind": "metric", "id": "schedule.max_exit_delay"}, '
            '{"kind": "template", "id": "impact.rework", "entities": ["S-001:T31C"]}, '
            '{"kind": "template", "id": "next.review"}]}',
        ]
    )


def _parse_blocks(data: object) -> list[ExplanationBlock]:
    if not isinstance(data, dict) or not isinstance(data.get("blocks"), list):
        return []
    blocks: list[ExplanationBlock] = []
    for item in data["blocks"]:
        if not isinstance(item, dict):
            continue
        kind, ident = item.get("kind"), item.get("id")
        entities = [e for e in item.get("entities") or [] if isinstance(e, str)]
        try:
            if kind == "metric" and isinstance(ident, str):
                blocks.append(MetricBlock(metric=ident, entity_id=entities[0] if entities else None))
            elif kind == "template" and isinstance(ident, str):
                blocks.append(TemplateBlock(template_id=ident, entities=tuple(entities)))
        except ValueError:
            continue  # 계약에 맞지 않는 블록은 버린다
    return blocks


def rewrite_wanted(reading: Reading) -> bool:
    """규칙 기반이 못 읽은 곳(연산·대상 '해당 없음', 다시 설명할 것, 빠진 값)이 있음 — 다시 쓰기를 부를 조건
    (비서 흐름과 scripts/compare_llm.py가 같이 쓴다)."""
    proposal = reading.proposal
    unread = reading.op.top == NONE_OPTION or any(t.top == NONE_OPTION for t in reading.targets)
    return unread or bool(proposal.draft.missing()) or any(i.slot == TEXT_ISSUE for i in proposal.issues)


def rewrite_request(llm: Guarded, text: str, vocab: MapVocabulary) -> str | None:
    """규칙 기반이 못 읽은 요청을 정규 문장으로. 원문에 없는 숫자가 생기면 버린다.

    경로가 여러 모델이면 받아들일 만한 답을 먼저 준 모델의 답을 쓴다(빠른 빈 답·원문 반복 뒤 늦은 정상 답을 기다림).
    모델이 '이해 못 함'으로 답하면 그 판단을 최종으로 본다 — 더 조심스러운 모델의 거절을 다음 모델의 추측으로 덮지
    않는다(정확도 우선, docs/input.md(외부 AI) 2절). 그 경우 규칙 기반 질문으로 간다.
    """
    if not llm.usable:
        return None
    try:
        data = llm.generate_json(
            _rewrite_prompt(text, vocab),
            REWRITE_SCHEMA,
            timeout_s=10.0,
            task="rewrite",
            accept=lambda answer: refused(answer) or accepted_rewrite(answer, text, vocab) is not None,
        )
    except (LlmBlocked, LlmUnavailable):
        return None
    return accepted_rewrite(data, text, vocab)


def refused(data: object) -> bool:
    """모델이 '이해 못 함'으로 답함(형식은 맞음). 경로는 이 답을 최종으로 받는다."""
    return isinstance(data, dict) and data.get("understood") is False


def accepted_rewrite(data: object, text: str, vocab: MapVocabulary) -> str | None:
    """받아들일 수 있는 다시 쓰기면 정규화한 문장(앞뒤 공백 없음, 300자까지), 아니면 None.

    이해 못 함·빈 문장·원문 그대로·원문에 없는 숫자는 받지 않는다.
    """
    if not isinstance(data, dict) or not data.get("understood") or not isinstance(data.get("request"), str):
        return None
    rewritten = str(data["request"]).strip()[:300]
    if not rewritten or rewritten == text.strip() or not numbers_kept(text, rewritten, vocab):
        return None
    return rewritten


def numbers_kept(original: str, rewritten: str, vocab: MapVocabulary) -> bool:
    """다시 쓴 문장의 숫자가 모두 원문에 있음. 지도 블록 코드·규격 ID는 지도에 있으면 숫자를 따지지 않는다."""
    rest = rewritten
    for code in sorted({e.code for e in vocab.blocks.values()}, key=len, reverse=True):
        rest = re.sub(rf"(?<![A-Za-z0-9]){re.escape(code)}(?![A-Za-z0-9])", " ", rest, flags=re.IGNORECASE)
    for spec_id in sorted(vocab.specs, key=len, reverse=True):
        rest = re.sub(re.escape(spec_id), " ", rest, flags=re.IGNORECASE)
    allowed = {float(n) for n in _NUMBER.findall(original)}
    return all(float(n) in allowed for n in _NUMBER.findall(rest))


def _rewrite_prompt(text: str, vocab: MapVocabulary) -> str:
    blocks = [f"- {e.code}: {e.block.name}" for e in sorted(vocab.blocks.values(), key=lambda b: b.code)]
    ops = ", ".join(OP_LABELS.values())
    intents = ", ".join(INTENT_LABELS.values())
    return "\n".join(
        [
            "조선소 설계변경 요청을 아래 형식의 한 문장으로 다시 쓰세요. "
            "원문에 없는 숫자·부재 번호·값을 만들지 마세요.",
            "형식 예: 'T31C 판 7번 두께 15mm에서 17mm로 변경 (강도 보강)', "
            "'P11C 화물 스트리핑 글로브 밸브 1번 볼 밸브로 사양 변경 (선주 요청)'.",
            "블록은 아래 코드로, 부재는 종류(판·보강재·브라켓·스풀·밸브·서포트)와 번호로 적으세요. "
            "모르면 understood=false.",
            f"연산: {ops}. 사유: {intents}(원문에 없으면 적지 마세요).",
            "",
            "[블록]",
            *blocks,
            "",
            f"[요청] {text}",
        ]
    )
