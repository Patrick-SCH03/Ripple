"""E2' 일정 정확도 도구의 성질(ripple/eval/schedule_accuracy.py): 손으로 센 지표 · 경계 · 기준 판정 ·
결정성 · 확인 모드 왕복.

전체 개발 분할 측정은 `scripts/eval_schedule.py`(시간이 걸려 여기서는 앞쪽 사례만 쓴다).
"""

from __future__ import annotations

from harness import Checker

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.dataset import EcnSplit
from ripple.eval.schedule_accuracy import (
    DelayAccuracy,
    DelayPair,
    ScheduleAccuracy,
    accuracy,
    delay_accuracy,
    delay_pairs,
    risk_reference,
)
from ripple.generator.actuals import HiddenModel
from ripple.generator.build import generate
from ripple.generator.io import load_config


def _pair(exit_estimate: int, exit_actual: int, delivery: tuple[int | None, int | None] = (0, 0)) -> DelayPair:
    return DelayPair("E", exit_estimate, exit_actual, delivery[0], delivery[1], uncertain=False)


def _delay(mae: float | None, large: float | None, false_alarm: float | None, miss: float | None) -> DelayAccuracy:
    """기준 판정만 보려고 지표를 직접 넣은 비교 값."""
    return DelayAccuracy(cases=1, delayed=1, mae=mae, large_share=large, false_alarm=false_alarm, miss=miss)


def _summary(exit: DelayAccuracy, delivery: DelayAccuracy, cases: int = 1) -> ScheduleAccuracy:
    return ScheduleAccuracy(cases=cases, excluded=0, uncertain=0, exit=exit, delivery=delivery)


def run(c: Checker) -> None:
    c.section("E2' 일정 정확도 도구(손으로 센 지표·경계·기준·결정성·확인 모드 왕복)")
    # (엔진, 실제): 맞음 0·0 · 오경보 2·0 · 누락 0·3 · 크게 틀림 1·9(오차 8) · 맞힌 지연 4·4 → 오차 0·2·3·8·0
    d = delay_accuracy([(0, 0), (2, 0), (0, 3), (1, 9), (4, 4)])
    c.check(
        "평균 절대 오차 13/5 = 2.6일 · 7일 이상 1/5 · 오경보 1/2(실제 0인 사례 중) · 누락 1/3(실제 지연 중)",
        d.cases == 5
        and d.delayed == 3
        and abs((d.mae or 0) - 2.6) < 1e-12
        and d.large_share == 0.2
        and d.false_alarm == 0.5
        and abs((d.miss or 0) - 1 / 3) < 1e-12
        and not d.passed,
        d,
    )
    edge = delay_accuracy([(0, 7), (0, 6)])
    empty = delay_accuracy([])
    late_only = delay_accuracy([(3, 3)])
    c.check(
        "경계: 오차 7일은 '7일 이상', 6일은 아님 · 분모가 0이면 그 지표는 없음(실제 지연 없음 → 누락률 없음)",
        edge.large_share == 0.5
        and delay_accuracy([(0, 0)]).miss is None
        and late_only.false_alarm is None
        and late_only.miss == 0
        and empty.mae is None
        and empty.cases == 0,
        (edge, late_only),
    )
    # (실제, 위험): 지연 3·위험 5 · 지연 2·위험 0 · 0·위험 4 · 0·0 · 위험 없음(옛 결과) → 위험 있는 4건만
    risky = [
        DelayPair("A", 0, 3, 0, 0, uncertain=False, exit_risk=5),
        DelayPair("B", 0, 2, 0, 0, uncertain=False, exit_risk=0),
        DelayPair("C", 0, 0, 0, 0, uncertain=False, exit_risk=4),
        DelayPair("D", 0, 0, 0, 0, uncertain=False, exit_risk=0),
        DelayPair("E", 0, 1, 0, 0, uncertain=False),
    ]
    ref = risk_reference(risky)
    c.check(
        "일정 위험 참고(판정과 무관): 위험 있는 4건 · 실제 지연 2건 중 위험 > 0 1건 · 실제 0인 2건 중 위험 > 0 1건 ·"
        " 실제 ≤ 위험 3건(지연 2·위험 0만 못 덮음)",
        (ref.cases, ref.delayed, ref.delayed_flagged, ref.on_time, ref.on_time_flagged, ref.covered)
        == (4, 2, 1, 2, 1, 3),
        ref,
    )
    paired = accuracy([_pair(0, 0, (None, 2)), _pair(0, 0, (1, None)), _pair(0, 0, (3, 3)), _pair(1, 1)])
    c.check(
        "인도 지연은 엔진·숨긴 모델 둘 다 계산한 사례만 비교(4건 중 2건), 출구 지연은 모두",
        paired.exit.cases == 4 and paired.delivery.cases == 2 and paired.delivery.mae == 0,
        paired,
    )
    ok = _delay(2.0, 0.05, 0.10, 0.10)
    c.check(
        "기준 경계: 오차 2일·7일 이상 5%·오경보 10%·누락 10%는 충족, 바로 바깥은 미달, 두 값 모두 충족해야 합격",
        ok.passed
        and _delay(None, None, None, None).passed
        and not _delay(2.0000001, 0.05, 0.10, 0.10).passed
        and not _delay(2.0, 0.0500001, 0.10, 0.10).passed
        and not _delay(2.0, 0.05, 0.1000001, 0.10).passed
        and not _delay(2.0, 0.05, 0.10, 0.1000001).passed
        and _summary(ok, ok).passed
        and not _summary(ok, _delay(0, 0, 0, 0.5)).passed
        and not _summary(_delay(3.0, 0, 0, 0), ok).passed
        and not _summary(ok, ok, cases=0).passed,
    )
    config = load_config()
    generated = generate(config)
    settings = Settings.from_env({})
    params_path = PROJECT_ROOT / "params" / "cost_v1.yaml"
    rulebook, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
    hidden = HiddenModel(generated, params_path)
    first = delay_pairs(generated, hidden, rulebook, params, EcnSplit.DEV, config.scenario_date, limit=12)
    second = delay_pairs(generated, hidden, rulebook, params, EcnSplit.DEV, config.scenario_date, limit=12)
    c.check(
        "개발 분할 앞 12건: 두 번 재도 같은 사례·일수(고정 시드), 제외 + 사례 = 12, ECN 번호 순",
        first == second
        and len(first[0]) + first[1] == 12
        and [p.ecn_id for p in first[0]] == sorted(p.ecn_id for p in first[0]),
    )
    oracle = HiddenModel(generated, params_path, oracle=True)
    checked, _ = delay_pairs(generated, oracle, rulebook, params, EcnSplit.DEV, config.scenario_date)
    known = [p for p in checked if not p.uncertain]
    c.check(
        "확인 모드(대표값·잡음 0)와는 판단 불가 없는 개발 사례의 출구·인도 지연이 모두 같음(지연 있는 사례 포함)",
        len(known) >= 190
        and any(p.exit_actual > 0 for p in known)
        and all(p.exit_estimate == p.exit_actual and p.delivery_estimate == p.delivery_actual for p in known),
        [p for p in known if p.exit_estimate != p.exit_actual or p.delivery_estimate != p.delivery_actual],
    )
