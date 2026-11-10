"""생성기 설정 읽기와 결과 쓰기(파일 I/O는 여기서만)."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from operator import attrgetter
from pathlib import Path
from typing import Any

from ripple.config.loaders import read_yaml
from ripple.config.settings import DEMO_GENERATOR_CONFIG, GENERATOR_CONFIG, PROJECT_ROOT
from ripple.contracts.domain import GraphSnapshot

from .build import Generated
from .config import GeneratorConfig

DEFAULT_CONFIG_PATH = GENERATOR_CONFIG
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "synthetic"
DEMO_CONFIG_PATH = DEMO_GENERATOR_CONFIG  # 시연 합성 지도(기본 설정 + 블록 사이 관계 보강)
DEMO_OUTPUT_ROOT = PROJECT_ROOT / "data" / "synthetic_demo"


Cell = Callable[[Any], object]
"""항목 하나 → 열 값."""
KIND: Mapping[str, Cell] = {"kind": lambda item: item.kind.value}
"""종류 열은 열거형의 값."""


@dataclass(frozen=True, slots=True)
class CsvTable:
    """CSV 파일 하나: 지도의 목록 하나를 행으로, 열마다 같은 이름의 필드(computed에 있으면 그 값)."""

    name: str
    items: Callable[[GraphSnapshot], Iterable[Any]]
    columns: tuple[str, ...]
    computed: Mapping[str, Cell] = field(default_factory=dict)
    """이 표에서 필드를 그대로 쓰지 않는 열 → 값."""

    def rows(self, snapshot: GraphSnapshot) -> Iterable[tuple[object, ...]]:
        cells = [self.computed.get(column, attrgetter(column)) for column in self.columns]
        return (tuple(cell(item) for cell in cells) for item in self.items(snapshot))


CSV_TABLES = (
    CsvTable(
        "parts.csv",
        lambda s: s.parts,
        ("part_id", "block_id", "kind", "name", "spec_id", "qty", "thickness_mm", "grade", "system", "drawing_no"),
        KIND,
    ),
    CsvTable("connections.csv", lambda s: s.connections, ("a", "b", "kind", "length_m"), KIND),
    CsvTable(
        "purchase_orders.csv",
        lambda s: s.purchase_orders,
        (
            "po_id",
            "supplier_id",
            "planned_order_date",
            "material_secured_days",
            "fabrication_start_days",
            "lead_time_days",
            "entered_on",
            "observations",
        ),
        {  # 단계 진입일·관측은 JSON
            "entered_on": lambda po: json.dumps(
                {k.value: v.isoformat() for k, v in po.entered_on.items()}, ensure_ascii=False
            ),
            "observations": lambda po: json.dumps(
                [[o.status.value, o.observed_on.isoformat()] for o in po.observations]
            ),
        },
    ),
    CsvTable(
        "po_lines.csv",
        lambda s: s.po_lines,
        ("po_id", "line_no", "spec_id", "qty", "unit_price_krw", "consumed_by_activity_id", "part_count"),
        {"part_count": lambda line: len(line.part_ids)},
    ),
    CsvTable(
        "activities.csv",
        lambda s: s.activities,
        ("activity_id", "block_id", "kind", "planned_start", "duration_days", "actual_start", "actual_finish"),
        KIND,
    ),
)
"""write_outputs가 쓰는 CSV(이 순서로)."""


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> GeneratorConfig:
    """설정 파일. 최상위에 extends(같은 폴더의 파일 이름)가 있으면 그 파일을 읽고 이 파일의 최상위 키로 덮어쓴다
    (시연 합성 지도 generator/demo_map.yaml = 기본 설정 + relations)."""
    return GeneratorConfig.model_validate(_read_config(path, ()))


def _read_config(path: Path, chain: tuple[Path, ...]) -> dict[str, Any]:
    if path.resolve() in chain:
        raise ValueError(f"생성기 설정 extends 순환: {path}")
    raw = read_yaml(path)
    if not isinstance(raw, dict):
        raise ValueError(f"생성기 설정이 표가 아니에요: {path}")
    base = raw.pop("extends", None)
    if base is None:
        return raw
    merged = _read_config(path.parent / str(base), (*chain, path.resolve()))
    merged.update(raw)
    return merged


def write_outputs(generated: Generated, out_dir: Path) -> list[Path]:
    """같은 생성 결과면 같은 바이트를 쓴다. CSV는 엑셀에서 열기 쉽게 UTF-8 BOM으로 쓴다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot = generated.snapshot
    written = [_write_text(out_dir / "snapshot.json", snapshot.model_dump_json(indent=1) + "\n")]
    for split in ("dev", "eval"):
        lines = "".join(e.model_dump_json() + "\n" for e in generated.ecns if e.split.value == split)
        written.append(_write_text(out_dir / f"ecn_{split}.jsonl", lines))
    for table in CSV_TABLES:
        written.append(_write_csv(out_dir / table.name, table.columns, table.rows(snapshot)))
    return written


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _write_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence[object]]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows([["" if v is None else v for v in row] for row in rows])
    return path
