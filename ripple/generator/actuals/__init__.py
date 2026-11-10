"""숨긴 실제 비용·지연 모델(docs/data.md(생성기) 6-1, actuals-v5): 평가(E2a·E2'·E7)의 정답.

엔진(ripple.engine)을 import하지 않는 같은 명세의 다른 구현이다. 생성기가 정한 참 날짜·고정 시드로 뽑은 참 파라미터·
항목 잡음·가끔 생기는 미반영 비용으로 설계변경 하나의 (확정일, 보류)에 대한 실제 비용과 지연을 계산한다.

모듈:
- model: 입구(요인 고정·참 파라미터·사례 시드)와 결과 조립
- world: 지도 찾아보기 표·참 발주 단계, case: 결정(확정일·보류)과 참 기준 일정
- params: 참 파라미터 표본·사례 시드, lead: 새 규격 리드타임, network: 일정 망·전진 계산
- material: 자재비 차이·재고 전용, impacts: 변경 후 보기·작은 작업 표시, purchase: 발주 손실·전용·할증
- work: 새 부재 공수·재작업(난이도·도장 뒤 고정 항목·수행 주체 단가)·작은 작업
- schedule: 자재 도착·변경 일정, delivery: 인도 지연·지체상금
- amounts: 잡음 전 항목 금액(모듈별 몫 합치기), outcome: 결과 형식·항목 잡음·미반영 비용, common: 공통 상수·도우미
"""

from .common import VERSION
from .delivery import delivery_added
from .lead import PLATE_DELAY_DAYS, quantile_days
from .model import FACTORS, Factor, HiddenModel
from .outcome import ActualItem, ActualOutcome

__all__ = [
    "FACTORS",
    "PLATE_DELAY_DAYS",
    "VERSION",
    "ActualItem",
    "ActualOutcome",
    "Factor",
    "HiddenModel",
    "delivery_added",
    "quantile_days",
]
