"""가상 예시 사례 3건(docs/backtest.md 1절) — 실제 회사·호선·사례가 아니다. 양식 채우는 법과 검사에 쓴다.

발견 단계(선행의장·조립·탑재)·재제작 방식(사내 재제작·스풀 없음·사외 재발주)·
지연 기준(구역 출구·탑재·빈 칸)이 서로 다르고, 일부 칸을 비워 '가정'·'비교 불가' 처리를 보인다.
"""

from __future__ import annotations

EXAMPLE_MARK = "예시(가상)"

EXAMPLE_ROWS: tuple[dict[str, object], ...] = (
    {
        "case_no": "예시(가상)-1",
        "content": "예시(가상) 기관실 연료유 배관 경로 변경(격벽 관통 → 우회)",
        "cause": "설계 간섭",
        "area": "예시(가상) 기관실 측부 블록",
        "block_type": "곡",
        "block_weight_t": 280,
        "stage": "선행의장",
        "members": 3,
        "spools": 4,
        "spool_method": "사내 재제작",
        "drawings": 2,
        "po_changes": 1,
        "mh_min": 120,
        "mh_max": 180,
        "cost_min": 900,
        "cost_max": 1400,
        "delay_days": 5,
        "delay_basis": "구역 출구",
        "performer": "사내 협력사",
        "decision_days": 7,
    },
    {
        "case_no": "예시(가상)-2",
        "content": "예시(가상) 갑판 종보강재 치수 보강(선급 코멘트)",
        "cause": "규정",
        "area": "예시(가상) 화물창 갑판 블록",
        "block_type": "평",
        "block_weight_t": 350,
        "stage": "조립",
        "members": 6,
        "spools": 0,
        "spool_method": None,
        "drawings": 1,
        "po_changes": None,
        "mh_min": 60,
        "mh_max": 90,
        "cost_min": 300,
        "cost_max": 500,
        "delay_days": 0,
        "delay_basis": "탑재",
        "performer": "직영",
        "decision_days": 3,
    },
    {
        "case_no": "예시(가상)-3",
        "content": "예시(가상) 선수부 밸브 사양 변경에 따른 스풀 재제작",
        "cause": "기자재 사양",
        "area": "예시(가상) 선수부 블록",
        "block_type": "선수미",
        "block_weight_t": None,
        "stage": "탑재",
        "members": 1,
        "spools": 2,
        "spool_method": "사외 재발주",
        "drawings": 1,
        "po_changes": 1,
        "mh_min": None,
        "mh_max": None,
        "cost_min": 200,
        "cost_max": 400,
        "delay_days": 10,
        "delay_basis": None,
        "performer": None,
        "decision_days": None,
    },
)
"""양식 열 키(ripple/eval/backtest/case.py COLUMNS) → 값. 원문 칸(변경 내용·블록·구역)에도 '예시(가상)'을 붙인다."""
