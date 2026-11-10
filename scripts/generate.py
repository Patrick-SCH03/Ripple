"""합성 데이터를 만든다.

실행: uv run python scripts/generate.py [--seed 20261020] [--out data/synthetic] [--map base|demo]
결과: <out>/<시드>/snapshot.json · ecn_dev.jsonl · ecn_eval.jsonl · CSV
--map demo: 시연 합성 지도(generator/demo_map.yaml, 기본 출력 data/synthetic_demo) — RIPPLE_SYNTHETIC_MAP=demo가 읽는다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ripple.generator.build import generate
from ripple.generator.io import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_OUTPUT_ROOT,
    DEMO_CONFIG_PATH,
    DEMO_OUTPUT_ROOT,
    load_config,
    write_outputs,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ripple 합성 데이터 생성")
    parser.add_argument("--seed", type=int, default=None, help="시드(기본: 설정 파일의 seed)")
    parser.add_argument("--out", type=Path, default=None, help="출력 폴더의 상위 폴더")
    parser.add_argument("--map", choices=("base", "demo"), default="base", help="기본 합성 지도 · 시연 합성 지도")
    args = parser.parse_args(argv)

    demo = args.map == "demo"
    config = load_config(DEMO_CONFIG_PATH if demo else DEFAULT_CONFIG_PATH)
    root = args.out or (DEMO_OUTPUT_ROOT if demo else DEFAULT_OUTPUT_ROOT)
    generated = generate(config, args.seed)
    out_dir = root / str(generated.seed)
    paths = write_outputs(generated, out_dir)
    snapshot = generated.snapshot
    print(f"스냅샷 {snapshot.snapshot_id} (시드 {generated.seed}, 설정 {generated.config_version})")
    print(
        f"블록 {len(snapshot.blocks)} · 부재 {len(snapshot.parts)} · 연결 {len(snapshot.connections)} · "
        f"발주 {len(snapshot.purchase_orders)} · 발주 품목 {len(snapshot.po_lines)} · "
        f"공정 {len(snapshot.activities)} · "
        f"재고 {len(snapshot.stock)} · 설계변경 {len(generated.ecns)}"
    )
    print(f"썼어요: {', '.join(p.name for p in paths)} → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
