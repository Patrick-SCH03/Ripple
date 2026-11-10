"""공식 메일 초안의 성질(ripple/explain/mail.py, docs/records.md(통보) — 합성 지도, 키·네트워크 없이).

본문 숫자는 수치 블록에서만(E4), 협력사 메일에는 보류 유지 가능 기한 말고 내부 계산값 없음, 대상별 받는 사람·참조,
가상 연락처는 합성 모드에만·이메일은 예약 도메인만, 보류 기한의 뜻(기준일 + 보류 가능 일수), 많은 대상은 문단을 나눔.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import yaml
from harness import Checker
from pydantic import ValidationError

from ripple.agent.resources import AssistantResources, directory_of
from ripple.config.loaders import (
    load_contacts,
    load_decision_config,
    load_lexicon,
    load_params,
    load_rulebook,
    read_yaml,
)
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.assistant import EmailDraft, Notification, NotificationTarget
from ripple.contracts.change import ChangeCause, SourceDocument, SourceKind
from ripple.contracts.contacts import ContactBook
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.domain import DataMode
from ripple.contracts.explain import METRICS, TemplateBlock
from ripple.contracts.result import AnalysisResult
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.explain.audit import audit
from ripple.explain.compose import notifications
from ripple.explain.mail import CAUSE_LABELS, ITEMS_PER_PARAGRAPH, _listed
from ripple.explain.render import Directory, crew_activities, name_of, result_entities
from ripple.generator.build import generate
from ripple.generator.io import load_config

GATE = PROJECT_ROOT / "eval" / "gate_cases" / "2" / "inputs"
HOLD_LINES = ("hold.until", "mail.supplier.hold_basis")


def run(c: Checker) -> None:
    settings = Settings.from_env({})
    contacts = load_contacts(settings.contacts_path)
    _book(c, settings.contacts_path)
    config = load_config()
    generated = generate(config)
    snapshot = generated.snapshot
    index = GraphIndex(snapshot)
    rulebook, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    results: dict[str, AnalysisResult] = {}
    for case in ("G2-002", "G2-003"):
        body = yaml.safe_load((GATE / f"{case}.yaml").read_text("utf-8"))
        results[case] = analyze(index, AnalysisRequest.model_validate(body["request"]), rulebook, params)
    for ecn in [e for e in generated.ecns if e.split is EcnSplit.DEV][:40]:
        request = AnalysisRequest(change=ecn.change, as_of=config.scenario_date)
        try:
            results[ecn.change.ecn_id] = analyze(index, request, rulebook, params)
        except RequestError:
            continue
    modes = {
        mode: AssistantResources.build(
            snapshot,
            index,
            load_lexicon(settings.lexicon_path),
            load_decision_config(settings.decision_path),
            rulebook,
            params,
            mode,
            contacts,
        ).directory.contacts
        for mode in DataMode
    }
    c.check(
        "비서 자원: 가상 연락처는 합성 모드에만 붙고 real 모드에는 붙지 않음",
        modes[DataMode.SYNTHETIC] == contacts and modes[DataMode.REAL] is None,
    )
    synthetic = directory_of(snapshot, contacts)
    _numbers(c, results, synthetic)
    _recipients(c, results, synthetic, contacts)
    _hold(c, results["G2-003"], synthetic)
    _real(c, results["G2-002"], directory_of(snapshot, None))
    _paragraphs(c)


def _book(c: Checker, path: Path) -> None:
    c.section("메일: 시연용 가상 연락처")
    raw = read_yaml(path)
    book = ContactBook.model_validate(raw)
    people = (book.procurement, book.production, *book.suppliers.values(), *book.drawing.values())
    emails = [person.email for person in people]
    c.check(
        "가상 연락처 이메일은 모두 예약 도메인 .example(배달되지 않음)", all(e.endswith(".example") for e in emails)
    )
    valve = {**raw["suppliers"]["SUP-VL1"], "email": "a@b.com"}
    try:
        ContactBook.model_validate({**raw, "suppliers": {**raw["suppliers"], "SUP-VL1": valve}})
        refused = False
    except ValidationError:
        refused = True
    c.check("예약 도메인이 아닌 이메일이 섞이면 연락처 묶음을 거부", refused)
    c.check(
        "합성 지도의 협력사 넷·도면 분야(설계 포함) 연락처가 모두 있음",
        set(book.suppliers) == {"SUP-ST1", "SUP-ST2", "SUP-PP1", "SUP-VL1"}
        and {"hull", "piping", "outfitting", "machinery", "design"} <= set(book.drawing),
    )
    label = METRICS["hold.until"].label
    c.check("보류 날짜 라벨은 '보류 유지 가능 기한'(결정 기한이 아님)", label == "보류 유지 가능 기한", label)


ALLOWED_METRICS: dict[NotificationTarget, set[str]] = {
    NotificationTarget.SUPPLIER: {"hold.until"},
    NotificationTarget.CREW: {"timing.deadline"},  # 작업반(사내 협력사)에는 확정 예정 시점만
}


def _mails(result: AnalysisResult, directory: Directory) -> list[tuple[Notification, EmailDraft]]:
    found = []
    for notice in notifications(result, directory):
        assert notice.email is not None
        found.append((notice, notice.email))
    return found


def _numbers(c: Checker, results: dict[str, AnalysisResult], directory: Directory) -> None:
    c.section("메일: 본문 숫자는 수치 블록에서만(E4), 협력사 메일에 내부 계산값 없음")
    problems: list[str] = []
    outside: list[str] = []
    texts: list[str] = []
    count = 0
    for case, result in results.items():
        names = {e: name_of(e, result, directory) for ids in result_entities(result).values() for e in ids}
        for notice, mail in _mails(result, directory):
            count += 1
            for paragraph in mail.paragraphs:
                problems += [f"{case}/{notice.recipient_id}: {p}" for p in audit(paragraph, result, names)]
                texts += [b.text for b in paragraph.blocks]
            metrics = {b.metric for p in mail.paragraphs for b in p.blocks if b.metric}
            allowed = ALLOWED_METRICS.get(notice.target, set())
            if metrics - allowed:
                outside.append(f"{case}/{notice.target.value}: {sorted(metrics)}")
    c.check(f"사례 {len(results)}건의 메일 {count}통, 본문 문단 모두 E4 통과", count > 0 and not problems, problems[:3])
    c.check(
        "협력사 메일의 수치는 보류 유지 가능 기한뿐, 작업반 메일은 결정 기한뿐, 사내 메일엔 수치 없음",
        not outside,
        outside[:3],
    )
    informal = [t for t in texts if t.endswith(("요.", "예요.", "에요."))]
    c.check("공식 메일 본문에 해요체 끝맺음이 섞이지 않음", not informal, informal[:3])


def _recipients(c: Checker, results: dict[str, AnalysisResult], directory: Directory, contacts: ContactBook) -> None:
    c.section("메일: 대상별 받는 사람·참조·제목·인사말")
    warn = results["G2-002"]
    mails = _mails(warn, directory)
    by_target = {n.target: m for n, m in mails}
    supplier = by_target[NotificationTarget.SUPPLIER]
    fabricator = by_target[NotificationTarget.FABRICATOR]
    drawing = by_target[NotificationTarget.DRAWING]
    person = supplier.to[0] if supplier.to else None
    c.check(
        "협력사: 받는 사람 = 그 협력사 담당, 참조 = 구매 담당, 인사말은 회사 이름으로",
        person is not None
        and person in contacts.suppliers.values()
        and supplier.cc == (contacts.procurement,)
        and supplier.salutation == f"{person.organization} {person.name} {person.title}님께",
        (supplier.to, supplier.cc, supplier.salutation),
    )
    c.check(
        "사내 제작 블록: 받는 사람 = 생산관리, 참조 없음, 인사말은 부서로(같은 회사 동료)",
        fabricator.to == (contacts.production,)
        and fabricator.cc == ()
        and fabricator.salutation.startswith(f"{contacts.production.department} "),
        (fabricator.to, fabricator.salutation),
    )
    c.check(
        "도면: 받는 사람 = 그 분야 도면 담당, 참조 없음",
        len(drawing.to) == 1 and drawing.to[0] in contacts.drawing.values() and drawing.cc == (),
        drawing.to,
    )
    change = warn.request.change
    ships = "·".join(change.ship_ids)
    c.check(
        "제목·관련 건 줄에 호선·ECN 번호, 관련 건 줄에 변경 제목, 서명 조직·가상 표시",
        all(
            m.subject.startswith(f"[설계변경 검토] {ships} {change.ecn_id} ")
            and m.reference == f"{ships} 호선 · {change.ecn_id} {change.title}"
            and m.sender == contacts.sender
            and m.fictional
            for _, m in mails
        ),
        [m.subject for _, m in mails],
    )
    sourced = warn.request.change.model_copy(
        update={
            "cause": ChangeCause.OWNER_REQUEST,
            "source": SourceDocument(kind=SourceKind.TEXT, ecn_ref="2026-034", revision="C", items=1),
        }
    )
    based = warn.model_copy(update={"request": warn.request.model_copy(update={"change": sourced})})
    refs = {m.reference for _, m in _mails(based, directory)}
    c.check(
        "문서로 넣고 원인을 고르면 관련 건 줄에 원문 번호·개정·변경 원인(모든 메일 같음)",
        refs == {f"{ships} 호선 · {change.ecn_id} {change.title} · 원문 2026-034 Rev.C · 변경 원인 선주 요청"},
        refs,
    )
    web = (PROJECT_ROOT / "web" / "src" / "lib" / "request.ts").read_text("utf-8")
    web_names = dict(
        re.findall(r"^\s+(\w+): '([^']+)',$", web.split("CHANGE_CAUSE_NAMES", 1)[1].split("}", 1)[0], re.M)
    )
    c.check(
        "변경 원인 이름은 메일(서버)과 화면이 같음",
        web_names == {cause.value: label for cause, label in CAUSE_LABELS.items()},
        web_names,
    )
    crews = [(n, m) for n, m in mails if n.target is NotificationTarget.CREW]
    expected_crews = set(crew_activities(warn))
    texts = [b.text for _, m in crews for p in m.paragraphs for b in p.blocks]
    c.check(
        "작업반(사전 점검 P-06 수행 주체): 작업반마다 한 통 · 받는 사람 = 작업반 가상 연락처(작업반장) · "
        "참조 = 생산관리 · 제목 꼬리 · 하도급법 안내 · 결정 기한",
        bool(crews)
        and {n.recipient_id for n, _ in crews} == expected_crews
        and all(
            len(m.to) == 1
            and m.to[0].name == "작업반장"
            and m.cc == (contacts.production,)
            and m.subject.endswith("관련 작업 변경 사전 공유")
            for _, m in crews
        )
        and any("하도급법" in t for t in texts)
        and any("결정 기한" in t for t in texts),
        [(n.recipient_id, m.to, m.subject) for n, m in crews][:2],
    )
    every = [m for r in results.values() for _, m in _mails(r, directory)]
    c.check(
        "모든 사례의 메일에 받는 사람이 있고 이메일은 모두 .example",
        all(m.to and all(x.email.endswith(".example") for x in (*m.to, *m.cc)) for m in every),
    )


def _hold(c: Checker, result: AnalysisResult, directory: Directory) -> None:
    c.section("메일: 보류 권고(기준일부터 보류할 때의 유지 가능 기한)")
    advice = {h.po_id: h for h in result.timing.holds}
    suppliers = [m for n, m in _mails(result, directory) if n.target is NotificationTarget.SUPPLIER]
    held = [m for m in suppliers if any(po in advice for po in _pos(m))]
    c.check("보류 권고가 있는 사례에 보류 대상 발주의 협력사 메일이 있음", bool(held))
    ok = True
    for mail in held:
        lines = [b for p in mail.paragraphs for b in p.blocks]
        until = [b for b in lines if b.metric == "hold.until"]
        basis = [b for b in lines if b.template_id == "mail.supplier.hold_basis"]
        ok = ok and bool(basis) and bool(until)
        for block in until:
            hold = advice[block.entity_ids[0]]
            shown = f"{hold.hold_until.year}년 {hold.hold_until.month}월 {hold.hold_until.day}일"
            expected = result.request.as_of + timedelta(days=hold.max_hold_days)
            ok = ok and shown in block.text and hold.hold_until == expected
    c.check("기한 줄 앞에 '기준일부터 보류할 경우' 전제 문장, 날짜 = 기준일 + 보류 가능 일수", ok)
    plain = [m for m in suppliers if not any(po in advice for po in _pos(m))]
    c.check(
        "보류 권고가 없는 발주만 있는 협력사 메일엔 보류 문장·기한이 없음",
        all(not (_kinds(m) & set(HOLD_LINES)) for m in plain),
    )


def _real(c: Checker, result: AnalysisResult, directory: Directory) -> None:
    c.section("메일: 실데이터 지도(연락처 없음)")
    mails = _mails(result, directory)
    c.check(
        "받는 사람·참조 비움, 인사말은 '받는 쪽 이름 담당자님께', 서명 조직·가상 표시 없음",
        bool(mails)
        and all(
            not m.to and not m.cc and m.salutation == f"{n.recipient} 담당자님께" and m.sender is None for n, m in mails
        )
        and not any(m.fictional for _, m in mails),
        [(m.to, m.salutation) for _, m in mails][:2],
    )


def _paragraphs(c: Checker) -> None:
    c.section("메일: 대상이 많으면 문단을 나눔")
    ids = [f"DWG-{i:03d}" for i in range(ITEMS_PER_PARAGRAPH * 2 + 5)]
    chunks = _listed("mail.heading.drawing", "mail.item.drawing", ids)
    blocks = [b for chunk in chunks for b in chunk if isinstance(b, TemplateBlock)]
    items = [b for b in blocks if b.template_id == "mail.item.drawing"]
    heads = [b for b in blocks if b.template_id == "mail.heading.drawing"]
    c.check(
        f"대상 {len(ids)}개 → 문단 셋(머리는 첫 문단 맨 앞에만, 항목은 빠짐없이 순서대로)",
        len(chunks) == 3
        and len(heads) == 1
        and chunks[0][0] == heads[0]
        and [e for b in items for e in b.entities] == ids,
    )


def _pos(mail: EmailDraft) -> list[str]:
    return [e for p in mail.paragraphs for b in p.blocks if b.template_id == "mail.item.po" for e in b.entity_ids]


def _kinds(mail: EmailDraft) -> set[str]:
    return {b.metric or b.template_id or "" for p in mail.paragraphs for b in p.blocks}
