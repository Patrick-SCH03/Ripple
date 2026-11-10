"""실시간 시연 세계(docs/operations.md(서비스) 6절): 합성 기본 지도를 한국 시간 오늘 기준으로 생성기로 만든다.

생성기는 모든 날짜를 기준일(scenario_date) + 며칠로 만들어, 기준일만 오늘로 바꾸면 날짜만 옮겨진 같은 세계가 된다
(같은 시드 · 같은 설계변경 · 같은 시연 사례). 날이 바뀌면 작업 공간이 다음 요청에서 새 날의 세계로 넘어간다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ripple.contracts.dataset import EcnSplit, GeneratedEcn
from ripple.contracts.domain import GraphSnapshot
from ripple.generator.build import generate
from ripple.generator.io import DEFAULT_CONFIG_PATH, load_config


@dataclass(frozen=True, slots=True)
class LiveWorld:
    day: date
    snapshot: GraphSnapshot
    ecns: tuple[GeneratedEcn, ...]  # 개발 분할 설계변경 이력(화면 샘플을 고른다)


def live_world(day: date, config_path: Path = DEFAULT_CONFIG_PATH) -> LiveWorld:
    """생성기 설정(기본 · 시연 합성 지도 generator/demo_map.yaml)으로 day를 기준일로 한 시연 세계."""
    config = load_config(config_path)
    generated = generate(config.model_copy(update={"scenario_date": day}))
    return LiveWorld(day, generated.snapshot, tuple(e for e in generated.ecns if e.split is EcnSplit.DEV))
