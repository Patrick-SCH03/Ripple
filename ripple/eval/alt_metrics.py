"""3단계 관문 채점(docs/gate_cases.md): 대안 비교 기대값과 분석 결과를 항목마다 비교한다.

대안은 ID로 맞추고 빠진 대안·더한 대안은 불일치다. 대안마다 연산(정규형)·범위 축소·판정(상태, 비율 ±0.001)·
총액(대표값·최소·최대 각각 ±1%)·구역 출구 지연(±0일)·마감일·최적 조합(확정일·보류·총액)·순위를, 그리고 권고,
날짜별 최저 비용 대안 구간(대안·시작일·끝일·시작일 총액), 만들지 않은 대안과 그 이유를 비교한다.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from ripple.contracts.analysis import HoldAction
from ripple.contracts.change import ChangeOp
from ripple.contracts.evaluation import ExpectedAlternative, GateCase, OmissionReason
from ripple.contracts.result import AlternativeResult, AnalysisResult, ZeroLossDeadline

from .cost_metrics import CostCaseScore, Mismatch, amount_mismatches, require_same_case

RATIO_TOLERANCE = 0.001  # 판정 비율 ±0.001
EPS = 1e-9

# 대안 라벨의 앞부분 → 템플릿(요청 검증을 통과하지 못해 뺀 대안의 안내에서 대안을 찾는다)
LABEL_PREFIXES = (
    ("판 두께 대신 보강재 추가", "ALT-T1"),
    ("강종 상향", "ALT-T2"),
    ("강종 대신 두께 증가", "ALT-T3"),
    ("보강재 대신 판 두께 증가", "ALT-T4"),
    ("적용 범위 축소", "ALT-T5"),
)
# 템플릿을 만들지 않은 이유 안내(엔진 결과 notes) → (대안, 이유)
SKIPPED = (
    (re.compile(r"강종의 단가 없음 — 강종 대안 생략"), "ALT-T2", OmissionReason.NO_UPPER_GRADE),
    (re.compile(r"기준 보강재 없음 — 보강재 대안 생략"), "ALT-T1", OmissionReason.NO_REFERENCE_STIFFENER),
    (re.compile(r"(정보 없음|산정 불가) — 보강재 대안 생략"), "ALT-T1", OmissionReason.MISSING_DATA),
    (re.compile(r"정보 없음 — 범위 축소 대안 생략"), "ALT-T5", OmissionReason.MISSING_DATA),
)
INVALID = re.compile(r"^(?P<label>.+?): 지도와 맞지 않아 제외")


def op_key(op: ChangeOp) -> str:
    """연산 정규형: ID 목록은 정렬, 보강재 중량(qty)은 t 소수 셋째 자리(.5는 위로)."""
    data = op.model_dump(mode="json")
    for key, value in data.items():
        if isinstance(value, list):
            data[key] = sorted(value)
    if isinstance(data.get("qty"), float):
        data["qty"] = float(Decimal(repr(data["qty"])).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def omissions(notes: Iterable[str]) -> set[tuple[str, OmissionReason]]:
    """결과 안내에서 만들지 않은 템플릿과 이유를 찾는다."""
    found: set[tuple[str, OmissionReason]] = set()
    for note in notes:
        found |= {(alt, reason) for pattern, alt, reason in SKIPPED if pattern.search(note)}
        invalid = INVALID.match(note)
        if invalid:
            label = invalid["label"]
            found |= {
                (alt, OmissionReason.INVALID_ON_MAP) for prefix, alt in LABEL_PREFIXES if label.startswith(prefix)
            }
    return found


def _ratio_differs(want: float | None, got: float | None) -> bool:
    """판정 비율이 다른가: 한쪽만 비었거나, 유한하지 않거나(NaN·무한대는 늘 불일치), ±0.001 밖."""
    if want is None or got is None:
        return (want is None) != (got is None)
    if not (math.isfinite(want) and math.isfinite(got)):
        return True
    return abs(want - got) > RATIO_TOLERANCE + EPS


def _holds(holds: Iterable[HoldAction]) -> str:
    return str(sorted((h.po_id, h.hold_days) for h in holds))


def _deadline(deadline: ZeroLossDeadline | None) -> str:
    return "없음" if deadline is None else f"{deadline.kind.value} {deadline.last_day.isoformat()}"


def _alternative_mismatches(w: ExpectedAlternative, g: AlternativeResult, item: str) -> list[Mismatch]:
    out: list[Mismatch] = []
    want_ops, got_ops = sorted(op_key(op) for op in w.ops), sorted(op_key(op) for op in g.ops)
    if want_ops != got_ops:
        out.append(Mismatch(f"{item} 연산", str(want_ops), str(got_ops)))
    if w.scope_reduced != g.scope_reduced:
        out.append(Mismatch(f"{item} 범위 축소", str(w.scope_reduced), str(g.scope_reduced)))
    if w.eligibility.status is not g.eligibility.status:
        out.append(Mismatch(f"{item} 판정", w.eligibility.status.value, g.eligibility.status.value))
    want_ratio, got_ratio = w.eligibility.ratio_vs_request, g.eligibility.ratio_vs_request
    if _ratio_differs(want_ratio, got_ratio):
        out.append(Mismatch(f"{item} 판정 비율", str(want_ratio), str(got_ratio)))
    out += amount_mismatches(f"{item} 총액", w.total, g.total)
    if w.max_exit_delay_days != g.max_exit_delay_days:
        out.append(Mismatch(f"{item} 구역 출구 지연(일)", str(w.max_exit_delay_days), str(g.max_exit_delay_days)))
    if g.deadline != w.deadline:
        out.append(Mismatch(f"{item} 추가손실 0 마감일", _deadline(w.deadline), _deadline(g.deadline)))
    best = w.best
    if best is None or g.best_confirm_on is None or g.best_total is None:
        if (best is None) != (g.best_confirm_on is None):
            out.append(
                Mismatch(f"{item} 최적 조합", "없음" if best is None else "있음", "있음" if best is None else "없음")
            )
    else:
        if best.confirm_on != g.best_confirm_on:
            out.append(Mismatch(f"{item} 최적 확정일", best.confirm_on.isoformat(), g.best_confirm_on.isoformat()))
        if _holds(best.holds) != _holds(g.best_holds):
            out.append(Mismatch(f"{item} 최적 보류", _holds(best.holds), _holds(g.best_holds)))
        out += amount_mismatches(f"{item} 최적 총액", best.total, g.best_total)
    if w.rank != g.rank:
        out.append(Mismatch(f"{item} 순위", str(w.rank), str(g.rank)))
    return out


def score_alt_case(case: GateCase, result: AnalysisResult) -> CostCaseScore:
    """한 사례를 채점한다. 다른 지도·요청으로 계산한 결과는 채점하지 않는다(ValueError)."""
    require_same_case(case, result)
    expected = case.expected.alternatives
    if expected is None:
        raise ValueError(f"{case.case_id}: 3단계 기대값이 없어요")
    out: list[Mismatch] = []

    # 대안 목록과 대안마다의 칸
    got = {a.alt_id: a for a in result.alternatives}
    want = {a.alt_id: a for a in expected.alternatives}
    out += [Mismatch(f"대안 {alt_id}", "있음", "없음") for alt_id in sorted(want.keys() - got.keys())]
    out += [Mismatch(f"대안 {alt_id}", "없음", "있음") for alt_id in sorted(got.keys() - want.keys())]
    for alt_id in sorted(want.keys() & got.keys()):
        out += _alternative_mismatches(want[alt_id], got[alt_id], f"대안 {alt_id}")

    # 권고
    rec, got_rec = expected.recommendation, result.recommendation
    if got_rec is None:
        out.append(Mismatch("권고", rec.alt_id, "없음"))
    else:
        if (rec.alt_id, rec.confirm_on) != (got_rec.alt_id, got_rec.confirm_on):
            out.append(
                Mismatch(
                    "권고 대안·확정일",
                    f"{rec.alt_id} {rec.confirm_on.isoformat()}",
                    f"{got_rec.alt_id} {got_rec.confirm_on.isoformat()}",
                )
            )
        if _holds(rec.holds) != _holds(got_rec.holds):
            out.append(Mismatch("권고 보류", _holds(rec.holds), _holds(got_rec.holds)))
        out += amount_mismatches("권고 총액", rec.total, got_rec.total)

    # 날짜별 가장 싼 대안(요청의 보류만)
    want_spans = [(s.alt_id, s.start, s.end) for s in expected.cheapest_by_date]
    got_spans = [(s.alt_id, s.start, s.end) for s in result.cheapest_by_date]
    if want_spans != got_spans:
        out.append(Mismatch("날짜별 최저 비용 대안 구간", _spans(want_spans), _spans(got_spans)))
    else:
        for w_span, g_span in zip(expected.cheapest_by_date, result.cheapest_by_date, strict=True):
            out += amount_mismatches(
                f"구간 {w_span.alt_id} {w_span.start.isoformat()} 시작일 총액", w_span.total, g_span.total
            )

    # 만들지 않은 대안과 이유
    want_omitted = sorted((o.alt_id, o.reason.value) for o in expected.omitted)
    got_omitted = sorted((alt, reason.value) for alt, reason in omissions(result.notes))
    if want_omitted != got_omitted:
        out.append(Mismatch("만들지 않은 대안", str(want_omitted), str(got_omitted)))
    return CostCaseScore(case.case_id, tuple(out))


def _spans(spans: Sequence[tuple[str, date, date]]) -> str:
    return ", ".join(f"{alt} {start}~{end}" for alt, start, end in spans)
