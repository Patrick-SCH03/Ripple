"""규모 진단(E5): 기본 지도(14블록)와 실선 규모로 늘린 지도(150블록)에서 같은 방식으로 분석 시간을 잰다.

  uv run python scripts/eval_scale.py [결과 폴더]      기본 결과 폴더는 eval/reports

늘린 지도는 기본 생성기 설정에 화물탱크 구역 8개(구역마다 블록 17개·배관 계통 2개)를 메모리에서만
더한 것이다(파일은 바꾸지 않음). 데모 기준 블록(T31C·P11C)과 구역은 그대로다. 지도마다 평가 분할
설계변경 100건을 순서대로 한 번씩 분석한다(대안 끔, 추가손실 곡선 61일, 한 프로세스·한 스레드,
첫 호출 포함). 기계 사양은 결과에 적는다.

진단이라 종료 코드는 늘 0이다. 결과 JSON: <결과 폴더>/scale_timing.json
"""

from __future__ import annotations

import json
import platform
import statistics
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.dataset import EcnSplit
from ripple.contracts.params import ParamSet
from ripple.contracts.rulebook import RuleBook
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import impact_report
from ripple.generator.build import generate
from ripple.generator.config import BlockConfig, GeneratorConfig, PipeSystemConfig, ZoneConfig
from ripple.generator.io import load_config

SAMPLE = 100
TANKS = (1, 2, 4, 5, 6, 7, 8, 9)  # No.3은 기본 지도의 화물탱크 구역
# (코드 틀, 이름 틀, 중량 t, 탱크 안 탑재 순서 일수)
TEMPLATES: tuple[tuple[str, str, float, int], ...] = (
    ("B{n}1P", "No.{n} COT 이중저 좌", 450, 0),
    ("B{n}1S", "No.{n} COT 이중저 우", 450, 2),
    ("B{n}2P", "No.{n} COT 이중저 후 좌", 420, 4),
    ("B{n}2S", "No.{n} COT 이중저 후 우", 420, 6),
    ("T{n}1C", "No.{n} COT 횡격벽", 280, 10),
    ("L{n}1C", "No.{n} 중심선 종격벽", 300, 15),
    ("L{n}2C", "No.{n} 중심선 종격벽 후", 290, 17),
    ("S{n}1P", "No.{n} COT 선측 좌", 350, 25),
    ("S{n}1S", "No.{n} COT 선측 우", 350, 27),
    ("S{n}2P", "No.{n} COT 선측 후 좌", 340, 29),
    ("S{n}2S", "No.{n} COT 선측 후 우", 340, 31),
    ("W{n}1P", "No.{n} 웹 프레임 좌", 220, 33),
    ("W{n}1S", "No.{n} 웹 프레임 우", 220, 35),
    ("D{n}1C", "No.{n} COT 갑판", 330, 45),
    ("D{n}2C", "No.{n} COT 갑판 후", 320, 47),
    ("U{n}1C", "No.{n} 상부 스툴", 200, 50),
    ("U{n}2C", "No.{n} 상부 스툴 후", 200, 52),
)
ADJACENCY = (  # 탱크 안 이웃 블록(틀 쌍). 탱크 사이는 T{n}1C — 앞 탱크 B1P
    ("B{n}1P", "B{n}1S"),
    ("B{n}1P", "S{n}1P"),
    ("B{n}1S", "S{n}1S"),
    ("S{n}1P", "D{n}1C"),
    ("S{n}1S", "D{n}1C"),
    ("L{n}1C", "B{n}1P"),
    ("L{n}1C", "D{n}1C"),
    ("T{n}1C", "B{n}1P"),
    ("T{n}1C", "L{n}1C"),
    ("B{n}2P", "B{n}1P"),
    ("B{n}2S", "B{n}1S"),
    ("B{n}2P", "B{n}2S"),
    ("S{n}2P", "S{n}1P"),
    ("S{n}2S", "S{n}1S"),
    ("S{n}2P", "D{n}2C"),
    ("S{n}2S", "D{n}2C"),
    ("D{n}2C", "D{n}1C"),
    ("L{n}2C", "L{n}1C"),
    ("L{n}2C", "D{n}2C"),
    ("W{n}1P", "S{n}1P"),
    ("W{n}1S", "S{n}1S"),
    ("U{n}1C", "D{n}1C"),
    ("U{n}2C", "D{n}2C"),
)


def scaled(base: GeneratorConfig) -> GeneratorConfig:
    """기본 설정 + 화물탱크 구역 8개. 구역 출구 뒤 150일이라 출구→인도 여유가 음수가 되지 않는다."""
    zones, blocks, adjacency = list(base.zones), list(base.blocks), list(base.adjacency)
    systems = list(base.piping.systems)
    previous: str | None = None
    for k, n in enumerate(TANKS):
        zone = f"ZC{n}"
        zones.append(ZoneConfig(code=zone, name=f"No.{n} 화물탱크 구역", post_exit_days=150, forecast_delay_days=0))
        for code, name, weight, offset in TEMPLATES:
            blocks.append(
                BlockConfig(
                    code=code.format(n=n),
                    zone=zone,
                    name=name.format(n=n),
                    weight_t=weight,
                    pe_offset=15 + 25 * k + offset,
                )
            )
        adjacency.extend((a.format(n=n), b.format(n=n)) for a, b in ADJACENCY)
        if previous is not None:
            adjacency.append((f"T{n}1C", previous))
        previous = f"B{n}1P"
        systems.append(PipeSystemConfig(code=f"CO{n}", name=f"cargo_oil_{n}", label=f"No.{n} 화물유", block=f"B{n}1P"))
        systems.append(
            PipeSystemConfig(code=f"WB{n}", name=f"water_ballast_{n}", label=f"No.{n} 평형수", block=f"S{n}1P")
        )
    piping = base.piping.model_copy(update={"systems": tuple(systems)})
    return base.model_copy(
        update={"zones": tuple(zones), "blocks": tuple(blocks), "adjacency": tuple(adjacency), "piping": piping}
    )


def summary(ms: list[float]) -> dict[str, float]:
    ordered = sorted(ms)
    k = (len(ordered) - 1) * 0.95
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return {
        "n": len(ms),
        "mean_ms": round(statistics.fmean(ms), 1),
        "median_ms": round(statistics.median(ms), 1),
        "p95_ms": round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 1),
        "max_ms": round(max(ms), 1),
        "over_1s": sum(1 for v in ms if v > 1000.0),
    }


def run(label: str, config: GeneratorConfig, rulebook: RuleBook, params: ParamSet) -> dict[str, Any]:
    started = time.perf_counter()
    generated = generate(config)
    generate_s = time.perf_counter() - started
    snapshot = generated.snapshot
    index = GraphIndex(snapshot)
    analyze_ms: list[float] = []
    propagate_ms: list[float] = []
    by_op: dict[str, list[float]] = {}
    for ecn in [e for e in generated.ecns if e.split is EcnSplit.EVAL][:SAMPLE]:
        request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of)
        started = time.perf_counter()
        analyze(index, request, rulebook, params)
        analyze_ms.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        impact_report(index, request, rulebook, params.version)
        propagate_ms.append((time.perf_counter() - started) * 1000)
        by_op.setdefault(ecn.change.ops[0].op, []).append(analyze_ms[-1])
    return {
        "label": label,
        "snapshot_id": snapshot.snapshot_id,
        "counts": {
            "zones": len(snapshot.zones),
            "blocks": len(snapshot.blocks),
            "parts": len(snapshot.parts),
            "connections": len(snapshot.connections),
            "purchase_orders": len(snapshot.purchase_orders),
            "po_lines": len(snapshot.po_lines),
            "activities": len(snapshot.activities),
            "drawings": len(snapshot.drawings),
        },
        "generate_s": round(generate_s, 2),
        "analyze": summary(analyze_ms),
        "propagate_only": summary(propagate_ms),
        "analyze_mean_ms_by_op": {op: round(statistics.fmean(v), 1) for op, v in sorted(by_op.items())},
    }


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "eval" / "reports"
    rulebook = load_rulebook(PROJECT_ROOT / "rules" / "propagation.yaml")
    params = load_params(PROJECT_ROOT / "params" / "cost_v1.yaml")
    base = load_config()
    runs = [run("기본 지도", base, rulebook, params), run("150블록으로 늘린 지도", scaled(base), rulebook, params)]
    machine = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor(),
        "measured_on": date.today().isoformat(),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "scale_timing.json"
    target.write_text(
        json.dumps({"machine": machine, "runs": runs}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for r in runs:
        print(f"{r['label']} {r['snapshot_id']} {r['counts']}")
        print(f"  분석 {r['analyze']}\n  전파만 {r['propagate_only']}")
    print(f"썼어요: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
