"""숨긴 모델 요인 분리 진단(E2a·E2'): 요인을 하나씩 확인 모드 값으로 고정하거나 하나만 켜고 개발 분할 지표를 다시 잰다.

  uv run python scripts/eval_factors.py                       기본 시드, 요인별 E2a·E2'
  uv run python scripts/eval_factors.py --seeds 1,2,3,4,5     다른 시드(합성 세계 전체를 다시 만듦)
  uv run python scripts/eval_factors.py --lead 1.0,1.1,1.2    리드타임 배율 대리 계산(아래)

요인은 `ripple/generator/actuals/`의 FACTORS(참 파라미터 · 항목 잡음 · 미반영 비용 · 착수 하한 · 실제 발주일 ·
리드타임 변동)다. '뺌' = 그 요인만 확인 모드 값으로, '만 켬' = 그 요인만 평가와 같이(나머지는 확인 모드 값).

`--lead`: 확인 모드(엔진과 구역 출구 지연 194/194 일치)에 새 규격 리드타임 배율만 고정값으로 넣은 일정을 '추정',
평가와 같은 숨긴 모델을 '실제'로 둔 E2' 구역 출구 지표 — 일정 위험 표시를 고를 때 참고하는 대리 계산이다.
숨긴 모델의 리드타임 변동은 판만 실제 입고 지연 분포(actuals-v2)이고 그 밖은 우리가 정한 0.9~1.2라 방향만 본다.

기준 판정이 아니라 원인 분리용 진단이라 종료 코드는 늘 0이다. 평가 분할은 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ripple.config.loaders import load_params, load_rulebook, load_strength
from ripple.config.settings import Settings
from ripple.contracts.change import ChangeRequest
from ripple.contracts.dataset import EcnSplit
from ripple.eval.cost_accuracy import CostAccuracy, cost_pairs
from ripple.eval.cost_accuracy import accuracy as cost_accuracy
from ripple.eval.schedule_accuracy import DelayAccuracy, ScheduleAccuracy, delay_accuracy, delay_pairs
from ripple.eval.schedule_accuracy import accuracy as schedule_accuracy
from ripple.generator.actuals import FACTORS, Factor, HiddenModel
from ripple.generator.build import Generated, generate
from ripple.generator.io import load_config

NAMES: dict[Factor, str] = {
    "params": "참 파라미터",
    "noise": "항목 잡음",
    "unmodeled": "미반영 비용",
    "start_floor": "착수 하한",
    "order_date": "실제 발주일",
    "lead_time": "리드타임 변동",
}

FactorJob = tuple[int | None, str, frozenset[Factor]]  # (시드, 설정 이름, 고정할 요인)
LeadJob = tuple[int | None, float]  # (시드, 고정 배율)


def setups() -> list[tuple[str, frozenset[Factor]]]:
    """모두 켬 → 요인마다 뺌 → 요인마다 만 켬 → 모두 뺌(확인 모드)."""
    rows: list[tuple[str, frozenset[Factor]]] = [("모두 켬(평가와 같음)", frozenset())]
    rows += [(f"{NAMES[f]} 뺌", frozenset({f})) for f in FACTORS]
    rows += [(f"{NAMES[f]}만 켬", frozenset(FACTORS) - {f}) for f in FACTORS]
    rows.append(("모두 뺌(확인 모드)", frozenset(FACTORS)))
    return rows


def measure(job: FactorJob) -> tuple[int, str, CostAccuracy, ScheduleAccuracy]:
    seed, label, fixed = job
    settings = Settings.from_env({})
    config = load_config()
    generated = generate(config, seed)
    hidden = HiddenModel(generated, settings.params_path, fixed=fixed)
    rulebook, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    strength = load_strength(settings.strength_path)
    costs, cost_excluded = cost_pairs(generated, hidden, rulebook, params, strength, EcnSplit.DEV, config.scenario_date)
    delays, delay_excluded = delay_pairs(generated, hidden, rulebook, params, EcnSplit.DEV, config.scenario_date)
    return generated.seed, label, cost_accuracy(costs, cost_excluded), schedule_accuracy(delays, delay_excluded)


class FixedLead(HiddenModel):
    """대리 계산용: 확인 모드에 새 규격 리드타임 배율만 고정값으로."""

    def __init__(self, generated: Generated, params_path: Path, lead: float) -> None:
        super().__init__(generated, params_path, fixed=set(FACTORS) - {"lead_time"})
        self.lead = lead

    def _lead_days(self, change: ChangeRequest, spec_id: str, category: str, lead: int) -> int:
        return round(lead * self.lead)


def lead_proxy(job: LeadJob) -> tuple[int, float, DelayAccuracy, int]:
    """(시드, 배율, 추정 vs 실제 구역 출구 최대 지연, 추정이 지연을 낸 사례 수)."""
    seed, lead = job
    settings = Settings.from_env({})
    config = load_config()
    generated = generate(config, seed)
    actual = HiddenModel(generated, settings.params_path)
    estimate = FixedLead(generated, settings.params_path, lead)
    as_of = config.scenario_date
    dev = sorted((e for e in generated.ecns if e.split is EcnSplit.DEV), key=lambda e: e.change.ecn_id)
    pairs = [
        (
            estimate.outcome(e.change, as_of, as_of).max_exit_delay_days,
            actual.outcome(e.change, as_of, as_of).max_exit_delay_days,
        )
        for e in dev
    ]
    return generated.seed, lead, delay_accuracy(pairs), sum(est > 0 for est, _ in pairs)


def _pct(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value:.{digits}%}"


def _delay(d: DelayAccuracy) -> str:
    mae = "-" if d.mae is None else f"{d.mae:.2f}일"
    return (
        f"실제 지연 {d.delayed}건 · 누락 {_pct(d.miss)} · 오경보 {_pct(d.false_alarm)} · 평균 오차 {mae} · "
        f"7일 이상 {_pct(d.large_share)}"
    )


def _cost(c: CostAccuracy) -> str:
    bias = "-" if c.bias_median is None else f"{c.bias_median:+.1%}"
    return (
        f"중앙값 {_pct(c.ape_median)} · 90백분위 {_pct(c.ape_p90)} · 50만원 이내 {_pct(c.small_within)} · "
        f"부호 중앙값 {bias} → {'합격' if c.passed else '미달'}"
    )


def _pool(jobs: int) -> ProcessPoolExecutor:
    return ProcessPoolExecutor(max_workers=max(1, min(jobs, (os.cpu_count() or 2) - 1)))


def run_factors(seeds: Iterable[int | None]) -> None:
    jobs: list[FactorJob] = [(seed, label, fixed) for seed in seeds for label, fixed in setups()]
    with _pool(len(jobs)) as pool:
        results = list(pool.map(measure, jobs))
    current = None
    for seed, label, cost, schedule in results:
        if seed != current:
            current = seed
            print(f"요인 분리 · 시드 {seed} · 개발 분할(E2a 사례 {cost.cases}건 · E2' 사례 {schedule.cases}건)")
        print(f"  {label}")
        print(f"    E2a {_cost(cost)}")
        print(f"    E2' 구역 출구 {_delay(schedule.exit)} → {'합격' if schedule.passed else '미달'}")


def run_lead(seeds: Iterable[int | None], leads: list[float]) -> None:
    jobs: list[LeadJob] = [(seed, lead) for seed in seeds for lead in leads]
    with _pool(len(jobs)) as pool:
        results = list(pool.map(lead_proxy, jobs))
    print("리드타임 배율 대리 계산(추정 = 확인 모드 + 고정 배율, 실제 = 평가와 같은 숨긴 모델, 개발 분할)")
    for seed, lead, d, flagged in results:
        print(f"  시드 {seed} · 배율 {lead:g}: {_delay(d)} · 추정이 지연을 낸 사례 {flagged}건")


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", default="", help="쉼표로 나눈 시드(합성 세계 전체를 다시 만든 개발 분할)")
    parser.add_argument("--lead", default="", help="쉼표로 나눈 리드타임 배율: 대리 계산만 잰다")
    args = parser.parse_args()
    seeds: list[int | None] = [int(s) for s in args.seeds.split(",") if s.strip()] or [None]
    leads = [float(s) for s in args.lead.split(",") if s.strip()]
    if leads:
        run_lead(seeds, leads)
    else:
        run_factors(seeds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
