"""확정 시점 평가가 계산하는 분석 규칙 ID(docs/engine.md(비용·일정) 7·8-3절): 1단계 전파 규칙(rules.RULES) 밖의 것.

R-S01 = 일정 지연(impacts), R-H01 = 발주 보류 권고(hold), R-L01 = 인도 지연(impacts).
"""

from __future__ import annotations

SCHEDULE_RULE, HOLD_RULE, DELIVERY_RULE = "R-S01", "R-H01", "R-L01"
ANALYSIS_RULES = frozenset({SCHEDULE_RULE, HOLD_RULE, DELIVERY_RULE})
