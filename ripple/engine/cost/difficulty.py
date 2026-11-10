"""블록 난이도 계수(docs/engine.md(비용·일정) 4-4, cost-v6): 형상 × 의장 밀도 × 전장품, 상한 cap.

재작업 공수에만 곱하고 재작업 배수와 따로 보인다(CostLine.difficulty). 계수 파라미터는 범위 없이 대표값만 둔다
(밀도 문턱은 클수록 계수가 작아져 시나리오 방향이 정해지지 않기 때문 — 평가기가 읽을 때 검사한다).

- 형상: difficulty.shape.<평·곡·선수미>, 지도에 형상이 없으면 1(키 없음)
- 의장 밀도: 1 + (outfit_max − 1) × min(1, (의장품 수 ÷ 강재 중량) ÷ outfit_full_per_t), 의장품 수가 없으면 1
- 전장품: 1 + (electric_max − 1) × min(1, (전장품 수 ÷ 강재 중량) ÷ electric_full_per_t), 전장품 수가 없으면 1
- 계수 = min(형상 × 의장 × 전장, cap). 세 계수는 소수 넷째 자리, 계수는 여섯째 자리에서 반올림한다(숨긴 모델도 같은 식)
"""

from __future__ import annotations

from dataclasses import dataclass

from ripple.contracts.domain import Block
from ripple.contracts.result import BlockDifficulty

from .amounts import Params

SHAPE = "difficulty.shape."
OUTFIT_MAX, OUTFIT_FULL = "difficulty.outfit_max", "difficulty.outfit_full_per_t"
ELECTRIC_MAX, ELECTRIC_FULL = "difficulty.electric_max", "difficulty.electric_full_per_t"
CAP = "difficulty.cap"


@dataclass(frozen=True, slots=True)
class Difficulty:
    factor: BlockDifficulty
    keys: tuple[str, ...]  # 쓴 파라미터 키(비용 줄 param_keys에 더한다)

    @property
    def value(self) -> float:
        return self.factor.value


def block_difficulty(block: Block | None, params: Params) -> Difficulty:
    """블록 하나의 난이도 계수. 블록을 모르거나 입력이 없으면 1(파라미터를 쓰지 않음)."""
    keys: list[str] = []
    shape = block.shape if block is not None else None
    shape_factor = 1.0
    if shape is not None:
        keys.append(f"{SHAPE}{shape.value}")
        shape_factor = round(params.value(keys[-1]), 4)
    weight = block.steel_weight_t if block is not None else 0.0
    outfit = _density(block.outfit_items if block else None, weight, params, OUTFIT_MAX, OUTFIT_FULL, keys)
    electric = _density(block.electric_items if block else None, weight, params, ELECTRIC_MAX, ELECTRIC_FULL, keys)
    cap = params.value(CAP) if keys else 1.0
    if keys:
        keys.append(CAP)
    product = shape_factor * outfit * electric
    factor = BlockDifficulty(
        shape=shape,
        shape_factor=shape_factor,
        outfit_factor=outfit,
        electric_factor=electric,
        cap=max(cap, 1.0),
        value=round(min(product, max(cap, 1.0)), 6),
        capped=product > max(cap, 1.0) + 1e-9,
    )
    return Difficulty(factor=factor, keys=tuple(keys))


def _density(items: int | None, weight: float, params: Params, top: str, full: str, keys: list[str]) -> float:
    """밀도 계수: 1 + (최댓값 − 1) × min(1, (수 ÷ 강재 중량) ÷ 최댓값이 되는 밀도). 수를 모르면 1."""
    if items is None or weight <= 0:
        return 1.0
    keys.extend((top, full))
    density = items / weight
    return round(1 + (params.value(top) - 1) * min(1.0, density / params.value(full)), 4)
