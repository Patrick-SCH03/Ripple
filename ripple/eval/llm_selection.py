"""외부 모델 비교 측정의 채택 순서(docs/input.md(외부 AI) 3절, 측정 전 등록한 규칙).

p95가 상한을 넘는 후보는 뒤로 뺀다(제외). 남은 후보에서 1차 지표(낮을수록 좋음: 틀림·사실 검사 위반 비율)의 최저값에서
허용 폭 안인 후보를 같다고 보고, 그중 2차 지표(높을수록 좋음: 완전 일치·쓰는 설명 비율)의 최고값에서 허용 폭 안인 후보를
같다고 보고, 그중 p95가 가장 짧은 후보가 이긴다. 이긴 후보를 빼고 되풀이해 전체 순서를 만든다.
허용 폭은 '그 단계 최고값에서 얼마 안'이다(반올림 구간이 아님).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

EPS = 1e-12  # 같은 값을 부동소수 오차로 가르지 않게


@dataclass(frozen=True, slots=True)
class Candidate:
    name: str
    primary: float  # 낮을수록 좋음
    secondary: float  # 높을수록 좋음
    p95_s: float


def rank(candidates: Sequence[Candidate], primary_tol: float, secondary_tol: float, p95_limit_s: float) -> list[str]:
    """채택 순서(앞이 1순위). 상한을 넘는 후보는 끝에 이름 순으로."""
    rest = [c for c in candidates if c.p95_s <= p95_limit_s]
    order: list[str] = []
    while rest:
        best_primary = min(c.primary for c in rest)
        tier = [c for c in rest if c.primary <= best_primary + primary_tol + EPS]
        best_secondary = max(c.secondary for c in tier)
        tier = [c for c in tier if c.secondary >= best_secondary - secondary_tol - EPS]
        winner = min(tier, key=lambda c: (c.p95_s, c.name))
        order.append(winner.name)
        rest.remove(winner)
    return order + sorted(c.name for c in candidates if c.p95_s > p95_limit_s)
