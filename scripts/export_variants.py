"""합성 지도를 회사마다 다른 모양의 엑셀(관문 변형 3종 V1~V3)로 쓴다(docs/input.md(엑셀 양식) 4절).
시연·열 확인 화면 점검용.

V1 머리글 동의어·한영·약어·열 섞기·덧붙인 열, V2 두 줄 머리글·단위 혼재·제목·메모 행, V3 날짜·코드 표기·시트 이름·다른
시트. 파일마다 정답 매핑(<이름>.truth.json, 계약 ConfirmedMapping)을 함께 쓴다. 합성 데이터라 실제 회사 양식이 아니다.

실행: uv run python scripts/export_variants.py <출력 폴더>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.ingest.variants import gate_variants


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="합성 지도 → 흔한 변형 엑셀 3종(정답 매핑 포함)")
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    snapshot = generate(load_config()).snapshot
    args.output.mkdir(parents=True, exist_ok=True)
    for variant in gate_variants(snapshot):
        path = args.output / f"ripple-variant-{variant.name}.xlsx"
        path.write_bytes(variant.data)
        truth = args.output / f"ripple-variant-{variant.name}.truth.json"
        truth.write_text(variant.truth.model_dump_json(indent=1), encoding="utf-8")
        print(f"{variant.name} → {path} (시트 {len(variant.truth.sheets)}개, 정답 {truth.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
