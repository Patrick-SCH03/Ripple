"""성질 검사 — 서버·API 키 없이 돈다. 실행: uv run python tests/check_all.py [묶음 이름 ...]

원칙: 수치가 아니라 성질을 본다. "A면 B가 유지된다" 같은 문장을 검사로 쓴다.
검사 묶음은 tests/checks/에 주제별로 있고, 각 묶음은 run(checker)를 가진다.
묶음 이름(예: cost schedule)을 주면 그 묶음만 돈다 — 고치는 동안 빨리 보는 용도이고, push 전에는 전체를 돌린다.
--shard k/n은 전체를 n갈래로 나눈 k번째만 돈다(여러 갈래를 동시에 띄워 시간을 줄인다).
"""

from __future__ import annotations

import io
import sys

from checks import (
    actuals,
    agent,
    alternatives,
    analysis,
    api,
    assistant,
    auth,
    auth_api,
    backtest,
    brief,
    cases,
    catalog,
    columns,
    contracts,
    cost,
    cost_accuracy,
    cost_detail,
    cost_split,
    decide,
    decision_agreement,
    delay,
    demo_daily,
    demo_map,
    demo_seed,
    ecn_trace,
    eval_report,
    evaluation,
    explain,
    exports,
    files,
    gate_tool,
    generator,
    generator_v3,
    graph,
    identity,
    import_memory,
    ingest,
    intake,
    labels,
    layers,
    live_world,
    llm,
    mail,
    manage,
    mapping_memory,
    ncr,
    nl,
    nl_eval,
    nl_generator,
    onboard,
    precheck,
    propagate,
    records,
    records_compat,
    rework,
    schedule,
    schedule_accuracy,
    schedule_p1,
    schedule_risk,
    showcase,
    state,
    state_basis,
    status_import,
    structure,
    translate,
    transport,
    updates,
    updates_api,
    weight,
    workspace,
)
from harness import Checker

SUITES = (
    contracts.run,
    assistant.run,
    identity.run,
    catalog.run,
    labels.run,
    layers.run,
    structure.run,
    api.run,
    workspace.run,
    live_world.run,
    decide.run,
    nl.run,
    nl_eval.run,
    generator.run,
    generator_v3.run,
    demo_map.run,
    nl_generator.run,
    explain.run,
    mail.run,
    translate.run,
    ingest.run,
    mapping_memory.run,
    import_memory.run,
    columns.run,
    agent.run,
    intake.run,
    llm.run,
    graph.run,
    state.run,
    state_basis.run,
    updates.run,
    updates_api.run,
    status_import.run,
    schedule.run,
    propagate.run,
    cost.run,
    cost_detail.run,
    rework.run,
    delay.run,
    weight.run,
    cost_split.run,
    analysis.run,
    ecn_trace.run,
    evaluation.run,
    eval_report.run,
    gate_tool.run,
    cost_accuracy.run,
    schedule_accuracy.run,
    schedule_risk.run,
    schedule_p1.run,
    transport.run,
    onboard.run,
    precheck.run,
    actuals.run,
    alternatives.run,
    decision_agreement.run,
    backtest.run,
    showcase.run,
    auth.run,
    auth_api.run,
    records.run,
    records_compat.run,
    manage.run,
    exports.run,
    files.run,
    brief.run,
    cases.run,
    ncr.run,
    demo_seed.run,
    demo_daily.run,
)


# 묶음별 대략 걸리는 초(2026-10-29 실측) — --shard로 나눌 때 균형만 맞춘다. 틀려도 검사 결과는 같고 없으면 5초로 본다
SECONDS = {
    "analysis": 126, "demo_daily": 78, "auth_api": 77, "alternatives": 64, "records": 63, "demo_seed": 62,
    "workspace": 57, "ingest": 57, "cost": 40, "schedule_p1": 39, "rework": 36, "brief": 35,
    "schedule_accuracy": 29, "schedule_risk": 28, "delay": 27, "live_world": 20, "llm": 20, "precheck": 18,
    "api": 16, "updates_api": 16, "onboard": 16, "cases": 14, "columns": 12, "manage": 11, "exports": 11,
}  # fmt: skip


def suite_name(run: object) -> str:
    return str(getattr(run, "__module__", "")).rsplit(".", 1)[-1]


def shard(names: list[str], spec: str) -> list[str]:
    """'k/n' — 묶음을 n갈래로 시간 균형 있게 나눈 것 중 k번째(1부터). 로컬 CI가 갈래마다 따로 띄워 동시에 돌린다."""
    k, n = (int(part) for part in spec.split("/"))
    loads = [0] * n
    picked: list[list[str]] = [[] for _ in range(n)]
    for name in sorted(names, key=lambda s: -SECONDS.get(s, 5)):
        lane = loads.index(min(loads))
        loads[lane] += SECONDS.get(name, 5)
        picked[lane].append(name)
    return picked[k - 1]


def main(args: list[str]) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    if args[:1] == ["--shard"]:
        picked = shard([suite_name(run) for run in SUITES], args[1])
        return main(picked) if picked else 0  # 빈 갈래가 전체를 돌지 않게
    names = args
    known = {suite_name(run) for run in SUITES}
    unknown = sorted(set(names) - known)
    if unknown:
        print(f"없는 묶음: {', '.join(unknown)} (있는 묶음: {', '.join(sorted(known))})")
        return 2
    checker = Checker()
    for run in SUITES:
        if not names or suite_name(run) in names:
            run(checker)
    print(f"\n{checker.passed} passed, {checker.failed} failed")
    return 1 if checker.failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
