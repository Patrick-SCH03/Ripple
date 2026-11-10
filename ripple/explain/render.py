"""블록 검증과 렌더링: 고른 블록(Explanation) → 화면 문장(RenderedText).

- 템플릿 블록: 템플릿이 있고 쓰임(설명·알림)이 맞고, 엔터티 자리 수가 맞고, 엔터티가 이 분석 결과에 있어야 한다.
  설명 템플릿은 문장이 이 결과에서 참이어야 한다(판정은 엔진 판정과 같게, 마감·보류·재작업·발주 변경·도면·판단 불가는
  그 영향이 실제로 있을 때만 — 기본 설명과 같은 조건, fact_problem).
- 수치 블록: 이 분석 결과에 값이 있어야 한다(값·문장 틀은 ripple.explain.metrics).
LLM이 고른 블록은 문제를 모아 돌려주고(check), 렌더링은 통과한 블록만 쓴다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from string import Formatter

from ripple.contracts.contacts import ContactBook
from ripple.contracts.domain import DIRECT_PERFORMER, EntityType
from ripple.contracts.explain import (
    Explanation,
    MetricBlock,
    RenderedBlock,
    RenderedText,
    TemplateBlock,
    TextBlock,
    TextPart,
)
from ripple.contracts.result import AnalysisResult, DeadlineKind, ImpactType
from ripple.contracts.translation import Glossary

from .metrics import render_metric
from .templates import REASONS, TEMPLATES, VERDICT_TEMPLATES, Slot, Use


@dataclass(frozen=True, slots=True)
class Directory:
    """분석 결과 밖의 이름·담당 정보(지도에서 만든다)."""

    names: Mapping[str, str] = field(default_factory=dict)  # 엔터티 ID → 이름(부재·블록·발주·도면·협력사)
    po_supplier: Mapping[str, str] = field(default_factory=dict)  # 발주 → 협력사 ID
    block_fabricator: Mapping[str, str | None] = field(default_factory=dict)  # 블록 → 사외 제작 협력사(없으면 사내)
    drawing_discipline: Mapping[str, str] = field(default_factory=dict)  # 도면 ID → 분야
    contacts: ContactBook | None = None  # 알림 메일 연락처(합성 지도에만, 실데이터 지도는 None)
    crew_contacts: Mapping[str, str] = field(
        default_factory=dict
    )  # 작업반 ID → 연락처 이메일(시연 지도는 가상 '.example')
    glossary: Glossary | None = None  # 1.36.0 현장 통보문(작업반 메일) 번역 초안 용어집(없으면 한국어만)


def po_of(line_id: str) -> str:
    """발주 품목 ID('PO-0130#3') → 발주 ID('PO-0130'). 품목 ID는 '{발주 ID}#{품목 번호}'이고 발주 ID에도 #가 올 수
    있어(엑셀 가져오기는 글자 그대로) 마지막 #에서 자른다. 발주 ID 자체에는 쓰지 않는다."""
    return line_id.rsplit("#", 1)[0]


def result_entities(result: AnalysisResult) -> dict[Slot, frozenset[str]]:
    """템플릿 엔터티 자리에 넣을 수 있는 이 분석의 엔터티."""
    found: dict[Slot, set[str]] = {slot: set() for slot in Slot}
    for impact in result.impacts:
        if impact.entity_type is EntityType.PART:
            found[Slot.PART].add(impact.entity_id)
        elif impact.entity_type is EntityType.BLOCK:
            found[Slot.BLOCK].add(impact.entity_id)
        elif impact.entity_type is EntityType.PO_LINE:
            found[Slot.PO].add(po_of(impact.entity_id))
        elif impact.entity_type is EntityType.PO:
            found[Slot.PO].add(impact.entity_id)
        elif impact.entity_type is EntityType.DRAWING:
            found[Slot.DRAWING].add(impact.entity_id)
        elif impact.entity_type is EntityType.ACTIVITY:
            found[Slot.ACTIVITY].add(impact.entity_id)
    found[Slot.PART].update(request_parts(result))
    found[Slot.PO].update(h.po_id for h in result.timing.holds)
    found[Slot.BLOCK].update(result.onboard.block_ids if result.onboard else ())  # 후행 설치 선택지의 블록(6-8)
    found[Slot.ACTIVITY].update(notify_activities(result))  # 사전 점검 P-06이 짚은 착수·완료 공정
    return {slot: frozenset(ids) for slot, ids in found.items()}


def notify_activities(result: AnalysisResult) -> frozenset[str]:
    """사전 점검 P-06(현장 공유)이 짚은 공정: 이미 착수·완료한 블록 공정(수행 주체 근거 연결의 출발)."""
    return frozenset(
        link.src
        for item in result.prechecks
        if item.rule_id == "P-06"
        for link in item.evidence
        if link.relation == "performed_by"
    )


def crew_activities(result: AnalysisResult) -> dict[str, list[str]]:
    """작업반 ID → P-06이 짚은 그 작업반의 공정(공정 ID 순). 직영·수행 주체 모름은 뺀다(작업반 알림 대상이 아님)."""
    found: dict[str, set[str]] = {}
    for item in result.prechecks:
        if item.rule_id != "P-06":
            continue
        for link in item.evidence:
            if link.relation == "performed_by" and link.dst != DIRECT_PERFORMER:
                found.setdefault(link.dst, set()).add(link.src)
    return {crew: sorted(ids) for crew, ids in sorted(found.items())}


def request_parts(result: AnalysisResult) -> frozenset[str]:
    """요청 연산이 가리키는 부재(변경의 대상)."""
    found: set[str] = set()
    for op in result.request.change.ops:
        for name in ("part_ids", "removed_part_ids", "crosses_part_ids"):
            found.update(getattr(op, name, ()) or ())
        for name in ("plate_part_id", "pipe_part_id", "attach_to_part_id"):
            value = getattr(op, name, None)
            if value:
                found.add(value)
    return frozenset(found)


def rework_blocks(result: AnalysisResult) -> list[str]:
    """재작업 영향이 있고 재작업 공수가 있는(R-B01 줄 금액 최대값 > 0) 블록, ID 순. 의장품만 바뀌고 선행의장 전이라
    공수가 0인 블록은 빼서 판정(8-4)과 같은 기준으로 설명·알림을 낸다(docs/engine.md(비용·일정) 4-4)."""
    worked = {line.entity_id for line in result.cost_lines if line.rule_id == "R-B01" and line.amount.high > 0}
    return sorted(_impacted(result, ImpactType.REWORK, EntityType.BLOCK) & worked)


def _impacted(result: AnalysisResult, impact_type: ImpactType, *types: EntityType) -> frozenset[str]:
    return frozenset(
        po_of(i.entity_id) if i.entity_type is EntityType.PO_LINE else i.entity_id
        for i in result.impacts
        if i.impact_type is impact_type and i.entity_type in types
    )


def po_loss_pos(result: AnalysisResult) -> list[str]:
    """발주 변경·취소 손실 줄(R-T01·R-M02, 높은 값 > 0)이 있는 발주, ID 순 — 협력사와 손실 보상을 협의할 발주."""
    marker = f":{ImpactType.PO_CHANGE.value}:"
    return sorted(
        {
            po_of(line.line_id.split(marker, 1)[1])
            for line in result.cost_lines
            if marker in line.line_id and line.amount.high > 0
        }
    )


def fact_problem(template_id: str, entities: Sequence[str], result: AnalysisResult) -> str | None:
    """설명 템플릿의 문장이 이 결과에서 참인가(아니면 문제). 기본 설명이 블록을 고르는 조건과 같다.

    LLM이 고른 설명이 엔진 결과와 어긋나는 말(경고인데 '바로 승인', 보류 권고가 없는 발주에 '보류하면')을
    하지 않게 한다.
    """
    if template_id.startswith("verdict.") and template_id != REASONS:
        expected = VERDICT_TEMPLATES[result.verdict.level]
        return None if template_id == expected else f"엔진 판정과 다른 판정 문장(필요한 것 {expected})"
    deadline = result.timing.deadline.kind
    entity = entities[0] if entities else ""
    facts: dict[str, tuple[bool, str]] = {
        "timing.urgent": (deadline is DeadlineKind.CONFIRM_NOW, "확정을 미뤄도 바로 손실 없음"),
        "timing.relaxed": (deadline is DeadlineKind.NONE_IN_HORIZON, "탐색 기간 안에 추가손실 발생"),
        "unresolved.note": (bool(result.unresolved), "판단 불가 항목 없음"),
        "po.consult": (bool(po_loss_pos(result)), "발주 변경·취소 손실 없음"),
        "hold.advice": (entity in {h.po_id for h in result.timing.holds}, f"보류 권고 없는 발주({entity})"),
        "impact.rework": (entity in rework_blocks(result), f"재작업 없는 블록({entity})"),
        "impact.po_change": (
            entity in _impacted(result, ImpactType.PO_CHANGE, EntityType.PO, EntityType.PO_LINE),
            f"발주 변경·취소 영향 없는 발주({entity})",
        ),
        "impact.drawing": (
            entity in _impacted(result, ImpactType.DRAWING_REVISION, EntityType.DRAWING),
            f"개정 영향 없는 도면({entity})",
        ),
        "impact.target": (entity in request_parts(result), f"요청 변경 대상 아닌 부재({entity})"),
    }
    holds, problem = facts.get(template_id, (True, ""))
    return None if holds else problem


def name_of(entity_id: str, result: AnalysisResult, directory: Directory) -> str:
    if entity_id in directory.names:
        return directory.names[entity_id]
    label = next((n.label for n in result.graph.nodes if n.id == entity_id), None)
    return label or entity_id


def check(explanation: Explanation, result: AnalysisResult, use: Use = Use.EXPLANATION) -> list[str]:
    """블록마다 문제(없으면 빈 목록). LLM이 고른 블록을 렌더링 전에 거른다."""
    entities = result_entities(result)
    problems = []
    for index, block in enumerate(explanation.blocks):
        problem = _problem(block, result, entities, use)
        if problem:
            problems.append(f"{index}: {problem}")
    return problems


def _problem(
    block: TemplateBlock | MetricBlock, result: AnalysisResult, entities: Mapping[Slot, frozenset[str]], use: Use
) -> str | None:
    if isinstance(block, MetricBlock):
        if render_metric(block, result, {}) is None:
            return f"이 분석에 값 없는 수치: {block.metric}"
        return _zero_delay(block.metric, result)
    if block.template_id == REASONS:
        return None if use is Use.EXPLANATION and not block.entities else "판정 이유 블록은 설명에만, 엔터티 없이 사용"
    template = TEMPLATES.get(block.template_id)
    if template is None:
        return f"없는 템플릿: {block.template_id}"
    if template.use is not use:
        return f"{block.template_id}: {use.value}용 템플릿 아님"
    if len(block.entities) != len(template.slots):
        return f"{block.template_id}: 엔터티 {len(template.slots)}개 필요"
    for entity, slot in zip(block.entities, template.slots, strict=True):
        if entity not in entities[slot]:
            return f"{block.template_id}: 이 분석에 없는 {slot.value}({entity})"
    if use is Use.EXPLANATION:
        fact = fact_problem(block.template_id, block.entities, result)
        if fact:
            return f"{block.template_id}: {fact}"
    return None


def _zero_delay(metric: str, result: AnalysisResult) -> str | None:
    """지연 수치는 0보다 클 때만 쓴다(기본 설명과 같은 조건 — '지연 0일'은 현업에 쓸모없는 줄)."""
    delivery = result.schedule.delivery
    zero = {
        "schedule.max_exit_delay": result.schedule.max_exit_delay_days == 0,
        "schedule.delivery_delay": delivery is None or delivery.added_delay_days == 0,
    }
    return f"지연 없음 — 쓰지 않는 수치: {metric}" if zero.get(metric, False) else None


def render(
    explanation: Explanation, result: AnalysisResult, directory: Directory, use: Use = Use.EXPLANATION
) -> RenderedText:
    """통과한 블록만 문장으로. 템플릿(기본 순서)에서 문제가 나면 프로그램 오류라 예외를 낸다.

    공식 메일(Use.MAIL)이면 수치 블록을 '라벨: 값'으로 쓴다(합니다체 문단에 명사형 줄이 섞이지 않게)."""
    entities = result_entities(result)
    names = {e: name_of(e, result, directory) for slot in entities.values() for e in slot}
    names.update({line.line_id: line.label for line in result.cost_lines})
    rendered = []
    for block in explanation.blocks:
        problem = _problem(block, result, entities, use)
        if problem:
            if explanation.source == "template":
                raise ValueError(f"기본 템플릿 블록 불일치: {problem}")
            continue
        rendered.append(_render_block(block, result, names, field=use is Use.MAIL))
    if not rendered:
        raise ValueError("렌더링할 블록 없음")
    return RenderedText(blocks=tuple(rendered), source=explanation.source)


def _render_block(
    block: TemplateBlock | MetricBlock, result: AnalysisResult, names: Mapping[str, str], *, field: bool = False
) -> RenderedBlock:
    if isinstance(block, MetricBlock):
        metric_text = render_metric(block, result, names, field=field)
        assert metric_text is not None
        entity_ids = (block.entity_id,) if block.entity_id else ()
        return RenderedBlock(
            kind="metric", text=metric_text.text, metric=block.metric, entity_ids=entity_ids, parts=metric_text.parts
        )
    if block.template_id == REASONS:
        reasons = [TextBlock(text=reason).text for reason in result.verdict.reasons]  # 숫자 없는 문장인지 다시 확인
        text = " · ".join(reasons)
        return RenderedBlock(kind="text", text=text, template_id=REASONS, parts=(TextPart(text=text),))
    template = TEMPLATES[block.template_id]
    TextBlock(text=template.text.format(*(f"{{{{e:{e}}}}}" for e in block.entities)))  # 템플릿 글 검증
    parts = _template_parts(template.text, block.entities, names)
    text = "".join(p.text for p in parts)
    return RenderedBlock(kind="text", text=text, template_id=block.template_id, entity_ids=block.entities, parts=parts)


def _template_parts(template: str, entities: Sequence[str], names: Mapping[str, str]) -> tuple[TextPart, ...]:
    """템플릿 글을 엔터티 자리({0}, {1} …)에서 나눠 글 조각과 엔터티 이름 조각으로."""
    parts: list[TextPart] = []
    auto = 0
    for literal, slot, _, _ in Formatter().parse(template):
        if literal:
            parts.append(TextPart(text=literal))
        if slot is None:
            continue
        index = int(slot) if slot else auto
        auto += 1
        entity = entities[index]
        parts.append(TextPart(text=names.get(entity) or entity, entity_id=entity))
    return tuple(parts)
