"""결정 도우미의 재료: 결재할 개정의 기록 본문과 업무상 오늘.

다시 계산하지 않는다 — 기록의 지도·계산 판이 지금 활성 지도와 다를 수 있어(실시간 시연 세계는 날마다 지도 ID가 바뀜)
활성 색인으로 다시 분석하면 오류가 나거나 결정 대화상자의 숫자(기록 본문)와 달라진다. 숫자는 모두 기록 본문의 분석
결과에 이미 계산된 값(곡선·보류 권고·선상 설치 선택지·일정 위험·노출 금액·대안 권고)에서만 온다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ripple.contracts.records import RecordBody
from ripple.contracts.result import AnalysisResult

DELAY_PENALTY_RULE = "R-L01"  # 지체상금 줄(docs/engine.md(비용·일정) 4-6)


@dataclass(frozen=True, slots=True)
class Facts:
    body: RecordBody
    today: date  # 업무상 오늘(records.metrics.business_today — 결재함 D-n과 같은 기준)

    @property
    def result(self) -> AnalysisResult:
        return self.body.result


def delay_penalty(result: AnalysisResult) -> int:
    """지체상금 줄의 대표 금액 합(없으면 0)."""
    return sum(line.amount.value for line in result.cost_lines if line.rule_id == DELAY_PENALTY_RULE)


def cause_unknown_with_penalty(result: AnalysisResult) -> bool:
    """변경 원인이 미입력이고 지체상금이 붙었나(선주 요청이면 인도일 조정 대상이 됨)."""
    return result.request.change.cause is None and delay_penalty(result) > 0
