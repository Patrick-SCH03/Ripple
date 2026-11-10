"""엑셀 내보내기 검사(분석 결과·결재 대장): 시트와 값이 API 응답 필드 그대로인지, 권한·작업 공간 규칙.

- 분석 결과(POST /api/analyses/export): 같은 요청의 분석 응답과 총액·마감일·분석 ID·비용 줄·곡선·영향 수가 같고,
  비용 줄 합 = 총액(합계 줄), 대안 비교 시트는 대안 탭과 같은 계산(대안 포함 분석)일 때만.
- 결재 대장(GET /api/manage/export): 결재·현황 응답의 결재함 줄과 같은 값, 팀장만.
- 글 칸이 '='로 시작해도 수식이 아닌 글자.
"""

from __future__ import annotations

import io
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from fastapi.testclient import TestClient
from harness import Checker
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from checks.records import ADMIN_PW, FIRST, MEMBER_PW, _action, _app, _client, _login, _record, _staff
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.approval import ApprovalPlan
from ripple.contracts.domain import DataMode
from ripple.contracts.result import AnalysisResult, HoldAdvice
from ripple.generator.build import generate
from ripple.generator.io import load_config, write_outputs
from ripple.ingest.out_labels import COST_ITEM, COST_KIND, name
from ripple.ingest.out_ledger import late_text
from ripple.ingest.out_table import Column, table
from ripple.records.approval import APPROVAL_LINE, hold_approval, plus_workdays

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SHEETS = ["요약", "영향 목록", "비용 근거", "가정값", "확정 시점 곡선", "중량 변화"]


def run(c: Checker) -> None:
    c.section("엑셀 내보내기: 분석 결과 · 결재 대장")
    _formula(c)
    _approval_hold(c)
    _ledger_late(c)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        write_outputs(generate(load_config()), root / "synthetic")
        _api(c, root)
        _real_mode(c, root)


def _formula(c: Checker) -> None:
    ws = Workbook().active
    assert isinstance(ws, Worksheet)
    table(ws, [Column("이름")], [['=HYPERLINK("x")']])
    cell = ws.cell(row=2, column=1)
    c.check("'='로 시작하는 글은 수식이 아닌 글자로", cell.data_type == "s" and cell.value == '=HYPERLINK("x")')


def _approval_hold(c: Checker) -> None:
    """보류 권고의 결재 기간 한 줄: 규칙은 서버 ripple/records/approval.py 한 곳(화면·엑셀은 결재 계획 값만 씀),
    근무일은 주말을 건너뜀, 무비용이면 '담당자 처리 — 결재 없음'."""
    tuesday = date(2026, 10, 20)

    def advice(days: int, until: date) -> HoldAdvice:
        return cast(HoldAdvice, SimpleNamespace(po_id="PO-0001", max_hold_days=days, hold_until=until))

    longer = hold_approval(advice(13, date(2026, 11, 2)), tuesday, 3)
    shorter = hold_approval(advice(8, date(2026, 10, 28)), tuesday, 3)
    free = hold_approval(advice(8, date(2026, 11, 2)), tuesday, 0)
    c.check(
        "근무일 6일 = 다음 주 수요일(주말 제외), 권고가 더 길면 공급사 협의 · 같거나 짧으면 그 안에 결재 · "
        "무비용은 결재 없음",
        plus_workdays(tuesday, 6) == date(2026, 10, 28)
        and longer.outlasts
        and longer.approval_end == date(2026, 10, 28)
        and longer.text
        == "결재 중(약 6근무일 — 결재 3단계 × 1~2일)에는 보류 유지 가능 · 권고 13일까지 보류 시 공급사 협의 필요"
        and not shorter.outlasts
        and shorter.text.startswith("권고 8일은 결재 기간(약 6근무일")
        and (free.text, free.short, free.approval_end) == ("담당자 처리 — 결재 없음", "담당자 처리 — 결재 없음", None),
        (longer, shorter, free),
    )
    web = (PROJECT_ROOT / "web" / "src" / "lib" / "approvalHold.ts").read_text("utf-8")
    c.check(
        "화면 lib/approvalHold.ts에는 결재 상수·근무일 셈이 없음(서버 결재 계획 값만 씀)",
        not re.search(r"export const APPROVAL_|addWorkingDays|getUTCDay", web),
    )


def _book(content: bytes) -> Workbook:
    return load_workbook(io.BytesIO(content))


def _rows(ws: Worksheet) -> list[tuple[Any, ...]]:
    return [row for row in ws.iter_rows(min_row=2, values_only=True) if any(v is not None for v in row)]


def _day(value: Any) -> date | None:
    return value.date() if isinstance(value, datetime) else value


def _strength_sample(client: TestClient, token: str) -> tuple[dict[str, Any], AnalysisResult, AnalysisResult]:
    """대안이 나오는 샘플 하나: (요청, 기본 분석, 대안 포함 분석)."""
    headers = {"X-Ripple-Workspace": token}
    for sample in client.get("/api/samples").json():
        request = sample["request"]
        wide = AnalysisResult.model_validate(
            client.post("/api/analyses", json=request | {"include_alternatives": True}, headers=headers).json()
        )
        if wide.alternatives:
            base = AnalysisResult.model_validate(client.post("/api/analyses", json=request, headers=headers).json())
            return request, base, wide
    raise AssertionError("대안이 나오는 샘플이 없어요")


def _analysis_book(c: Checker, kim: TestClient, token: str) -> dict[str, Any]:
    request, result, wide = _strength_sample(kim, token)
    response = kim.post("/api/analyses/export", json=request, headers={"X-Ripple-Workspace": token})
    disposition = response.headers.get("content-disposition", "")
    c.check(
        "분석 결과 엑셀: 200 · xlsx · 한글 파일 이름(filename*)과 영문 대체 이름",
        response.status_code == 200
        and response.headers.get("content-type", "").startswith(XLSX)
        and "filename*=UTF-8''Ripple_" in disposition
        and 'filename="ripple-analysis-' in disposition,
        (response.status_code, disposition),
    )
    book = _book(response.content)
    c.check(
        "시트: 요약 · 영향 목록 · 비용 근거 · 가정값 · 확정 시점 곡선 · 중량 변화 · 대안 비교",
        book.sheetnames == [*SHEETS, "대안 비교"],
    )
    _weight_rows(c, book, result)
    summary = {row[0]: row[1] for row in reversed(_rows(book["요약"]))}  # 같은 이름이면 첫 줄
    c.check(
        "요약: 설계변경 · 총변경비용(대표·최소·최대) · 결정 기한 · 판정 이유 · 분석 ID가 분석 응답과 같음",
        summary["설계변경"] == request["change"]["ecn_id"]
        and (summary["총변경비용(대표, 원)"], summary["총변경비용(최소, 원)"], summary["총변경비용(최대, 원)"])
        == (result.total.value, result.total.low, result.total.high)
        and _day(summary["결정 기한"]) == result.timing.deadline.last_day
        and summary["분석 ID"] == result.analysis_id
        and [r[1] for r in _rows(book["요약"]) if r[0] == "판정 이유"] == list(result.verdict.reasons),
        summary,
    )
    plan = result.approval_plan
    notes = [str(r[3] or "") for r in _rows(book["요약"]) if r[0] == "보류 권고"]
    c.check(
        "분석 응답에 결재 계획(1.33.0: 검토 전 결재선 3단계 또는 무비용 · 보류 권고마다 결재 기간), "
        "엑셀 보류 권고 비고 = 그 문구(규칙은 서버 한 곳)",
        plan is not None
        and len(plan.steps) == (0 if plan.no_cost else 3)
        and [h.po_id for h in plan.holds] == [a.po_id for a in result.timing.holds]
        and all(any(h.text in note for note in notes) for h in plan.holds),
        (plan, notes),
    )
    _cost_rows(c, book, result)
    curve = _rows(book["확정 시점 곡선"])
    marked = [r for r in curve if r[1] and "결정 기한" in r[1]]
    c.check(
        "확정 시점 곡선: 하루 한 줄(기준일 → 탐색 끝) · 추가손실이 곡선 값 · 결정 기한 표시는 그날 한 줄",
        len(curve) == len(result.timing.curve)
        and all(r[5] == p.additional_loss.value for r, p in zip(curve, result.timing.curve, strict=True))
        and (
            result.timing.deadline.kind.value == "none_in_horizon"
            or [_day(r[0]) for r in marked] == [result.timing.deadline.last_day]
        ),
    )
    factors = sum(len(line.factors) for line in result.cost_lines)
    c.check(
        "영향 목록 = 영향 수, 가정값 = 비용 줄 가정값 수",
        len(_rows(book["영향 목록"])) == len(result.impacts) and len(_rows(book["가정값"])) == factors,
    )
    alternatives = [r for r in book["대안 비교"].iter_rows(min_row=2, values_only=True) if r[2] is not None]
    advised = next(
        (a.label for a in wide.alternatives if wide.recommendation and a.alt_id == wide.recommendation.alt_id), None
    )
    c.check(
        "대안 비교: 대안 포함 분석의 대안마다 한 줄(총액 그대로) · 권고 표시는 권고한 대안 하나",
        [r[2] for r in alternatives[: len(wide.alternatives)]] == [a.label for a in wide.alternatives]
        and [r[12] for r in alternatives[: len(wide.alternatives)]] == [a.total.value for a in wide.alternatives]
        and [r[2] for r in alternatives if r[0] == "권고"] == [advised],
    )
    return request


def _weight_rows(c: Checker, book: Workbook, result: AnalysisResult) -> None:
    """중량 변화 시트(1.34.0): 부재마다 한 줄 + 블록 소계 + 합계 줄이 결과 필드 그대로, 요약 줄 = 합계 차이."""
    weight = result.weight_change
    rows = [r for r in _rows(book["중량 변화"]) if r[3] is not None]
    parts = [r for r in rows if r[2] is not None]
    blocks = [r for r in rows if str(r[3]).startswith("블록 소계")]
    total = next((r for r in rows if str(r[3]).startswith("합계")), None)
    summary = {row[0]: row[1] for row in _rows(book["요약"])}
    c.check(
        "중량 변화 시트: 부재 줄(원래·새 중량 그대로) · 블록 소계 = 결과 블록 값 · 합계 줄 = 결과 합계 · "
        "요약 '강재 중량 변화(t)' = 합계 차이",
        weight is not None
        and [(r[2], r[7], r[8]) for r in parts]
        == [(p.part_id, p.before_t, p.after_t) for b in weight.blocks for p in b.parts]
        and [(r[0], r[7], r[8], r[9]) for r in blocks]
        == [(b.block_id, b.before_t, b.after_t, b.delta_t) for b in weight.blocks]
        and total is not None
        and (total[7], total[8], total[9]) == (weight.before_t, weight.after_t, weight.delta_t)
        and summary.get("강재 중량 변화(t)") == (weight.delta_t if weight.blocks else 0),
        (weight, total, summary.get("강재 중량 변화(t)")),
    )


def _cost_rows(c: Checker, book: Workbook, result: AnalysisResult) -> None:
    rows = _rows(book["비용 근거"])
    order = {"labor": 0, "material": 1, "damages": 2}
    lines = sorted(
        result.cost_lines,
        key=lambda line: (order[line.kind.value] if line.kind else 0, -line.amount.value, line.line_id),
    )
    body, last = rows[:-1], rows[-1]
    split = result.cost_split
    c.check(
        "비용 근거: 구분 묶음(공수 → 재료비 → 지체상금) 안에서 금액 큰 순으로 비용 줄마다 한 줄(구분·세부 구분·"
        "대표·최소·최대·공수(MH) 그대로) · 마지막 합계 줄 = 총변경비용 = 줄 합 · 합계 공수 = 추가 공수",
        split is not None
        and [(r[1], r[2], r[3], r[9], r[10], r[11], r[12]) for r in body]
        == [
            (
                li.label,
                name(COST_KIND, li.kind),
                name(COST_ITEM, li.item),
                li.amount.value,
                li.amount.low,
                li.amount.high,
                li.hours.value if li.hours else None,
            )
            for li in lines
        ]
        and last[1] == "합계(총변경비용)"
        and (last[9], last[10], last[11]) == (result.total.value, result.total.low, result.total.high)
        and sum(r[9] for r in body) == result.total.value
        and (last[12], last[13], last[14]) == (split.labor_hours.value, split.labor_hours.low, split.labor_hours.high),
    )
    summary = {row[0]: row[1] for row in reversed(_rows(book["요약"]))}
    c.check(
        "요약: 추가 공수(MH) · 공수 금액 · 추가 재료비 · 그중 구매 = 결과 구분별 합(공수 금액 + 재료비 = 총변경비용)",
        split is not None
        and (
            summary.get("추가 공수(대표, MH)"),
            summary.get("공수 금액(대표, 원)"),
            summary.get("추가 재료비(대표, 원)"),
            summary.get("그중 구매(대표, 원)"),
        )
        == (split.labor_hours.value, split.labor.value, split.material.value, split.purchase.value)
        and (summary.get("지체상금(대표, 원)") is not None) == (split.damages.high != 0)
        and split.labor.value + split.material.value + split.damages.value == summary["총변경비용(대표, 원)"],
        summary,
    )


def _api(c: Checker, root: Path) -> None:
    app = _app(root, "api-export")
    with _client(app):
        lead = _client(app)
        _login(lead, "lead", FIRST)
        lead.post("/api/auth/password", json={"current_password": FIRST, "new_password": ADMIN_PW})
        kim = _staff(app, lead, "kim", "member", MEMBER_PW)
        token = kim.get("/api/samples").headers["X-Ripple-Workspace"]
        request = _analysis_book(c, kim, token)
        stale = kim.post("/api/analyses/export", json=request, headers={"X-Ripple-Workspace": "stale-token"})
        demo = _client(app)
        demo.post("/api/auth/demo")
        c.check(
            "작업 공간이 바뀌었으면 409, 체험도 합성 작업 공간이면 내려받음",
            stale.status_code == 409 and demo.post("/api/analyses/export", json=request).status_code == 200,
            stale.status_code,
        )
        _ledger(c, lead, kim, request, token)


def _ledger(c: Checker, lead: TestClient, kim: TestClient, request: dict[str, Any], token: str) -> None:
    result = kim.post("/api/analyses", json=request, headers={"X-Ripple-Workspace": token}).json()
    _record(kim, request, result["analysis_id"], token, 0)
    _action(kim, request["change"]["ecn_id"], "request_review", token)
    # 결재함은 내 단계 건만(docs/records.md(기록·결재) 14절): 파트장 단계를 팀장이 전결해 팀장 단계로 넘긴다
    _action(lead, request["change"]["ecn_id"], "approve", token, reason="파트장 부재로 전결")
    other = next(
        s["request"]
        for s in kim.get("/api/samples").json()
        if s["request"]["change"]["ecn_id"] != request["change"]["ecn_id"]
    )
    waiting = kim.post("/api/analyses", json=other, headers={"X-Ripple-Workspace": token}).json()
    _record(kim, other, waiting["analysis_id"], token, 0)
    _action(kim, other["change"]["ecn_id"], "request_review", token)  # 파트장 단계 — 팀장에게는 전결 묶음
    overview = lead.get("/api/manage/overview").json()
    inbox, proxy = overview["inbox"], overview["proxy"]
    response = lead.get("/api/manage/export")
    book = _book(response.content)
    rows = _rows(book["결재 대장"])
    c.check(
        "결재 대장: 팀장 200 · 시트 넷 · 결재함 줄마다 한 줄(설계변경·개정·요청자·마감·총액·차액 그대로) 뒤에 "
        "전결 묶음 줄, 담당자 403",
        response.status_code == 200
        and book.sheetnames == ["결재 대장", "현황", "상태별", "블록별"]
        and [(r[0], r[2], _day(r[17]), r[20], r[25]) for r in rows]
        == [
            (i["ecn_id"], i["revision"], date.fromisoformat(i["deadline"]), i["total"]["value"], i["cheaper_by"])
            for i in (*inbox, *proxy)
        ]
        and all(r[14] == f"{i['requested_by']['name']}(담당자)" for r, i in zip(rows, (*inbox, *proxy), strict=True))
        and len(inbox) >= 1
        and len(proxy) >= 1
        and kim.get("/api/manage/export").status_code == 403,
        (response.status_code, rows[:1], inbox[:1]),
    )
    _ledger_line(c, rows, inbox, proxy)


def _ledger_line(c: Checker, rows: list[tuple[Any, ...]], inbox: list[Any], proxy: list[Any]) -> None:
    """결재 대장의 결재선 열(docs/records.md(기록·결재) 14절): 화면 결재함 줄과 같은 값."""
    mine, extra = rows[: len(inbox)], rows[len(inbox) :]
    item, held = inbox[0], proxy[0]
    signer = item["signed"][0]["actor"]["name"]
    plan = item["approval_plan"]
    c.check(
        "결재 대장 결재선 열: 결재함(내 결재·전결 가능) · 지금 단계(n/전체) · 결재선(단계 수) · "
        "승인한 단계(전결 표시) · 단계 대기 시간 · 남은 결재 올릴 기한·단계당 1일 기한·지남·결정은 빨라야"
        "(결재 계획 그대로)",
        [r[4] for r in mine] == ["내 결재"] * len(inbox)
        and [r[4] for r in extra] == ["전결 가능"] * len(proxy)
        and (mine[0][5], mine[0][6], mine[0][7])
        == ("팀장(2/3단계)", "파트장 → 팀장 → 본부장(3단계)", f"파트장 {signer}(전결)")
        and mine[0][8] == item["step_waiting_hours"]
        and _day(mine[0][9]) == (date.fromisoformat(plan["submit_by"]) if plan["submit_by"] else None)
        and _day(mine[0][10]) == (date.fromisoformat(plan["submit_by_low"]) if plan["submit_by_low"] else None)
        and mine[0][11] == _late_cell(plan["late"], plan["late_low"], plan["submit_by_low"] is not None)
        and _day(mine[0][12]) == (date.fromisoformat(plan["earliest"]) if plan["earliest"] else None)
        and (extra[0][5], extra[0][7]) == ("파트장(1/3단계)", None)
        and held["step"] == "part_lead",
        (mine[0][4:13], extra[0][4:13]),
    )


def _late_cell(late: bool, late_low: bool, has_low: bool) -> str | None:
    """정답: 결재 대장 '결재 기한 지남' 칸 — 화면 submitLine의 주의(대표만 지남)·위험(단계당 1일로도 지남)과 같은 뜻."""
    if not late:
        return None
    return "지남(단계당 1일로는 가능)" if has_low and not late_low else "지남"


def _ledger_late(c: Checker) -> None:
    """결재 대장 '지남' 칸이 대표만 지남과 단계당 1일로도 지남을 가른다(옛 계획 = '지남')."""
    common: dict[str, Any] = {
        "no_cost": False,
        "line": APPROVAL_LINE,
        "steps": APPROVAL_LINE,
        "line_steps": 3,
        "days_per_step_low": 1,
        "days_per_step": 2,
        "workdays": 6,
        "submit_by": date(2026, 10, 27),
    }
    low = {"submit_by_low": date(2026, 10, 30)}
    plans = {
        "기한 전": ApprovalPlan.model_validate({**common, **low}),
        "대표만 지남": ApprovalPlan.model_validate({**common, **low, "late": True, "earliest": date(2026, 11, 9)}),
        "둘 다 지남": ApprovalPlan.model_validate(
            {**common, **low, "late": True, "late_low": True, "earliest": date(2026, 11, 12)}
        ),
        "옛 계획 지남": ApprovalPlan.model_validate({**common, "late": True, "earliest": date(2026, 11, 9)}),
    }
    got = {k: late_text(p) for k, p in plans.items()}
    c.check(
        "결재 대장 지남 칸: 기한 전 빈칸 · 대표만 지남 '지남(단계당 1일로는 가능)'(화면 주의) · 둘 다 지남 '지남'"
        "(화면 위험) · 단계당 1일 기한 없는 옛 계획 '지남'",
        got == {k: _late_cell(p.late, p.late_low, p.submit_by_low is not None) for k, p in plans.items()}
        and got
        == {
            "기한 전": None,
            "대표만 지남": "지남(단계당 1일로는 가능)",
            "둘 다 지남": "지남",
            "옛 계획 지남": "지남",
        },
        got,
    )


TRANSPORT_ECN = "ECN-D-0130"  # 외자재 운송이 붙는 시연 샘플(samples.DEMO_ECNS)
TRANSPORT_NAME = {"sea": "선박", "air": "항공"}


def _real_mode(c: Checker, root: Path) -> None:
    """점검 D-7·M-3: 실데이터 모드(설정)에서 기본 합성 지도를 분석해 내보내면 요약 '데이터'는 기록·결재 대장과
    같은 유효 데이터 모드('실제 데이터'), '자재가 늦게 오면' 비고는 화면 구역 출구 카드와 같은 근거(운송 일수)."""
    app = _app(root, "api-export-real", extra={"RIPPLE_AUTH": "off", "RIPPLE_DATA_MODE": "real"})
    with _client(app) as dev:
        samples = dev.get("/api/samples")
        headers = {"X-Ripple-Workspace": samples.headers["X-Ripple-Workspace"]}
        request = next(s["request"] for s in samples.json() if s["ecn_id"] == TRANSPORT_ECN)
        result = AnalysisResult.model_validate(dev.post("/api/analyses", json=request, headers=headers).json())
        book = _book(dev.post("/api/analyses/export", json=request, headers=headers).content)
    rows = {r[0]: r for r in reversed(_rows(book["요약"]))}
    risk = result.schedule.risk
    legs = risk.transport if risk is not None else ()
    note = str(rows["자재가 늦게 오면 최대 지연(일)"][2] or "") if "자재가 늦게 오면 최대 지연(일)" in rows else ""
    c.check(
        f"실데이터 모드 + 기본 합성 지도: 엑셀 요약 '데이터' = 실제 데이터(분석 결과의 지도 모드는 합성) · "
        f"{TRANSPORT_ECN} '자재가 늦게 오면' 비고에 '운송 선박 n일 포함'(화면 exitRiskText와 같은 근거)",
        result.data_mode is DataMode.SYNTHETIC
        and rows["데이터"][1] == "실제 데이터"
        and not rows["데이터"][2]
        and bool(legs)
        and risk is not None
        and rows["자재가 늦게 오면 최대 지연(일)"][1] == risk.max_exit_delay_days
        and all(f"운송 {TRANSPORT_NAME[leg.mode]} {leg.days}일 포함" in note for leg in legs),
        (rows.get("데이터"), note, legs),
    )
