"""E1·2단계 관문 평가 보고서와 사례별 손 계산 대조표를 만든다."""

from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import cast

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.domain import EntityType
from ripple.contracts.evaluation import GateCase, GateCaseInput
from ripple.contracts.result import AnalysisResult, ImpactReport
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.overlay import ChangeView
from ripple.engine.propagate import impact_report
from ripple.eval.cost_metrics import close
from ripple.eval.evidence_metrics import EvidenceCheck, LineEvidence, check_cost_line, check_impact
from ripple.eval.impact_metrics import CaseScore, Key, score_case, score_gate
from ripple.generator.build import generate
from ripple.generator.io import load_config
from scripts.gate_cases import STAGES, _load_cases

SUMMARY = PROJECT_ROOT / "docs" / "eval_summary.md"
REPORTS = PROJECT_ROOT / "eval" / "reports"
Cell = str | int | float | bool | None


def _ratio(tp: int, other: int) -> str:
    return f"{tp / (tp + other):.3f}" if tp + other else "1.000"


def _breakdown(rows: dict[str, Counter[str]]) -> list[str]:
    out = ["| 구분 | tp | fn | fp | recall | precision |", "|---|---:|---:|---:|---:|---:|"]
    for name, counts in sorted(rows.items()):
        tp, fn, fp = counts["tp"], counts["fn"], counts["fp"]
        out.append(f"| {name} | {tp} | {fn} | {fp} | {_ratio(tp, fn)} | {_ratio(tp, fp)} |")
    return out


def _write_workbook(sheets: dict[str, list[list[Cell]]]) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        for name, rows in sheets.items():
            with (REPORTS / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                csv.writer(stream).writerows(rows)
        return REPORTS / "E1 사례별.csv"
    book = Workbook()
    active = book.active
    assert active is not None
    book.remove(active)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="24516B")
        for column in sheet.columns:
            letter = get_column_letter(column[0].column)
            width = min(68, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
            sheet.column_dimensions[letter].width = width
            for cell in column[1:]:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
    path = REPORTS / "hand_calc_table.xlsx"
    book.save(path)
    return path


def _amount_fields(case: GateCase, result: AnalysisResult) -> tuple[bool, bool, bool]:
    expected = case.expected.total
    assert expected is not None
    wanted = {line.line_id: line for line in case.expected.cost_lines}
    actual = {line.line_id: line for line in result.cost_lines}
    checks = []
    for want, got in ((expected, result.total),):
        checks.append((close(want.value_krw, got.value), close(want.low, got.low), close(want.high, got.high)))
    for line_id, line_want in wanted.items():
        line_got = actual.get(line_id)
        if line_got is None:
            checks.append((False, False, False))
        else:
            checks.append(
                (
                    close(line_want.amount.value_krw, line_got.amount.value),
                    close(line_want.amount.low, line_got.amount.low),
                    close(line_want.amount.high, line_got.amount.high),
                )
            )
    return (
        all(row[0] for row in checks),
        all(row[1] for row in checks),
        all(row[2] for row in checks),
    )


def _cost_flags(case: GateCase, result: AnalysisResult) -> dict[str, bool]:
    timing, verdict = case.expected.timing, case.expected.verdict
    assert timing is not None and verdict is not None
    amounts = _amount_fields(case, result)
    return {
        "비용 줄 집합": {line.line_id for line in case.expected.cost_lines}
        == {line.line_id for line in result.cost_lines},
        "대표 금액": amounts[0],
        "최소 금액": amounts[1],
        "최대 금액": amounts[2],
        "구역 출구 지연": timing.zone_exit_delays
        == {zone.zone_id: zone.delay_days for zone in result.schedule.zone_exits if zone.delay_days > 0},
        "인도 지연": timing.delivery_added_days
        == (None if result.schedule.delivery is None else result.schedule.delivery.added_delay_days),
        "판정": verdict.level is result.verdict.level and set(verdict.reasons) == set(result.verdict.reasons),
    }


def _report(
    scores: list[CaseScore],
    breakdowns: dict[str, dict[str, Counter[str]]],
    flags: list[dict[str, bool]],
    evidence: list[tuple[str, EvidenceCheck]],
    lines: list[tuple[str, LineEvidence]],
    contracts: Counter[str],
    workbook: Path,
    required: list[str],
) -> str:
    gate = score_gate(scores, required)
    pooled = gate.pooled("impacts")
    tp = len(pooled.matched)
    fn = len(pooled.expected - pooled.produced)
    fp = len(pooled.produced - pooled.expected)
    out = [
        "# 관문 평가 지표 요약",
        "",
        "- 실행: `uv run python scripts/eval_report.py`",
        f"- 대상: E1 {len(scores)}건, 2단계 {len(flags)}건; 표: `{workbook.relative_to(PROJECT_ROOT).as_posix()}`",
        "",
        "## 영향 노드 재현율·정밀도",
        "",
        "- 정의: (엔터티 ID, 영향 종류, 규칙 ID) 집합을 사례 ID와 묶어 비교. "
        "재현율 = tp/(tp+fn), 정밀도 = tp/(tp+fp). 분모 0이면 1.000.",
        f"- 합계: tp {tp}, fn {fn}, fp {fp}, 정답 {len(pooled.expected)}, "
        f"출력 {len(pooled.produced)}, 재현율 {_ratio(tp, fn)}, 정밀도 {_ratio(tp, fp)}.",
    ]
    for title, rows in breakdowns.items():
        out += ["", f"### {title}", "", *_breakdown(rows)]
    out += [
        "",
        "## 계산 정답률",
        "",
        "- 정의: 사례별 비용 줄 ID 집합, 총액 및 대응되는 각 줄의 대표·최소·최대(각 ±1%, 최소 1원), "
        "양수 구역 출구 지연 지도, 인도 추가 지연, 판정 수준·이유 집합을 기대값과 비교.",
        "",
    ]
    for name in flags[0] if flags else ():
        out.append(f"- {name}: {sum(row[name] for row in flags)}/{len(flags)}건 일치.")
    out += [
        "",
        "## 계약 적합률(참고)",
        "",
        "- 정의: 각 단계의 결과를 `model_dump` 후 같은 Pydantic 결과 계약으로 다시 검증한 비율. "
        "생성 중 계약 예외가 나면 스크립트 실패.",
        f"- 검증 통과: {contracts['pass']}/{contracts['all']}건.",
        "",
        "## 의미상 근거 완전성",
        "",
        "- 정의: 영향마다 요청 대상 부재/그 연산의 NEW 부재(인도 지연은 구역 출구 이정표) 출발, "
        "모든 홉의 방향 있는 원본·변경 후 연결 또는 허용 가상 연결, 영향 엔터티 종착·마지막 홉의 "
        "규칙 ID 일치를 모두 요구. 경로가 없는 직접 영향은 영향 엔터티를 출발점으로 간주.",
    ]
    n = len(evidence)
    complete = sum(check.complete for _, check in evidence)
    out.append(
        f"- 완전: {complete}/{n} ({_ratio(complete, n - complete)}). "
        f"출발 실패 {sum(not check.origin_ok for _, check in evidence)}, "
        f"연결 실패 {sum(not check.links_ok for _, check in evidence)}, "
        f"종착·규칙 실패 {sum(not check.terminal_ok for _, check in evidence)}."
    )
    for kind, count in sorted(Counter(check.origin_kind for _, check in evidence).items()):
        out.append(f"- 출발 유형 `{kind}`: {count}건.")
    for kind, count in sorted(
        Counter(v.split(":", 1)[0] for _, check in evidence for v in check.virtual_links).items()
    ):
        out.append(f"- 허용 가상 연결 `{kind}`: {count}홉.")
    failed = [(case_id, check) for case_id, check in evidence if not check.complete]
    if failed:
        out += ["", "### 근거 불완전 영향 원문", ""]
        for case_id, check in failed:
            why = ", ".join(
                name
                for name, ok in (("출발", check.origin_ok), ("연결", check.links_ok), ("종착·규칙", check.terminal_ok))
                if not ok
            )
            path = (
                " / ".join(f"{h.src} -{h.relation.value}-> {h.dst} [{h.rule_id}]" for h in check.impact.path)
                or "(빈 경로)"
            )
            out.append(
                f"- {case_id} · {check.impact.entity_id}/{check.impact.impact_type.value}/"
                f"{check.impact.rule_id} · {why} · `{path}`"
            )
    out += [
        "",
        "## 비용 근거 대응",
        "",
        "- 정의: 일반 비용 줄은 (규칙 ID, 엔터티 ID, 영향 종류) 키로 대응. "
        "`C-01:material`은 요청 대상/NEW 직접 자재 계산, `C-02:new_work`는 추가 연산의 NEW 직접 제작, "
        "`R-L01:ld`는 같은 호선의 인도 지연, `R-M01:stock/handling`은 재고/품목 전용 영향으로 대응.",
        f"- 대응: {sum(item.matched for _, item in lines)}/{len(lines)}줄.",
        "",
        "| 유형 | 대응 | 전체 |",
        "|---|---:|---:|",
    ]
    categories = sorted({item.category for _, item in lines})
    for category in categories:
        group = [item for _, item in lines if item.category == category]
        out.append(f"| {category} | {sum(item.matched for item in group)} | {len(group)} |")
    missing = [(case_id, item) for case_id, item in lines if not item.matched]
    if missing:
        out += ["", "### 근거 없는 비용 줄", ""]
        out += [f"- {case_id} · `{item.line_id}` · 키 `{item.key}`" for case_id, item in missing]
    return "\n".join(out) + "\n"


def _required_ids(stage: int, cases: list[GateCase], built: dict[str, GateCaseInput]) -> list[str]:
    """필수 사례 ID = 사례 입력 생성기가 지금 지도로 만드는 사례(`gate_cases.py score`와 같은 기준).

    건수를 코드에 두지 않고, 저장된 사례 파일 집합이 그것과 같을 때만 돌려준다(사례가 늘거나 줄면 생성기와 파일이
    함께 바뀌어야 하고, 한쪽만 바뀌면 보고서를 쓰지 않는다)."""
    required = sorted(built)
    stored = {case.case_id for case in cases}
    if not required:
        raise ValueError(f"{stage}단계 입력 생성기가 사례를 만들지 않았어요")
    if stored != set(required):
        missing = ", ".join(sorted(set(required) - stored)) or "없음"
        extra = ", ".join(sorted(stored - set(required))) or "없음"
        raise ValueError(
            f"{stage}단계 사례 파일이 입력 생성기 사례와 달라요(파일에 없음: {missing} · 생성기에 없음: {extra})"
        )
    return required


def main() -> int:
    settings = Settings.from_env({})
    rulebook, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    config = load_config()
    generated = generate(config)
    indexes: dict[int, GraphIndex] = {}
    scores: list[CaseScore] = []
    breakdowns: dict[str, dict[str, Counter[str]]] = {
        "엔터티 종류별": defaultdict(Counter),
        "영향 종류별": defaultdict(Counter),
        "규칙 ID별": defaultdict(Counter),
    }
    flags: list[dict[str, bool]] = []
    evidence: list[tuple[str, EvidenceCheck]] = []
    lines: list[tuple[str, LineEvidence]] = []
    contracts: Counter[str] = Counter()
    sheets: dict[str, list[list[Cell]]] = {
        "E1 사례별": [["사례 ID", "입력 문장/연산", "기대 영향 수", "엔진 영향 수", "tp", "fn", "fp", "일치"]],
        "E1 영향 상세": [["사례 ID", "엔터티", "영향 종류", "규칙 ID", "기대", "엔진"]],
        "2단계 사례별": [
            ["사례 ID", "비용 줄 집합", "대표 금액", "최소 금액", "최대 금액", "구역 출구 지연", "인도 지연", "판정"]
        ],
    }
    required: dict[int, list[str]] = {}
    for stage in (1, 2):
        cases = _load_cases(STAGES[stage], False)
        built = {
            item.case_id: item for item in STAGES[stage].build(generated.snapshot, generated.seed, config.scenario_date)
        }
        required[stage] = _required_ids(stage, cases, built)
        for case in cases:
            if (
                GateCaseInput.model_validate(case.model_dump(include=set(GateCaseInput.model_fields)))
                != built[case.case_id]
            ):
                raise ValueError(f"{case.case_id}: 저장 입력과 생성 입력이 달라요")
            seed = case.snapshot.generator_seed
            if seed not in indexes:
                indexes[seed] = GraphIndex(generate(load_config(), seed).snapshot)
            index = indexes[seed]
            request = AnalysisRequest.model_validate(case.request)
            result: ImpactReport | AnalysisResult = (
                impact_report(index, request, rulebook, params.version)
                if stage == 1
                else analyze(index, request, rulebook, params)
            )
            if result.versions.snapshot_id != case.snapshot.snapshot_id or result.request != request:
                raise ValueError(f"{case.case_id}: 결과의 지도/요청이 사례와 달라요")
            contracts["all"] += 1
            result.__class__.model_validate(result.model_dump())
            contracts["pass"] += 1
            view = ChangeView(index, request.change)
            evidence.extend((case.case_id, check_impact(index, request, impact, view)) for impact in result.impacts)
            if stage == 1:
                assert isinstance(result, ImpactReport)
                score = score_case(case, result, index)
                scores.append(score)
                expected = cast(frozenset[Key], score.impacts.expected)
                produced = cast(frozenset[Key], score.impacts.produced)
                matched = expected & produced
                sentence = request.change.raw_text or "; ".join(
                    str(op.model_dump(exclude_none=True)) for op in request.change.ops
                )
                sheets["E1 사례별"].append(
                    [
                        case.case_id,
                        sentence,
                        len(expected),
                        len(produced),
                        len(matched),
                        len(expected - produced),
                        len(produced - expected),
                        expected == produced,
                    ]
                )
                for entity, effect, rule in sorted(expected | produced):
                    sheets["E1 영향 상세"].append(
                        [
                            case.case_id,
                            entity,
                            effect,
                            rule,
                            (entity, effect, rule) in expected,
                            (entity, effect, rule) in produced,
                        ]
                    )
                for key in expected | produced:
                    entity, effect, rule = key
                    status = "tp" if key in matched else "fn" if key in expected else "fp"
                    entity_type = (
                        EntityType.PART.value if entity in view.new_parts else (index.type_of(entity) or "unknown")
                    )
                    for title, name in (
                        ("엔터티 종류별", str(entity_type)),
                        ("영향 종류별", effect),
                        ("규칙 ID별", rule),
                    ):
                        breakdowns[title][name][status] += 1
            else:
                assert isinstance(result, AnalysisResult)
                row = _cost_flags(case, result)
                flags.append(row)
                sheets["2단계 사례별"].append([case.case_id, *(row[name] for name in row)])
                lines.extend(
                    (case.case_id, check_cost_line(line, result.impacts, index, request, view))
                    for line in result.cost_lines
                )
    workbook = _write_workbook(sheets)
    SUMMARY.write_text(
        _report(scores, breakdowns, flags, evidence, lines, contracts, workbook, required[1]),
        encoding="utf-8",
        newline="\n",
    )
    print(f"E1 {len(scores)}건, 2단계 {len(flags)}건, 영향 {len(evidence)}건, 비용 줄 {len(lines)}건")
    print(
        f"계약 {contracts['pass']}/{contracts['all']}, "
        f"근거 {sum(check.complete for _, check in evidence)}/{len(evidence)}, "
        f"비용 대응 {sum(line.matched for _, line in lines)}/{len(lines)}"
    )
    print(SUMMARY)
    print(workbook)
    for case_id, check in evidence:
        if not check.complete:
            failed = [
                name
                for name, ok in (("출발", check.origin_ok), ("연결", check.links_ok), ("종착·규칙", check.terminal_ok))
                if not ok
            ]
            print(
                f"근거 실패 {case_id} {check.impact.entity_id}/{check.impact.impact_type.value}/"
                f"{check.impact.rule_id}: {failed}; 경로 {check.impact.path}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
