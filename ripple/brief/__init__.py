"""결정 도우미(계약 1.31.0, docs/records.md(기록·결재) 결정 도우미 절): 팀장이 결재하는 순간 보는 세 줄 요약과
서명 전 확인할 것.

기록 본문(분석 결과) → 세 줄(규칙 템플릿, lines) · 확인할 것 후보(checks) → 고르기(규칙 순서 또는 AI, pick)
→ 검사(audit).
숫자·판정은 엔진 결과(기록 본문)에서만 온다. AI는 합성 데이터에서 확인할 것의 선택·순서만 정한다. 다시 계산하지 않는다.
"""

from .audit import audit
from .build import BriefError, CaseFinder, build_brief, no_cases

__all__ = ["BriefError", "CaseFinder", "audit", "build_brief", "no_cases"]
