"""생성기 설정 계약(generator/config.yaml). 범위는 [최소, 최대]로 적고 생성기가 그 안에서 뽑는다."""

from __future__ import annotations

import math
from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from ripple.contracts.base import Frozen
from ripple.contracts.domain import ActivityKind, BlockShape, TransportMode

OpName = Literal[
    "thickness", "grade", "dimension", "add_part", "remove_part", "reroute_pipe", "equipment_spec", "add_penetration"
]
DensityLevel = Literal["low", "mid", "high"]


class Span(Frozen):
    """[최소, 최대] 범위."""

    lo: float
    hi: float

    @model_validator(mode="before")
    @classmethod
    def _from_pair(cls, value: object) -> object:
        if isinstance(value, list | tuple) and len(value) == 2:
            return {"lo": value[0], "hi": value[1]}
        return value

    @model_validator(mode="after")
    def _ordered(self) -> Span:
        if self.lo > self.hi:
            raise ValueError(f"범위의 최소가 최대보다 커요: [{self.lo}, {self.hi}]")
        return self


class ShipConfig(Frozen):
    ship_id: str
    ship_type: str
    dwt: int = Field(gt=0)
    contract_price_krw: int = Field(gt=0)
    delivery_offset_days: int = Field(gt=0)
    sea_trial_before_delivery_days: int = Field(default=30, ge=0)  # v3 시운전 이정표 = 인도일 − 이 일수


class ZoneConfig(Frozen):
    code: str
    name: str
    post_exit_days: int = Field(ge=0)
    forecast_delay_days: int = Field(default=0, ge=0)


class BlockConfig(Frozen):
    code: str
    zone: str
    name: str
    weight_t: float = Field(gt=0)
    pe_offset: int  # v3: 기준일 대비 PE 착수 계획일(v2의 탑재 착수일 자리). 소조립~선행도장은 거꾸로, 탑재는 PE 뒤로
    shape: BlockShape = BlockShape.FLAT  # v3 블록 형상(난이도 계수 입력)
    density: DensityLevel = "low"  # v3 의장·전장 밀도 수준(DensityConfig에서 개수를 뽑음)


class DurationConfig(Frozen):
    base: Span
    per_100t: Span


class ActivityConfig(Frozen):
    sub_assembly: DurationConfig
    panel: DurationConfig
    assembly: DurationConfig
    pre_outfitting: DurationConfig
    pre_painting: DurationConfig
    pre_erection: DurationConfig  # v3 PE
    erection: DurationConfig
    gap_days: Span
    actual_delay_days: Span


class DensitySpan(Frozen):
    """강재 t당 의장품·전장품 수 범위."""

    outfit: Span
    electric: Span


class DensityConfig(Frozen):
    low: DensitySpan
    mid: DensitySpan
    high: DensitySpan


class CrewConfig(Frozen):
    """사내 협력사 작업반 하나(가상 이름·가상 연락처)."""

    code: str
    name: str
    processes: tuple[ActivityKind, ...] = Field(min_length=1)
    contact: str


class CrewsConfig(Frozen):
    teams: tuple[CrewConfig, ...] = Field(min_length=1)
    share: float = Field(ge=0, le=1)  # 블록 공정(탑재 제외) 중 작업반이 맡을 확률


class PartsConfig(Frozen):
    plates_per_block: Span
    plate_grid_cols: Span
    plate_area_m2: Span
    base_thickness_mm: Span
    stiffeners_per_block: Span
    brackets_per_block: Span
    joint_plates: Span
    grades: dict[str, float]
    stiffener_spacing_m: Span
    span_m: Span
    head_m: Span


class PipeSystemConfig(Frozen):
    code: str
    name: str  # 계통 키(Part.system, 렉시콘 키)
    label: str = Field(min_length=1)  # 부재 이름·도면 제목·설계변경 제목에 쓰는 현장 이름(지도 pipe_systems)
    block: str  # 계통의 주 블록(설계변경 이력의 배관 대상은 이 블록 부재만)
    extends_to: str | None = None  # v3 블록 경계를 넘어 이어지는 이웃 블록
    equipment: str | None = None  # v3 계통 장비 이름(주 블록, 예: 평형수 펌프)


class PenetrationConfig(Frozen):
    system: str
    through_block: str
    count: Span


class PipingConfig(Frozen):
    systems: tuple[PipeSystemConfig, ...]
    spools_per_system: Span
    valves_per_system: Span
    supports_per_system: Span
    penetrations: PenetrationConfig
    cross_block_spools: Span  # v3 이웃 블록으로 이어지는 스풀 수


class EvidenceMix(Frozen):
    entered_on: float = Field(ge=0)
    observations_only: float = Field(ge=0)
    unknown: float = Field(ge=0)


class ProcurementConfig(Frozen):
    plate_lead_days: Span
    pipe_lead_days: Span
    valve_lead_days: Span
    equipment_lead_days: Span  # v3 장비(펌프)
    parts_lead_days: Span  # v3 사외 단품(관통 칼라)
    material_secured_ratio: Span
    fabrication_start_ratio: Span
    order_slack_days: Span
    specs_per_steel_po: Span
    evidence: EvidenceMix
    stock_lots: Span


class PriceConfig(Frozen):
    plate_per_t: Span
    section_per_t: Span
    pipe_per_m: Span
    valve_each: Span
    support_each: Span
    equipment_each: Span  # v3 장비(펌프)
    collar_each: Span  # v3 관통 칼라


class EcnConfig(Frozen):
    dev: int = Field(ge=1)
    eval: int = Field(ge=1)
    op_mix: dict[OpName, float]
    request_window_days: Span


class DemoConfig(Frozen):
    assembly_block: str
    not_started_block: str
    control_zone: str


ImportKind = Literal["valve", "equipment"]


class ImportSpecConfig(Frozen):
    """v4 외자재 규격 묶음: 배관 계통(코드)의 주 블록 부재 종류가 쓰는 규격과 그 운송 방식."""

    system: str
    kind: ImportKind
    transport: TransportMode


class ImportsConfig(Frozen):
    """외자재: 규격 단위로 원산지·운송 방식, 생산 표준 리드타임(운송 제외, 가정)."""

    std_lead_days: dict[ImportKind, int]
    specs: tuple[ImportSpecConfig, ...] = ()

    @model_validator(mode="after")
    def _leads(self) -> ImportsConfig:
        missing = sorted({s.kind for s in self.specs} - set(self.std_lead_days))
        if missing or any(days <= 0 for days in self.std_lead_days.values()):
            raise ValueError(f"외자재 생산 표준 리드타임이 없거나 0 이하예요: {missing}")
        return self


class RelationsConfig(Frozen):
    """시연 합성 지도의 블록 사이 관계 보강(generator/demo_map.yaml, docs/data.md(생성기) 12절).

    erection_after: 후행 블록 → 그 탑재 전에 탑재를 끝내야 하는 선행 블록들(같은 호선, lag 0). 기본 지도에는 없다."""

    name: str = Field(min_length=1)  # 지도 목록에 보이는 이름('합성'이 드러나게)
    erection_after: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _acyclic(self) -> RelationsConfig:
        if "합성" not in self.name:
            raise ValueError("시연 지도 이름에 '합성'이 있어야 해요")
        if any(after in before for after, before in self.erection_after.items()):
            raise ValueError("탑재 순서에 자기 자신이 선행인 블록이 있어요")
        seen: set[str] = set()
        done: set[str] = set()

        def visit(code: str) -> None:
            if code in done:
                return
            if code in seen:
                raise ValueError(f"탑재 순서에 순환이 있어요: {code}")
            seen.add(code)
            for pred in self.erection_after.get(code, ()):
                visit(pred)
            done.add(code)

        for code in sorted(self.erection_after):
            visit(code)
        return self


class GeneratorConfig(Frozen):
    version: str = Field(pattern=r"^generator-v\d+$")
    scenario_date: date
    seed: int
    ship: ShipConfig
    zones: tuple[ZoneConfig, ...] = Field(min_length=1)
    blocks: tuple[BlockConfig, ...] = Field(min_length=1)
    adjacency: tuple[tuple[str, str], ...]
    activities: ActivityConfig
    parts: PartsConfig
    piping: PipingConfig
    procurement: ProcurementConfig
    prices: PriceConfig
    density: DensityConfig  # v3
    crews: CrewsConfig  # v3
    ecn: EcnConfig
    demo: DemoConfig
    imports: ImportsConfig | None = None  # v4 외자재 규격(없으면 모두 국산·모름)
    relations: RelationsConfig | None = None  # 시연 합성 지도의 관계 보강(기본 지도는 없음)

    @model_validator(mode="after")
    def _consistent(self) -> GeneratorConfig:
        self._check_blocks()
        self._check_v3()
        if self.relations is not None:
            named = set(self.relations.erection_after) | {c for v in self.relations.erection_after.values() for c in v}
            unknown = sorted(named - {b.code for b in self.blocks})
            if unknown:
                raise ValueError(f"탑재 순서에 없는 블록: {unknown}")
        if self.imports is not None:
            unknown = sorted({s.system for s in self.imports.specs} - {s.code for s in self.piping.systems})
            if unknown:
                raise ValueError(f"외자재 규격의 배관 계통이 없어요: {unknown}")
        for name, mix in (("op_mix", self.ecn.op_mix), ("grades", self.parts.grades)):
            if not math.isclose(sum(mix.values()), 1.0, abs_tol=1e-9):
                raise ValueError(f"{name}의 합이 1이 아니에요")
        evidence = self.procurement.evidence
        if not math.isclose(evidence.entered_on + evidence.observations_only + evidence.unknown, 1.0, abs_tol=1e-9):
            raise ValueError("발주 근거 형태 비율의 합이 1이 아니에요")
        return self

    def _check_v3(self) -> None:
        """v3: 작업반 코드가 겹치지 않고 탑재·이정표는 맡지 않음, 계통이 이어지는 블록이 있음."""
        codes = [team.code for team in self.crews.teams]
        if len(set(codes)) != len(codes):
            raise ValueError("작업반 코드가 겹쳐요")
        if any(k in (ActivityKind.ERECTION, ActivityKind.MILESTONE) for t in self.crews.teams for k in t.processes):
            raise ValueError("작업반은 탑재·이정표를 맡지 않아요(탑재는 직영)")
        blocks = {b.code for b in self.blocks}
        for system in self.piping.systems:
            if system.extends_to is not None and system.extends_to not in blocks - {system.block}:
                raise ValueError(f"배관 계통 {system.code}가 이어지는 블록이 없어요")

    def _check_blocks(self) -> None:
        zones = {z.code for z in self.zones}
        blocks = {b.code for b in self.blocks}
        if len(blocks) != len(self.blocks):
            raise ValueError("블록 코드가 겹쳐요")
        missing_zone = sorted(b.code for b in self.blocks if b.zone not in zones)
        if missing_zone:
            raise ValueError(f"없는 구역을 쓰는 블록: {missing_zone}")
        unknown = sorted({c for pair in self.adjacency for c in pair} - blocks)
        if unknown:
            raise ValueError(f"블록 이음에 없는 블록: {unknown}")
        for system in self.piping.systems:
            if system.block not in blocks:
                raise ValueError(f"배관 계통 {system.code}의 블록이 없어요")
        if self.piping.penetrations.system not in {s.code for s in self.piping.systems}:
            raise ValueError("관통 배관 계통이 없어요")
        if self.piping.penetrations.through_block not in blocks:
            raise ValueError("관통 블록이 없어요")
        demo_blocks = {self.demo.assembly_block, self.demo.not_started_block}
        if not demo_blocks <= blocks or self.demo.control_zone not in zones:
            raise ValueError("데모 고정점이 설정에 없어요")
