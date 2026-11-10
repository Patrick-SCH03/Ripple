"""계약 레이어: 모든 레이어가 공유하는 Pydantic 모델과 식별 규칙.

- domain: 연결 지도의 노드·관계와 상태 어휘
- change: 설계변경 요청과 변경 연산 8종
- analysis: 분석 요청과 버전 묶음
- result: 분석 결과(영향·금액·일정·시점·대안)
- explain: 설명·알림 초안의 블록 형식(수치 블록·글 템플릿 블록)과 렌더링 결과
- assistant: AI 비서의 변경 초안(연산별 슬롯)·질문·대화 차례·알림
- lexicon: 규칙 기반 해석기의 현장 용어 사전
- dataset: 생성기가 만드는 설계변경 사례와 문장 사례
- rulebook, params: 규칙표·비용 파라미터 YAML의 형식
- identity: 스냅샷 ID·분석 ID(내용 해시)
- system: 시스템 상태 응답

다른 ripple 모듈을 import하지 않는다(tests/checks/layers.py가 검사한다).
계약을 바꾸면 CONTRACT_VERSION을 올리고 docs/domain.md를 함께 고친다.
"""

from .base import CONTRACT_VERSION, Frozen

__all__ = ["CONTRACT_VERSION", "Frozen"]
