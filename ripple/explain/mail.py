"""공식 메일 초안(docs/records.md(통보)): 알림 대상마다 받는 사람·참조·제목·인사말·관련 건·본문 문단(합니다체).

본문은 서버 메일 템플릿(Use.MAIL)과 수치 블록('라벨: 값')만 쓴다 — 숫자는 수치 블록에서만 나온다(E4 검출기 대상).
협력사 메일에는 보류 유지 가능 기한 말고는 내부 계산값(비용·결정 기한·지연)을 넣지 않는다.
사내 협력사 작업반 메일에는 결정 기한(확정 예정 시점)만 넣는다 — 작업 지시가 언제 다시 올지 알게.
연락처는 합성 지도의 시연용 가상 연락처(Directory.contacts)뿐이다. 없으면(실데이터 지도) 받는 사람을 비운다.
"""

from __future__ import annotations

from collections.abc import Sequence

from ripple.contracts.assistant import EmailDraft, NotificationTarget
from ripple.contracts.change import ChangeCause
from ripple.contracts.contacts import RESERVED_DOMAIN, Contact
from ripple.contracts.explain import Explanation, ExplanationBlock, MetricBlock, RenderedText, TemplateBlock
from ripple.contracts.result import AnalysisResult

from .render import Directory, render, request_parts
from .templates import Use

SUBJECT_TAIL = {
    NotificationTarget.SUPPLIER: "관련 발주 진행 현황 확인 요청",
    NotificationTarget.FABRICATOR: "관련 블록 재작업 사전 공유",
    NotificationTarget.DRAWING: "관련 도면 개정 요청",
    NotificationTarget.CREW: "관련 작업 변경 사전 공유",
}
ITEMS_PER_PARAGRAPH = 30  # 한 문단(RenderedText) 블록 한도 40 안에서 머리 한 줄과 함께
CAUSE_LABELS: dict[ChangeCause, str] = {
    ChangeCause.OWNER_REQUEST: "선주 요청",
    ChangeCause.CLASS_RULE: "선급·규정",
    ChangeCause.DESIGN_ERROR: "설계 오류·간섭",
    ChangeCause.PRODUCTION: "현장 오작·변형",
    ChangeCause.EQUIPMENT: "기자재 사양",
}
"""변경 원인 이름(화면 web/src/lib/request.ts CHANGE_CAUSE_NAMES와 같게)."""


def supplier_mail(
    result: AnalysisResult, directory: Directory, supplier_id: str, recipient: str, po_ids: Sequence[str]
) -> EmailDraft:
    """발주 변경·보류가 생긴 협력사: 대상 발주 · 검토 내용 · 요청 사항.

    보류 권고가 있는 발주면 다음 단계 중지 확인과 보류 유지 가능 기한(기준일부터 보류할 때)을 더한다."""
    holds = {h.po_id for h in result.timing.holds}
    requests: list[ExplanationBlock] = [_t("mail.heading.request"), _t("mail.supplier.status")]
    held = [po for po in po_ids if po in holds]
    requests += [_t("mail.supplier.hold", po) for po in held]
    if held:
        requests.append(_t("mail.supplier.hold_basis"))
        requests += [MetricBlock(metric="hold.until", entity_id=po) for po in held]
    paragraphs: list[list[ExplanationBlock]] = [
        [_t("mail.supplier.intro")],
        *_listed("mail.heading.po", "mail.item.po", po_ids),
        [_t("mail.heading.review"), _t("mail.supplier.review")],
        requests,
        [_t("mail.supplier.closing"), _t("mail.thanks")],
    ]
    contacts = directory.contacts
    contact = contacts.suppliers.get(supplier_id) if contacts else None
    cc = (contacts.procurement,) if contacts and contact else ()
    return _draft(NotificationTarget.SUPPLIER, result, directory, recipient, contact, cc, paragraphs)


def fabricator_mail(
    result: AnalysisResult, directory: Directory, block_id: str, recipient: str, fabricator: str | None
) -> EmailDraft:
    """재작업이 생긴 블록의 제작 담당: 사외 제작이면 그 협력사(참조 구매), 사내면 생산관리."""
    paragraphs: list[list[ExplanationBlock]] = [
        [_t("mail.fabricator.intro")],
        [_t("mail.heading.block"), _t("mail.item.block", block_id)],
        [_t("mail.heading.request"), _t("mail.fabricator.request")],
        [_t("mail.fabricator.closing"), _t("mail.thanks")],
    ]
    contacts = directory.contacts
    contact: Contact | None = None
    cc: tuple[Contact, ...] = ()
    if contacts and fabricator:
        contact = contacts.suppliers.get(fabricator)
        cc = (contacts.procurement,) if contact else ()
    elif contacts:
        contact = contacts.production
    return _draft(NotificationTarget.FABRICATOR, result, directory, recipient, contact, cc, paragraphs)


def drawing_mail(
    result: AnalysisResult, directory: Directory, discipline: str, recipient: str, drawing_ids: Sequence[str]
) -> EmailDraft:
    """개정이 필요한 도면의 분야 담당(분야를 모르면 설계 담당)."""
    paragraphs: list[list[ExplanationBlock]] = [
        [_t("mail.drawing.intro")],
        *_listed("mail.heading.drawing", "mail.item.drawing", drawing_ids),
        [_t("mail.heading.request"), _t("mail.drawing.scope"), _t("mail.drawing.share")],
        [_t("mail.drawing.closing"), _t("mail.thanks")],
    ]
    contacts = directory.contacts
    contact = (contacts.drawing.get(discipline) or contacts.drawing.get("design")) if contacts else None
    return _draft(NotificationTarget.DRAWING, result, directory, recipient, contact, (), paragraphs)


CREW_PERSON = "작업반장"
"""작업반 메일의 받는 사람 호칭(지도의 작업반 연락처에는 사람 이름이 없어 지어내지 않는다)."""
PARTS_SHOWN = 10


def crew_mail(
    result: AnalysisResult, directory: Directory, crew_id: str, recipient: str, activity_ids: Sequence[str]
) -> EmailDraft:
    """사내 협력사 작업반(사전 점검 P-06): 대상 공정 · 바뀌는 부재 · 확정 일정(결정 기한) · 요청 사항(작업 상태 회신,
    하도급법 — 확정 후 서면 지시·대금 사전 협의).

    받는 사람은 지도의 작업반 연락처(가상 '.example'일 때만), 참조는 생산관리."""
    parts = sorted(request_parts(result))[:PARTS_SHOWN]
    paragraphs: list[list[ExplanationBlock]] = [
        [_t("mail.crew.intro")],
        *_listed("mail.heading.activity", "mail.item.activity", activity_ids),
        *(_listed("mail.heading.part", "mail.item.part", parts) if parts else []),
        [_t("mail.heading.schedule"), MetricBlock(metric="timing.deadline")],
        [_t("mail.heading.request"), _t("mail.crew.status"), _t("mail.crew.subcontract")],
        [_t("mail.crew.closing"), _t("mail.thanks")],
    ]
    contacts = directory.contacts
    email = directory.crew_contacts.get(crew_id)
    contact: Contact | None = None
    if contacts is not None and email and email.lower().endswith(RESERVED_DOMAIN):
        contact = Contact(organization=recipient[:60], name=CREW_PERSON, email=email)
    cc = (contacts.production,) if contacts and contact else ()
    return _draft(NotificationTarget.CREW, result, directory, recipient, contact, cc, paragraphs)


def _draft(
    target: NotificationTarget,
    result: AnalysisResult,
    directory: Directory,
    recipient: str,
    contact: Contact | None,
    cc: tuple[Contact, ...],
    paragraphs: Sequence[Sequence[ExplanationBlock]],
) -> EmailDraft:
    change = result.request.change
    ships = "·".join(change.ship_ids)
    rendered: list[RenderedText] = [
        render(Explanation(blocks=tuple(blocks), source="template"), result, directory, Use.MAIL)
        for blocks in paragraphs
    ]
    contacts = directory.contacts
    colleague = contacts is not None and contact is not None and contact.organization == contacts.organization
    return EmailDraft(
        to=(contact,) if contact else (),
        cc=cc,
        subject=f"[설계변경 검토] {ships} {change.ecn_id} {SUBJECT_TAIL[target]}",
        salutation=f"{contact.honorific(colleague)}께" if contact else f"{recipient} 담당자님께",
        reference=reference_of(result)[:300],
        paragraphs=tuple(rendered),
        sender=contacts.sender if contacts else None,
        fictional=contacts is not None and contact is not None,
    )


def reference_of(result: AnalysisResult) -> str:
    """'관련 건' 한 줄: 호선 · 기록 번호 제목 · 원문 번호와 개정(문서 접수로 넣었을 때) · 변경 원인(입력했을 때).

    받는 쪽이 어느 문서·개정을 기준으로 할지 알게 한다 — 옛 개정으로 계속 작업하는 일을 막고, 사유 없이 변경만
    통보하지 않게. 내부 계산값은 넣지 않는다."""
    change = result.request.change
    parts = [f"{'·'.join(change.ship_ids)} 호선", f"{change.ecn_id} {change.title}"]
    source = change.source
    if source is not None and (source.ecn_ref or source.revision):
        ref = " ".join(p for p in (source.ecn_ref, f"Rev.{source.revision}" if source.revision else None) if p)
        parts.append(f"원문 {ref}")
    if change.cause is not None:
        parts.append(f"변경 원인 {CAUSE_LABELS[change.cause]}")
    return " · ".join(parts)


def _listed(heading: str, item: str, entity_ids: Sequence[str]) -> list[list[ExplanationBlock]]:
    """대상 목록 문단: 머리 한 줄 + 항목. 항목이 많으면 문단을 나눈다(첫 문단에만 머리)."""
    chunks = [entity_ids[i : i + ITEMS_PER_PARAGRAPH] for i in range(0, len(entity_ids), ITEMS_PER_PARAGRAPH)]
    found: list[list[ExplanationBlock]] = []
    for index, chunk in enumerate(chunks):
        head: list[ExplanationBlock] = [_t(heading)] if index == 0 else []
        found.append([*head, *(_t(item, entity) for entity in chunk)])
    return found


def _t(template_id: str, *entities: str) -> TemplateBlock:
    return TemplateBlock(template_id=template_id, entities=entities)
