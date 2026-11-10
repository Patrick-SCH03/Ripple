"""합성 NCR 묶음(합성 모드 전용, docs/records.md '합성 NCR'): 사전 점검 유형별 부적합 보고의 시연 재료.

- 재료: 지도 생성기 설정(블록·배관 계통·작업반)과 씨앗만 쓴다(기준일은 쓰지 않아 실시간 시연 세계에서 날이 바뀌어도
  같은 묶음). 설계변경 번호를 가리키지 않아 시연 목록·과거 사례의 설계변경과 겹치지 않는다.
- 한 건: NCR-S-0001 꼴 번호 · 유형(사전 점검 P-01~P-06 + 기타 2종) · 분야 짝 · 발견 단계 · 조치 수행 주체 · 원인 한 줄 ·
  조치 한 줄. 모든 문장 앞에 '[합성 묶음(시연)]'을 붙인다. 유형 비율·작업반 비율은 params/ncr_v1.yaml(근거 없는 가정).
- 건수만 센다(비율·대표 손실 금액은 만들지 않는다). 실데이터 모드는 빈 묶음 + 이유.
- 같은 설정·씨앗이면 같은 묶음(건마다 (씨앗, 'ncr', 판, 번호) 난수원).
"""

from __future__ import annotations

import math
import random
import typing
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from pydantic import Field, model_validator

from ripple.config.loaders import read_yaml
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.base import Frozen
from ripple.contracts.domain import STAGE_OF_ACTIVITY, ActivityKind, BlockStage, DataMode
from ripple.contracts.ncr import (
    NCR_TYPE_NAMES,
    SYNTHETIC_LABEL,
    NcrDiscipline,
    NcrRecord,
    NcrSummary,
    NcrType,
    NcrTypeCount,
)
from ripple.generator.config import GeneratorConfig
from ripple.generator.rng import sub_rng, weighted

DEFAULT_PATH = PROJECT_ROOT / "params" / "ncr_v1.yaml"
NCR_TYPES: tuple[NcrType, ...] = typing.get_args(NcrType)
REAL_REASON = "실데이터 모드 — 합성 NCR 미생성(실제 NCR 이력 미수신)"
DIRECT = "직영"

D = NcrDiscipline
S = BlockStage
DISCIPLINE_NAMES = {
    D.HULL: "선체",
    D.PIPING: "배관",
    D.HULL_OUTFITTING: "선장",
    D.MACHINERY: "기장",
    D.ELECTRIC: "전장",
}
ACTIVITY_OF_STAGE: Mapping[BlockStage, ActivityKind] = MappingProxyType({s: k for k, s in STAGE_OF_ACTIVITY.items()})


class NcrSettings(Frozen):
    version: str = Field(min_length=1)
    count: int = Field(ge=1, le=500)
    recent: int = Field(ge=1, le=50)
    types: dict[NcrType, float]
    crew_share: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _weights(self) -> NcrSettings:
        if set(self.types) != set(NCR_TYPES) or any(w < 0 for w in self.types.values()):
            raise ValueError("NCR 유형 비율 오류 — 유형 8종(P-01~P-06·X-01·X-02) 모두에 0 이상 필요")
        if not math.isclose(sum(self.types.values()), 1.0, abs_tol=1e-9):
            raise ValueError("NCR 유형 비율의 합이 1이 아님")
        return self


def load_ncr_settings(path: Path = DEFAULT_PATH) -> NcrSettings:
    return NcrSettings.model_validate(read_yaml(path))


@dataclass(frozen=True, slots=True)
class Story:
    """유형 하나의 글감: 분야 짝 · 발견 단계 · 원인 · 조치.
    현업 사례 유형을 일반화했고 지어낸 숫자는 없다."""

    pairs: tuple[tuple[NcrDiscipline, NcrDiscipline], ...]
    stages: tuple[BlockStage, ...]
    causes: tuple[str, ...]
    actions: tuple[str, ...]


STORIES: Mapping[str, Story] = MappingProxyType(
    {
        "P-01": Story(
            ((D.PIPING, D.HULL), (D.MACHINERY, D.HULL)),
            (S.PRE_PAINTING, S.PRE_ERECTION, S.ERECTED),
            ("{block} 블록 선행의장 완료 후 {system} 배관 변경 확정 — 블록 단계 설치 불가",),
            (
                "변경 배관 재제작 후 탑재 뒤 선상 후행 설치",
                "블록 설치분 철거 후 선상 재설치",
            ),
        ),
        "P-02": Story(
            ((D.PIPING, D.HULL),),
            (S.ASSEMBLY, S.PRE_OUTFITTING),
            ("{system} 배관이 지나는 {block} 블록 판의 관통부·칼라가 {b} 도면에 누락",),
            ("현장 판 절단·칼라 부착 후 용접 검사 재실시",),
        ),
        "P-03": Story(
            ((D.PIPING, D.PIPING), (D.PIPING, D.HULL)),
            (S.PRE_ERECTION, S.ERECTED),
            ("{block} 블록 경계의 {system} 배관 연결부가 상대 블록 배관과 불일치",),
            ("연결 스풀 재계측 후 현장 맞춤 스풀로 교체 연결",),
        ),
        "P-04": Story(
            ((D.HULL, D.PIPING), (D.PIPING, D.ELECTRIC), (D.HULL_OUTFITTING, D.MACHINERY)),
            (S.ASSEMBLY, S.PRE_OUTFITTING),
            ("{block} 블록 {a} 도면만 수정, {b} 도면은 옛 개정으로 작업 — 블록 안 간섭 발생",),
            ("{b} 도면 개정 후 간섭 부위 재작업",),
        ),
        "P-05": Story(
            ((D.PIPING, D.HULL_OUTFITTING),),
            (S.PRE_OUTFITTING, S.ERECTED),
            ("새 {system} 스풀의 서포트가 도면·발주에서 누락",),
            ("서포트 단품 긴급 발주 후 현장 설치",),
        ),
        "P-06": Story(
            ((D.HULL, D.HULL), (D.HULL, D.HULL_OUTFITTING)),
            (S.PRE_PAINTING, S.PRE_ERECTION),
            ("도면에 반영한 보강재 추가가 {block} 블록 현장에 미공유",),
            ("도장 후 보강재 추가 시공 · 화기작업·재도장",),
        ),
        "X-01": Story(
            ((D.HULL, D.HULL),),
            (S.SUB_ASSEMBLY, S.PANEL, S.ASSEMBLY),
            ("{block} 블록 부재 취부 위치가 도면과 불일치",),
            ("취부 해체 후 재정렬·용접",),
        ),
        "X-02": Story(
            ((D.HULL, D.HULL), (D.PIPING, D.PIPING)),
            (S.SUB_ASSEMBLY, S.PRE_OUTFITTING),
            ("{block} 블록에 도면과 다른 규격 자재 지급",),
            ("맞는 규격 자재로 교체 후 재가공",),
        ),
    }
)


@dataclass(frozen=True, slots=True)
class NcrBundle:
    """합성 NCR 묶음. 실데이터 모드면 빈 묶음(synthetic 거짓)과 이유."""

    records: tuple[NcrRecord, ...] = ()
    synthetic: bool = False
    version: str | None = None
    reason: str | None = None

    def counts(self) -> dict[str, int]:
        """유형 → 건수(0건 유형 포함). 빈 묶음이면 빈 표 — 사전 점검은 이 건수만 싣는다."""
        if not self.synthetic:
            return {}
        return {t: sum(1 for r in self.records if r.ncr_type == t) for t in NCR_TYPES}

    def summary(self, recent: int) -> NcrSummary:
        if not self.synthetic:
            return NcrSummary(available=False, synthetic=False, reason=self.reason or REAL_REASON)
        counts = self.counts()
        return NcrSummary(
            available=True,
            synthetic=True,
            version=self.version,
            total=len(self.records),
            counts=tuple(NcrTypeCount(ncr_type=t, name=NCR_TYPE_NAMES[t], count=counts[t]) for t in NCR_TYPES),
            recent=tuple(sorted(self.records, key=lambda r: r.ncr_id, reverse=True)[:recent]),
        )


def ncr_bundle(config: GeneratorConfig, data_mode: DataMode, settings: NcrSettings | None = None) -> NcrBundle:
    """합성 모드면 설정·씨앗으로 만든 묶음, 아니면 빈 묶음(만들지 않는다)."""
    if data_mode is not DataMode.SYNTHETIC:
        return NcrBundle(reason=REAL_REASON)
    chosen = settings or load_ncr_settings()
    records = tuple(_record(config, chosen, number) for number in range(1, chosen.count + 1))
    return NcrBundle(records=records, synthetic=True, version=chosen.version)


def _pick[T](rng: random.Random, options: tuple[T, ...]) -> T:
    return options[rng.randrange(len(options))]


def _record(config: GeneratorConfig, settings: NcrSettings, number: int) -> NcrRecord:
    rng = sub_rng(config.seed, "ncr", settings.version, str(number))
    ncr_type = weighted(rng, settings.types)
    story = STORIES[ncr_type]
    block = _pick(rng, config.blocks)
    system = _pick(rng, config.piping.systems)
    pair = _pick(rng, story.pairs)
    stage = _pick(rng, story.stages)
    words = {
        "block": block.code,
        "system": system.label,
        "a": DISCIPLINE_NAMES[pair[0]],
        "b": DISCIPLINE_NAMES[pair[1]],
    }
    return NcrRecord(
        ncr_id=f"NCR-S-{number:04d}",
        ncr_type=ncr_type,
        disciplines=pair,
        found_stage=stage,
        performer=_performer(rng, config, settings, stage),
        cause=f"[{SYNTHETIC_LABEL}] " + _pick(rng, story.causes).format(**words),
        action=f"[{SYNTHETIC_LABEL}] " + _pick(rng, story.actions).format(**words),
    )


def _performer(rng: random.Random, config: GeneratorConfig, settings: NcrSettings, stage: BlockStage) -> str:
    """조치 수행 주체: 그 단계 공정을 맡는 작업반이 있으면 비율대로 작업반, 아니면 직영.
    탑재는 직영이다(생성기와 같음)."""
    activity = ACTIVITY_OF_STAGE.get(stage)
    teams = tuple(t for t in config.crews.teams if activity is not None and activity in t.processes)
    if teams and rng.random() < settings.crew_share:
        return _pick(rng, teams).name
    return DIRECT
