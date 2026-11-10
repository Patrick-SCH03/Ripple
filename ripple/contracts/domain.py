"""도메인 계약: 연결 지도에 들어가는 노드·관계와 상태 어휘.

엔진, 합성 데이터 생성기, 엑셀 가져오기, API가 모두 이 모델을 공유한다.

상태(발주 단계, 블록 공정 단계)는 저장하지 않는다. 계획·확인 날짜·관측과 기준일로
그때그때 계산한다(ripple.engine). 그래야 "이날 확정하면?" 같은 가정 분석이 같은
데이터로 된다. 계산 규칙은 docs/domain.md에 있다.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import Literal

from pydantic import Field, model_validator

from .base import Frozen

# ---------- 어휘 (순서가 의미 있는 열거형은 정의 순서가 진행 순서) ----------


class DataMode(StrEnum):
    """real 모드에서는 외부 LLM·임베딩 호출을 어댑터 경계에서 막는다."""

    SYNTHETIC = "synthetic"
    REAL = "real"


class EntityType(StrEnum):
    SHIP = "ship"
    ZONE = "zone"
    BLOCK = "block"
    PART = "part"
    PO = "po"
    PO_LINE = "po_line"
    STOCK = "stock"
    ACTIVITY = "activity"
    DRAWING = "drawing"


class PartKind(StrEnum):
    PLATE = "plate"  # 판
    STIFFENER = "stiffener"  # 보강재(론지·수직 보강재)
    BRACKET = "bracket"
    COLLAR = "collar"  # 관통부 칼라·슬리브
    PIPE_SPOOL = "pipe_spool"
    VALVE = "valve"
    PIPE_SUPPORT = "pipe_support"
    EQUIPMENT = "equipment"


OUTFIT_PART_KINDS: frozenset[PartKind] = frozenset(
    {PartKind.PIPE_SPOOL, PartKind.VALVE, PartKind.PIPE_SUPPORT, PartKind.EQUIPMENT}
)
"""선행의장에서 블록에 다는 의장품(칼라는 선체 쪽 관통 부재라 넣지 않는다). 재작업은 선행의장 공정부터만 다시 한다."""


class Relation(StrEnum):
    """연결 지도의 관계 종류. 변경은 이 관계를 따라 번진다."""

    PART_OF = "part_of"  # 부재 → 블록
    SUPPLIED_BY = "supplied_by"  # 부재 → 발주 품목
    BUTT_WELD = "butt_weld"  # 부재 ↔ 부재: 맞대기 용접
    FILLET_WELD = "fillet_weld"  # 부재 ↔ 부재: 필릿 용접
    PENETRATION = "penetration"  # 배관이 판을 지남
    SUPPORT = "support"  # 서포트가 배관을 받침
    PIPE_JOINT = "pipe_joint"  # 배관끼리 연결(플랜지·용접)
    DRAWN_IN = "drawn_in"  # 부재 → 도면
    CONSUMED_BY = "consumed_by"  # 발주 품목 → 그 자재를 쓰는 공정
    PRECEDES = "precedes"  # 공정 → 후행 공정
    SAME_SPEC = "same_spec"  # 재고 로트 ↔ 같은 규격 수요


class ConnectionKind(StrEnum):
    """부재끼리의 연결. 값은 Relation의 부분집합이다."""

    BUTT_WELD = "butt_weld"
    FILLET_WELD = "fillet_weld"
    PENETRATION = "penetration"
    SUPPORT = "support"
    PIPE_JOINT = "pipe_joint"


class POStatus(StrEnum):
    """발주 단계. 취소·변경 비용 구간(params po_cancel_ratio)과 1:1로 대응한다."""

    NOT_ORDERED = "not_ordered"  # 미발주
    ORDERED = "ordered"  # 발주(공급사 자재 확보 전)
    MATERIAL_SECURED = "material_secured"  # 자재 확보
    IN_FABRICATION = "in_fabrication"  # 제작
    RECEIVED = "received"  # 입고
    PROCESSED = "processed"  # 가공(그 자재를 쓰는 공정 착수) 이후


PO_STATUS_ORDER: tuple[POStatus, ...] = tuple(POStatus)


class BlockStage(StrEnum):
    NOT_STARTED = "not_started"  # 미착수
    STEEL_RECEIVED = "steel_received"  # 강재 입고
    SUB_ASSEMBLY = "sub_assembly"  # 소조립
    PANEL = "panel"  # 판넬조립(옛 이름 판계, 값 그대로)
    ASSEMBLY = "assembly"  # 대조립(옛 이름 조립, 값 그대로)
    PRE_OUTFITTING = "pre_outfitting"  # 선행의장
    PRE_PAINTING = "pre_painting"  # 선행도장
    PRE_ERECTION = "pre_erection"  # PE(탑재 전 블록 합치기, 1.32.0)
    ERECTED = "erected"  # 탑재


BLOCK_STAGE_ORDER: tuple[BlockStage, ...] = tuple(BlockStage)


class ActivityKind(StrEnum):
    SUB_ASSEMBLY = "sub_assembly"
    PANEL = "panel"
    ASSEMBLY = "assembly"
    PRE_OUTFITTING = "pre_outfitting"
    PRE_PAINTING = "pre_painting"
    PRE_ERECTION = "pre_erection"  # PE(1.32.0)
    ERECTION = "erection"
    MILESTONE = "milestone"  # 구역 탑재 완료·진수·시운전·인도처럼 기간 0인 이정표


STAGE_OF_ACTIVITY: Mapping[ActivityKind, BlockStage] = MappingProxyType(
    {
        ActivityKind.SUB_ASSEMBLY: BlockStage.SUB_ASSEMBLY,
        ActivityKind.PANEL: BlockStage.PANEL,
        ActivityKind.ASSEMBLY: BlockStage.ASSEMBLY,
        ActivityKind.PRE_OUTFITTING: BlockStage.PRE_OUTFITTING,
        ActivityKind.PRE_PAINTING: BlockStage.PRE_PAINTING,
        ActivityKind.PRE_ERECTION: BlockStage.PRE_ERECTION,
        ActivityKind.ERECTION: BlockStage.ERECTED,
    }
)
"""블록 공정이 착수되면 블록이 이 단계로 넘어간다(이정표는 블록 단계와 무관)."""

BLOCK_ACTIVITY_ORDER: tuple[ActivityKind, ...] = tuple(STAGE_OF_ACTIVITY)
"""블록 공정 순서(소조립 → 판넬조립 → 대조립 → 선행의장 → 선행도장 → PE → 탑재). 블록 단계 순서와 같다."""

DIRECT_PERFORMER = "direct"
"""공정 수행 주체 중 직영(원청이 직접). 그 밖의 값은 작업반 ID(Crew.crew_id, 1.32.0)."""


class SupplierKind(StrEnum):
    STEEL = "steel"  # 기자재 공급사(강재)
    PIPE = "pipe"  # 기자재 공급사(배관재)
    EQUIPMENT = "equipment"  # 기자재 공급사(밸브·장비)
    BLOCK = "block"  # 사외 블록 제작 협력사
    OUTFITTING = "outfitting"
    PARTS = "parts"  # 사외 협력사(단품 제작: 브라켓·서포트·칼라, 1.32.0)


class BlockShape(StrEnum):
    """블록 형상(1.32.0): 재작업 난이도 계수의 입력(docs/engine.md(비용·일정) 4-4)."""

    FLAT = "flat"  # 평블록
    CURVED = "curved"  # 곡블록
    BOW_STERN = "bow_stern"  # 선수미 블록


MaterialCategory = Literal["plate", "section", "pipe", "valve", "fitting", "equipment"]
MaterialOrigin = Literal["domestic", "import"]
"""1.33.0 규격의 원산지 구분: 국산 · 외자재(해외에서 들여옴)."""
TransportMode = Literal["air", "sea"]
"""1.33.0 외자재의 운송 방식: 항공 · 선박(일수는 params transport_days)."""
ASSUMED_TRANSPORT: TransportMode = "sea"
"""외자재인데 운송 방식이 비었을 때 가정하는 방식(더 긴 쪽이라 보수적)."""
ASSUMED_TRANSPORT_NOTE = "가정(운송 방식 없음 → 선박)"
"""그 가정을 비용 줄·일정 근거·안내에 남기는 말."""


# ---------- 노드 ----------


class SourceRef(Frozen):
    """원본 위치. 엑셀 가져오기면 파일·시트·행, 생성기면 생성 파일·행."""

    file: str
    sheet: str | None = None
    row: int | None = Field(default=None, ge=1)


class LDTerms(Frozen):
    """건조계약의 지체상금 조건. 없으면 params liquidated_damages 기본값을 쓴다."""

    grace_days: int = Field(ge=0)
    rate_per_day_of_price: float = Field(gt=0, lt=0.01)
    max_days: int = Field(gt=0)


class Ship(Frozen):
    ship_id: str  # 호선 번호, 예: "S-001"
    ship_type: str  # 예: "suezmax_crude_oil_tanker"
    dwt: int = Field(gt=0)
    contract_price_krw: int = Field(gt=0)
    delivery_date: date  # 계약 인도일
    ld_terms: LDTerms | None = None


class Zone(Frozen):
    zone_id: str  # 예: "S-001:ZCT"
    ship_id: str
    name: str


class ZoneBoundary(Frozen):
    """부분 모델의 경계 조건: 구역 출구 이정표와 계약 인도일 사이.

    경계 조건이 없는 구역은 블록·이정표 지연만 내고, 인도 지연·지체상금은
    '계산 불가'로 둔다(docs/domain.md 5절).
    """

    zone_id: str
    exit_activity_id: str  # 구역 탑재 완료 이정표
    float_to_delivery_days: int = Field(ge=0)  # 출구 이정표 → 계약 인도일, 모델 밖 경로의 여유
    forecast_delivery_delay_days: int = Field(default=0, ge=0)  # 이 변경과 무관하게 이미 예상되는 인도 지연


class Block(Frozen):
    block_id: str  # 호선을 붙인 고유 ID, 예: "S-001:B31P"
    ship_id: str
    zone_id: str
    name: str
    steel_weight_t: float = Field(gt=0)
    fabricator_id: str | None = None  # 사외 제작이면 협력사 ID
    source: SourceRef | None = None
    # 1.32.0 재작업 난이도 계수의 입력(비면 계수 1, 지도 ID 정규형에서 뺀다 — identity.snapshot_id)
    shape: BlockShape | None = None
    outfit_items: int | None = Field(default=None, ge=0)  # 블록의 의장품 수(선행의장 밀도 = 수 ÷ 강재 중량)
    electric_items: int | None = Field(default=None, ge=0)  # 블록의 전장품 수


class MaterialSpec(Frozen):
    spec_id: str  # 예: "PL-AH36-14.0"
    category: MaterialCategory
    description: str
    grade: str | None = None
    thickness_mm: float | None = Field(default=None, gt=0)
    unit: Literal["t", "ea", "m"]
    unit_price_krw: int = Field(ge=0)
    std_lead_time_days: int | None = Field(default=None, gt=0)  # 없으면 params lead_time_days[분류]
    nominal_diameter_dn: int | None = Field(default=None, gt=0)  # 배관·밸브·부속의 호칭 구경(연결 규격)
    pressure_class: str | None = None  # 연결 압력 등급, 예: "10K"(연결 규격)
    # 1.33.0 외자재: 원산지 구분과 운송 방식(외자재일 때만). 외자재인데 운송 방식이 비면 엔진은 선박으로
    # 가정한다(더 긴 쪽 — ASSUMED_TRANSPORT). 외자재 규격의 std_lead_time_days는 생산 리드타임(운송 제외)이고,
    # 새로 발주할 때 운송 일수를 더한다(docs/engine.md(비용·일정) 5절). 비면 지도 ID 정규형에서 뺀다
    origin: MaterialOrigin | None = None
    transport: TransportMode | None = None

    @model_validator(mode="after")
    def _transport_of_import(self) -> MaterialSpec:
        if self.transport is not None and self.origin != "import":
            raise ValueError("운송 방식은 외자재 규격에만 기재")
        return self

    @property
    def import_transport(self) -> TransportMode | None:
        """새로 발주할 때 더할 운송 방식: 외자재면 적은 방식, 비었으면 선박(가정), 국산·모름이면 None."""
        if self.origin != "import":
            return None
        return self.transport or ASSUMED_TRANSPORT

    @property
    def transport_assumed(self) -> bool:
        """외자재인데 운송 방식이 비어 선박으로 가정하는가."""
        return self.origin == "import" and self.transport is None


class Part(Frozen):
    part_id: str  # 예: "S-001:B31P-PL-0012"
    ship_id: str
    block_id: str
    kind: PartKind
    name: str
    spec_id: str
    qty: float = Field(gt=0)
    drawing_no: str
    revision: str
    system: str | None = None  # 배관 계통 키, 예: "cargo_stripping"(현장 이름은 지도의 pipe_systems)
    pid_class: str | None = None  # 배관 부품 분류(일반 공학 용어)
    thickness_mm: float | None = Field(default=None, gt=0)
    grade: str | None = None
    stiffener_spacing_m: float | None = Field(default=None, gt=0)  # 강도 사전검사 입력
    span_m: float | None = Field(default=None, gt=0)
    head_m: float | None = Field(default=None, gt=0)  # 설계 수두(압력 대용)
    weight_kg: float | None = Field(default=None, gt=0)
    source: SourceRef | None = None
    # 1.32.0 다른 분야 도면(도면 ID, 예: 배관도에도 그려진 관통 판). 설계변경 사전 점검에서만 쓰고 R-D01 도면 개정은
    # drawing_no·revision만 본다. 비면 지도 ID 정규형에서 뺀다
    secondary_drawing_ids: tuple[str, ...] = ()


class Connection(Frozen):
    a: str  # part_id
    b: str  # part_id
    kind: ConnectionKind
    length_m: float | None = Field(default=None, gt=0)  # 용접 길이 등

    @model_validator(mode="after")
    def _distinct_ends(self) -> Connection:
        if self.a == self.b:
            raise ValueError("연결의 두 끝이 같은 부재")
        return self


class Supplier(Frozen):
    supplier_id: str
    name: str
    kind: SupplierKind


class Crew(Frozen):
    """사내 협력사 작업반(1.32.0): 블록 공정을 맡아 수행한다. 공정의 performer가 crew_id로 가리킨다."""

    crew_id: str
    name: str = Field(min_length=1)
    processes: tuple[ActivityKind, ...] = ()  # 주로 맡는 블록 공정
    contact: str | None = None  # 연락처(시연 지도는 가상 '.example')

    @model_validator(mode="after")
    def _own_id(self) -> Crew:
        if self.crew_id == DIRECT_PERFORMER:
            raise ValueError(f"작업반 ID로 '{DIRECT_PERFORMER}'(직영) 사용 불가")
        if ActivityKind.MILESTONE in self.processes:
            raise ValueError("작업반은 이정표 담당 불가")
        return self


class StatusObservation(Frozen):
    """발주대장에서 확인한 상태. observed_on은 확인한 날이지 그 단계에 들어간 날이 아니다.

    관측은 날짜 단위다. 같은 날 서로 다른 상태 관측은 진입일 범위를 비게 만들어 거부한다.
    """

    status: POStatus
    observed_on: date
    source: SourceRef | None = None


class PurchaseOrder(Frozen):
    """발주. 단계 진입일은 확인된 날짜 → 관측 범위 → 계획 순으로 추정한다(docs/domain.md 3절).

    entered_on에는 확인된 단계 진입일만 넣는다. observations는 가져올 때마다 쌓인다.
    """

    po_id: str
    ship_id: str
    supplier_id: str
    planned_order_date: date | None = None  # 아직 정하지 않았으면 None
    material_secured_days: int = Field(ge=0)  # 발주 뒤 공급사 자재 확보까지
    fabrication_start_days: int = Field(ge=0)  # 발주 뒤 제작 착수까지
    lead_time_days: int = Field(gt=0)  # 발주 뒤 입고까지
    entered_on: dict[POStatus, date] = Field(default_factory=dict)
    observations: tuple[StatusObservation, ...] = ()
    source: SourceRef | None = None

    @model_validator(mode="after")
    def _consistent(self) -> PurchaseOrder:
        if not self.material_secured_days <= self.fabrication_start_days <= self.lead_time_days:
            raise ValueError("자재 확보 ≤ 제작 착수 ≤ 리드타임 순서 필요")
        if POStatus.NOT_ORDERED in self.entered_on:
            raise ValueError("미발주에는 진입일 불가")
        known = [self.entered_on[s] for s in PO_STATUS_ORDER if s in self.entered_on]
        if known != sorted(known):
            raise ValueError("확인된 단계 진입일이 단계 순서를 거스름")
        by_day: dict[date, set[POStatus]] = {}
        for obs in self.observations:
            by_day.setdefault(obs.observed_on, set()).add(obs.status)
        clashes = sorted(day for day, statuses in by_day.items() if len(statuses) > 1)
        if clashes:
            raise ValueError(f"같은 날 서로 다른 발주 상태 관측: {clashes[0]}")
        rank = PO_STATUS_ORDER.index
        timeline = sorted(self.observations, key=lambda o: (o.observed_on, rank(o.status)))
        ranks = [rank(o.status) for o in timeline]
        if ranks != sorted(ranks):
            raise ValueError("관측된 발주 상태가 시간이 지나며 되돌아감")
        for obs in self.observations:
            for stage, entered in self.entered_on.items():
                reached = rank(stage) <= rank(obs.status)
                if reached and entered > obs.observed_on:
                    raise ValueError(f"{obs.observed_on}에 이미 {stage} 이상인데 진입일이 그 뒤")
                if not reached and entered <= obs.observed_on:
                    raise ValueError(f"{obs.observed_on}에 아직 {stage} 전인데 진입일이 그 전")
        return self


class POLine(Frozen):
    po_id: str
    line_no: int = Field(ge=1)
    spec_id: str
    qty: float = Field(gt=0)
    unit_price_krw: int = Field(ge=0)
    part_ids: tuple[str, ...] = ()  # 이 품목이 공급하는 부재
    consumed_by_activity_id: str | None = None  # 이 공정이 착수하면 '가공'으로 본다
    source: SourceRef | None = None

    @property
    def line_id(self) -> str:
        """발주 품목 ID, 예: \"PO-0007#1\". 영향·화면이 이 형식으로 가리킨다."""
        return f"{self.po_id}#{self.line_no}"


class StockLot(Frozen):
    """입고된 자재. 잉여 자재 전용 계산에 쓴다."""

    lot_id: str
    spec_id: str
    qty: float = Field(gt=0)
    received_date: date
    processed: bool = False
    reserved_block_id: str | None = None


class Precedence(Frozen):
    activity_id: str  # 선행 공정
    lag_days: int = Field(default=0, ge=0)


class ActivityCheck(StrEnum):
    """현장에서 확인한 공정 상태."""

    NOT_STARTED = "not_started"  # 미착수
    IN_PROGRESS = "in_progress"  # 진행 중
    FINISHED = "finished"  # 완료


class ActivityConfirmation(Frozen):
    """현장 확인 기록: 그날 공정이 그 상태였다(docs/domain.md 12절).

    일정 계산은 실제 착수·완료일만 쓰고 확인은 쓰지 않는다 — '마지막 확인일' 표시용이다. 그래서 진행 중·완료
    확인은 그날까지의 실제 날짜가 있어야 하고, 미착수 확인은 그날까지 실제 착수일이 없어야 한다.
    """

    state: ActivityCheck
    confirmed_on: date


class Activity(Frozen):
    """공정. 일정 계산은 달력일 기준이다."""

    activity_id: str  # 예: "S-001:B31P:assembly"
    ship_id: str
    block_id: str | None  # 이정표면 None
    kind: ActivityKind
    duration_days: int = Field(ge=0)
    planned_start: date  # 계획 착수일. 이보다 일찍 시작하지 않는다
    predecessors: tuple[Precedence, ...] = ()
    actual_start: date | None = None
    actual_finish: date | None = None
    confirmations: tuple[ActivityConfirmation, ...] = ()  # 비어 있으면 지도 ID 정규형에서 뺀다(identity.snapshot_id)
    # 1.32.0 수행: DIRECT_PERFORMER(직영) 또는 작업반 ID. 비면 모름(인건비는 블록 제작 협력사 규칙),
    # 지도 ID 정규형에서 뺀다
    performer: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _shape(self) -> Activity:
        is_milestone = self.kind is ActivityKind.MILESTONE
        if is_milestone and (self.block_id is not None or self.duration_days != 0):
            raise ValueError("이정표는 블록 없이 기간 0 필요")
        if is_milestone and self.performer is not None:
            raise ValueError("이정표에는 수행 주체 불가")
        if not is_milestone and self.block_id is None:
            raise ValueError("블록 공정에는 블록 ID 필요")
        if self.actual_finish is not None and (self.actual_start is None or self.actual_finish < self.actual_start):
            raise ValueError("실제 완료일은 실제 착수일 이후 필요")
        for check in self.confirmations:
            problem = confirmation_problem(check, self.actual_start, self.actual_finish)
            if problem:
                raise ValueError(problem)
        return self


def confirmation_problem(check: ActivityConfirmation, started: date | None, finished: date | None) -> str | None:
    """현장 확인이 공정의 실제 착수·완료일과 어긋나는 이유(없으면 None)."""
    day = check.confirmed_on
    started_by = started is not None and started <= day
    finished_by = finished is not None and finished <= day
    if check.state is ActivityCheck.NOT_STARTED and started_by:
        return f"{day}에 미착수로 확인했는데 실제 착수일({started})이 그 전"
    if check.state is ActivityCheck.IN_PROGRESS and not (started_by and not finished_by):
        return f"{day}에 진행 중 확인이면 그날까지 실제 착수일 필요·완료일 불가"
    if check.state is ActivityCheck.FINISHED and not finished_by:
        return f"{day}에 완료 확인이면 그날까지 실제 완료일 필요"
    return None


class Drawing(Frozen):
    drawing_no: str
    revision: str
    discipline: Literal["hull", "piping", "outfitting", "machinery"]
    title: str

    @property
    def drawing_id(self) -> str:
        """도면 ID, 예: \"DWG-T31C-H01@A\"(도면 번호@개정)."""
        return drawing_key(self.drawing_no, self.revision)


class PipeSystem(Frozen):
    """배관 계통 이름표: 계통 키(Part.system)와 화면·설명에 쓰는 현장 이름."""

    system: str
    name: str = Field(min_length=1)  # 예: "화물 스트리핑"


class GraphSnapshot(Frozen):
    """연결 지도 한 벌. snapshot_id는 내용 해시다(ripple.contracts.identity)."""

    snapshot_id: str
    origin: Literal["generator", "excel_import"]
    data_mode: DataMode
    ships: tuple[Ship, ...]
    zones: tuple[Zone, ...]
    boundaries: tuple[ZoneBoundary, ...] = ()
    blocks: tuple[Block, ...]
    specs: tuple[MaterialSpec, ...]
    parts: tuple[Part, ...]
    connections: tuple[Connection, ...]
    suppliers: tuple[Supplier, ...]
    purchase_orders: tuple[PurchaseOrder, ...]
    po_lines: tuple[POLine, ...]
    stock: tuple[StockLot, ...]
    activities: tuple[Activity, ...]
    drawings: tuple[Drawing, ...]
    pipe_systems: tuple[PipeSystem, ...] = ()  # 이름표가 없는 계통은 키를 그대로 보인다(엑셀 가져오기 등)
    crews: tuple[Crew, ...] = ()  # 1.32.0 사내 협력사 작업반(비면 지도 ID 정규형에서 뺀다)

    @model_validator(mode="after")
    def _well_formed(self) -> GraphSnapshot:
        if self.origin == "generator" and self.data_mode is not DataMode.SYNTHETIC:
            raise ValueError("생성기가 만든 지도는 synthetic 모드 필요")
        _require_unique("ships", (s.ship_id for s in self.ships))
        _require_unique("zones", (z.zone_id for z in self.zones))
        _require_unique("boundaries", (b.zone_id for b in self.boundaries))
        _require_unique("blocks", (b.block_id for b in self.blocks))
        _require_unique("specs", (s.spec_id for s in self.specs))
        _require_unique("parts", (p.part_id for p in self.parts))
        _require_unique("suppliers", (s.supplier_id for s in self.suppliers))
        _require_unique("purchase_orders", (p.po_id for p in self.purchase_orders))
        _require_unique("po_lines", (li.line_id for li in self.po_lines))
        _require_unique("stock", (s.lot_id for s in self.stock))
        _require_unique("activities", (a.activity_id for a in self.activities))
        _require_unique("drawings", (d.drawing_id for d in self.drawings))
        _require_unique("pipe_systems", (s.system for s in self.pipe_systems))
        _require_unique("crews", (c.crew_id for c in self.crews))
        return self


def drawing_key(drawing_no: str, revision: str) -> str:
    return f"{drawing_no}@{revision}"


def _require_unique(collection: str, ids: Iterable[str]) -> None:
    duplicated = sorted(key for key, count in Counter(ids).items() if count > 1)
    if duplicated:
        raise ValueError(f"{collection}에 겹치는 ID: {', '.join(duplicated[:5])}")
