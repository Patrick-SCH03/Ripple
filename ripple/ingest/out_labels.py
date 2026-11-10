"""엑셀 내보내기의 이름표(화면 web/src/lib/labels.ts·records.ts와 같은 말). 모르는 값은 코드 그대로 쓴다.

블록 단계·공정 이름은 두지 않는다 — 계산식·이유·사건 문장에 이미 현장 이름으로 들어 있다.
"""

from __future__ import annotations

from collections.abc import Mapping

from ripple.contracts.result import VERDICT_NAMES

VERDICT = VERDICT_NAMES
DEADLINE_KIND = {
    "by_date": "이날까지 확정하면 추가손실 0",
    "confirm_now": "기준일 확정 필요(다음 날부터 추가손실)",
    "none_in_horizon": "탐색 기간 끝까지 추가손실 없음",
}
CAUSE = {
    "owner_request": "선주 요청",
    "class_rule": "선급·규정",
    "design_error": "설계 오류·간섭",
    "production": "현장 오작·변형",
    "equipment": "기자재 사양",
}
DESIGN_STATUS = {
    "unknown": "미입력",
    "in_review": "설계 검토 중",
    "owner_pending": "선주 승인 대기",
    "approved": "승인",
}
DATA_MODE = {"synthetic": "합성 데이터", "real": "실제 데이터"}
IMPACT = {
    "modify_part": "부재 수정",
    "po_change": "발주 변경·취소",
    "reorder": "새 규격 발주",
    "po_hold": "발주 보류",
    "rework": "블록 재작업",
    "taper": "테이퍼 가공",
    "weld_recheck": "용접 재검토",
    "collar_resize": "칼라 치수 변경",
    "drawing_revision": "도면 개정",
    "schedule_delay": "예상 일정 지연",
    "delivery_delay": "예상 인도 지연",
    "reallocate_stock": "잉여 자재 전용",
    "needs_confirmation": "확인 필요",
}
ENTITY = {
    "ship": "선박",
    "zone": "구역",
    "block": "블록",
    "part": "부재",
    "po": "발주",
    "po_line": "발주 품목",
    "stock": "재고",
    "activity": "공정",
    "drawing": "도면",
}
SEVERITY = {"high": "높음", "medium": "보통", "low": "낮음", "info": "정보"}
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}
RELATION = {
    "part_of": "소속",
    "supplied_by": "공급",
    "butt_weld": "맞대기 용접",
    "fillet_weld": "필릿 용접",
    "penetration": "관통",
    "support": "지지",
    "pipe_joint": "배관 연결",
    "drawn_in": "도면",
    "consumed_by": "소비 공정",
    "precedes": "선후행",
    "same_spec": "같은 규격",
}
DETERMINACY = {"known": "계산됨", "state_unknown": "판단 불가(상태를 몰라 가능한 범위 전체)"}
PARAM_STATUS = {"evidence": "근거 있음", "assumption": "가정", "mentor": "현업 확인"}
ELIGIBILITY = {"meets": "충족(예비)", "short": "부족", "designer": "설계자 확인"}
ORIGIN = {"request": "요청안", "template": "대안", "llm": "AI 제안 대안", "user": "사용자 대안"}
STATE = {
    "requested": "요청",
    "analyzed": "분석",
    "in_review": "검토",
    "approved": "승인",
    "rejected": "반려",
    "on_hold": "보류",
    "in_progress": "실행",
    "closed": "종료",
}
ROLE = {"admin": "팀장", "part_lead": "파트장", "executive": "본부장", "member": "담당자", "demo": "체험"}
STEP = {"part_lead": "파트장", "team_lead": "팀장", "executive": "본부장"}
TRANSPORT = {"air": "항공", "sea": "선박"}  # 외자재 운송 방식(화면 lib/summary.ts TRANSPORT_NAMES와 같음)
"""결재선 단계(docs/records.md(기록·결재) 14절, 화면 lib/approval.ts STEP_LABEL과 같은 말)."""
MATERIAL = {
    "plate": "판재",
    "section": "형강",
    "pipe": "배관",
    "valve": "밸브",
    "fitting": "배관 부속",
    "equipment": "장비",
}
"""리드타임 파라미터의 자재 분류(일정 위험 배율)."""
SHAPE = {"flat": "평블록", "curved": "곡블록", "bow_stern": "선수미 블록"}
"""블록 형상(1.32.0 난이도 계수 입력)."""
INPUT = {
    "qty": "수량",
    "new_qty": "새 수량",
    "moved_qty": "전용 수량",
    "unit_price": "단가(원)",
    "new_unit_price": "새 단가(원)",
    "weight_t": "중량(t)",
    "hours": "공수(시간)",
    "days": "일수",
    "count": "개수",
    "bought_value": "신규 구매 금액(원)",
}
"""비용 줄 입력값 이름. 단계(stage)는 계산식에 현장 이름으로 들어 있어 따로 쓰지 않는다."""


OP = {
    "thickness": "두께 변경",
    "grade": "강종 변경",
    "dimension": "치수 변경",
    "add_part": "부재 추가",
    "remove_part": "부재 삭제",
    "reroute_pipe": "배관 경로 변경",
    "equipment_spec": "장비 사양 변경",
    "add_penetration": "관통부 추가",
}
"""변경 연산 이름(화면 lib/labels.ts OP_NAMES와 같은 말)."""
WEIGHT_SOURCE = {
    "qty_t": "규격 수량(t) — 자재비 차이와 같은 값",
    "weight_kg": "부재 중량(kg ÷ 1000)",
    "none": "중량 정보 없음",
}
"""1.34.0 중량 변화의 부재 중량 근거(화면 lib/weightChange.ts와 같은 말)."""
COST_KIND = {"labor": "공수", "material": "재료비", "damages": "지체상금"}
"""1.35.0 비용 줄 구분(화면 lib/costSplit.ts COST_KIND_NAMES와 같은 말)."""
COST_ITEM = {
    "rework": "재작업",
    "new_work": "신규 작업",
    "onboard": "선상 설치",
    "after_paint": "도장 뒤 작업",
    "weld": "용접",
    "machining": "가공",
    "drawing": "도면",
    "material_diff": "자재 차이",
    "stock": "재고 전용",
    "po_change": "발주 변경·취소",
    "reorder": "새 발주 할증",
    "transfer": "잉여 자재 전용",
    "liquidated_damages": "지체상금",
}
"""1.35.0 비용 줄 세부 구분(화면 lib/costSplit.ts COST_ITEM_NAMES와 같은 말)."""
COG_NOTE = "무게중심: 좌표 정보 필요(다음 단계)"
"""무게중심은 계산하지 않는다는 안내(화면 WeightChange와 같은 글)."""


def name(table: Mapping[str, str], code: object) -> str:
    """코드 → 이름(열거형 값 포함). 모르면 코드 그대로."""
    key = str(getattr(code, "value", code))
    return table.get(key, key)
