"""결정 도우미(계약 1.31.0, docs/records.md(기록·결재) 13절): 세 줄 요약 · 서명 전 확인할 것 · AI 고르기 · API.

- 성질: 합성 기본 지도의 개발 분할 설계변경과 그 가정 계산 변형(대안 포함·선상 설치·보류 적용·선주 요청·원인 미입력)으로
  줄 3개 순서 · 글 속 숫자 출처(ripple.brief.audit) · 규칙 결정성 · 권고 우선순위 · computed=true 값 = 엔진 값.
- 검사 함수가 지어낸 숫자·틀린 요일·순서를 잡는지(반례).
- 안 정하면 줄의 분기(마감일까지 · 오늘 · 기간 안 없음 · 이미 지남 · 대표값 0).
- 가짜 모델로 AI 고르기: 정상 · 후보 밖 · 중복 · 빈 답 · 3개 넘음 · 예외 → 규칙, 실데이터는 부르지 않음,
  세 줄은 그대로.
- API: 검토·보류가 아니면 409 · 없으면 404 · 체험·실데이터 · 같은 기록은 다시 부르지 않음 ·
  활성 합성 지도 + 실데이터 기록.
- 기억 키: 같은 기록 ID · 다른 개정(A → B → A)이면 응답 개정이 각각.
"""

from __future__ import annotations

import re
import tempfile
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from fixtures import AS_OF, analysis_result, timing
from harness import Checker

from checks.records import (
    ADMIN_ENV,
    _action,
    _analysis,
    _body,
    _client,
    _do,
    _people,
    _record,
    _save,
    _settings_for,
    _who,
)
from ripple.api.app import create_app
from ripple.brief import audit, build_brief
from ripple.config.loaders import load_params, load_rulebook, load_strength
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.analysis import AnalysisRequest, HoldAction
from ripple.contracts.brief import BriefCheck, BriefLine, DecisionBrief, PastCases
from ripple.contracts.change import ChangeCause
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.domain import DataMode
from ripple.contracts.records import EcnAction, RecordBody
from ripple.contracts.result import (
    REQUEST_ALT,
    Amount,
    AnalysisResult,
    CurvePoint,
    OnboardDirection,
    TimingResult,
    expected_deadline,
)
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.eval.cost_gate_inputs import cost_gate_inputs
from ripple.explain.format import money
from ripple.generator.build import generate
from ripple.generator.io import load_config, write_outputs
from ripple.llm.base import Guarded
from ripple.llm.route import load_routes

DEV_SAMPLE = 40  # 개발 분할에서 볼 설계변경 수(기본 + 가정 계산 변형)
LD_CASE = "G2-002"  # 지체상금이 있는 2단계 관문 사례(선주 요청·원인 미입력)
RECORD_ID = "R-00000000000000b1"
CASES_WAIT_S = 180  # 합성 과거 사례 묶음을 기다리는 상한(보통 6초)
DEMO_ECNS = ("ECN-D-0119", "ECN-D-0043")  # 시연 시나리오의 설계변경(화면 샘플)
ORDER = ["change", "loss", "advice"]


class Fake:
    """가짜 모델: answer(프롬프트)를 돌려주거나 예외를 낸다. 부른 횟수를 센다."""

    name = "가짜 모델"

    def __init__(self, answer: Callable[[str], object]) -> None:
        self.answer = answer
        self.calls = 0

    def generate_json(self, prompt: str, schema: object, timeout_s: float) -> object:
        self.calls += 1
        return self.answer(prompt)


def _keys_in(prompt: str) -> list[str]:
    """프롬프트의 후보 키(후보 줄 = '- 키: 글 / 틀리면: …')."""
    tail = prompt.split("[후보]", 1)[1]
    return [line[2:].split(": ", 1)[0] for line in tail.splitlines() if line.startswith("- ")]


def _brief(result: AnalysisResult, *, today: Any = None, llm: Guarded | None = None, **body: Any) -> DecisionBrief:
    record = _record_body(result, **body)
    return build_brief(record, record_id=RECORD_ID, revision=1, today=today or result.request.as_of, llm=llm)


def _record_body(result: AnalysisResult, mode: DataMode = DataMode.SYNTHETIC) -> RecordBody:
    return RecordBody(
        ecn_id=result.request.change.ecn_id, snapshot_id=result.versions.snapshot_id, data_mode=mode, result=result
    )


def run(c: Checker) -> None:
    config = load_config()
    generated = generate(config)
    index = GraphIndex(generated.snapshot)
    book = load_rulebook(PROJECT_ROOT / "rules" / "propagation.yaml")
    params = load_params(PROJECT_ROOT / "params" / "cost_v1.yaml")
    strength = load_strength(PROJECT_ROOT / "rules" / "strength.yaml")

    def run_one(request: AnalysisRequest) -> AnalysisResult:
        return analyze(index, request, book, params, strength)

    dev = [AnalysisRequest(change=e.change, as_of=e.as_of) for e in generated.ecns if e.split is EcnSplit.DEV]
    results = _variants(run_one, dev[:DEV_SAMPLE])
    ld = {k.case_id: k for k in cost_gate_inputs(generated.snapshot, generated.seed, config.scenario_date)}[LD_CASE]
    owner = ld.request.change.model_copy(update={"cause": ChangeCause.OWNER_REQUEST})
    results += [run_one(ld.request), run_one(ld.request.model_copy(update={"change": owner}))]
    _properties(c, results)
    _computed(c, results, run_one)
    _audit_catches(c, results)
    _loss(c)
    _ai(c, results)
    _cache_by_revision(c, results[0])
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        write_outputs(generated, root / "synthetic")
        _api(c, root)
        _past_cases(c, root)


def _variants(
    run_one: Callable[[AnalysisRequest], AnalysisResult], requests: list[AnalysisRequest]
) -> list[AnalysisResult]:
    """기본 분석과 가정 계산 변형: 보류 권고가 있으면 그 보류 적용, 선상 설치 선택지가 있으면 선상 설치,
    앞 8건은 대안 포함."""
    found: list[AnalysisResult] = []
    for n, request in enumerate(requests):
        base = run_one(request)
        found.append(base)
        if base.timing.holds:
            hold = base.timing.holds[0]
            held = (HoldAction(po_id=hold.po_id, hold_days=max(1, hold.max_hold_days)),)
            found.append(run_one(request.model_copy(update={"holds": held})))
        if base.onboard is not None:
            found.append(run_one(request.model_copy(update={"outfit_on_board": True})))
        if n < 8:
            found.append(run_one(request.model_copy(update={"include_alternatives": True})))
    return found


# ---------- 성질 ----------


def _first_advice(result: AnalysisResult) -> str:
    """독립 정답: 권고 우선순위(더 저렴한 충족 대안 → 보류 권고 → 선상 설치 → 판정)의 첫 성립."""
    rec = result.recommendation
    request = next((a for a in result.alternatives if a.alt_id == REQUEST_ALT), None)
    if rec is not None and request is not None and rec.alt_id != REQUEST_ALT:
        base = request.best_total or request.total
        if base.value > rec.total.value:
            return "advice.cheaper"
    applied = {h.po_id for h in result.request.holds}
    hold = next((h for h in result.timing.holds if h.po_id not in applied), None)
    if hold is not None and (hold.deadline_after != result.timing.deadline or hold.avoided.high > 0):
        return "advice.hold"
    option = result.onboard
    if (
        option is not None
        and option.direction is OnboardDirection.TO_ON_BOARD
        and (
            option.erection_delay_then_days < option.erection_delay_now_days
            or option.exit_delay_then_days < option.exit_delay_now_days
        )
    ):
        return "advice.onboard"
    return "advice.approve" if result.verdict.level.value == "approve" else "advice.review"


def _properties(c: Checker, results: list[AnalysisResult]) -> None:
    c.section(f"결정 도우미: 성질(개발 분할 {DEV_SAMPLE}건 + 가정 계산 변형 = {len(results)}개 결과)")
    problems: list[str] = []
    orders, shape, again, advice = [], [], [], []
    kinds: set[str] = set()
    for result in results:
        brief = _brief(result)
        ecn = result.request.change.ecn_id
        problems += [f"{ecn}: {p}" for p in audit(brief, _record_body(result), result.request.as_of)]
        if [line.kind for line in brief.lines] != ORDER:
            orders.append(ecn)
        keys = [check.key for check in brief.checks]
        if len(keys) > 3 or len(set(keys)) != len(keys) or brief.picked_by != "rule":
            shape.append(ecn)
        if _brief(result).model_dump() != brief.model_dump():
            again.append(ecn)
        if brief.lines[2].template_id != _first_advice(result):
            advice.append(f"{ecn}: {brief.lines[2].template_id} ≠ {_first_advice(result)}")
        kinds |= {line.template_id for line in brief.lines} | {k.split(":")[0] + ":" + k.split(":")[1] for k in keys}
    c.check(
        "글 속 숫자가 모두 기록 본문 값(검사 함수 통과), 계산하지 않은 '틀리면'에 숫자 없음", not problems, problems[:4]
    )
    c.check("세 줄은 change · loss · advice 순서로 정확히 3개", not orders, orders[:4])
    c.check("확인할 것 3개 이하·키 고유, AI 없이는 규칙 순서(picked_by rule)", not shape, shape[:4])
    c.check("같은 결과면 같은 답(두 번 만들어 바이트 단위로 같음)", not again, again[:4])
    c.check("권고 = 고정 우선순위의 첫 성립(더 저렴한 대안 → 보류 → 선상 설치 → 판정)", not advice, advice[:4])
    wanted = {"advice.cheaper", "advice.hold", "advice.onboard", "assume:holds", "assume:onboard", "assume:lead_time"}
    wanted |= {"assume:owner_deal", "assume:cause", "loss.by_date"}
    c.check(
        "표본이 권고·가정 줄을 고루 지남(대안 · 보류 · 선상 설치 · 리드타임 · 선주 요청 · 원인 미입력)",
        wanted <= kinds,
        sorted(wanted - kinds),
    )


def _computed(c: Checker, results: list[AnalysisResult], run_one: Callable[[AnalysisRequest], AnalysisResult]) -> None:
    c.section("결정 도우미: computed=true의 숫자 = 엔진이 그 가정을 바꿔 계산한 값")
    wrong: list[str] = []
    seen = 0
    for result in results:
        for check in _brief(result).checks:
            if not check.computed:
                continue
            seen += 1
            expected = _expected_numbers(check.key, result, run_one)
            if expected is None or not all(part in check.why for part in expected):
                wrong.append(f"{result.request.change.ecn_id} {check.key}: {check.why} ⊉ {expected}")
    c.check(
        "선상 설치(반대 방식으로 다시 분석한 출구 지연·총액 차이) · 리드타임 위험 · 노출 금액(원인 미입력의 지체상금)",
        seen > 0 and not wrong,
        (seen, wrong[:3]),
    )


def _expected_numbers(
    key: str, result: AnalysisResult, run_one: Callable[[AnalysisRequest], AnalysisResult]
) -> list[str] | None:
    """그 확인할 것의 '틀리면'에 있어야 할 숫자 표기(엔진으로 따로 구함)."""
    if key == "assume:onboard":
        flipped = run_one(result.request.model_copy(update={"outfit_on_board": False}))
        delta = flipped.total.value - result.total.value
        parts = [money(abs(delta))]
        if flipped.schedule.max_exit_delay_days != result.schedule.max_exit_delay_days:
            parts.append(f"{result.schedule.max_exit_delay_days}일 → {flipped.schedule.max_exit_delay_days}일")
        return parts
    if key == "assume:lead_time":
        risk = result.schedule.risk
        return None if risk is None else [f"→ {risk.max_exit_delay_days}일"]
    if key == "assume:owner_deal":
        bare = result.request.change.model_copy(update={"cause": None})
        plain = run_one(result.request.model_copy(update={"change": bare}))
        penalty = sum(line.amount.value for line in plain.cost_lines if line.rule_id == "R-L01")
        return [money(penalty)]
    return None


def _audit_catches(c: Checker, results: list[AnalysisResult]) -> None:
    c.section("결정 도우미 검사 함수: 지어낸 숫자·틀린 요일·순서를 잡는다(반례)")
    result = next(r for r in results if r.timing.deadline.kind.value == "by_date")
    body, today = _record_body(result), result.request.as_of
    good = _brief(result)

    def with_line(index: int, text: str) -> DecisionBrief:
        lines = list(good.lines)
        lines[index] = BriefLine(kind=lines[index].kind, text=text, template_id=lines[index].template_id)
        return good.model_copy(update={"lines": tuple(lines)})

    day = result.timing.deadline.last_day
    wrong_weekday = "월화수목금토일"[(day.weekday() + 1) % 7]
    cases = {
        "기록에 없는 금액": with_line(1, good.lines[1].text + " 또는 12,345만원"),
        "기록에 없는 일수": with_line(0, good.lines[0].text + " 997일"),
        "틀린 요일": with_line(1, f"{day.month}월 {day.day}일({wrong_weekday})까지 확정해요."),
        "남은 숫자": with_line(2, good.lines[2].text + " 3.7"),
        "순서 바뀜": good.model_copy(update={"lines": (good.lines[1], good.lines[0], good.lines[2])}),
        "기록에 없는 개수": with_line(0, good.lines[0].text + f" 영향 {len(result.impacts) + 917}곳"),
        "기록에 없는 D-n": with_line(1, good.lines[1].text + f" (D-{(day - today).days + 40})"),
        "기록에 없는 배율": with_line(2, good.lines[2].text + " 판재 × 9.7"),
        "계산하지 않은 '틀리면'의 숫자": good.model_copy(
            update={
                "checks": (
                    BriefCheck(key="state:x", text="확인해 주세요.", why="틀리면 3일 늦어져요.", computed=False),
                )
            }
        ),
        "키가 겹치는 확인할 것": good.model_copy(
            update={"checks": (BriefCheck(key="k", text="가", why="나"), BriefCheck(key="k", text="다", why="라"))}
        ),
    }
    caught = {name: bool(audit(brief, body, today)) for name, brief in cases.items()}
    c.check("통과하던 도우미에 하나씩 넣으면 모두 걸림", not audit(good, body, today) and all(caught.values()), caught)


# ---------- 안 정하면 줄 ----------


def _flat_then(high: int) -> TimingResult:
    """대표값은 그대로이고 최대만 늘어나는 곡선(마감일까지 2일)."""
    base = Amount.exact(1_000_000)
    points = tuple(
        CurvePoint(
            confirm_on=AS_OF + timedelta(days=i),
            total=Amount(value=1_000_000, low=1_000_000, high=1_000_000 + (high if i >= 2 else 0)),
            additional_loss=Amount(value=0, low=0, high=high if i >= 2 else 0),
            max_exit_delay_days=0,
        )
        for i in range(4)
    )
    return TimingResult(base_cost=base, curve=points, deadline=expected_deadline(points))


def _loss(c: Checker) -> None:
    c.section("결정 도우미: 안 정하면 줄의 분기")

    def loss(losses: list[int] | TimingResult, days: int = 0) -> BriefLine:
        shaped = losses if isinstance(losses, TimingResult) else timing(losses)
        result = analysis_result(timing=shaped.model_dump(mode="json"))
        return _brief(result, today=AS_OF + timedelta(days=days)).lines[1]

    by_date, today, none = loss([0, 0, 50_000, 50_000]), loss([0, 30_000, 30_000, 30_000]), loss([0, 0, 0, 0])
    passed, flat = loss([0, 0, 50_000, 50_000], days=3), loss(_flat_then(20_000))
    c.check(
        "마감일까지(D-n · 다음 날 늘어나는 금액) · 오늘 · 기간 안 없음 · 이미 지남(오늘 확정할 때 늘어난 금액)",
        by_date.template_id == "loss.by_date"
        and "(D-1)" in by_date.text
        and "다음 날부터 5만원 증가" in by_date.text
        and today.template_id == "loss.today"
        and "내일부터 3만원 증가" in today.text
        and none.template_id == "loss.none"
        and passed.template_id == "loss.passed"
        and "기준일 대비 5만원 추가" in passed.text,
        (by_date.text, today.text, none.text, passed.text),
    )
    c.check(
        "다음 날 대표값이 0이면 '+0원' 대신 대표 금액은 그대로 · 최대만(결재함 '미루면'과 같은 분기)",
        flat.template_id == "loss.by_date" and "대표 금액은 그대로" in flat.text and "최대 2만원" in flat.text,
        flat.text,
    )


# ---------- AI 고르기 ----------


def _ai(c: Checker, results: list[AnalysisResult]) -> None:
    c.section("결정 도우미: 가짜 모델로 AI 고르기(확인할 것의 선택·순서만)")
    result = max(results, key=lambda r: len(_brief(r).checks))
    rule = _brief(result)
    keys = [check.key for check in rule.checks]

    def picked(answer: Callable[[str], object], mode: DataMode = DataMode.SYNTHETIC) -> tuple[DecisionBrief, Fake]:
        fake = Fake(answer)
        return _brief(result, llm=Guarded(fake, mode)), fake

    normal, fake = picked(lambda prompt: {"checks": list(reversed(_keys_in(prompt)))[:2]})
    c.check(
        "정상 답: 고른 키 순서대로 · picked_by ai · 세 줄은 규칙 그대로(권고를 AI가 바꾸지 않음) · 한 번 부름",
        len(keys) >= 2
        and normal.picked_by == "ai"
        and [k.key for k in normal.checks] == list(reversed(_keys_in(_prompt_of(result))))[:2]
        and normal.lines == rule.lines
        and fake.calls == 1,
        (normal.picked_by, [k.key for k in normal.checks]),
    )

    def boom(_: str) -> object:
        raise RuntimeError("모델이 멈춤")

    bad_answers: dict[str, Callable[[str], object]] = {
        "후보 밖 키": lambda p: {"checks": ["state:없는-발주"]},
        "중복": lambda p: {"checks": [_keys_in(p)[0], _keys_in(p)[0]]},
        "빈 답": lambda p: {"checks": []},
        "형식 오류": lambda p: {"blocks": []},
        "3개 넘음": lambda p: {"checks": (_keys_in(p) * 2)[:4]},
        "예외": boom,
    }
    fallen = {name: picked(answer)[0] for name, answer in bad_answers.items()}
    c.check(
        "후보 밖 · 중복 · 빈 답 · 형식 오류 · 3개 넘음 · 예외 → 규칙 순서(같은 결과)",
        all(b.picked_by == "rule" and b.model_dump() == rule.model_dump() for b in fallen.values()),
        {name: b.picked_by for name, b in fallen.items()},
    )
    real_guard, guard_fake = picked(lambda p: {"checks": _keys_in(p)[:1]}, mode=DataMode.REAL)
    leak = Fake(lambda p: {"checks": _keys_in(p)[:1]})
    from_real = _brief(result, llm=Guarded(leak, DataMode.SYNTHETIC), mode=DataMode.REAL)
    c.check(
        "실데이터: 경계가 실데이터 모드면 모델을 부르지 않고, 경계가 합성이어도 기록 본문이 실데이터면 부르지 않음",
        guard_fake.calls == 0
        and real_guard.picked_by == "rule"
        and leak.calls == 0
        and from_real.picked_by == "rule"
        and from_real.data_mode is DataMode.REAL,
        (guard_fake.calls, leak.calls),
    )
    routes = load_routes(PROJECT_ROOT / "params" / "llm_v1.yaml").routes
    brief_route, explain_route = routes.get("brief"), routes["explain"]
    c.check(
        "경로 설정: brief 작업이 있고 예산 6초 이하, 1순위는 설명 고르기와 같은 모델",
        brief_route is not None and brief_route.budget_s <= 6 and brief_route.models[0] == explain_route.models[0],
        brief_route,
    )


def _prompt_of(result: AnalysisResult) -> str:
    seen: list[str] = []

    def keep(prompt: str) -> object:
        seen.append(prompt)
        return {"checks": []}

    _brief(result, llm=Guarded(Fake(keep), DataMode.SYNTHETIC))
    return seen[0]


# ---------- API ----------


def _api(c: Checker, root: Path) -> None:
    c.section("결정 도우미 API: 검토·보류 중에만 · 권한 · 같은 기록은 다시 부르지 않음 · 실데이터 기록")
    fake = Fake(lambda prompt: {"checks": _keys_in(prompt)[-1:]})
    app = create_app(_settings_for(root, "brief-api"), environ=ADMIN_ENV, llm_factory=lambda _settings: fake)
    with _client(app):
        app.state.cases.wait(CASES_WAIT_S)  # 과거 사례 묶음이 다 만들어진 뒤에 본다(만드는 중이면 기억하지 않아서)
        people = _people(app)
        lead, kim, demo = people["lead"], people["kim"], people["demo"]
        request, result, token = _analysis(kim, 0)
        ecn = request["change"]["ecn_id"]
        _record(kim, request, result["analysis_id"], token, 0)
        early = lead.get(f"/api/ecns/{ecn}/brief")
        _action(kim, ecn, "request_review", token)
        first = lead.get(f"/api/ecns/{ecn}/brief")
        calls = fake.calls
        again = lead.get(f"/api/ecns/{ecn}/brief")
        status = lead.get(f"/api/ecns/{ecn}").json()["status"]
        body = first.json()
        c.check(
            "기록만(분석) 409 invalid_transition · 검토 중 200(진행 중 개정의 기록 · 세 줄 순서 · 합성은 AI가 고름)",
            early.status_code == 409
            and early.json()["detail"]["code"] == "invalid_transition"
            and first.status_code == 200
            and body["record_id"] == status["record_id"]
            and body["revision"] == status["review"]["revision"]
            and [line["kind"] for line in body["lines"]] == ORDER
            and body["picked_by"] == ("ai" if body["checks"] else "rule"),
            (early.status_code, first.status_code, body.get("picked_by")),
        )
        c.check(
            "같은 기록 · 같은 날 · 같은 AI 경로면 기억한 답(모델을 또 부르지 않음) · 담당자·체험은 403"
            "(결재하는 사람만, 외부 AI를 못 부르게) · 없는 ECN 404",
            again.json() == body
            and fake.calls == calls
            and demo.get(f"/api/ecns/{ecn}/brief").status_code == 403
            and kim.get(f"/api/ecns/{ecn}/brief").status_code == 403
            and fake.calls == calls
            and lead.get("/api/ecns/ECN-NONE/brief").status_code == 404,
            (fake.calls, calls),
        )
        held = _action(lead, ecn, "hold", token, reason="발주 상태 확인 뒤 결정")
        on_hold = lead.get(f"/api/ecns/{ecn}/brief")
        _action(lead, ecn, "reject", token, reason="대안으로 다시 올려 주세요")
        rejected = lead.get(f"/api/ecns/{ecn}/brief")
        c.check(
            "보류 중 200 · 반려 뒤 409(결재 대기가 아님)",
            held.status_code == 200 and on_hold.status_code == 200 and rejected.status_code == 409,
            (held.status_code, on_hold.status_code, rejected.status_code),
        )
        _real_record(c, app, lead, demo, fake, AnalysisResult.model_validate(result))


def _real_record(c: Checker, app: Any, lead: Any, demo: Any, fake: Fake, result: AnalysisResult) -> None:
    """활성 지도는 합성인데 실데이터 기록을 결재하는 경우: 본문이 외부 AI로 가지 않는다."""
    store = app.state.records
    body = _body(result, ecn="ECN-REAL-0001", mode=DataMode.REAL)
    member = _who("kim")
    _save(store, body, member, 0)
    _do(store, "ECN-REAL-0001", EcnAction.REQUEST_REVIEW, member, snapshot=result.versions.snapshot_id)
    before = fake.calls
    got = lead.get("/api/ecns/ECN-REAL-0001/brief")
    c.check(
        "활성 합성 지도 + 실데이터 기록 → AI를 부르지 않음(규칙 순서) · 과거 사례에 합성 없음 · 체험은 403",
        got.status_code == 200
        and got.json()["picked_by"] == "rule"
        and got.json()["data_mode"] == "real"
        and got.json()["cases"]["synthetic"] is False
        and not any(item["synthetic"] for item in got.json()["cases"]["items"])
        and fake.calls == before
        and demo.get("/api/ecns/ECN-REAL-0001/brief").status_code == 403,
        (got.status_code, fake.calls, before),
    )
    numbers = re.findall(r"\d", " ".join(line["text"] for line in got.json()["lines"]))
    c.check("실데이터 기록도 세 줄이 그대로 나옴(숫자는 기록 본문)", len(numbers) > 0)


def _past_cases(c: Checker, root: Path) -> None:
    c.section("결정 도우미 API: 비슷한 과거 사례(기록이 깔린 지도 기준 · 만드는 중 · 지도를 모름)")
    app = create_app(_settings_for(root, "brief-cases"), environ=ADMIN_ENV)
    with _client(app):
        people = _people(app)
        lead, kim = people["lead"], people["kim"]
        samples = kim.get("/api/samples")
        token = samples.headers["X-Ripple-Workspace"]
        requests = {s["request"]["change"]["ecn_id"]: s["request"] for s in samples.json()}
        results: dict[str, AnalysisResult] = {}
        for ecn in DEMO_ECNS:
            analysed = kim.post("/api/analyses", json=requests[ecn], headers={"X-Ripple-Workspace": token}).json()
            results[ecn] = AnalysisResult.model_validate(analysed)
            _record(kim, requests[ecn], analysed["analysis_id"], token, 0)
            _action(kim, ecn, "request_review", token)
        app.state.cases.wait(CASES_WAIT_S)
        got = {ecn: lead.get(f"/api/ecns/{ecn}/brief").json()["cases"] for ecn in DEMO_ECNS}
        c.check(
            "시연 설계변경(ECN-D-0119·0043) 결재 카드에 합성 과거 사례 1~3건 · 요약 · 합성 표시 · 자기 자신 없음",
            all(
                cases["status"] == "ready"
                and cases["synthetic"]
                and 1 <= len(cases["items"]) <= 3
                and cases["summary"]
                and all(item["synthetic"] and item["case_id"] != ecn for item in cases["items"])
                for ecn, cases in got.items()
            ),
            {ecn: (cases["status"], len(cases["items"]), cases.get("summary")) for ecn, cases in got.items()},
        )
        _cheaper_from_recorded(c, kim, lead, requests["ECN-D-0119"], token)
        _shelf_states(c, app, results["ECN-D-0119"])
    _not_cached_while_building(c, results["ECN-D-0119"])


def _cheaper_from_recorded(c: Checker, kim: Any, lead: Any, request: dict[str, Any], token: str) -> None:
    """대안 없이 기록한 ECN-D-0119: 같은 지도·같은 판이라 도우미가 대안 포함으로 한 번 계산 →
    권고가 대안 탭과 같은 숫자."""
    tab = kim.post(
        "/api/analyses", json={**request, "include_alternatives": True}, headers={"X-Ripple-Workspace": token}
    ).json()
    rec = tab["recommendation"]
    base = next(a for a in tab["alternatives"] if a["alt_id"] == "ALT-REQ")
    saving = (base["best_total"] or base["total"])["value"] - rec["total"]["value"]
    label = next(a["label"] for a in tab["alternatives"] if a["alt_id"] == rec["alt_id"])
    advice = lead.get("/api/ecns/ECN-D-0119/brief").json()["lines"][2]
    c.check(
        "대안 없이 기록해도 같은 지도·같은 판이면 권고 = 대안 탭의 최저 비용 조합"
        "(이름 · 확정 총액 · 요청안보다 적은 금액)",
        advice["template_id"] == "advice.cheaper"
        and label in advice["text"]
        and f"{money(saving)} 절감" in advice["text"]
        and money(rec["total"]["value"]) in advice["text"],
        (advice, label, saving),
    )


def _not_cached_while_building(c: Checker, result: AnalysisResult) -> None:
    """과거 사례를 만드는 중에 만든 도우미는 기억하지 않는다 — 다음 요청이 ready를 받는다(15분 동안 building 아님)."""
    from ripple.api.brief import BriefService

    service = BriefService()
    body = _record_body(result)

    def ask(status: Literal["ready", "building"]) -> DecisionBrief:
        return service.brief(
            body,
            record_id=RECORD_ID,
            revision=1,
            today=result.request.as_of,
            model=None,
            configured=DataMode.SYNTHETIC,
            cases=lambda _r: PastCases(status=status, synthetic=True),
        )

    building, ready, again = ask("building"), ask("ready"), ask("building")
    c.check(
        "building 응답은 기억하지 않아 다음 요청이 ready, ready는 기억(그 뒤 같은 날·같은 기록은 ready 그대로)",
        (building.cases.status, ready.cases.status, again.cases.status) == ("building", "ready", "ready"),
        (building.cases.status, ready.cases.status, again.cases.status),
    )


def _cache_by_revision(c: Checker, result: AnalysisResult) -> None:
    """같은 본문(기록 ID)을 다른 개정으로 다시 부르면(A → B → A) 기억 키에 개정이 들어가 응답 개정이 각각 맞다
    (개정이 키에 없으면 B가 A의 기억을 받아 revision 1이 나온다)."""
    from ripple.api.brief import BriefService

    service = BriefService()
    body = _record_body(result)

    def ask(revision: int) -> DecisionBrief:
        return service.brief(
            body,
            record_id=RECORD_ID,
            revision=revision,
            today=result.request.as_of,
            model=None,
            configured=DataMode.SYNTHETIC,
            cases=lambda _r: PastCases(status="ready", synthetic=True),
        )

    got = [ask(revision).revision for revision in (1, 2, 1)]
    again = ask(2)
    c.check(
        "같은 기록 ID · 다른 개정(1 → 2 → 1)이면 응답 개정이 각각(기억 키에 개정), 다시 부르면 그 개정의 기억",
        got == [1, 2, 1] and again.revision == 2 and again.record_id == RECORD_ID,
        (got, again.revision),
    )


def _shelf_states(c: Checker, app: Any, result: AnalysisResult) -> None:
    """만드는 중이면 building(빈 답). 기록의 지도를 서버가 모르면(지난 날의 실시간 세계) 그 기준일 세계를 다시 만들어
    지도 ID가 같을 때만 묶음, 다르면 unavailable — 다른 지도의 사례를 끌어오지 않음."""
    from ripple.api.past_cases import finder_for
    from ripple.cases import CaseShelf, EngineKit

    context = app.state.context

    def fresh_shelf() -> CaseShelf:
        return CaseShelf(EngineKit(context.rulebook, context.params), context.settings.params_path, lambda i, e: ())

    fresh = fresh_shelf()
    body = _record_body(result)
    store, holder, outcomes = app.state.records, app.state.workspaces, app.state.outcomes
    building = finder_for(fresh, holder, body, store, outcomes)(result)
    fresh.wait(CASES_WAIT_S)
    ready = finder_for(fresh, holder, body, store, outcomes)(result)
    c.check(
        "새 선반: 처음엔 building(빈 답) → 다 만들면 ready",
        building.status == "building" and not building.items and ready.status == "ready",
        (building.status, ready.status),
    )
    lost = fresh_shelf()  # 서버가 기록 지도를 모름(holder 없음): 기록 기준일로 다시 만든 세계와 지도 ID가 같으면 묶음
    first = finder_for(lost, None, body, store, outcomes)(result)
    lost.wait(CASES_WAIT_S)
    regained = finder_for(lost, None, body, store, outcomes)(result)
    other = body.model_copy(update={"snapshot_id": "G-00000000000000cc"})  # 다시 만든 세계와 다른 지도
    finder_for(lost, None, other, store, outcomes)(result)
    lost.wait(CASES_WAIT_S)
    unknown = finder_for(lost, None, other, store, outcomes)(result)
    c.check(
        "기록 지도를 모르면 그 기준일 세계를 다시 만들어 building → ready(같은 지도 ID), 지도 ID가 다르면 unavailable",
        first.status == "building"
        and regained.status == "ready"
        and len(regained.items) >= 1
        and unknown.status == "unavailable"
        and not unknown.items,
        (first.status, regained.status, unknown.status),
    )
