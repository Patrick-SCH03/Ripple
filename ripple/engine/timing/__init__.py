"""확정 시점(docs/engine.md(비용·일정) 1·6·7·8절): 판정일마다 평가하고, 추가손실 곡선과 발주 보류 권고를 낸다.

evaluate(t, holds) = 판정일 t의 영향 → 비용 줄 → 변경 일정(CPM) → 인도 지연 → 지체상금 → 일정·인도 영향.
risk(t, holds) = 같은 날 새 자재 리드타임만 분류별 범위 끝으로 늘린 일정(6-6 일정 위험 — 비용은 대표 그대로,
판정은 8-4 검토 필요 이유 하나에만 쓴다).
선상 설치 요청(6-3)이면 탑재를 늦출 의장품을 배 위로 보내고 할증 줄(C-03)을 더한다. 선주 요청 변경(4-6 허용 지연)이면
지체상금 줄 대신 인도 영향에 노출 금액을 싣는다.

모듈: evaluator(평가기·상태와 곡선 메모) · context(평가 문맥·하루 평가 조건) · day(하루 평가) ·
adjust(일정 조정 6-3) · ships(변경 일정 6-4·6-7) · delivery(인도 지연·지체상금 4-6) · impacts(일정·인도 영향 7절) ·
risk(일정 위험 6-6) · onboard(선상 설치 6-3·6-8) · curve(추가손실 곡선 8-1) · hold(발주 보류 권고 8-3) ·
rule_ids(분석 규칙 ID).
"""

from .evaluation import Evaluation
from .evaluator import Evaluator
from .impacts import merge_impacts
from .rule_ids import ANALYSIS_RULES

__all__ = ["ANALYSIS_RULES", "Evaluation", "Evaluator", "merge_impacts"]
