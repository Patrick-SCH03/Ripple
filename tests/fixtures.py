"""검사용 최소 계약 객체. 각 함수는 유효한 객체를 만들고, 검사는 한 군데씩 바꿔 본다."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ripple.contracts.analysis import AnalysisRequest, Versions
from ripple.contracts.base import CONTRACT_VERSION
from ripple.contracts.change import ChangeRequest
from ripple.contracts.domain import GraphSnapshot
from ripple.contracts.graphview import GraphView
from ripple.contracts.identity import analysis_id
from ripple.contracts.result import (
    Amount,
    AnalysisResult,
    CostLine,
    CurvePoint,
    ScheduleImpact,
    TimingResult,
    Unresolved,
    UnresolvedKind,
    expected_deadline,
)

AS_OF = date(2026, 10, 20)

THICKNESS_OP: dict[str, Any] = {"op": "thickness", "part_ids": ["S-001:T31C-PL-0001"], "from_mm": 12, "to_mm": 14}

VERSIONS = Versions(
    contract=CONTRACT_VERSION,
    snapshot_id="G-0000000000000000",
    rules="rules-v0",
    params="cost-v1",
    engine="0.1.0",
)


def change_body(**override: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "ecn_id": "E-1",
        "title": "T31C 판 두께 증가",
        "ship_ids": ["S-001"],
        "intent": "strength",
        "ops": [THICKNESS_OP],
    }
    return {**body, **override}


def change_request(**override: Any) -> ChangeRequest:
    return ChangeRequest.model_validate(change_body(**override))


def request_body(**override: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"change": change_body(), "as_of": AS_OF.isoformat(), "horizon_days": 3}
    return {**body, **override}


def analysis_request(**override: Any) -> AnalysisRequest:
    return AnalysisRequest.model_validate(request_body(**override))


def curve(losses: list[int], base: int = 1_000_000) -> tuple[CurvePoint, ...]:
    return tuple(
        CurvePoint(
            confirm_on=AS_OF + timedelta(days=i),
            total=Amount.exact(base + loss),
            additional_loss=Amount.exact(loss),
            max_exit_delay_days=0,
        )
        for i, loss in enumerate(losses)
    )


def timing(losses: list[int]) -> TimingResult:
    points = curve(losses)
    return TimingResult(base_cost=points[0].total, curve=points, deadline=expected_deadline(points))


def cost_line(line_id: str = "L1", value: int = 1_000_000) -> CostLine:
    return CostLine(
        line_id=line_id,
        rule_id="R-D01",
        entity_id="DWG-T31C-001",
        label="도면 수정",
        formula="16h × 42,000원",
        inputs={"hours": 16, "rate": 42000},
        amount=Amount(value=value, low=value // 2, high=value * 2),
    )


def result_body(**override: Any) -> dict[str, Any]:
    request = analysis_request()
    line = cost_line()
    body: dict[str, Any] = {
        "analysis_id": analysis_id(VERSIONS, request),
        "versions": VERSIONS.model_dump(mode="json"),
        "request": request.model_dump(mode="json"),
        "data_mode": "synthetic",
        "impacts": [],
        "cost_lines": [line.model_dump(mode="json")],
        "total": line.amount.model_dump(),
        "schedule": ScheduleImpact().model_dump(mode="json"),
        "timing": timing([0, 0, 50_000, 50_000]).model_dump(mode="json"),
        "unresolved": [Unresolved(kind=UnresolvedKind.DELIVERY, reason="경계 조건 없음").model_dump(mode="json")],
        "graph": GraphView(snapshot_id=VERSIONS.snapshot_id, nodes=(), edges=()).model_dump(mode="json"),
        "verdict": {"level": "review", "reasons": ["발주 변경이 있어 검토가 필요해요"]},
    }
    return {**body, **override}


def analysis_result(**override: Any) -> AnalysisResult:
    return AnalysisResult.model_validate(result_body(**override))


def snapshot_body(**override: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "snapshot_id": "G-placeholder",
        "origin": "generator",
        "data_mode": "synthetic",
        "ships": [
            {
                "ship_id": "S-001",
                "ship_type": "suezmax_crude_oil_tanker",
                "dwt": 158000,
                "contract_price_krw": 130_000_000_000,
                "delivery_date": "2027-12-15",
            }
        ],
        "zones": [{"zone_id": "S-001:ZCT", "ship_id": "S-001", "name": "화물탱크 구역"}],
        "blocks": [
            {
                "block_id": "S-001:T31C",
                "ship_id": "S-001",
                "zone_id": "S-001:ZCT",
                "name": "No.3 COT 횡격벽",
                "steel_weight_t": 180.0,
            }
        ],
        "specs": [
            {
                "spec_id": "PL-AH36-12.0",
                "category": "plate",
                "description": "AH36 12mm 후판",
                "grade": "AH36",
                "thickness_mm": 12.0,
                "unit": "t",
                "unit_price_krw": 900000,
            }
        ],
        "parts": [
            {
                "part_id": "S-001:T31C-PL-0001",
                "ship_id": "S-001",
                "block_id": "S-001:T31C",
                "kind": "plate",
                "name": "횡격벽 하단 판 1",
                "spec_id": "PL-AH36-12.0",
                "qty": 1.2,
                "drawing_no": "DWG-T31C-001",
                "revision": "A",
                "thickness_mm": 12.0,
                "grade": "AH36",
            }
        ],
        "connections": [],
        "suppliers": [],
        "purchase_orders": [],
        "po_lines": [],
        "stock": [],
        "activities": [],
        "drawings": [],
    }
    return {**body, **override}


def snapshot(**override: Any) -> GraphSnapshot:
    return GraphSnapshot.model_validate(snapshot_body(**override))
