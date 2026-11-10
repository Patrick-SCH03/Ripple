"""기본 설명과 알림 초안: 분석 결과에서 정해진 순서로 블록을 고른다(LLM 없이, real 모드 기본).

알림 대상(docs/records.md(통보)): 발주 변경·보류가 생긴 협력사, 재작업이 생긴 블록의 제작 담당(사외 협력사
또는 사내 생산), 사전 점검 P-06이 짚은 공정을 맡은 사내 협력사 작업반, 개정이 필요한 도면의 분야 담당.
알림마다 공식 메일 초안(ripple/explain/mail.py)을 함께 만든다. 작업반 메일에는 용어집이 있으면 번역 초안(1.36.0,
ripple/explain/translate.py — 고정 문장·용어집, 외부 AI 없음)을 덧붙인다.
"""

from __future__ import annotations

from collections import defaultdict

from ripple.contracts.assistant import EmailDraft, Notification, NotificationTarget
from ripple.contracts.domain import EntityType
from ripple.contracts.explain import Explanation, ExplanationBlock, MetricBlock, TemplateBlock
from ripple.contracts.result import AnalysisResult, DeadlineKind, ImpactType

from .mail import crew_mail, drawing_mail, fabricator_mail, supplier_mail
from .render import Directory, crew_activities, name_of, po_loss_pos, po_of, render, rework_blocks
from .templates import REASONS, VERDICT_TEMPLATES, Use
from .translate import translate_mail

DISCIPLINE_NAMES = {"hull": "선체", "piping": "배관", "outfitting": "의장", "machinery": "기관"}


def default_explanation(result: AnalysisResult) -> Explanation:
    """판정 → 이유 → 총비용 → 마감일 → 일정 지연(허용 지연·선상 설치) → 보류 권고 → 발주 손실 협의 → 재작업 → 판단 불가
    → 다음 할 일."""
    blocks: list[ExplanationBlock] = [
        TemplateBlock(template_id=VERDICT_TEMPLATES[result.verdict.level]),
        TemplateBlock(template_id=REASONS),
        MetricBlock(metric="cost.total"),
        MetricBlock(metric="timing.deadline"),
    ]
    deadline = result.timing.deadline.kind
    if deadline is DeadlineKind.CONFIRM_NOW:
        blocks.append(TemplateBlock(template_id="timing.urgent"))
    elif deadline is DeadlineKind.NONE_IN_HORIZON:
        blocks.append(TemplateBlock(template_id="timing.relaxed"))
    if result.schedule.max_exit_delay_days > 0:
        blocks.append(MetricBlock(metric="schedule.max_exit_delay"))
    delivery = result.schedule.delivery
    if delivery is not None and delivery.added_delay_days > 0:
        blocks.append(MetricBlock(metric="schedule.delivery_delay"))
        if delivery.permissible:
            blocks.append(TemplateBlock(template_id="delivery.permissible"))
    if result.onboard is not None:
        template = "onboard.applied" if result.request.outfit_on_board else "onboard.option"
        blocks.append(TemplateBlock(template_id=template, entities=(result.onboard.block_ids[0],)))
    if result.timing.holds:
        hold = result.timing.holds[0]
        blocks += [
            TemplateBlock(template_id="hold.advice", entities=(hold.po_id,)),
            MetricBlock(metric="hold.max_days", entity_id=hold.po_id),
            MetricBlock(metric="hold.until", entity_id=hold.po_id),
        ]
    if po_loss_pos(result):
        blocks.append(TemplateBlock(template_id="po.consult"))
    for block_id in rework_blocks(result)[:2]:
        blocks.append(TemplateBlock(template_id="impact.rework", entities=(block_id,)))
    if result.unresolved:
        blocks.append(TemplateBlock(template_id="unresolved.note"))
    blocks.append(TemplateBlock(template_id="next.review"))
    return Explanation(blocks=tuple(blocks), source="template")


def notifications(result: AnalysisResult, directory: Directory) -> tuple[Notification, ...]:
    """대상마다 알림 초안 하나(협력사 → 제작 담당 → 작업반 → 도면 담당 순, 같은 종류는 ID 순)."""
    return (
        *_supplier_notices(result, directory),
        *_fabricator_notices(result, directory),
        *_crew_notices(result, directory),
        *_drawing_notices(result, directory),
    )


def _supplier_notices(result: AnalysisResult, directory: Directory) -> list[Notification]:
    """발주 변경·보류가 생긴 협력사마다 한 통(발주를 묶음)."""
    holds = {h.po_id for h in result.timing.holds}
    by_supplier: dict[str, list[str]] = defaultdict(list)
    for po_id in _changed_pos(result):
        by_supplier[directory.po_supplier.get(po_id, po_id)].append(po_id)
    found = []
    for supplier, po_ids in sorted(by_supplier.items()):
        blocks: list[ExplanationBlock] = [TemplateBlock(template_id="notify.supplier.opening")]
        for po_id in po_ids:
            blocks.append(TemplateBlock(template_id="notify.supplier.po", entities=(po_id,)))
            if po_id in holds:
                blocks += [
                    TemplateBlock(template_id="notify.supplier.hold", entities=(po_id,)),
                    MetricBlock(metric="hold.until", entity_id=po_id),
                ]
        blocks.append(TemplateBlock(template_id="notify.supplier.closing"))
        name = directory.names.get(supplier, supplier)
        mail = supplier_mail(result, directory, supplier, name, po_ids)
        found.append(
            _notice(NotificationTarget.SUPPLIER, supplier, name, blocks, result, directory, Use.SUPPLIER, mail)
        )
    return found


def _fabricator_notices(result: AnalysisResult, directory: Directory) -> list[Notification]:
    """재작업이 생긴 블록마다 제작 담당(사외 제작 협력사, 없으면 사내 생산)에게 한 통."""
    found = []
    for block_id in rework_blocks(result):
        fabricator = directory.block_fabricator.get(block_id)
        block_name = name_of(block_id, result, directory)
        recipient = directory.names.get(fabricator, fabricator) if fabricator else f"사내 생산 담당({block_name})"
        blocks: list[ExplanationBlock] = [
            TemplateBlock(template_id="notify.fabricator.rework", entities=(block_id,)),
            TemplateBlock(template_id="notify.fabricator.closing"),
        ]
        mail = fabricator_mail(result, directory, block_id, recipient, fabricator)
        found.append(
            _notice(
                NotificationTarget.FABRICATOR,
                fabricator or block_id,
                recipient,
                blocks,
                result,
                directory,
                Use.FABRICATOR,
                mail,
            )
        )
    return found


def _crew_notices(result: AnalysisResult, directory: Directory) -> list[Notification]:
    """사전 점검 P-06(현장 공유)이 짚은 공정을 맡은 사내 협력사 작업반마다 한 통: 맡은 공정 · 결정 기한 · 하도급법 안내
    (사내 협력사도 하도급법 대상 — 확정 후 서면 지시, 추가 대금 사전 협의). 직영·수행 주체 모름은 보내지 않는다."""
    found = []
    for crew_id, activity_ids in crew_activities(result).items():
        blocks: list[ExplanationBlock] = [
            TemplateBlock(template_id="notify.crew.opening"),
            *(TemplateBlock(template_id="notify.crew.activity", entities=(a,)) for a in activity_ids),
            MetricBlock(metric="timing.deadline"),
            TemplateBlock(template_id="notify.crew.subcontract"),
            TemplateBlock(template_id="notify.crew.closing"),
        ]
        name = directory.names.get(crew_id, crew_id)
        mail = crew_mail(result, directory, crew_id, name, activity_ids)
        if directory.glossary is not None:  # 1.36.0 번역 초안(작업반 통보만, 고정 문장·용어집)
            mail = translate_mail(mail, result, directory.glossary, name)
        found.append(_notice(NotificationTarget.CREW, crew_id, name, blocks, result, directory, Use.CREW, mail))
    return found


def _drawing_notices(result: AnalysisResult, directory: Directory) -> list[Notification]:
    """개정이 필요한 도면을 분야마다 묶어 그 분야 도면 담당에게 한 통(분야를 모르면 설계)."""
    by_discipline: dict[str, list[str]] = defaultdict(list)
    for drawing_id in sorted({i.entity_id for i in result.impacts if i.entity_type is EntityType.DRAWING}):
        by_discipline[directory.drawing_discipline.get(drawing_id, "design")].append(drawing_id)
    found = []
    for discipline, drawing_ids in sorted(by_discipline.items()):
        blocks: list[ExplanationBlock] = [
            TemplateBlock(template_id="notify.drawing.revise", entities=(d,)) for d in drawing_ids
        ]
        blocks.append(TemplateBlock(template_id="notify.drawing.closing"))
        recipient = f"{DISCIPLINE_NAMES.get(discipline, discipline)} 도면 담당"
        mail = drawing_mail(result, directory, discipline, recipient, drawing_ids)
        found.append(
            _notice(
                NotificationTarget.DRAWING,
                f"discipline:{discipline}",
                recipient,
                blocks,
                result,
                directory,
                Use.DRAWING,
                mail,
            )
        )
    return found


def _notice(
    target: NotificationTarget,
    recipient_id: str,
    recipient: str,
    blocks: list[ExplanationBlock],
    result: AnalysisResult,
    directory: Directory,
    use: Use,
    email: EmailDraft,
) -> Notification:
    body = render(Explanation(blocks=tuple(blocks), source="template"), result, directory, use)
    return Notification(target=target, recipient_id=recipient_id, recipient=recipient, body=body, email=email)


def _changed_pos(result: AnalysisResult) -> list[str]:
    """발주 변경·보류 영향이 있는 발주(품목 영향은 발주로 모음), ID 순."""
    kinds = {ImpactType.PO_CHANGE, ImpactType.PO_HOLD}
    pos = {
        po_of(i.entity_id) if i.entity_type is EntityType.PO_LINE else i.entity_id
        for i in result.impacts
        if i.impact_type in kinds and i.entity_type in (EntityType.PO, EntityType.PO_LINE)
    }
    return sorted(pos | {h.po_id for h in result.timing.holds})
