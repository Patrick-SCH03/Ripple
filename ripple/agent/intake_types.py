"""문서 접수 조율이 주고받는 값: 확정을 요청한 사람(Actor — 로그인 ID와 체험·개발 계정 여부, 수정 기록 줄에 그대로
남는다). 서비스(intake.py)와 수정 기록 줄(intake_records.py)이 함께 쓴다."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Actor:
    login_id: str
    demo: bool = False
    dev: bool = False
