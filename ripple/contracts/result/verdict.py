"""요약 판정 계약(docs/engine.md(비용·일정) 8-4)."""

from __future__ import annotations

from pydantic import Field, model_validator

from ..base import Frozen
from .vocab import VerdictLevel


class Verdict(Frozen):
    """요약 판정(엔진의 순수 함수, docs/engine.md(비용·일정) 8-4). 이유는 숫자 없는 고정 문장, 수치는 결과 필드로
    본다."""

    level: VerdictLevel
    reasons: tuple[str, ...] = Field(min_length=1, max_length=7)  # 1.29.0 검토 필요 6개 + 설계 승인 전

    @model_validator(mode="after")
    def _plain(self) -> Verdict:
        if any(any(ch.isdigit() for ch in reason) for reason in self.reasons):
            raise ValueError("판정 이유에 숫자 불가(수치는 결과 필드로)")
        return self
