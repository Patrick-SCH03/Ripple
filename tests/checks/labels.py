"""이름표 누락(계약 1.32.0): 계약 열거형의 새 값이 화면·엔진 글에 원문(영어 값·파라미터 키)으로 나오지 않는다.

- 화면 이름표(web/src/lib/labels.ts·assistant.ts)가 계약 열거형 값을 모두 덮는다(공정·블록 단계·부재 종류·영향 종류·
  협력사 구분·블록 형상·자재 분류·통보 대상, 이정표 꼬리는 생성기 이정표 ID).
- 엔진 이름표(describe)가 블록 공정·블록 단계·이정표를 덮고, 화면과 같은 이름이다(판넬조립·대조립·PE).
- 비용 줄 가정값 이름표(factors)가 파라미터의 모든 키를 덮는다(톤당 공수는 합친 이름이라 따로).
"""

from __future__ import annotations

import re
import typing

from harness import Checker

from ripple.config.loaders import load_params
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.assistant import NotificationTarget
from ripple.contracts.domain import (
    ActivityKind,
    BlockShape,
    BlockStage,
    MaterialCategory,
    PartKind,
    SupplierKind,
)
from ripple.contracts.result import ImpactType
from ripple.engine.cost.factors import WORK_HOURS, factor_name
from ripple.engine.describe import ACTIVITY_NAMES, BLOCK_STAGE_NAMES, MILESTONE_NAMES
from ripple.generator.build import generate
from ripple.generator.io import load_config

WEB = PROJECT_ROOT / "web" / "src" / "lib"


def ts_record(file: str, name: str) -> dict[str, str]:
    """TS 파일의 `export const NAME ... = { 키: '값', … }` 객체 하나를 키 → 값으로 읽는다(한 줄·여러 줄 모두)."""
    text = (WEB / file).read_text(encoding="utf-8")
    start = re.search(rf"export const {name}\b[^=]*=\s*{{", text)
    if start is None:
        return {}
    body = text[start.end() : text.index("}", start.end())]
    return dict(re.findall(r"'?([\w-]+)'?\s*:\s*'([^']*)'", body))


def run(c: Checker) -> None:
    _web(c)
    _engine(c)
    _factors(c)


def _web(c: Checker) -> None:
    c.section("이름표: 화면 이름표가 계약 값을 모두 덮음(새 값이 원문으로 보이지 않게)")
    block_kinds = {k.value for k in ActivityKind if k is not ActivityKind.MILESTONE}
    milestones = _milestone_tails()
    wanted = {
        ("labels.ts", "ACTIVITY_NAMES"): block_kinds | milestones,
        ("labels.ts", "BLOCK_STAGE_NAMES"): {s.value for s in BlockStage},
        ("labels.ts", "PART_KIND_NAMES"): {k.value for k in PartKind},
        ("labels.ts", "IMPACT_NAMES"): {k.value for k in ImpactType},
        ("labels.ts", "SUPPLIER_KIND_NAMES"): {k.value for k in SupplierKind},
        ("labels.ts", "BLOCK_SHAPE_NAMES"): {k.value for k in BlockShape},
        ("labels.ts", "MATERIAL_NAMES"): set(typing.get_args(MaterialCategory)),
        ("assistant.ts", "NOTIFY_TARGETS"): {k.value for k in NotificationTarget},
    }
    gaps = {
        f"{file}:{name}": sorted(values - set(ts_record(file, name)))
        for (file, name), values in wanted.items()
        if values - set(ts_record(file, name))
    }
    c.check(
        "공정·블록 단계·부재·영향·협력사 구분·블록 형상·자재 분류·통보 대상 이름표에 빠진 값이 없음", not gaps, gaps
    )
    web = ts_record("labels.ts", "ACTIVITY_NAMES")
    stages = ts_record("labels.ts", "BLOCK_STAGE_NAMES")
    c.check(
        "화면 블록 단계 이름표는 진행 순서(계약 BlockStage 정의 순서)대로",
        list(stages) == [s.value for s in BlockStage],
        list(stages),
    )
    same = {
        k.value: (ACTIVITY_NAMES[k], web.get(k.value)) for k in ACTIVITY_NAMES if ACTIVITY_NAMES[k] != web.get(k.value)
    }
    c.check("화면 공정 이름 = 엔진 공정 이름(판넬조립·대조립·PE)", not same, same)


def _engine(c: Checker) -> None:
    c.section("이름표: 엔진 이름표가 블록 공정·블록 단계·이정표를 덮음")
    kinds = {k for k in ActivityKind if k is not ActivityKind.MILESTONE}
    c.check(
        "엔진 공정·블록 단계 이름표가 계약 값을 모두 덮음",
        set(ACTIVITY_NAMES) == kinds and set(BLOCK_STAGE_NAMES) == set(BlockStage),
        (kinds - set(ACTIVITY_NAMES), set(BlockStage) - set(BLOCK_STAGE_NAMES)),
    )
    tails = _milestone_tails()
    c.check("생성기 이정표(구역 출구·진수·시운전·인도)마다 엔진 이름이 있음", tails <= set(MILESTONE_NAMES), tails)
    renamed = (
        ACTIVITY_NAMES[ActivityKind.PANEL],
        ACTIVITY_NAMES[ActivityKind.ASSEMBLY],
        ACTIVITY_NAMES[ActivityKind.PRE_ERECTION],
    )
    c.check("현장 이름: 판계 → 판넬조립, 조립 → 대조립, PE", renamed == ("판넬조립", "대조립", "PE"), renamed)


LINE_PREFIXES = (
    "rework_multiplier.",
    "rework.",
    "labor_rate_per_hour.",
    "difficulty.",
    "after_paint.",
    "delay_ripple.",
    "outfitting.",
    "minor_work_hours.",
    "po_cancel_ratio.",
    "liquidated_damages.",
)
"""비용 줄·지연 파급 비용이 가정값으로 싣는 파라미터 묶음(cost-v6 새 묶음 포함). 톤당 공수는 합친 이름이라 따로."""


def _factors(c: Checker) -> None:
    c.section("이름표: 비용 줄 가정값 이름표가 파라미터 키를 덮음(cost-v6 새 키 포함)")
    params = load_params(Settings.from_env({}).params_path)
    used = [k for k in params.params if k.startswith(LINE_PREFIXES) and not k.startswith(WORK_HOURS)]
    missing = sorted(k for k in used if factor_name(k) is None)
    c.check(
        f"가정값 이름표에 없는 키가 없음({len(used)}개 — 화면에 파라미터 키가 그대로 보이지 않게)",
        bool(used) and not missing,
        missing,
    )


def _milestone_tails() -> set[str]:
    """생성기 지도의 이정표 ID 꼬리(구역 출구는 'exit')."""
    snapshot = generate(load_config()).snapshot
    return {a.activity_id.rsplit(":", 1)[-1] for a in snapshot.activities if a.kind is ActivityKind.MILESTONE}
