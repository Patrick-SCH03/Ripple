"""고정 가정값 표(docs/backtest.md 4절): 양식에 칸이 없어 늘 가정으로 넣는 값·변환 규칙과 그 출처.

백테스트 기본값(defaults.yaml)·생성기 설정(generator/config.yaml)·비용 파라미터에서 읽는다
— 값을 바꾸면 이 표도 따라 바뀐다.
"""

from __future__ import annotations

from ripple.contracts.domain import BLOCK_ACTIVITY_ORDER
from ripple.engine.describe import ACTIVITY_NAMES
from ripple.generator.config import DurationConfig

from .case import BLOCK_TYPES
from .crew import CREW_KINDS
from .engine import Engine
from .plan import half_up, middle
from .scope import LABEL_OF_BASIS, LABEL_OF_METHOD

Row = tuple[str, str, str]  # 항목, 값, 출처
DEFAULTS = "백테스트 기본값"
GENERATOR = "생성기 설정"
OUTSIDE_LEAD = "lead_time_days.pipe"
PRIME_RATE, CREW_RATE = "labor_rate_per_hour.prime", "labor_rate_per_hour.crew"
SHAPE = "difficulty.shape."


def fixed_assumptions(engine: Engine) -> tuple[Row, ...]:
    return (*_conversion(engine), *_work(engine), *_schedule(engine), *_prices(engine))


def _conversion(engine: Engine) -> list[Row]:
    defaults, params = engine.defaults, engine.params
    spool, member, weights = defaults.spool, defaults.member, defaults.block_weight_t
    outside = half_up(params.value(OUTSIDE_LEAD))
    return [
        ("바뀐 부재", f"보강재 1개 {member.weight_t:g}t, 치수 변경(재작업·도면 개정, 발주는 그대로)", DEFAULTS),
        (
            "재제작 방식",
            "사내 재제작·사외 재발주 = 옛 스풀을 빼고 같은 규격 새 스풀"
            "(옛 스풀 발주 변경·취소 + 새 스풀 리드타임 관문), "
            f"치수 변경 = 같은 자재 다시 가공(발주·리드타임 없음) · 비면 {LABEL_OF_METHOD[spool.method]}",
            DEFAULTS,
        ),
        (
            "새 스풀 리드타임",
            f"사내 재제작 {spool.in_house_lead_days}일 · 사외 재발주 {outside}일(엔진 파라미터 {OUTSIDE_LEAD})",
            f"{DEFAULTS} · 비용 파라미터",
        ),
        ("재제작 스풀 1개", f"{spool.weight_t:g}t · {spool.length_m:g}m(새 스풀 무게는 엔진 환산 중량)", DEFAULTS),
        (
            "블록 무게(빈 칸)",
            f"평 {weights.flat:g}t · 곡 {weights.curved:g}t · 선수미 {weights.bow_stern:g}t"
            f" · 종류 모름 {weights.unknown:g}t",
            DEFAULTS,
        ),
        ("확정일", "기준일 + 결정까지 걸린 일수(비면 기준일)", "변환 규칙"),
    ]


def _work(engine: Engine) -> list[Row]:
    """수행 주체·난이도·비교 기준(엔진 0.10.0 · cost-v6)."""
    params, defaults = engine.params, engine.defaults
    prime, crew = half_up(params.value(PRIME_RATE)), half_up(params.value(CREW_RATE))
    kinds = "·".join(ACTIVITY_NAMES[kind] for kind in CREW_KINDS)
    shapes = " · ".join(f"{label} {params.value(SHAPE + value):g}" for label, value in BLOCK_TYPES.items())
    return [
        (
            "수행 주체",
            f"직영 = 블록 공정 모두 직영(단가 {prime:,}원/시간), "
            f"사내 협력사 = {kinds} 공정을 작업반 하나가 맡고 탑재는 직영"
            f"(작업반 단가 {crew:,}원/시간), 비면 '모름'(사외 제작이 없어 직영 단가)",
            f"변환 규칙 · 비용 파라미터 {PRIME_RATE}·{CREW_RATE}",
        ),
        (
            "블록 난이도",
            f"블록 종류 → 형상 계수({shapes}), 비면 1 · 의장품·전장품 수는 양식에 없어 밀도 계수 1",
            "비용 파라미터 difficulty",
        ),
        (
            "공수 비교",
            "공수가 있는 모든 비용 줄의 합(재작업·작업반 몫·도장 뒤 고정 항목·작은 작업·도면 개정)",
            "변환 규칙",
        ),
        ("비용 비교", "총변경비용(총액) · 지연 파급 비용(총액 밖·가정)은 엔진 값 그대로 따로 표시", "변환 규칙"),
        ("지연 비교", f"사례의 지연 기준(탑재·구역 출구·인도), 비면 {LABEL_OF_BASIS[defaults.delay_basis]}", DEFAULTS),
    ]


def _schedule(engine: Engine) -> list[Row]:
    schedule, gen = engine.defaults.schedule, engine.generator
    durations = " · ".join(
        f"{ACTIVITY_NAMES[kind]} {_formula(getattr(gen.activities, kind.value))}" for kind in BLOCK_ACTIVITY_ORDER
    )
    procurement = gen.procurement
    steel, pipe = half_up(middle(procurement.plate_lead_days)), half_up(middle(procurement.pipe_lead_days))
    slack = half_up(middle(procurement.order_slack_days))
    return [
        ("기준일", f"발견 단계가 진행 중인 구간의 {schedule.stage_position:.0%} 위치", DEFAULTS),
        ("공정 기간(일, W = 블록 무게 t)", durations, f"{GENERATOR} 범위의 가운데"),
        ("공정 사이 간격", f"{half_up(middle(gen.activities.gap_days))}일", f"{GENERATOR} 범위의 가운데"),
        (
            "발주 리드타임·여유",
            f"강재 {steel}일 · 스풀 {pipe}일 · 소비 공정 착수 전 여유 {slack}일",
            f"{GENERATOR} 범위의 가운데",
        ),
        ("탑재 완료 → 구역 출구 여유", f"{schedule.exit_slack_days}일", DEFAULTS),
        ("구역 출구 → 인도 여유", f"{schedule.float_to_delivery_days}일(지체상금 계산의 경계 조건)", DEFAULTS),
    ]


def _prices(engine: Engine) -> list[Row]:
    prices, ship = engine.generator.prices, engine.generator.ship
    return [
        (
            "자재 단가",
            f"판 {half_up(middle(prices.plate_per_t)):,}원/t · 형강 {half_up(middle(prices.section_per_t)):,}원/t · "
            f"스풀 {half_up(middle(prices.pipe_per_m)):,}원/m",
            f"{GENERATOR} 범위의 가운데",
        ),
        ("선가", f"{ship.contract_price_krw:,}원(지체상금에만 쓰임)", GENERATOR),
    ]


def _formula(config: DurationConfig) -> str:
    return f"{middle(config.base):g} + {middle(config.per_100t):g}×W/100"
