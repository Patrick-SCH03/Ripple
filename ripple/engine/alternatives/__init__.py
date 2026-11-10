"""대안(docs/engine.md(대안)): 강도형 요청의 템플릿 대안·강도 사전검사·최적 조합·권고. 순수 계산이다."""

from __future__ import annotations

from .compare import Baseline, Comparison, compare
from .templates import Plan, plan

__all__ = ["Baseline", "Comparison", "Plan", "compare", "plan"]
