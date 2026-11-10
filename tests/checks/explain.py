"""설명·알림 렌더러의 성질: 템플릿에 숫자 없음, 수치는 결과 필드에서만, 잘못된 고르기는 거름, E4 검출기."""

from __future__ import annotations

import re

import yaml
from harness import Checker

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.assistant import NotificationTarget
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.domain import EntityType
from ripple.contracts.explain import (
    METRICS,
    Explanation,
    MetricBlock,
    RenderedBlock,
    RenderedText,
    TemplateBlock,
    TextBlock,
)
from ripple.contracts.result import AnalysisResult, DeadlineKind, ImpactType
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.explain.audit import audit
from ripple.explain.compose import default_explanation, notifications
from ripple.explain.format import money, money_range, object_particle, subject_particle, topic_particle
from ripple.explain.metrics import available_metrics, render_metric
from ripple.explain.render import (
    Directory,
    check,
    crew_activities,
    name_of,
    po_loss_pos,
    po_of,
    render,
    request_parts,
    result_entities,
    rework_blocks,
)
from ripple.explain.templates import REASONS, TEMPLATES, VERDICT_TEMPLATES, Slot, Use
from ripple.generator.build import generate
from ripple.generator.io import load_config


def run(c: Checker) -> None:
    _templates(c)
    _format(c)
    settings = Settings.from_env({})
    config = load_config()
    generated = generate(config)
    snapshot = generated.snapshot
    index = GraphIndex(snapshot)
    directory = Directory(
        names={p.part_id: p.name for p in snapshot.parts}
        | {b.block_id: b.name for b in snapshot.blocks}
        | {s.supplier_id: s.name for s in snapshot.suppliers},
        po_supplier={p.po_id: p.supplier_id for p in snapshot.purchase_orders},
        block_fabricator={b.block_id: b.fabricator_id for b in snapshot.blocks},
        drawing_discipline={d.drawing_id: d.discipline for d in snapshot.drawings},
    )
    results = {}
    for case in ("G2-002", "G2-003"):
        body = yaml.safe_load(
            (PROJECT_ROOT / "eval" / "gate_cases" / "2" / "inputs" / f"{case}.yaml").read_text("utf-8")
        )
        request = AnalysisRequest.model_validate(body["request"])
        results[case] = analyze(index, request, load_rulebook(settings.rules_path), load_params(settings.params_path))
    _rendering(c, results, directory)
    _parts(c, results, directory)
    rulebook, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    sample = []
    for ecn in [e for e in generated.ecns if e.split is EcnSplit.DEV][:40]:
        request = AnalysisRequest(change=ecn.change, as_of=config.scenario_date)
        try:
            sample.append(analyze(index, request, rulebook, params))
        except RequestError:
            continue
    _facts(c, results, sample)


def _templates(c: Checker) -> None:
    c.section("설명: 글 템플릿")
    bad = []
    for template_id, template in TEMPLATES.items():
        refs = template.text.format(*(f"{{{{e:X{i}}}}}" for i in range(len(template.slots))))
        if c.raises(lambda refs=refs: TextBlock(text=refs)):  # type: ignore[misc]
            bad.append(template_id)
    c.check("모든 글 템플릿이 숫자·한글 수사·수량 표현 없이 글 블록 검증을 통과", not bad, bad)
    placeholders = [t for t, tpl in TEMPLATES.items() if tpl.text.count("{") != len(tpl.slots)]
    c.check("템플릿 엔터티 자리 수 = 자리 종류 수", not placeholders, placeholders)
    c.check("템플릿 ID 형식이 계약 형식과 맞음", all(TemplateBlock(template_id=t).template_id == t for t in TEMPLATES))
    uses = {tpl.use for tpl in TEMPLATES.values()}
    c.check("설명·알림 세 종류 모두 템플릿이 있음", uses == set(Use), uses)


def _format(c: Checker) -> None:
    c.section("설명: 금액·조사 표기")
    c.check("1억 이상은 억·만원(화면과 같은 규칙)", money(224_214_705) == "2억 2,421만원")
    c.check("1만원 미만은 원 그대로, 음수는 절감", money(8_500) == "8,500원" and money(-120_000) == "절감 12만원")
    c.check("범위 표기", money_range(660_000, 7_890_000) == "66만~789만원")
    halves = (money(125_000), money(105_000), money(224_215_000), money_range(125_000, 135_000), money(-125_000))
    c.check(
        "만원 반올림은 화면(money.ts Math.round)과 같은 사사오입(125,000원 → 13만원, 짝수 쪽으로 내리지 않음)",
        halves == ("13만원", "11만원", "2억 2,422만원", "13만~14만원", "절감 13만원"),
        halves,
    )
    c.check("은/는 조사", topic_particle("총변경비용") == "은" and topic_particle("영향 항목 수") == "는")
    particles = (
        object_particle("바꿀 두께"),
        object_particle("바꿀 규격"),
        subject_particle("'판 7'"),
        subject_particle("판 2"),
        object_particle("PO-0130"),
        topic_particle("T31C"),
    )
    c.check(
        "을/를·이/가 조사: 받침으로 고르고 숫자는 한자어 읽기(7=칠·2=이), 영문 끝은 둘 다 적음",
        particles == ("를", "을", "이", "가", "을", "은(는)"),
        particles,
    )


def _rendering(c: Checker, results: dict[str, AnalysisResult], directory: Directory) -> None:
    c.section("설명: 기본 설명·알림 렌더링과 E4 검출기")
    for case, result in results.items():
        names = {e: name_of(e, result, directory) for ids in result_entities(result).values() for e in ids}
        explanation = render(default_explanation(result), result, directory)
        c.check(f"{case}: 기본 설명이 통과(E4 검출기 문제 0)", audit(explanation, result, names) == [])
        c.check(
            f"{case}: 기본 설명의 숫자는 모두 수치 블록(글 블록에 숫자 없음)",
            all(not any(ch.isdigit() for ch in _strip(b, names)) for b in explanation.blocks if b.kind == "text"),
        )
        notices = notifications(result, directory)
        c.check(
            f"{case}: 알림 초안이 모두 E4 통과",
            notices != () and all(audit(n.body, result, names) == [] for n in notices),
        )
    warn, approve = results["G2-002"], results["G2-003"]
    targets = {n.target for n in notifications(warn, directory)}
    crew = {NotificationTarget.CREW} if crew_activities(warn) else set()
    c.check(
        "탑재 뒤 두께 변경(경고): 협력사·재작업 블록 담당·도면 담당 + 사전 점검 P-06 작업반에게 알림",
        targets == {NotificationTarget.SUPPLIER, NotificationTarget.FABRICATOR, NotificationTarget.DRAWING, *crew},
        targets,
    )
    crew_notice = next((n for n in notifications(warn, directory) if n.target is NotificationTarget.CREW), None)
    c.check(
        "작업반 알림: 맡은 공정(공정 이름) · 결정 기한 수치 블록 · 하도급법 안내",
        crew_notice is not None
        and any(b.template_id == "notify.crew.activity" for b in crew_notice.body.blocks)
        and any(b.metric == "timing.deadline" for b in crew_notice.body.blocks)
        and any("하도급법" in b.text for b in crew_notice.body.blocks),
        crew_notice and [b.text for b in crew_notice.body.blocks],
    )
    hold_notice = next(n for n in notifications(approve, directory) if n.target is NotificationTarget.SUPPLIER)
    c.check(
        "보류 권고가 있는 발주의 협력사 알림에 보류 유지 가능 기한 수치 블록",
        any(b.metric == "hold.until" for b in hold_notice.body.blocks),
    )
    names = {e: name_of(e, warn, directory) for ids in result_entities(warn).values() for e in ids}
    rendered = render(default_explanation(warn), warn, directory)

    def shifted(text: str) -> str:  # 출구 지연 일수(지도마다 다름)를 다른 값으로
        return re.sub(r"(\d+)일", lambda m: f"{int(m.group(1)) + 7}일", text, count=1)

    tampered = tuple(
        RenderedBlock(kind=b.kind, text=shifted(b.text), metric=b.metric, entity_ids=b.entity_ids)
        if b.metric == "schedule.max_exit_delay"
        else b
        for b in rendered.blocks
    )
    c.check(
        "E4 검출기: 수치 블록의 숫자를 바꾸면 찾음",
        tampered != rendered.blocks and audit(RenderedText(blocks=tampered, source="llm"), warn, names) != [],
    )
    sneaky = (*rendered.blocks, RenderedBlock(kind="text", text="이틀 안에 끝나요.", template_id="next.review"))
    c.check(
        "E4 검출기: 글 블록의 한글 수사를 찾음", audit(RenderedText(blocks=sneaky, source="llm"), warn, names) != []
    )
    choice = Explanation(
        blocks=(
            TemplateBlock(template_id="impact.rework", entities=("S-001:F11C",)),
            MetricBlock(metric="hold.max_days", entity_id="PO-9999"),
            TemplateBlock(template_id="notify.supplier.po", entities=("PO-0078",)),
            TemplateBlock(template_id="verdict.warn"),
            MetricBlock(metric="cost.total"),
        ),
        source="llm",
    )
    problems = check(choice, warn)
    c.check(
        "LLM이 고른 블록 검사: 없는 엔터티·값 없는 수치·다른 쓰임의 템플릿을 거름",
        [p.split(":")[0] for p in problems] == ["0", "1", "2"],
        problems,
    )
    kept = render(choice, warn, directory)
    c.check(
        "통과한 블록만 렌더링(나머지는 버림)",
        [b.template_id or b.metric for b in kept.blocks] == ["verdict.warn", "cost.total"],
    )
    available = {(m.metric, m.entity_id) for m in available_metrics(approve)}
    c.check(
        "값이 있는 수치만 고를 수 있음(경계 조건 있는 인도 지연, 보류 권고 발주)",
        ("hold.until", "PO-0130") in available and all(m in METRICS for m, _ in available),
    )
    c.check(
        "판정 이유 블록은 결과의 숫자 없는 이유 문장을 그대로 씀",
        render(Explanation(blocks=(TemplateBlock(template_id=REASONS),), source="template"), warn, directory)
        .blocks[0]
        .text.startswith(warn.verdict.reasons[0]),
    )


def _parts(c: Checker, results: dict[str, AnalysisResult], directory: Directory) -> None:
    c.section("설명: 블록 조각(근거 칩·값 강조)")
    for case, result in results.items():
        names = {e: name_of(e, result, directory) for ids in result_entities(result).values() for e in ids}
        bodies = [
            render(default_explanation(result), result, directory),
            *(n.body for n in notifications(result, directory)),
        ]
        blocks = [b for body in bodies for b in body.blocks]
        every = [MetricBlock(metric=m.metric, entity_id=m.entity_id) for m in available_metrics(result)]
        blocks += render(Explanation(blocks=tuple(every), source="llm"), result, directory).blocks
        c.check(
            f"{case}: 설명·알림·값 있는 수치 전부 조각이 있고 이으면 블록 글",
            all(b.parts and "".join(p.text for p in b.parts) == b.text for b in blocks),
        )
        c.check(
            f"{case}: 엔터티 조각의 글은 그 엔터티 이름",
            all(p.text == names[p.entity_id] for b in blocks for p in b.parts if p.entity_id and p.entity_id in names),
        )
        mismatched = [
            b.metric
            for b in blocks
            if b.metric is not None
            and (
                shown := render_metric(
                    MetricBlock(metric=b.metric, entity_id=b.entity_ids[0] if b.entity_ids else None), result, names
                )
            )
            is not None
            and tuple(p.text for p in b.parts if p.value) != shown.numbers
        ]
        c.check(f"{case}: 값 조각은 수치 블록의 숫자 표기 그대로(강조한 것이 실제 수치)", not mismatched, mismatched)
        c.check(
            f"{case}: 글 블록에는 값 조각이 없고 수치 블록마다 값 조각이 있음",
            all(not any(p.value for p in b.parts) for b in blocks if b.kind == "text")
            and all(any(p.value for p in b.parts) for b in blocks if b.kind == "metric"),
        )


def _facts(c: Checker, results: dict[str, AnalysisResult], sample: list[AnalysisResult]) -> None:
    c.section("설명: 템플릿 문장이 이 결과에서 참인지(사실 조건)")

    def problems(result: AnalysisResult, template_id: str, *entities: str) -> list[str]:
        block = TemplateBlock(template_id=template_id, entities=entities)
        return check(Explanation(blocks=(block,), source="llm"), result)

    for case, result in results.items():
        passing = [t for t in VERDICT_TEMPLATES.values() if not problems(result, t)]
        c.check(
            f"{case}: 판정 문장은 엔진 판정과 같은 것 하나만 통과",
            passing == [VERDICT_TEMPLATES[result.verdict.level]],
            passing,
        )
        kind = result.timing.deadline.kind
        c.check(
            f"{case}: '바로 손실'·'미뤄도 손실 없음' 문장은 마감 종류가 맞을 때만",
            (not problems(result, "timing.urgent")) == (kind is DeadlineKind.CONFIRM_NOW)
            and (not problems(result, "timing.relaxed")) == (kind is DeadlineKind.NONE_IN_HORIZON),
            kind,
        )
        c.check(
            f"{case}: 판단 불가 안내는 판단 불가가 있을 때만",
            (not problems(result, "unresolved.note")) == bool(result.unresolved),
        )
        entities = result_entities(result)
        held = {h.po_id for h in result.timing.holds}
        c.check(
            f"{case}: 보류 문장은 보류 권고가 있는 발주에만",
            all((not problems(result, "hold.advice", po)) == (po in held) for po in entities[Slot.PO]),
        )
        rework = set(rework_blocks(result))
        c.check(
            f"{case}: 재작업 문장은 재작업이 있는 블록에만",
            all((not problems(result, "impact.rework", b)) == (b in rework) for b in entities[Slot.BLOCK]),
        )
        changed = {
            i.entity_id.rsplit("#", 1)[0] if i.entity_type is EntityType.PO_LINE else i.entity_id
            for i in result.impacts
            if i.impact_type is ImpactType.PO_CHANGE and i.entity_type in (EntityType.PO, EntityType.PO_LINE)
        }
        c.check(
            f"{case}: 발주 변경 문장은 발주 변경·취소 영향이 있는 발주에만",
            all((not problems(result, "impact.po_change", po)) == (po in changed) for po in entities[Slot.PO]),
        )
        targets = request_parts(result)
        c.check(
            f"{case}: '요청한 변경의 대상' 문장은 요청 연산의 부재에만",
            all((not problems(result, "impact.target", p)) == (p in targets) for p in entities[Slot.PART]),
        )
    warn, approve = results["G2-002"], results["G2-003"]
    c.check(
        "보기 사례가 실제로 갈림: 경고 사례에 재작업 블록, 승인 사례에 보류만 있고 변경 없는 발주",
        bool(rework_blocks(warn)) and any(problems(approve, "impact.po_change", h.po_id) for h in approve.timing.holds),
    )

    def metric_ok(result: AnalysisResult, metric: str) -> bool:
        return not check(Explanation(blocks=(MetricBlock(metric=metric),), source="llm"), result)

    def delays_follow(result: AnalysisResult) -> bool:
        delivery = result.schedule.delivery
        return metric_ok(result, "schedule.max_exit_delay") == (result.schedule.max_exit_delay_days > 0) and metric_ok(
            result, "schedule.delivery_delay"
        ) == (delivery is not None and delivery.added_delay_days > 0)

    no_delivery = approve.model_copy(update={"schedule": approve.schedule.model_copy(update={"delivery": None})})
    every = [*results.values(), no_delivery, *sample]
    wrong = [r.request.change.ecn_id for r in every if not delays_follow(r)]
    deliveries = {None if r.schedule.delivery is None else r.schedule.delivery.added_delay_days > 0 for r in every}
    c.check(
        f"지연 수치(구역 출구·인도)는 지연이 0보다 클 때만 통과({len(every)}건, 지연 있음·없음·인도 계산 없음 포함)",
        not wrong
        and {r.schedule.max_exit_delay_days > 0 for r in every} == {True, False}
        and deliveries == {None, True, False},
        (wrong[:3], deliveries),
    )

    def po_loss(result: AnalysisResult) -> bool:  # 발주 변경·취소 손실 줄(높은 값 > 0)이 있음 — 정의를 따로 적음
        return any(":po_change:" in line.line_id and line.amount.high > 0 for line in result.cost_lines)

    def consults(result: AnalysisResult) -> bool:
        return any(getattr(b, "template_id", None) == "po.consult" for b in default_explanation(result).blocks)

    wrong_consult = [
        r.request.change.ecn_id
        for r in every
        if consults(r) != po_loss(r) or (not problems(r, "po.consult")) != po_loss(r)
    ]
    c.check(
        f"손실 보상 협의 문장은 발주 변경·취소 손실이 있을 때만 넣고 통과({len(every)}건, 있음·없음 모두 포함)",
        not wrong_consult and {po_loss(r) for r in every} == {True, False},
        wrong_consult[:3],
    )
    positive = next(line for r in every for line in r.cost_lines if line.amount.high > 0)
    with_hash = approve.model_copy(
        update={
            "cost_lines": (
                positive.model_copy(update={"line_id": "R-T01:po_change:PO#0131#1"}),
                positive.model_copy(update={"line_id": "R-T01:po_change:PO#0130#2"}),
            )
        }
    )
    hashed = po_loss_pos(with_hash)
    c.check(
        "발주 ID에 #가 있어도 협의 대상 발주를 품목 번호(마지막 #)만 떼어 구분(PO#0130·PO#0131)",
        hashed == ["PO#0130", "PO#0131"] and po_of("PO#0130#2") == "PO#0130",
        hashed,
    )
    failing = [
        (r.request.change.ecn_id, check(default_explanation(r), r)) for r in sample if check(default_explanation(r), r)
    ]
    c.check(
        f"기본 설명은 사실 조건을 모두 통과(개발 분할 {len(sample)}건)",
        not failing and len(sample) >= 30,
        failing[:3],
    )


def _strip(block: RenderedBlock, names: dict[str, str]) -> str:
    text = block.text
    for entity in block.entity_ids:
        text = text.replace(names.get(entity, entity), "")
    return text
