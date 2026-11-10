"""E2a 비용 정확도 측정(docs/evaluation.md, `ripple/eval/cost_accuracy.py`): 엔진 대표 총액 vs 숨긴 실제 모델 총액.

  uv run python scripts/eval_cost.py               개발 분할(200건)
  uv run python scripts/eval_cost.py --seeds 1,2,3,4,5
                                                    다른 시드(합성 세계 전체를 다시 만듦)의 개발 분할 — 강건성 참고
  uv run python scripts/eval_cost.py --split eval --final
                                                    평가 분할(100건) — 방법을 고정한 뒤 최종 인증 때 한 번만

기준 미달이면(시드를 여럿 재면 하나라도) 종료 코드 1.
"""

from __future__ import annotations

import argparse
import io
import sys

from ripple.config.loaders import load_params, load_rulebook, load_strength
from ripple.config.settings import Settings
from ripple.contracts.dataset import EcnSplit
from ripple.eval.cost_accuracy import MEDIAN_MAX, P90_MAX, SMALL_SHARE_MIN, CostAccuracy, accuracy, cost_pairs
from ripple.eval.split_args import add_split_args, split_run
from ripple.generator.actuals import HiddenModel
from ripple.generator.build import generate
from ripple.generator.io import load_config


def measure(settings: Settings, split: EcnSplit, seed: int | None) -> tuple[int, CostAccuracy]:
    config = load_config()
    generated = generate(config, seed)
    pairs, excluded = cost_pairs(
        generated,
        HiddenModel(generated, settings.params_path),
        load_rulebook(settings.rules_path),
        load_params(settings.params_path),
        load_strength(settings.strength_path),
        split,
        config.scenario_date,
    )
    return generated.seed, accuracy(pairs, excluded)


def report(label: str, result: CostAccuracy) -> None:
    print(f"E2a 비용 정확도 · {label} · 사례 {result.cases}건(제외 {result.excluded}건)")
    if result.ape_median is not None and result.ape_p90 is not None:
        print(
            f"  실제 총액 절댓값 100만원 이상 {result.big}건: "
            f"오차 중앙값 {result.ape_median:.1%}(기준 ≤ {MEDIAN_MAX:.0%}) · "
            f"90백분위 {result.ape_p90:.1%}(기준 ≤ {P90_MAX:.0%})"
        )
    if result.small_within is not None:
        print(f"  미만 {result.small}건: 오차 50만원 이내 {result.small_within:.1%}(기준 ≥ {SMALL_SHARE_MIN:.0%})")
    print(f"  판단 불가·계산 불가가 있는 사례 {result.uncertain}건 · 미반영 비용이 생긴 사례 {result.unmodeled}건")
    if result.bias_median is not None and result.in_range is not None:
        print(
            f"  참고(기준 아님): 큰 사례 부호 있는 오차 중앙값 {result.bias_median:+.1%}(+ = 과대 추정) · "
            f"실제가 엔진 범위 안 {result.in_range:.1%}"
        )
    print("  합격" if result.passed else "  미달")


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    add_split_args(parser)
    run = split_run(parser.parse_args())
    if run is None:
        return 2
    settings = Settings.from_env({})
    results = [measure(settings, run.split, seed) for seed in run.seeds]
    for seed, result in results:
        report(f"{run.name} 분할 · 시드 {seed}", result)
    passed = sum(result.passed for _, result in results)
    if len(results) > 1:
        print(f"합격 {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
