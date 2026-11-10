"""E7 결정 일치 측정(docs/evaluation.md, `ripple/eval/decision_agreement.py`): 엔진 권고 vs 숨긴 실제 모델 기준 최선.

  uv run python scripts/eval_decision.py               개발 분할(200건 × 확정 가능일 기준일·+10일·+20일)
  uv run python scripts/eval_decision.py --seeds 1,2,3,4,5
                                                        다른 시드(합성 세계 전체를 다시 만듦)의 개발 분할 — 강건성 참고
  uv run python scripts/eval_decision.py --oracle      진단: 숨긴 모델 확인 모드(대표값·잡음 0) — 기준 판정 아님
  uv run python scripts/eval_decision.py --split eval --final
                                                        평가 분할(100건) — 방법을 고정한 뒤 최종 인증 때 한 번만

조건·시드마다 프로세스를 나눠 잰다. 기준 미달이면(조건·시드 중 하나라도) 종료 코드 1.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from concurrent.futures import ProcessPoolExecutor

from ripple.config.loaders import load_params, load_rulebook, load_strength
from ripple.config.settings import Settings
from ripple.contracts.dataset import EcnSplit
from ripple.eval.decision_agreement import (
    CONFIRM_SHIFTS,
    REGRET_MAX,
    SAME_MIN,
    DecisionAgreement,
    agreement,
    decision_cases,
    hidden_total,
)
from ripple.eval.split_args import add_split_args, split_run
from ripple.generator.actuals import HiddenModel
from ripple.generator.build import generate
from ripple.generator.io import load_config

Job = tuple[EcnSplit, int | None, int, bool]  # (분할, 시드, 확정 가능일 + 일수, 확인 모드)


def measure(job: Job) -> tuple[int, int, DecisionAgreement, DecisionAgreement]:
    """(시드, 확정 가능일 + 일수, 전체, 참고: 충족 대안 2개 이상인 사례만)."""
    split, seed, shift, oracle = job
    settings = Settings.from_env({})
    config = load_config()
    generated = generate(config, seed)
    hidden = HiddenModel(generated, settings.params_path, oracle=oracle)
    cases, excluded = decision_cases(
        generated,
        hidden_total(hidden, config.scenario_date),
        load_rulebook(settings.rules_path),
        load_params(settings.params_path),
        load_strength(settings.strength_path),
        split,
        config.scenario_date,
        shift,
    )
    return generated.seed, shift, agreement(cases, excluded), agreement(c for c in cases if c.meets > 1)


def _ratio(value: float | None) -> str:
    return "-" if value is None else f"{value:.2%}"


def report(label: str, r: DecisionAgreement, multi: DecisionAgreement) -> None:
    same = "-" if r.same is None else f"{r.same:.1%}"
    ratio = _ratio(r.regret_ratio)
    zero = "-" if r.zero_regret is None else f"{r.zero_regret:.1%}"
    mean = "-" if r.mean_regret is None else f"{r.mean_regret:,.0f}원"
    print(f"E7 결정 일치 · {label} · 사례 {r.cases}건(제외 {r.excluded}건)")
    print(
        f"  같은 조합 {same}(기준 ≥ {SAME_MIN:.0%}) · 평균 후회 / 평균 실제 최선 {ratio}(기준 ≤ {REGRET_MAX:.0%})"
        f" · 평균 후회 {mean}"
    )
    print(
        f"  참고: 후회 0 {zero} · 충족 대안 2개 이상 {r.with_alternatives}건 · 엔진 권고에 보류 {r.engine_held}건 · "
        f"실제 최선에 보류 {r.best_held}건 · 엔진이 확정 가능일보다 늦게 확정 {r.engine_later}건 · "
        f"판단 불가 {r.uncertain}건"
    )
    multi_same = "-" if multi.same is None else f"{multi.same:.1%}"
    print(
        f"  참고: 충족 대안 2개 이상 {multi.cases}건만 — 같은 조합 {multi_same} · "
        f"평균 후회 / 평균 실제 최선 {_ratio(multi.regret_ratio)}"
    )
    print("  합격" if r.passed else "  미달")


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    add_split_args(parser)
    parser.add_argument("--oracle", action="store_true", help="진단: 숨긴 모델을 확인 모드로(기준 판정 아님)")
    args = parser.parse_args()
    run = split_run(args, dev_only=args.oracle, refused="다른 시드·확인 모드는 개발 분할로만 재요.")
    if run is None:
        return 2
    jobs: list[Job] = [(run.split, seed, shift, args.oracle) for seed in run.seeds for shift in CONFIRM_SHIFTS]
    with ProcessPoolExecutor(max_workers=max(1, min(len(jobs), (os.cpu_count() or 2) - 1))) as pool:
        results = list(pool.map(measure, jobs))
    mode = " · 확인 모드(진단)" if args.oracle else ""
    for seed, shift, result, multi in results:
        report(f"{run.name} 분할 · 시드 {seed} · 확정 가능일 기준일 + {shift}일{mode}", result, multi)
    passed = sum(result.passed for _, _, result, _ in results)
    print(f"합격 {passed}/{len(results)}(조건·시드마다)")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
