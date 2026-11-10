"""E2' 일정 정확도 측정(docs/evaluation.md, `ripple/eval/schedule_accuracy.py`): 엔진 일정 지연 vs 숨긴 실제 모델 지연.

  uv run python scripts/eval_schedule.py               개발 분할(200건)
  uv run python scripts/eval_schedule.py --seeds 1,2,3,4,5
                                                        다른 시드(합성 세계 전체를 다시 만듦)의 개발 분할 — 강건성 참고
  uv run python scripts/eval_schedule.py --split eval --final
                                                        평가 분할(100건) — 방법을 고정한 뒤 최종 인증 때 한 번만

기준 미달이면(시드를 여럿 재면 하나라도) 종료 코드 1. 일정 위험 참고 줄은 합격 판정과 무관하다
(엔진 판정은 위험을 검토 필요 이유 하나에만 쓴다, docs/engine.md(비용·일정) 8-4).
"""

from __future__ import annotations

import argparse
import io
import sys

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import Settings
from ripple.contracts.dataset import EcnSplit
from ripple.eval.schedule_accuracy import (
    FALSE_ALARM_MAX,
    LARGE_DAYS,
    LARGE_SHARE_MAX,
    MAE_MAX,
    MISS_MAX,
    DelayAccuracy,
    RiskReference,
    ScheduleAccuracy,
    accuracy,
    delay_pairs,
    risk_reference,
)
from ripple.eval.split_args import add_split_args, split_run
from ripple.generator.actuals import HiddenModel
from ripple.generator.build import generate
from ripple.generator.io import load_config


def measure(settings: Settings, split: EcnSplit, seed: int | None) -> tuple[int, ScheduleAccuracy, RiskReference]:
    config = load_config()
    generated = generate(config, seed)
    pairs, excluded = delay_pairs(
        generated,
        HiddenModel(generated, settings.params_path),
        load_rulebook(settings.rules_path),
        load_params(settings.params_path),
        split,
        config.scenario_date,
    )
    return generated.seed, accuracy(pairs, excluded), risk_reference(pairs)


def _share(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def line(label: str, d: DelayAccuracy) -> str:
    mae = "-" if d.mae is None else f"{d.mae:.2f}일"
    return (
        f"  {label} {d.cases}건(실제 지연 {d.delayed}건): 평균 절대 오차 {mae}(기준 ≤ {MAE_MAX:.0f}일) · "
        f"{LARGE_DAYS}일 이상 {_share(d.large_share)}(≤ {LARGE_SHARE_MAX:.0%}) · "
        f"오경보 {_share(d.false_alarm)}(≤ {FALSE_ALARM_MAX:.0%}) · 누락 {_share(d.miss)}(≤ {MISS_MAX:.0%})"
        f" — {'충족' if d.passed else '미달'}"
    )


def _part(count: int, total: int) -> str:
    return f"{count}/{total}건" + (f"({count / total:.1%})" if total else "")


def risk_line(ref: RiskReference) -> str:
    return (
        f"  참고 · 일정 위험(리드타임 범위 끝) 구역 출구 최대 지연 {ref.cases}건: "
        f"실제 지연 사례 중 위험 > 0 {_part(ref.delayed_flagged, ref.delayed)} · "
        f"실제 0인 사례 중 위험 > 0 {_part(ref.on_time_flagged, ref.on_time)} · "
        f"실제 ≤ 위험 {_part(ref.covered, ref.cases)} — "
        "판 리드타임 변동만 실제 입고 지연 분포(그 밖은 우리가 정한 범위), E2' 합격과 무관"
    )


def report(label: str, result: ScheduleAccuracy, ref: RiskReference) -> None:
    print(f"E2' 일정 정확도 · {label} · 사례 {result.cases}건(제외 {result.excluded}건)")
    print(line("구역 출구 최대 지연", result.exit))
    print(line("늘어난 인도 지연(둘 다 계산된 사례)", result.delivery))
    print(f"  판단 불가·계산 불가가 있는 사례 {result.uncertain}건")
    print(risk_line(ref))
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
    for seed, result, ref in results:
        report(f"{run.name} 분할 · 시드 {seed}", result, ref)
    passed = sum(result.passed for _, result, _ in results)
    if len(results) > 1:
        print(f"합격 {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
