"""계약의 성질: 받아야 할 것은 받고, 모순은 거부한다."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fixtures import (
    AS_OF,
    THICKNESS_OP,
    VERSIONS,
    analysis_request,
    analysis_result,
    change_body,
    change_request,
    request_body,
    result_body,
)
from fixtures import timing as make_timing
from harness import Checker
from pydantic import TypeAdapter

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.change import CHANGE_OP_TYPES, OP_NAMES, ChangeOp
from ripple.contracts.domain import (
    BLOCK_STAGE_ORDER,
    PO_STATUS_ORDER,
    STAGE_OF_ACTIVITY,
    Activity,
    ActivityKind,
    BlockStage,
    ConnectionKind,
    POStatus,
    PurchaseOrder,
    Relation,
)
from ripple.contracts.explain import (
    METRICS,
    Explanation,
    MetricBlock,
    RenderedBlock,
    TemplateBlock,
    TextBlock,
    TextPart,
    quantity_expressions,
)
from ripple.contracts.graphview import GraphEdge, GraphNode, GraphView
from ripple.contracts.identity import analysis_id
from ripple.contracts.result import (
    AlternativeResult,
    Amount,
    AnalysisResult,
    DeadlineKind,
    DeliveryImpact,
    Hop,
    Impact,
    ImpactReport,
    Recommendation,
    ScheduleImpact,
    ScheduleRisk,
    TimingResult,
    Unresolved,
    UnresolvedKind,
    ZoneExitDelay,
    additional_loss_of,
)

OP_ADAPTER: TypeAdapter[Any] = TypeAdapter(ChangeOp)

MINIMAL_OPS: dict[str, dict[str, Any]] = {
    "thickness": {"part_ids": ["p1"], "from_mm": 12, "to_mm": 14},
    "grade": {"part_ids": ["p1"], "from_grade": "AH32", "to_grade": "AH36"},
    "dimension": {"part_ids": ["p1"], "field": "length_mm", "from_value": 1000, "to_value": 1200},
    "add_part": {"block_id": "b1", "kind": "stiffener", "spec_id": "s1", "qty": 1},
    "remove_part": {"part_ids": ["p1"]},
    "reroute_pipe": {"removed_part_ids": ["p1"], "added_spool_spec_ids": ["s1"]},
    "equipment_spec": {"part_ids": ["v1"], "from_spec_id": "s1", "to_spec_id": "s2"},
    "add_penetration": {"plate_part_id": "p1", "pipe_part_id": "p2", "diameter_mm": 150},
}

PO_BASE: dict[str, Any] = {
    "po_id": "PO-1",
    "ship_id": "S-001",
    "supplier_id": "SUP-1",
    "planned_order_date": "2026-09-01",
    "material_secured_days": 10,
    "fabrication_start_days": 20,
    "lead_time_days": 60,
}


def _op_rejected(body: dict[str, Any]) -> bool:
    return Checker.raises(lambda: OP_ADAPTER.validate_python(body))


def run(c: Checker) -> None:
    _change_ops(c)
    _requests(c)
    _vocabulary(c)
    _purchase_orders(c)
    _activities(c)
    _amounts_and_timing(c)
    _alternatives(c)
    _results(c)
    _schedule_risk(c)
    _impact_reports(c)
    _explanations(c)


def _change_ops(c: Checker) -> None:
    c.section("계약: 변경 연산")
    c.check("변경 연산은 8종", len(OP_NAMES) == 8 == len(CHANGE_OP_TYPES), sorted(OP_NAMES))
    c.check("최소 입력 예시가 연산 8종을 모두 덮음", set(MINIMAL_OPS) == OP_NAMES)
    for name, body in MINIMAL_OPS.items():
        parsed = OP_ADAPTER.validate_python({"op": name, **body})
        c.check(f"'{name}': 최소 입력이 같은 연산으로 읽힘", parsed.op == name)
        c.check(
            f"'{name}': 정의 안 된 필드는 거부",
            _op_rejected({"op": name, **body, "x": 1}),
        )
    c.check(
        "없는 연산 이름은 거부", c.raises(lambda: OP_ADAPTER.validate_python({"op": "teleport", "part_ids": ["p1"]}))
    )
    c.check("대상 부재가 비면 거부", c.raises(lambda: OP_ADAPTER.validate_python({**THICKNESS_OP, "part_ids": []})))
    c.check("두께는 0보다 커야 함", c.raises(lambda: OP_ADAPTER.validate_python({**THICKNESS_OP, "from_mm": 0})))
    same: dict[str, dict[str, Any]] = {
        "thickness": {"from_mm": 12, "to_mm": 12},
        "grade": {"from_grade": "AH36", "to_grade": "AH36"},
        "dimension": {"from_value": 1000, "to_value": 1000},
        "equipment_spec": {"from_spec_id": "s1", "to_spec_id": "s1"},
    }
    for name, values in same.items():
        body = {"op": name, **MINIMAL_OPS[name], **values}
        c.check(f"'{name}': 변경 전후가 같으면 거부", _op_rejected(body))
    c.check(
        "배관 경로 변경은 빼거나 더하는 스풀이 있어야 함",
        c.raises(lambda: OP_ADAPTER.validate_python({"op": "reroute_pipe", "crosses_part_ids": ["p9"]})),
    )


def _requests(c: Checker) -> None:
    c.section("계약: 변경·분석 요청")
    request = change_request()
    c.check("ECN은 연산이 한 개 이상", c.raises(lambda: change_request(ops=[])))
    c.check("ECN은 호선이 한 개 이상", c.raises(lambda: change_request(ship_ids=[])))
    c.check("같은 호선이 두 번이면 거부", c.raises(lambda: change_request(ship_ids=["S-001", "S-001"])))
    c.check("계약 모델은 만든 뒤 바뀌지 않음", c.raises(lambda: setattr(request, "title", "x"), Exception))
    c.check("탐색 기간 0일은 거부", c.raises(lambda: analysis_request(horizon_days=0)))
    c.check("탐색 기간 366일은 거부", c.raises(lambda: analysis_request(horizon_days=366)))
    c.check("확정일이 기준일보다 앞서면 거부", c.raises(lambda: analysis_request(confirm_on="2026-10-19")))
    holds = [{"po_id": "PO-1", "hold_days": 5}, {"po_id": "PO-1", "hold_days": 9}]
    c.check("같은 발주에 보류 두 번은 거부", c.raises(lambda: analysis_request(holds=holds)))
    c.check("확정일이 없으면 기준일로 봄", analysis_request().effective_confirm_on == AS_OF)


def _vocabulary(c: Checker) -> None:
    c.section("계약: 상태 어휘")
    c.check(
        "발주 단계는 미발주에서 시작해 가공으로 끝남",
        PO_STATUS_ORDER[0] is POStatus.NOT_ORDERED and PO_STATUS_ORDER[-1] is POStatus.PROCESSED,
    )
    c.check(
        "발주 단계에 자재 확보가 발주와 제작 사이에 있음",
        PO_STATUS_ORDER[1:4] == (POStatus.ORDERED, POStatus.MATERIAL_SECURED, POStatus.IN_FABRICATION),
    )
    c.check(
        "블록 단계는 미착수에서 시작해 탑재로 끝남",
        BLOCK_STAGE_ORDER[0] is BlockStage.NOT_STARTED and BLOCK_STAGE_ORDER[-1] is BlockStage.ERECTED,
    )
    block_kinds = [k for k in ActivityKind if k is not ActivityKind.MILESTONE]
    c.check("이정표를 뺀 공정마다 블록 단계가 정해짐", set(STAGE_OF_ACTIVITY) == set(block_kinds))
    stages = [BLOCK_STAGE_ORDER.index(STAGE_OF_ACTIVITY[k]) for k in block_kinds]
    c.check("공정 순서대로 블록 단계도 앞으로만 감", stages == sorted(stages) and len(set(stages)) == len(stages))
    c.check("부재 연결 종류는 모두 관계 종류에 있음", {k.value for k in ConnectionKind} <= {r.value for r in Relation})


def _purchase_orders(c: Checker) -> None:
    c.section("계약: 발주 단계 관측")

    def po(**override: Any) -> PurchaseOrder:
        return PurchaseOrder.model_validate({**PO_BASE, **override})

    good = po(
        entered_on={"ordered": "2026-09-01", "material_secured": "2026-09-12"},
        observations=[
            {"status": "ordered", "observed_on": "2026-09-05"},
            {"status": "material_secured", "observed_on": "2026-09-15"},
            {"status": "material_secured", "observed_on": "2026-09-20"},
        ],
    )
    c.check("확인 날짜·관측이 서로 맞으면 받음", good.po_id == "PO-1")
    c.check("자재 확보 ≤ 제작 착수 ≤ 리드타임이 아니면 거부", c.raises(lambda: po(material_secured_days=30)))
    c.check("미발주 진입일은 거부", c.raises(lambda: po(entered_on={"not_ordered": "2026-09-01"})))
    c.check(
        "확인 진입일이 단계 순서를 거스르면 거부",
        c.raises(lambda: po(entered_on={"ordered": "2026-09-10", "material_secured": "2026-09-01"})),
    )
    backwards = [
        {"status": "in_fabrication", "observed_on": "2026-09-10"},
        {"status": "ordered", "observed_on": "2026-09-20"},
    ]
    c.check("관측 상태가 시간이 지나 되돌아가면 거부", c.raises(lambda: po(observations=backwards)))
    c.check(
        "이미 그 단계라고 관측됐는데 진입일이 관측 뒤면 거부",
        c.raises(
            lambda: po(
                entered_on={"ordered": "2026-09-01", "material_secured": "2026-09-18"},
                observations=[{"status": "material_secured", "observed_on": "2026-09-15"}],
            )
        ),
    )
    c.check(
        "아직 그 단계 전이라고 관측됐는데 진입일이 관측 전이면 거부",
        c.raises(
            lambda: po(
                entered_on={"ordered": "2026-09-01", "material_secured": "2026-09-10"},
                observations=[{"status": "ordered", "observed_on": "2026-09-15"}],
            )
        ),
    )
    same_day = [
        {"status": "ordered", "observed_on": "2026-09-15"},
        {"status": "received", "observed_on": "2026-09-15"},
    ]
    c.check("같은 날 서로 다른 상태 관측은 거부", c.raises(lambda: po(observations=same_day)))
    repeated = [{"status": "ordered", "observed_on": "2026-09-15"}] * 2
    c.check("같은 날 같은 상태를 두 번 관측한 것은 받음", len(po(observations=repeated).observations) == 2)


def _activities(c: Checker) -> None:
    c.section("계약: 공정")
    base: dict[str, Any] = {
        "activity_id": "S-001:T31C:assembly",
        "ship_id": "S-001",
        "block_id": "S-001:T31C",
        "kind": "assembly",
        "duration_days": 20,
        "planned_start": "2026-10-01",
    }
    c.check("블록 공정은 받음", Activity.model_validate(base).duration_days == 20)
    c.check("블록 공정에 블록이 없으면 거부", c.raises(lambda: Activity.model_validate({**base, "block_id": None})))
    milestone = {**base, "activity_id": "S-001:ZCT:exit", "kind": "milestone", "block_id": None, "duration_days": 0}
    c.check("이정표는 블록 없이 기간 0으로 받음", Activity.model_validate(milestone).block_id is None)
    c.check("이정표에 기간이 있으면 거부", c.raises(lambda: Activity.model_validate({**milestone, "duration_days": 3})))
    c.check(
        "실제 완료일이 실제 착수일보다 앞서면 거부",
        c.raises(
            lambda: Activity.model_validate({**base, "actual_start": "2026-10-05", "actual_finish": "2026-10-04"})
        ),
    )


def _amounts_and_timing(c: Checker) -> None:
    c.section("계약: 금액·추가손실 곡선")
    c.check("금액은 최소 ≤ 대표값 ≤ 최대", c.raises(lambda: Amount(value=10, low=11, high=20)))
    c.check(
        "금액 합은 대표값·최소·최대를 각각 더함",
        Amount.total([Amount(value=2, low=1, high=3)] * 3) == Amount(value=6, low=3, high=9),
    )
    c.check(
        "기간 끝까지 추가손실 0이면 '기간 안 추가손실 없음'",
        make_timing([0, 0, 0]).deadline.kind is DeadlineKind.NONE_IN_HORIZON,
    )
    now = make_timing([0, 10, 10]).deadline
    c.check(
        "다음 날 바로 추가손실이 생기면 '기준일에 확정'", now.kind is DeadlineKind.CONFIRM_NOW and now.last_day == AS_OF
    )
    by = make_timing([0, 0, 0, 7, 9]).deadline
    c.check(
        "추가손실이 처음 생기기 전날이 마감일",
        by.kind is DeadlineKind.BY_DATE and by.last_day == AS_OF + timedelta(days=2),
    )
    later = make_timing([0, 0, 5, 0, 0]).deadline
    c.check("한 번 생긴 추가손실 뒤의 0은 마감일을 늘리지 않음", later.last_day == AS_OF + timedelta(days=1))
    good = make_timing([0, 0, 50])
    wrong_deadline = {**good.model_dump(), "deadline": {"kind": "none_in_horizon", "last_day": "2026-10-22"}}
    c.check("곡선과 맞지 않는 마감일은 거부", c.raises(lambda: TimingResult.model_validate(wrong_deadline)))
    gap = good.model_dump()
    gap["curve"][2]["confirm_on"] = date(2026, 10, 25)
    c.check("곡선 날짜가 하루씩이 아니면 거부", c.raises(lambda: TimingResult.model_validate(gap)))
    nonzero = good.model_dump()
    nonzero["curve"][0]["additional_loss"] = {"value": 1, "low": 1, "high": 1}
    c.check("기준일의 추가손실이 0이 아니면 거부", c.raises(lambda: TimingResult.model_validate(nonzero)))
    hidden = good.model_dump()
    hidden["curve"][2]["total"] = {"value": 9_000_000, "low": 9_000_000, "high": 9_000_000}
    hidden["curve"][2]["additional_loss"] = {"value": 0, "low": 0, "high": 0}
    hidden["deadline"] = {"kind": "none_in_horizon", "last_day": "2026-10-22"}
    c.check("총비용이 올랐는데 추가손실 0으로 낸 곡선은 거부", c.raises(lambda: TimingResult.model_validate(hidden)))
    spread = additional_loss_of(Amount(value=150, low=60, high=320), Amount(value=100, low=50, high=300))
    c.check("추가손실 범위는 시나리오별 차이의 최소~최대", spread == Amount(value=50, low=10, high=50), spread)
    cheaper = make_timing([0, -5, -5]).deadline
    c.check("뒤로 갈수록 싸지면(추가손실 ≤ 0) 기간 안 추가손실 없음", cheaper.kind is DeadlineKind.NONE_IN_HORIZON)


def _alternatives(c: Checker) -> None:
    c.section("계약: 대안 적격 판정")
    base: dict[str, Any] = {
        "alt_id": "A1",
        "label": "보강재 추가",
        "origin": "template",
        "ops": [MINIMAL_OPS["add_part"] | {"op": "add_part"}],
        "eligibility": {"status": "meets", "criterion": "보강재 단면계수 비율 ≥ 1"},
        "total": {"value": 10, "low": 5, "high": 20},
        "max_exit_delay_days": 0,
        "impacted_count": 3,
        "rank": 1,
        "best_confirm_on": "2026-10-20",
        "best_total": {"value": 10, "low": 5, "high": 20},
    }
    c.check("충족 대안은 순위를 받음", AlternativeResult.model_validate(base).rank == 1)
    no_best = {**base, "best_total": None}
    c.check("충족 대안에 최적 총액이 없으면 거부", c.raises(lambda: AlternativeResult.model_validate(no_best)))
    held = {
        **base,
        "eligibility": {"status": "short", "criterion": "x"},
        "rank": None,
        "best_confirm_on": None,
        "best_total": None,
        "best_holds": [{"po_id": "PO-0001", "hold_days": 3}],
    }
    c.check("충족이 아닌 대안에 최적 보류가 있으면 거부", c.raises(lambda: AlternativeResult.model_validate(held)))
    short = {**base, "eligibility": {"status": "short", "criterion": "x"}}
    c.check("부족 대안은 순위를 받지 않음", c.raises(lambda: AlternativeResult.model_validate(short)))
    reduced = {**base, "scope_reduced": True}
    c.check("적용 범위를 줄인 대안이 충족이면 거부", c.raises(lambda: AlternativeResult.model_validate(reduced)))
    designer = {
        **base,
        "scope_reduced": True,
        "rank": None,
        "best_confirm_on": None,
        "best_total": None,
        "eligibility": {"status": "designer", "criterion": "x"},
    }
    c.check("적용 범위를 줄인 대안은 설계자 확인으로 받음", AlternativeResult.model_validate(designer).rank is None)
    request_alt = {**base, "origin": "request", "eligibility": {"status": "designer", "criterion": "x"}, "rank": None}
    c.check("요청안이 충족이 아니면 거부", c.raises(lambda: AlternativeResult.model_validate(request_alt)))
    _recommendation(c, base)


def _recommendation(c: Checker, alt: dict[str, Any]) -> None:
    """대안 목록·권고의 일관성(docs/engine.md(대안) 4·6절)."""
    request = analysis_request(include_alternatives=True)
    first = {**alt, "alt_id": "ALT-REQ", "origin": "request", "label": "요청안"}
    second = {**alt, "alt_id": "ALT-T1", "rank": 2, "best_total": {"value": 30, "low": 5, "high": 40}}
    rec = {"alt_id": "ALT-REQ", "confirm_on": "2026-10-20", "holds": [], "total": alt["best_total"]}
    total = {"value": 10, "low": 5, "high": 20}
    spans = [
        {"alt_id": "ALT-REQ", "start": "2026-10-20", "end": "2026-10-21", "total": total},
        {"alt_id": "ALT-T1", "start": "2026-10-22", "end": "2026-10-23", "total": total},
    ]

    def result(**override: Any) -> AnalysisResult:
        body = {
            "alternatives": [first, second],
            "recommendation": rec,
            "cheapest_by_date": spans,
            "request": request.model_dump(mode="json"),
        }
        body["analysis_id"] = analysis_id(VERSIONS, AnalysisRequest.model_validate(body["request"]))
        return analysis_result(**{**body, **override})

    c.check(
        "요청안이 첫 항목이고 권고 = 1위 최적 조합이면 받음",
        result().recommendation == Recommendation.model_validate(rec),
    )
    c.check(
        "권고 총액이 1위 대안의 최적 총액과 다르면 거부",
        c.raises(lambda: result(recommendation={**rec, "total": {"value": 11, "low": 5, "high": 20}})),
    )
    c.check(
        "권고 보류가 1위 대안의 최적 보류와 다르면 거부",
        c.raises(lambda: result(recommendation={**rec, "holds": [{"po_id": "PO-0001", "hold_days": 3}]})),
    )
    c.check("1위가 아닌 대안을 권고하면 거부", c.raises(lambda: result(recommendation={**rec, "alt_id": "ALT-T1"})))
    c.check("대안이 있는데 권고가 없으면 거부", c.raises(lambda: result(recommendation=None)))
    c.check("요청안이 첫 항목이 아니면 거부", c.raises(lambda: result(alternatives=[second, first])))
    c.check("대안이 있는데 날짜별 최저 비용 대안 구간이 없으면 거부", c.raises(lambda: result(cheapest_by_date=[])))
    gap = [spans[0], {**spans[1], "start": "2026-10-23"}]
    c.check("구간 사이에 빈 날이 있으면 거부", c.raises(lambda: result(cheapest_by_date=gap)))
    short = [spans[0], {**spans[1], "end": "2026-10-22"}]
    c.check("구간이 탐색 기간 끝까지 가지 않으면 거부", c.raises(lambda: result(cheapest_by_date=short)))
    same = [spans[0], {**spans[1], "alt_id": "ALT-REQ"}]
    c.check("이웃 구간이 같은 대안이면 거부(하나로 묶어야 함)", c.raises(lambda: result(cheapest_by_date=same)))
    plain = analysis_request()
    c.check(
        "대안을 켜지 않은 분석에 대안이 있으면 거부",
        c.raises(
            lambda: result(
                request=plain.model_dump(mode="json"),
                analysis_id=analysis_id(VERSIONS, plain),
            )
        ),
    )
    later = analysis_request(include_alternatives=True, confirm_on="2026-10-21")
    c.check(
        "최적 조합의 확정일이 요청의 확정일(확정 가능일)보다 앞서면 거부",
        c.raises(
            lambda: result(
                request=later.model_dump(mode="json"),
                analysis_id=analysis_id(VERSIONS, later),
            )
        ),
    )
    strength = analysis_request(include_alternatives=True, change=change_body(intent="strength"))
    unknown = analysis_request(include_alternatives=True, change=change_body(intent=None))
    off_strength = analysis_request(change=change_body(intent="strength"))
    off_unknown = analysis_request(change=change_body(intent=None))
    c.check(
        "대안 포함 분석은 의도가 다르면 분석 ID가 다르고, 대안을 끈 분석은 의도와 무관",
        analysis_id(VERSIONS, strength) != analysis_id(VERSIONS, unknown)
        and analysis_id(VERSIONS, off_strength) == analysis_id(VERSIONS, off_unknown),
    )


def _results(c: Checker) -> None:
    c.section("계약: 분석 결과")
    result = analysis_result()
    c.check("최소 결과는 받음", result.total.value == 1_000_000)
    c.check("분석 ID가 버전·요청과 다르면 거부", c.raises(lambda: analysis_result(analysis_id="A-0000000000000000")))
    c.check(
        "총액이 비용 줄 합과 다르면 거부",
        c.raises(lambda: analysis_result(total={"value": 1, "low": 1, "high": 1})),
    )
    c.check("인도 지연을 못 냈는데 이유가 없으면 거부", c.raises(lambda: analysis_result(unresolved=[])))
    short_curve = make_timing([0, 0]).model_dump(mode="json")
    c.check("곡선 길이가 탐색 기간과 다르면 거부", c.raises(lambda: analysis_result(timing=short_curve)))
    body = result_body()
    rec = {"alt_id": "A9", "confirm_on": "2026-10-20", "total": body["total"]}
    c.check("없는 대안을 추천하면 거부", c.raises(lambda: analysis_result(recommendation=rec)))
    c.check("결과의 요청은 원래 요청과 같음", result.request == analysis_request())
    c.check(
        "요청 본문으로 만든 결과도 같은 분석 ID",
        analysis_result(request=request_body()).analysis_id == result.analysis_id,
    )
    c.check("늘어난 인도 지연 = 변경 뒤 − 변경 전", DeliveryImpact.of(2, 9).added_delay_days == 7)
    c.check(
        "늘어난 인도 지연이 변경 전·후 차이와 다르면 거부",
        c.raises(lambda: DeliveryImpact(forecast_delay_before_days=2, forecast_delay_after_days=9, added_delay_days=9)),
    )
    exit_delay = ZoneExitDelay(
        zone_id="S-001:ZCT",
        exit_activity_id="S-001:ZCT:exit",
        base_date=date(2027, 1, 16),
        new_date=date(2027, 1, 19),
        delay_days=3,
    )
    c.check(
        "구역 출구 최대 지연은 출구 지연의 최댓값(없으면 0)",
        ScheduleImpact(zone_exits=(exit_delay,), max_exit_delay_days=3).max_exit_delay_days == 3
        and ScheduleImpact().max_exit_delay_days == 0,
    )
    c.check(
        "구역 출구 최대 지연이 출구 지연과 다르면 거부",
        c.raises(lambda: ScheduleImpact(zone_exits=(exit_delay,), max_exit_delay_days=0)),
    )


def _exit(exit_id: str, days: int, zone: str | None = None) -> ZoneExitDelay:
    base = date(2027, 1, 16)
    return ZoneExitDelay(
        zone_id=zone or exit_id.removesuffix(":exit"),
        exit_activity_id=exit_id,
        base_date=base,
        new_date=base + timedelta(days=days),
        delay_days=days,
    )


def _schedule(rep: tuple[ZoneExitDelay, ...], risk: tuple[ZoneExitDelay, ...], **risk_kw: Any) -> ScheduleImpact:
    """대표 출구 rep와 위험 출구 risk로 일정 영향을 만든다(최대 지연은 목록에서)."""
    worst = max((z.delay_days for z in risk), default=0)
    return ScheduleImpact(
        zone_exits=rep,
        max_exit_delay_days=max((z.delay_days for z in rep), default=0),
        risk=ScheduleRisk(zone_exits=risk, max_exit_delay_days=worst, **risk_kw),
    )


def with_risk(rep_delivery: DeliveryImpact | None = None, **risk: Any) -> dict[str, Any]:
    """분석 결과 본문 덮어쓰기: 대표 일정은 출구 없음(인도는 rep_delivery), 위험은 risk로."""
    return {"schedule": ScheduleImpact(delivery=rep_delivery, risk=ScheduleRisk(**risk)).model_dump(mode="json")}


def _schedule_risk(c: Checker) -> None:
    c.section("계약: 일정 위험(대표 출구는 모두 위험에도 같은 ID로 · 지연 같거나 큼)")
    a, b = "S-001:ZCT:exit", "S-001:ZER:exit"
    ok = _schedule((_exit(a, 4),), (_exit(a, 6), _exit(b, 8)), ratios={"valve": 3.0})
    c.check(
        "대표 가 4일 · 위험 가 6일·나 8일(대표 0일·위험만 늦는 출구 포함)은 받고 JSON 왕복이 같음",
        ok.risk is not None
        and ok.risk.max_exit_delay_days == 8
        and ScheduleImpact.model_validate_json(ok.model_dump_json()) == ok,
    )
    c.check(
        "위험이 없는 이전 판 일정(risk 없음)도 받음",
        ScheduleImpact(zone_exits=(_exit(a, 4),), max_exit_delay_days=4).risk is None,
    )
    rejected = {
        "대표 출구 빠짐(다른 출구 지연이 더 커 최대값 검사는 통과하는 반례)": lambda: _schedule(
            (_exit(a, 4),), (_exit(b, 8),)
        ),
        "같은 출구 ID의 위험 지연이 대표보다 짧음": lambda: _schedule((_exit(a, 4),), (_exit(a, 3),)),
        "대표 출구를 다른 구역으로 대체": lambda: _schedule((_exit(a, 4),), (_exit(a, 4, zone="S-001:ZXX"),)),
        "위험 출구 중복": lambda: _schedule((), (_exit(a, 4), _exit(a, 5))),
        "위험 출구 순서가 ID 순이 아님": lambda: _schedule((), (_exit(b, 4), _exit(a, 5))),
        "위험 출구에 0일 지연": lambda: _schedule((), (_exit(a, 0),)),
        "배율이 1보다 작음": lambda: _schedule((), (), ratios={"plate": 0.9}),
        "위험 전용 이유가 인도 지연이 아님": lambda: _schedule(
            (), (), unresolved=(Unresolved(kind=UnresolvedKind.PO_STATE, reason="x"),)
        ),
        "위험 최대 지연이 목록과 다름": lambda: ScheduleImpact(
            risk=ScheduleRisk(zone_exits=(_exit(a, 4),), max_exit_delay_days=9)
        ),
        "위험 인도 지연이 대표보다 짧음(둘 다 계산됨)": lambda: ScheduleImpact(
            delivery=DeliveryImpact.of(0, 5), risk=ScheduleRisk(delivery=DeliveryImpact.of(0, 4))
        ),
    }
    passed = [name for name, build in rejected.items() if not c.raises(build)]
    c.check(f"모순 {len(rejected)}가지 거부(빠짐·짧음·대체·중복·순서·0일·배율·이유·최대·인도)", not passed, passed)
    reason = Unresolved(kind=UnresolvedKind.DELIVERY, reason="경계 조건 없음")
    risk_only = Unresolved(kind=UnresolvedKind.DELIVERY, entity_id="S-001", reason="위험에서만 경계 없는 구역이 늦어짐")
    c.check(
        "분석 결과: 위험 인도 계산 불가는 이유(대표 또는 위험 전용)가 있으면 받고, 위험 전용 이유만 있어도 받음",
        analysis_result(**with_risk()).schedule.risk is not None
        and analysis_result(**with_risk(unresolved=(risk_only,))).schedule.risk is not None,
    )
    c.check(
        "분석 결과: 위험 전용 이유가 대표 이유와 겹치거나, 인도 계산 불가 이유가 아무 데도 없으면 거부",
        c.raises(lambda: analysis_result(**with_risk(unresolved=(reason,))))
        and c.raises(lambda: analysis_result(unresolved=[], **with_risk(DeliveryImpact.of(0, 0))))
        and not c.raises(
            lambda: analysis_result(
                unresolved=[], **with_risk(DeliveryImpact.of(0, 0), delivery=DeliveryImpact.of(0, 0))
            )
        ),
    )


def _impact_reports(c: Checker) -> None:
    c.section("계약: 영향 보고")
    hop = Hop(src="p1", dst="PO-1#1", relation=Relation.SUPPLIED_BY, rule_id="R-T01")

    def impact(**override: Any) -> Impact:
        body: dict[str, Any] = {
            "entity_type": "po_line",
            "entity_id": "PO-1#1",
            "ship_id": "S-001",
            "impact_type": "po_change",
            "severity": "high",
            "rule_id": "R-T01",
            "path": [hop],
        }
        return Impact.model_validate(body | override)

    c.check("근거 경로가 영향 엔터티에서 끝나지 않으면 거부", c.raises(lambda: impact(entity_id="PO-2#1")))
    c.check("근거 경로의 마지막 규칙이 영향 규칙과 다르면 거부", c.raises(lambda: impact(rule_id="R-M02")))
    gap = Hop(src="x", dst="PO-1#1", relation=Relation.SAME_SPEC, rule_id="R-T01")
    c.check("근거 경로가 중간에 끊기면 거부", c.raises(lambda: impact(path=[hop, gap])))
    request = analysis_request()
    ends = (GraphNode(id="PO-1#1", type="po_line", label="PO-1 #1"), GraphNode(id="p1", type="part", label="판"))
    drawn = GraphView(
        snapshot_id=VERSIONS.snapshot_id,
        nodes=ends,
        edges=(GraphEdge(source="p1", target="PO-1#1", relation="supplied_by"),),
    )

    def report(**override: Any) -> ImpactReport:
        body: dict[str, Any] = {
            "analysis_id": analysis_id(VERSIONS, request),
            "versions": VERSIONS,
            "request": request,
            "data_mode": "synthetic",
            "impacts": [impact(), impact(impact_type="reorder")],
            "graph": drawn,
        }
        return ImpactReport.model_validate(body | override)

    c.check("키 순으로 정렬된 영향 보고는 받음", len(report().impacts) == 2)
    c.check("분석 ID가 버전·요청과 다르면 거부", c.raises(lambda: report(analysis_id="A-0000000000000000")))
    c.check("영향이 키 순이 아니면 거부", c.raises(lambda: report(impacts=[impact(impact_type="reorder"), impact()])))
    c.check("같은 키의 영향이 둘이면 거부", c.raises(lambda: report(impacts=[impact(), impact()])))
    other_map = drawn.model_copy(update={"snapshot_id": "G-1111111111111111"})
    c.check("영향 그래프의 지도가 분석 지도와 다르면 거부", c.raises(lambda: report(graph=other_map)))
    partial = GraphView(snapshot_id=VERSIONS.snapshot_id, nodes=ends[1:], edges=())
    c.check("근거 경로의 노드가 영향 그래프에 없으면 거부", c.raises(lambda: report(graph=partial)))


def _explanations(c: Checker) -> None:
    c.section("계약: 설명 블록")
    c.check("수치 키마다 라벨이 있음", all(spec.label for spec in METRICS.values()))
    c.check("없는 수치 키는 거부", c.raises(lambda: MetricBlock(metric="cost.cancel")))
    c.check("목록 수치에 엔터티가 없으면 거부", c.raises(lambda: MetricBlock(metric="hold.until")))
    c.check("단일 수치에 엔터티를 붙이면 거부", c.raises(lambda: MetricBlock(metric="cost.total", entity_id="PO-1")))
    c.check("글 블록에 숫자가 있으면 거부", c.raises(lambda: TextBlock(text="비용은 3억 원이에요")))
    c.check("글 블록에 전각 숫자가 있어도 거부", c.raises(lambda: TextBlock(text="지연 ３일")))
    c.check("글 블록에 금액 단어가 있으면 거부", c.raises(lambda: TextBlock(text="약 천만 원이 들어요")))
    ok = TextBlock(text="{{e:S-001:T31C-PL-0001}} 두께가 바뀌어 인접 판 가공이 필요해요")
    c.check("엔터티 참조 안의 숫자는 허용", ok.entity_ids() == ("S-001:T31C-PL-0001",))
    c.check("엔터티 참조 형식이 깨지면 거부", c.raises(lambda: TextBlock(text="{{S-001}} 확인이 필요해요")))
    blocks = [{"kind": "metric", "metric": "cost.total"}, {"kind": "template", "template_id": "verdict.approve"}]
    c.check(
        "수치·템플릿 블록을 섞은 설명은 받음",
        len(Explanation.model_validate({"blocks": blocks, "source": "llm"}).blocks) == 2,
    )
    free = [{"kind": "text", "text": "도면 수정이 먼저예요"}]
    c.check(
        "설명에 자유 글 블록은 못 넣음(LLM은 템플릿 ID만 고름)",
        c.raises(lambda: Explanation.model_validate({"blocks": free, "source": "llm"})),
    )
    c.check("템플릿 ID 형식이 깨지면 거부", c.raises(lambda: TemplateBlock(template_id="Verdict Approve")))
    c.check(
        "렌더링한 수치 블록에 수치 키가 없으면 거부",
        c.raises(lambda: RenderedBlock(kind="metric", text="총변경비용", template_id="verdict.approve")),
    )
    c.check("조각은 엔터티 이름이면서 값일 수 없음", c.raises(lambda: TextPart(text="7", entity_id="x", value=True)))
    block = {"kind": "text", "text": "T31C 블록에 재작업이 생겨요.", "template_id": "impact.rework"}
    chip = {"text": "T31C", "entity_id": "S-001:T31C"}
    rest = {"text": " 블록에 재작업이 생겨요."}
    c.check(
        "조각을 이은 글이 블록 글과 같고 엔터티가 블록 엔터티 안이면 받음",
        len(RenderedBlock.model_validate({**block, "entity_ids": ["S-001:T31C"], "parts": [chip, rest]}).parts) == 2,
    )
    c.check(
        "조각이 블록 글과 다르거나, 블록 엔터티 밖이거나, 글 블록에 값 조각이 있으면 거부",
        c.raises(lambda: RenderedBlock.model_validate({**block, "entity_ids": ["S-001:T31C"], "parts": [chip]}))
        and c.raises(lambda: RenderedBlock.model_validate({**block, "parts": [chip, rest]}))
        and c.raises(
            lambda: RenderedBlock.model_validate(
                {**block, "entity_ids": ["S-001:T31C"], "parts": [chip, {**rest, "value": True}]}
            )
        ),
    )
    quantities = (
        "약 천만 원이 들어요",
        "한 번 더 확인해요",
        "두 배로 늘어요",
        "이틀 늦어져요",
        "열흘 안에",
        "절반이 남아요",
        "삼십 일 안에",
        "십만 원",
        "첫째 블록",
        "이삼 일",
        "오차 범위 %",
        "한 달 미뤄요",
    )
    missed = [t for t in quantities if not quantity_expressions(t)]
    c.check("수량 검출기: 한글 수사·수량 표현을 모두 찾음", not missed, missed)
    plain = (
        "보류 조건을 확인해요",
        "일정이 밀려요",
        "이번 변경은 승인 가능해요",
        "구역 출구가 늦어져요",
        "두께가 바뀌어요",
        "세부 내용은 근거에 있어요",
        "제한 시간 안에",
        "도면 수정이 먼저예요",
        "발주를 늦추면 손실을 줄일 수 있어요",
        "이 변경으로 인도 일정이 늦어져요",
        "열람해 주세요",
        "만약 늦어지면",
    )
    flagged = [t for t in plain if quantity_expressions(t)]
    c.check("수량 검출기: 수량이 아닌 흔한 문장은 통과", not flagged, flagged)
    c.check("글 블록에 한글 수사가 있으면 거부", c.raises(lambda: TextBlock(text="이틀 늦어져요")))
