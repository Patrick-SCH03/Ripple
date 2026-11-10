"""관문 손 계산의 독립성 점검: 계산자에게 주는 글(명세·규칙·파라미터·할 일)에 사례의 답이나 대상이 새는지 찾는다.

찾는 것: 사례 번호(G1-001 등)와 ECN 번호, 대상 부재 ID(호선 접두어 있는 것·없는 것), 엔진이 낸 대안 금액(10만원 이상,
'1,234,567'과 화면 표기 '123만원'). 다른 ID·숫자의 일부로 들어간 것(예: 'PL-0012' 안의 'PL-001')은 세지 않고,
한글이 바로 붙은 것('4,850,923원')은 센다.

사례 입력은 계산자에게 판정 방향이 가지 않게 제목·focus를 지운 사본(`blind`)을 주고, 그 사본에 규칙 ID가 없는지
(`hint_leaks`) 본다 — focus·제목 메모는 적용 규칙과 판정 방향을 알려 준다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from ripple.contracts.domain import GraphSnapshot
from ripple.contracts.evaluation import GateCaseInput
from ripple.contracts.result import AnalysisResult
from ripple.explain.format import money

MIN_AMOUNT_KRW = 100_000  # 이보다 작은 금액은 우연히 겹치기 쉬워 찾지 않는다
RULE_ID = re.compile(r"(?<![0-9A-Za-z])R-[A-Z]\d{2}(?!\d)")


def needles(inputs: Iterable[GateCaseInput], results: Mapping[str, AnalysisResult] | None = None) -> dict[str, str]:
    """찾을 글 → 무엇인지. results는 사례 ID → 엔진 결과(3단계 금액을 찾을 때)."""
    found: dict[str, str] = {}
    for case in inputs:
        found[case.case_id] = f"{case.case_id} 사례 번호"
        found[case.request.change.ecn_id] = f"{case.case_id} ECN 번호"
        for op in case.request.change.ops:
            ids = [*getattr(op, "part_ids", ()), getattr(op, "attach_to_part_id", None)]
            for part_id in filter(None, ids):
                found[part_id] = found[part_id.split(":")[-1]] = f"{case.case_id} 대상 부재"
        result = (results or {}).get(case.case_id)
        if result is not None:
            for value in amounts(result):
                found[f"{value:,}"] = found[money(value)] = f"{case.case_id} 엔진 금액"
    return found


def amounts(result: AnalysisResult) -> set[int]:
    """대안 비교의 금액(대안 총액·최적 총액·구간 시작일 총액·권고 총액) 중 10만원 이상."""
    values = {a.total.value for a in result.alternatives}
    values |= {a.best_total.value for a in result.alternatives if a.best_total is not None}
    values |= {s.total.value for s in result.cheapest_by_date}
    if result.recommendation is not None:
        values.add(result.recommendation.total.value)
    return {v for v in values if abs(v) >= MIN_AMOUNT_KRW}


def map_ids(snapshot: GraphSnapshot) -> dict[str, str]:
    """지도의 실제 ID(블록·부재·발주·발주 품목·구역·도면·재고 로트) → 무엇인지. 계산자에게 주는 명세·할 일의 예시는
    자리 표시만 쓴다 — 실제 ID가 정답 엔터티와 겹치면 예시가 답을 알려 준다."""
    groups: dict[str, Iterable[str]] = {
        "블록": (b.block_id for b in snapshot.blocks),
        "부재": (p.part_id for p in snapshot.parts),
        "발주": (po.po_id for po in snapshot.purchase_orders),
        "발주 품목": (line.line_id for line in snapshot.po_lines),
        "구역": (z.zone_id for z in snapshot.zones),
        "도면": (d.drawing_id for d in snapshot.drawings),
        "재고 로트": (lot.lot_id for lot in snapshot.stock),
    }
    return {value: f"지도 {kind} ID" for kind, values in groups.items() for value in values}


def blind(case: GateCaseInput) -> GateCaseInput:
    """계산자에게 주는 사례 입력: 판정 방향이 드러날 수 있는 제목·focus를 지운 사본.

    계산에 쓰는 연산·기준일·확정일·보류는 그대로다. 저장소의 사례 입력(채점·검토용)은 바꾸지 않는다.
    """
    neutral = f"설계변경 {case.request.change.ecn_id}"
    change = case.request.change.model_copy(update={"title": neutral})
    request = case.request.model_copy(update={"change": change})
    return case.model_copy(update={"title": neutral, "focus": "", "request": request})


def hint_leaks(texts: Mapping[str, str]) -> list[str]:
    """글 이름 → 내용에 규칙 ID(R-T01 등)가 나온 곳 — 사례 입력으로 적용 규칙이 미리 가는지."""
    return [f"{name}: 규칙 ID({m.group(0)})" for name, text in texts.items() for m in RULE_ID.finditer(text)]


def find_leaks(texts: Mapping[str, str], wanted: Mapping[str, str]) -> list[str]:
    """글 이름 → 내용에서 찾을 글이 나온 곳('docs/x.md: G3-001 대상 부재(…)')."""
    found = []
    for name, text in texts.items():
        for needle, what in wanted.items():
            if re.search(rf"(?<![0-9A-Za-z_,.\-]){re.escape(needle)}(?![0-9A-Za-z_,\-])", text):
                found.append(f"{name}: {what}({needle})")
    return found
