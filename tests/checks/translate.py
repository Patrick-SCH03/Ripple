"""현장 통보문 번역 초안의 성질(계약 1.36.0, ripple/explain/translate.py · terms.py, docs/records.md(통보) 6절).

외부 AI 없이 고정 문장·용어집으로 만든다(키·네트워크 없이). 볼 것: 모든 템플릿·머리 문장이 언어마다 있고 자리 수가 같음,
번역본의 숫자·블록 번호·날짜가 원문과 같음, 용어집에 없는 말은 한국어 그대로·목록에 남음, 같은 입력 → 같은 출력,
한국어 원문 초안은 그대로, 작업반 통보만 번역, 언어 추가는 데이터만으로.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import yaml
from harness import Checker

from ripple.agent.resources import directory_of
from ripple.config.loaders import load_contacts, load_glossary, load_params, load_rulebook, read_yaml
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.assistant import EmailDraft, Notification, NotificationTarget
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.explain import RenderedBlock
from ripple.contracts.result import AnalysisResult
from ripple.contracts.translation import Glossary, MailTranslation
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import RequestError
from ripple.explain.compose import notifications
from ripple.explain.templates import TEMPLATES, Use
from ripple.explain.terms import TermTable
from ripple.explain.translate import CREW_TEMPLATES, TERMS_HEADING, TERMS_ITEM, glossary_problems, translate_mail
from ripple.generator.build import generate
from ripple.generator.io import load_config

GATE = PROJECT_ROOT / "eval" / "gate_cases" / "2" / "inputs"
NUMBER = re.compile(r"\d+")
CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-:]*\d[A-Za-z0-9.\-:]*|\d[A-Za-z0-9.\-:]*")
HANGUL_RUN = re.compile(r"[가-힣]+")
KOREAN_DATE = re.compile(r"(\d{4})년 (\d{1,2})월 (\d{1,2})일")
REQUIRED_TERMS = ("블록", "판 두께", "보강재", "용접", "재작업", "탑재", "도면 개정", "발주")


def run(c: Checker) -> None:
    settings = Settings.from_env({})
    glossary = load_glossary(settings.glossary_path)
    _glossary(c, settings.glossary_path, glossary)
    _terms(c, glossary)
    config = load_config()
    generated = generate(config)
    snapshot = generated.snapshot
    _coverage(c, snapshot.model_dump(mode="json"), glossary)
    index = GraphIndex(snapshot)
    rulebook, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    results: list[AnalysisResult] = []
    body = yaml.safe_load((GATE / "G2-002.yaml").read_text("utf-8"))
    results.append(analyze(index, AnalysisRequest.model_validate(body["request"]), rulebook, params))
    for ecn in [e for e in generated.ecns if e.split is EcnSplit.DEV][:40]:
        try:
            results.append(
                analyze(index, AnalysisRequest(change=ecn.change, as_of=config.scenario_date), rulebook, params)
            )
        except RequestError:
            continue
    contacts = load_contacts(settings.contacts_path)
    with_glossary = directory_of(snapshot, contacts, glossary)
    plain = directory_of(snapshot, contacts)
    pairs = [(r, n) for r in results for n in notifications(r, with_glossary)]
    crews = [(r, n) for r, n in pairs if n.target is NotificationTarget.CREW]
    _scope(c, results, pairs, crews, plain, glossary)
    _alignment(c, crews)
    _numbers(c, crews)
    _untranslated(c, crews, glossary)
    _determinism(c, crews, glossary)
    _real(c, results, directory_of(snapshot, None, glossary))
    _new_language(c, settings.glossary_path, crews)


def _names(node: Any, out: set[str]) -> set[str]:
    """지도 본문에서 'name' 값(엔터티 이름)을 모두 모은다."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "name" and isinstance(value, str):
                out.add(value)
            else:
                _names(value, out)
    elif isinstance(node, list):
        for value in node:
            _names(value, out)
    return out


# 작업반·협력사 고유 이름(합성): 번역하지 않고 한국어 그대로 두는 것이 규칙(지어내지 않는다)
PROPER_NAMES = {"한빛", "대성", "동진", "해송"}


def _coverage(c: Checker, body: Any, glossary: Glossary) -> None:
    c.section("번역 초안: 합성 지도 이름 용어집 범위")
    names = _names(body, set())
    gaps = {
        code: sorted(
            {
                m
                for name in names
                for m in TermTable({ko: t[code] for ko, t in glossary.terms.items()}).convert(name).missing
            }
            - PROPER_NAMES
        )
        for code in glossary.languages
    }
    c.check(
        f"합성 지도 이름 {len(names)}개의 조선 용어가 언어마다 용어집으로 모두 덮임(고유 이름 제외)",
        len(names) > 100 and not any(gaps.values()),
        gaps,
    )


def _glossary(c: Checker, path: Any, glossary: Glossary) -> None:
    c.section("번역 초안: 용어집·언어별 문장")
    c.check(
        "영어·베트남어가 있고, 작업반 메일의 모든 템플릿·머리 문장·수치 라벨이 언어마다 있으며 {0} 자리 수가 같음",
        {"en", "vi"} <= set(glossary.languages) and not glossary_problems(glossary),
        glossary_problems(glossary)[:3],
    )
    c.check(
        "작업반 메일 템플릿 목록은 모두 서버 템플릿(공식 메일용)",
        all(t in TEMPLATES and TEMPLATES[t].use is Use.MAIL for t in CREW_TEMPLATES),
    )
    missing = [t for t in REQUIRED_TERMS if t not in glossary.terms]
    c.check(
        f"핵심 조선 용어 {len(REQUIRED_TERMS)}개(블록·판 두께·보강재·용접·재작업·탑재·도면 개정·발주)가 용어집에 있음",
        not missing,
        missing,
    )
    raw = read_yaml(path)
    one = dict(raw["sentences"]["mail.crew.intro"])
    one.pop("vi")
    c.check(
        "한 문장에 한 언어 값이 빠지면 용어집을 거부(언어마다 모든 줄 필요)",
        c.raises(lambda: Glossary.model_validate({**raw, "sentences": {**raw["sentences"], "mail.crew.intro": one}})),
    )
    term = {**raw["terms"], "보강재": {"en": "stiffener"}}
    c.check("용어에 한 언어 값이 빠져도 거부", c.raises(lambda: Glossary.model_validate({**raw, "terms": term})))
    digits = {**raw["sentences"], "mail.thanks": {"en": "Thanks 2 you.", "vi": "Cảm ơn."}}
    c.check(
        "문장에 숫자를 쓰면 거부(숫자는 수치 블록 값으로만)",
        c.raises(lambda: Glossary.model_validate({**raw, "sentences": digits})),
    )
    slot = {**raw["sentences"], "mail.item.part": {"en": "- part", "vi": "- {0}"}}
    c.check(
        "자리({0}) 수가 한국어 템플릿과 다르면 문제로 잡힘(앱 시작 거부)",
        bool(glossary_problems(Glossary.model_validate({**raw, "sentences": slot}))),
    )


def _terms(c: Checker, glossary: Glossary) -> None:
    c.section("번역 초안: 용어 대역")
    table = TermTable({ko: t["en"] for ko, t in glossary.terms.items()})
    panel = table.name("T31C 판넬조립")
    c.check(
        "긴 용어 먼저(판넬조립 > 판), 이름은 '번역 (원문)'", panel.text == "T31C panel assembly (T31C 판넬조립)", panel
    )
    phrase = table.convert("판 두께 변경")
    c.check("띄어 쓴 여러 낱말 용어(판 두께)", phrase.text.startswith("plate thickness"), phrase)
    crew = table.name("한빛 작업반")
    c.check(
        "용어집에 없는 고유 이름은 한국어 그대로 두고 번역 안 한 말로 남김",
        crew.text == "한빛 work crew (한빛 작업반)" and crew.missing == ("한빛",),
        crew,
    )
    none = table.name("가나다라")
    c.check("맞는 용어가 하나도 없으면 원문 그대로(괄호 없음)", none.text == "가나다라" and not none.changed, none)
    # 용어집에 없는 낱말만(배관재·평형수탱크는 용어로 들어가 이제 통째로 바뀐다 — 아래 '합성어 용어' 검사)
    prefixes = {"배관공": "배관공", "평형수관": "평형수관", "우선 확인": "우선", "판정 보류": "판정"}
    split = {k: table.convert(k) for k in prefixes}
    c.check(
        "한 낱말 용어(배관·평형수·우·판)가 더 긴 낱말 앞머리에만 맞으면 그 덩어리 전체를 원문 그대로·목록에",
        all(t.text == k and not t.changed and prefixes[k] in t.missing for k, t in split.items()),
        {k: t.text for k, t in split.items()},
    )
    compounds = {k: table.convert(k) for k in ("배관재 협력사", "선수 평형수탱크", "평형수 체크 밸브 2")}
    c.check(
        "합성어 용어(배관재·평형수탱크·체크 밸브)는 통째로 바뀌고 남는 한글 없음",
        compounds["배관재 협력사"].text == "piping material subcontractor"
        and compounds["선수 평형수탱크"].text == "bow ballast water tank"
        and compounds["평형수 체크 밸브 2"].text == "ballast water check valve 2"
        and not any(t.missing for t in compounds.values()),
        {k: t.text for k, t in compounds.items()},
    )
    ids = table.name("No.3 COT 횡격벽 판 7")
    c.check(
        "블록 번호·숫자·영문은 그대로",
        ids.text.startswith("No.3 COT transverse bulkhead plate 7"),
        ids,
    )


def _scope(
    c: Checker,
    results: list[AnalysisResult],
    pairs: list[tuple[AnalysisResult, Notification]],
    crews: list[tuple[AnalysisResult, Notification]],
    plain: Any,
    glossary: Glossary,
) -> None:
    c.section("번역 초안: 작업반 통보만 · 한국어 원문 그대로")
    c.check(f"분석 {len(results)}건에 작업반 통보 {len(crews)}통", len(crews) >= 5, len(crews))
    others = [n for _, n in pairs if n.target is not NotificationTarget.CREW and n.email and n.email.translations]
    c.check("작업반 밖 알림(협력사·제작·도면)에는 번역 없음", not others)
    codes = tuple(glossary.languages)
    c.check(
        "작업반 통보마다 언어마다 번역 하나(용어집 언어 순서)",
        all(n.email and tuple(t.language for t in n.email.translations) == codes for _, n in crews),
    )
    same = True
    for result, notice in crews:
        before = {(n.target, n.recipient_id): n for n in notifications(result, plain)}
        original = before[(notice.target, notice.recipient_id)]
        assert notice.email is not None
        same = same and notice.email.model_copy(update={"translations": ()}) == original.email
        same = same and notice.body == original.body
    c.check("번역을 덧붙여도 한국어 원문 메일·카드 요약은 글자 하나 다르지 않음", same)


def _translations(
    crews: list[tuple[AnalysisResult, Notification]],
) -> list[tuple[AnalysisResult, EmailDraft, MailTranslation]]:
    return [(r, n.email, t) for r, n in crews if n.email for t in n.email.translations]


def _alignment(c: Checker, crews: list[tuple[AnalysisResult, Notification]]) -> None:
    c.section("번역 초안: 원문과 문단·블록이 하나씩 맞음")
    ok = True
    terms_ok = True
    for _, email, tr in _translations(crews):
        body, tail = tr.paragraphs[: len(email.paragraphs)], tr.paragraphs[len(email.paragraphs) :]
        ok = ok and len(body) == len(email.paragraphs) and len(tail) <= 1
        for ko, other in zip(email.paragraphs, body, strict=False):
            ok = ok and [_shape(b) for b in ko.blocks] == [_shape(b) for b in other.blocks]
        for paragraph in tail:
            ids = [b.template_id for b in paragraph.blocks]
            terms_ok = terms_ok and ids[0] == TERMS_HEADING and set(ids[1:]) == {TERMS_ITEM}
    c.check("번역 문단 = 원문 문단(같은 템플릿 ID·수치 키·엔터티 순서) + 끝 '주요 용어' 문단", ok)
    c.check("'주요 용어' 문단은 머리 한 줄 + 용어 줄(한국어 – 번역)", terms_ok)
    texts = [b.text for _, _, tr in _translations(crews) for p in tr.paragraphs for b in p.blocks]
    informal = [t for t in texts if t.endswith(("요.", "니다."))]
    c.check("번역 본문에 한국어 끝맺음 문장이 섞이지 않음(용어집 문장만)", not informal, informal[:2])
    c.check(
        "번역 머리 표기(한국어)는 합니다체 문장",
        all(tr.notice_ko.endswith("니다.") for _, _, tr in _translations(crews)),
    )
    notes = {n for _, _, tr in _translations(crews) for n in (tr.notice, tr.notice_ko)}
    c.check(
        "번역 머리는 원문 병기·원문 우선만('초안' 표기 없음 — 11-03 사용자 결정)",
        bool(notes) and not [n for n in notes if any(w in n.lower() for w in ("초안", "draft", "nháp"))],
        sorted(notes),
    )


def _shape(block: RenderedBlock) -> tuple[object, ...]:
    return (block.kind, block.template_id, block.metric, block.entity_ids)


def _numbers(c: Checker, crews: list[tuple[AnalysisResult, Notification]]) -> None:
    c.section("번역 초안: 숫자·블록 번호·날짜가 원문과 같음")
    wrong: list[str] = []
    codes: list[str] = []
    dates_ok = True
    for result, email, tr in _translations(crews):
        heads = ((email.subject, tr.subject), (email.reference, tr.reference))
        for ko_head, tr_head in heads:
            if _numbers_of(ko_head) != _numbers_of(tr_head):
                wrong.append(f"{tr.language}: {ko_head} → {tr_head}")
        for ko_p, tr_p in zip(email.paragraphs, tr.paragraphs, strict=False):
            for ko, other in zip(ko_p.blocks, tr_p.blocks, strict=True):
                if _numbers_of(ko.text) != _numbers_of(other.text):
                    wrong.append(f"{tr.language}: {ko.text} → {other.text}")
                codes += [f"{tr.language}: {x}" for x in CODE.findall(ko.text) if x not in other.text]
                if ko.metric:
                    dates_ok = dates_ok and _same_date(ko, other, result)
    c.check("문단·제목·관련 건 줄마다 숫자(정수 집합)가 원문과 같음", not wrong, wrong[:3])
    c.check("원문의 블록 번호·ID(T31C·S-001·No.3 …)가 번역 블록에 그대로", not codes, codes[:3])
    c.check("날짜는 원문 날짜와 같은 날을 YYYY-MM-DD로(값 조각 하나)", dates_ok)


def _numbers_of(text: str) -> set[int]:
    return {int(n) for n in NUMBER.findall(text)}


def _same_date(ko: RenderedBlock, other: RenderedBlock, result: AnalysisResult) -> bool:
    match = KOREAN_DATE.search(ko.text)
    values = [p.text for p in other.parts if p.value]
    if match is None or len(values) != 1:
        return False
    day = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return values[0] == day.isoformat() and day == result.timing.deadline.last_day


def _untranslated(c: Checker, crews: list[tuple[AnalysisResult, Notification]], glossary: Glossary) -> None:
    c.section("번역 초안: 용어집에 없는 말은 한국어 그대로·목록에")
    leaks: list[str] = []
    for _, email, tr in _translations(crews):
        for ko_p, tr_p in zip(email.paragraphs, tr.paragraphs, strict=False):
            for ko, other in zip(ko_p.blocks, tr_p.blocks, strict=True):
                originals = {p.entity_id: p.text for p in ko.parts if p.entity_id}
                for part in other.parts:
                    core = part.text
                    if part.entity_id:
                        core = core.removesuffix(f" ({originals.get(part.entity_id, '')})")
                    leaks += [
                        f"{tr.language}: {run} in {part.text}"
                        for run in HANGUL_RUN.findall(core)
                        if not any(run in piece for piece in tr.untranslated)
                    ]
    c.check("번역 글의 한글은 엔터티 원문 괄호 말고는 모두 '번역 안 한 말' 목록에 있음", not leaks, leaks[:3])
    marked = all(
        glossary.languages[tr.language].original_mark in tr.reference
        for r, _, tr in _translations(crews)
        if HANGUL_RUN.search(r.request.change.title)
    )
    c.check("관련 건 줄의 변경 제목(자유 문장)은 한국어 그대로 두고 원문 표시를 붙임", marked)


def _determinism(c: Checker, crews: list[tuple[AnalysisResult, Notification]], glossary: Glossary) -> None:
    c.section("번역 초안: 결정적")
    same = True
    for result, notice in crews[:10]:
        assert notice.email is not None
        base = notice.email.model_copy(update={"translations": ()})
        again = translate_mail(base, result, glossary, notice.recipient)
        same = same and again == notice.email and again.model_dump_json() == notice.email.model_dump_json()
    c.check("같은 원문·결과·용어집이면 번역이 글자까지 같음", same)


def _real(c: Checker, results: list[AnalysisResult], directory: Any) -> None:
    c.section("번역 초안: 실데이터 지도(연락처 없음)")
    crews = [n for r in results for n in notifications(r, directory) if n.target is NotificationTarget.CREW]
    c.check(
        "연락처가 없어도(실데이터) 번역 초안은 붙고 인사말은 받는 쪽 이름으로",
        bool(crews)
        and all(n.email and n.email.translations and not n.email.to for n in crews)
        and all(n.recipient.split()[0] in t.salutation for n in crews if n.email for t in n.email.translations),
    )


def _new_language(c: Checker, path: Any, crews: list[tuple[AnalysisResult, Notification]]) -> None:
    c.section("번역 초안: 언어 추가는 데이터만")
    raw = read_yaml(path)
    copy = {key: {**texts, "uz": texts["en"]} for key, texts in raw["sentences"].items()}
    added = {
        **raw,
        "languages": {**raw["languages"], "uz": {**raw["languages"]["en"], "name": "O'zbekcha"}},
        "sentences": copy,
        "metrics": {key: {**texts, "uz": texts["en"]} for key, texts in raw["metrics"].items()},
        "terms": {key: {**texts, "uz": texts["en"]} for key, texts in raw["terms"].items()},
    }
    glossary = Glossary.model_validate(added)
    result, notice = crews[0]
    assert notice.email is not None
    base = notice.email.model_copy(update={"translations": ()})
    found = translate_mail(base, result, glossary, notice.recipient).translations
    c.check(
        "데이터 파일에 언어 하나(uz)를 더하면 코드 고침 없이 번역이 셋",
        not glossary_problems(glossary) and [t.language for t in found] == [*raw["languages"], "uz"],
        [t.language for t in found],
    )
