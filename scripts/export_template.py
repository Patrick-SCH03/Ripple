"""지금 합성 지도를 Ripple 지정 양식 엑셀로 쓴다(docs/input.md(엑셀 양식)). 시연·사용자 안내용 예시 파일.

실행: uv run python scripts/export_template.py <출력.xlsx>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.ingest.export import to_workbook


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="합성 지도 → Ripple 지정 양식 엑셀")
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    snapshot = generate(load_config()).snapshot
    args.output.parent.mkdir(parents=True, exist_ok=True)
    to_workbook(snapshot).save(args.output)
    print(f"지정 양식 → {args.output} (지도 {snapshot.snapshot_id}, 부재 {len(snapshot.parts)}개)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
