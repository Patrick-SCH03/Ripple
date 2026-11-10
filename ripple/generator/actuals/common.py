"""숨긴 모델 모듈들이 같이 쓰는 상수와 작은 도우미: 공정 순서·강재 분류·원 단위 반올림·새 부재 ID."""

from __future__ import annotations

import hashlib
import math
from datetime import timedelta

from ripple.contracts.domain import BLOCK_ACTIVITY_ORDER, BlockStage
from ripple.contracts.identity import canonical_json, normalized_op

VERSION = "actuals-v5"  # v5: 의장품 재작업은 선행의장 공정부터·배관도 개정 공수(엔진 0.12.0과 같은 식),
# v4: 외자재 새 발주의 참 운송 일수(엔진 0.11.0과 같은 규칙), v3: 블록 공정 PE·블록 난이도 계수·
# 도장 뒤 고정 항목·공정 수행 주체 단가(엔진 0.10.0과 같은 식)
DAY = timedelta(days=1)
STAGES = tuple(BlockStage)
WORK = tuple(kind.value for kind in BLOCK_ACTIVITY_ORDER)
STEEL = frozenset({"plate", "section"})
"""강재 규격 분류(판·형강): 새 부재의 정상 제작 공수(C-02)를 붙이는 부재 추가."""


def won(amount: float) -> int:
    """원 단위 반올림(0.5는 0에서 먼 쪽)."""
    rounded = math.floor(abs(amount) + 0.5)
    return rounded if amount >= 0 else -rounded


def new_part_key(op: object) -> str:
    """새 부재 임시 ID의 h8: 연산 정규형의 SHA-256 앞 8자리(ECN 번호·연산 순서와 무관, docs/engine.md(전파) 3절)."""
    return hashlib.sha256(canonical_json(normalized_op(op))).hexdigest()[:8]  # type: ignore[arg-type]
