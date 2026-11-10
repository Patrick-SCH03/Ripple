"""Ripple 엑셀 지정 양식 v1(docs/input.md(엑셀 양식)).

시트·열 정의 하나를 내보내기·가져오기·변형 생성이 함께 쓴다. 시트·열 이름은 현장 말(한글)이고, 코드 열(부재 종류·
발주 단계 등)은 한글 라벨과 계약 값을 모두 받는다. 단위는 열마다 고정(mm·m·t·kg·일·원)이다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType

from ripple.contracts.domain import ActivityCheck, ActivityKind, BlockShape, ConnectionKind, POStatus, SupplierKind
from ripple.engine.describe import ACTIVITY_NAMES, PART_KIND_NAMES, PO_STATUS_NAMES

from .normalize import code_key

TEMPLATE_VERSION = "excel-v1"
GUIDE_SHEET = "양식 안내"  # 내보낸 양식 맨 앞의 안내 시트(가져오기는 읽지 않는다)


class Kind(StrEnum):
    TEXT = "text"
    INT = "int"
    FLOAT = "float"
    DATE = "date"
    BOOL = "bool"
    CODE = "code"  # 정해진 값 중 하나(한글 라벨 또는 계약 값)
    LIST = "list"  # 쉼표·세미콜론·줄바꿈으로 나눈 여러 ID


@dataclass(frozen=True, slots=True)
class Column:
    key: str  # 내부 키(계약 필드와 대응, docs/input.md(엑셀 양식) 대응표)
    header: str  # 지정 양식 머리글
    kind: Kind
    required: bool = False
    unit: str = ""
    codes: Mapping[str, str] = MappingProxyType({})  # 계약 값 → 한글 라벨(코드 열)
    aliases: Mapping[str, tuple[str, ...]] = MappingProxyType({})  # 계약 값 → 옛 라벨(읽기만, 예: 판계 → 판넬조립)

    @property
    def title(self) -> str:
        """양식에 쓰는 머리글: 단위가 있으면 '두께(mm)'처럼 붙인다(가져오기는 둘 다 받는다)."""
        return f"{self.header}({self.unit})" if self.unit else self.header


@dataclass(frozen=True, slots=True)
class Sheet:
    key: str  # 내부 키
    name: str  # 지정 양식 시트 이름
    columns: tuple[Column, ...]
    required: bool = True
    absent: str = ""  # 선택 시트가 없을 때의 뜻(품질 리포트에 그대로 적음)
    needs_rows: bool = True  # 필수 시트에 데이터 행이 꼭 있어야 하는가(발주·선후행 등은 비어도 됨)
    quiet: bool = False  # 선택 시트가 없어도 경고하지 않음(계산에 쓰지 않는 기록 — 공정 확인)

    def column(self, key: str) -> Column:
        return next(c for c in self.columns if c.key == key)


def _codes(names: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(names))


CATEGORY_NAMES = _codes(
    {"plate": "판", "section": "형강", "pipe": "배관", "valve": "밸브", "fitting": "부속", "equipment": "장비"}
)
ORIGIN_NAMES = _codes({"domestic": "국산", "import": "외자재"})  # 1.33.0
ORIGIN_ALIASES = MappingProxyType({"domestic": ("내자", "국내"), "import": ("외자", "수입")})
TRANSPORT_NAMES = _codes({"air": "항공", "sea": "선박"})  # 1.33.0
TRANSPORT_ALIASES = MappingProxyType({"air": ("항공편", "항공 운송"), "sea": ("해상", "해상 운송")})
UNIT_NAMES = _codes({"t": "t", "ea": "EA", "m": "m"})
PART_KINDS = _codes({k.value: v for k, v in PART_KIND_NAMES.items()})
SUPPLIER_KINDS = _codes(
    {
        SupplierKind.STEEL.value: "강재",
        SupplierKind.PIPE.value: "배관",
        SupplierKind.EQUIPMENT.value: "장비",
        SupplierKind.BLOCK.value: "사외 블록 제작",
        SupplierKind.OUTFITTING.value: "의장",
        SupplierKind.PARTS.value: "사외 단품 제작",
    }
)
SUPPLIER_ALIASES = MappingProxyType({SupplierKind.BLOCK.value: ("블록 제작",)})
"""excel-v1 옛 라벨(1.32.0 전 양식 파일도 읽는다)."""
PO_STATUSES = _codes({k.value: v for k, v in PO_STATUS_NAMES.items()})
ACTIVITY_KINDS = _codes({**{k.value: v for k, v in ACTIVITY_NAMES.items()}, ActivityKind.MILESTONE.value: "이정표"})
ACTIVITY_ALIASES = MappingProxyType({ActivityKind.PANEL.value: ("판계",), ActivityKind.ASSEMBLY.value: ("조립",)})
"""공정 종류의 옛 라벨(1.32.0 이름 변경 전 양식 파일도 읽는다)."""
BLOCK_SHAPES = _codes(
    {BlockShape.FLAT.value: "평", BlockShape.CURVED.value: "곡", BlockShape.BOW_STERN.value: "선수미"}
)
DIRECT_LABEL = "직영"
"""공정 '수행 주체' 칸의 직영 표기(계약 값 domain.DIRECT_PERFORMER)."""
CONNECTION_KINDS = _codes(
    {
        ConnectionKind.BUTT_WELD.value: "맞대기 용접",
        ConnectionKind.FILLET_WELD.value: "필릿 용접",
        ConnectionKind.PENETRATION.value: "관통",
        ConnectionKind.SUPPORT.value: "지지",
        ConnectionKind.PIPE_JOINT.value: "배관 연결",
    }
)
DISCIPLINES = _codes({"hull": "선체", "piping": "배관", "outfitting": "의장", "machinery": "기계"})
ACTIVITY_CHECKS = _codes(
    {
        ActivityCheck.NOT_STARTED.value: "미착수",
        ActivityCheck.IN_PROGRESS.value: "진행 중",
        ActivityCheck.FINISHED.value: "완료",
    }
)

# 발주의 확인된 단계 진입일 열(발주 단계 → 열 키). 미발주는 진입일이 없다
ENTERED_COLUMNS: Mapping[POStatus, str] = MappingProxyType(
    {
        POStatus.ORDERED: "entered_ordered",
        POStatus.MATERIAL_SECURED: "entered_material_secured",
        POStatus.IN_FABRICATION: "entered_in_fabrication",
        POStatus.RECEIVED: "entered_received",
        POStatus.PROCESSED: "entered_processed",
    }
)

SHEETS: tuple[Sheet, ...] = (
    Sheet(
        "ships",
        "호선",
        (
            Column("ship_id", "호선번호", Kind.TEXT, True),
            Column("ship_type", "선종", Kind.TEXT, True),
            Column("dwt", "재화중량톤", Kind.INT, True, "t"),
            Column("contract_price_krw", "계약가", Kind.INT, True, "원"),
            Column("delivery_date", "계약 인도일", Kind.DATE, True),
            Column("ld_grace_days", "지체상금 유예일", Kind.INT, unit="일"),
            Column("ld_rate_per_day_of_price", "지체상금 일률", Kind.FLOAT),  # 하루 지체상금 ÷ 계약가
            Column("ld_max_days", "지체상금 최대일", Kind.INT, unit="일"),
        ),
    ),
    Sheet(
        "zones",
        "구역",
        (
            Column("zone_id", "구역ID", Kind.TEXT, True),
            Column("ship_id", "호선번호", Kind.TEXT, True),
            Column("name", "구역명", Kind.TEXT, True),
        ),
    ),
    Sheet(
        "boundaries",
        "구역 경계",
        (
            Column("zone_id", "구역ID", Kind.TEXT, True),
            Column("exit_activity_id", "출구 공정ID", Kind.TEXT, True),
            Column("float_to_delivery_days", "인도까지 여유", Kind.INT, True, "일"),
            Column("forecast_delivery_delay_days", "예상 인도 지연", Kind.INT, unit="일"),
        ),
        required=False,
        absent="구역 출구에서 인도까지의 경로 미확인 · 인도 지연·지체상금은 '계산 불가'로 표시",
    ),
    Sheet(
        "blocks",
        "블록",
        (
            Column("block_id", "블록ID", Kind.TEXT, True),
            Column("ship_id", "호선번호", Kind.TEXT, True),
            Column("zone_id", "구역ID", Kind.TEXT, True),
            Column("name", "블록명", Kind.TEXT, True),
            Column("steel_weight_t", "강재 중량", Kind.FLOAT, True, "t"),
            Column("fabricator_id", "제작 협력사ID", Kind.TEXT),
            Column("shape", "블록 형상", Kind.CODE, codes=BLOCK_SHAPES),
            Column("outfit_items", "의장품 수", Kind.INT),
            Column("electric_items", "전장품 수", Kind.INT),
        ),
    ),
    Sheet(
        "specs",
        "규격",
        (
            Column("spec_id", "규격ID", Kind.TEXT, True),
            Column("category", "분류", Kind.CODE, True, codes=CATEGORY_NAMES),
            Column("description", "규격 설명", Kind.TEXT, True),
            Column("grade", "강종", Kind.TEXT),
            Column("thickness_mm", "두께", Kind.FLOAT, unit="mm"),
            Column("unit", "단위", Kind.CODE, True, codes=UNIT_NAMES),
            Column("unit_price_krw", "단가", Kind.INT, True, "원"),
            Column("std_lead_time_days", "표준 리드타임", Kind.INT, unit="일"),  # 외자재면 생산 리드타임(운송 제외)
            Column("nominal_diameter_dn", "호칭 구경", Kind.INT, unit="DN"),
            Column("pressure_class", "압력 등급", Kind.TEXT),
            # 1.33.0 외자재: 비면 국산·모름(운송 일수를 더하지 않음). 운송 방식은 외자재일 때만(비면 선박 가정·경고)
            Column("origin", "원산지 구분", Kind.CODE, codes=ORIGIN_NAMES, aliases=ORIGIN_ALIASES),
            Column("transport", "운송 방식", Kind.CODE, codes=TRANSPORT_NAMES, aliases=TRANSPORT_ALIASES),
        ),
    ),
    Sheet(
        "parts",
        "부재",
        (
            Column("part_id", "부재ID", Kind.TEXT, True),
            Column("ship_id", "호선번호", Kind.TEXT, True),
            Column("block_id", "블록ID", Kind.TEXT, True),
            Column("kind", "부재 종류", Kind.CODE, True, codes=PART_KINDS),
            Column("name", "부재명", Kind.TEXT, True),
            Column("spec_id", "규격ID", Kind.TEXT, True),
            Column("qty", "수량", Kind.FLOAT, True),  # 규격 단위(t·EA·m)
            Column("drawing_no", "도면번호", Kind.TEXT, True),
            Column("revision", "개정", Kind.TEXT, True),
            Column("system", "배관 계통", Kind.TEXT),
            Column("pid_class", "배관 부품 분류", Kind.TEXT),
            Column("thickness_mm", "두께", Kind.FLOAT, unit="mm"),
            Column("grade", "강종", Kind.TEXT),
            Column("stiffener_spacing_m", "보강재 간격", Kind.FLOAT, unit="m"),
            Column("span_m", "스팬", Kind.FLOAT, unit="m"),
            Column("head_m", "설계 수두", Kind.FLOAT, unit="m"),
            Column("weight_kg", "중량", Kind.FLOAT, unit="kg"),
            Column("secondary_drawing_ids", "다른 분야 도면", Kind.LIST),  # 도면번호@개정
        ),
    ),
    Sheet(
        "suppliers",
        "협력사",
        (
            Column("supplier_id", "협력사ID", Kind.TEXT, True),
            Column("name", "협력사명", Kind.TEXT, True),
            Column("kind", "구분", Kind.CODE, True, codes=SUPPLIER_KINDS, aliases=SUPPLIER_ALIASES),
        ),
        needs_rows=False,
    ),
    Sheet(
        "crews",
        "작업반",
        (
            Column("crew_id", "작업반ID", Kind.TEXT, True),
            Column("name", "작업반명", Kind.TEXT, True),
            Column("processes", "담당 공정", Kind.LIST),  # 공정 종류 라벨(소조립·판넬조립…)
            Column("contact", "작업반 연락처", Kind.TEXT),
        ),
        required=False,
        absent="사내 협력사 작업반 목록 없음 · 재작업 비용은 작업반 몫으로 나누지 않고 한 줄로 표시(금액 동일)",
        quiet=True,
    ),
    Sheet(
        "purchase_orders",
        "발주",
        (
            Column("po_id", "발주번호", Kind.TEXT, True),
            Column("ship_id", "호선번호", Kind.TEXT, True),
            Column("supplier_id", "협력사ID", Kind.TEXT, True),
            Column("planned_order_date", "계획 발주일", Kind.DATE),
            Column("material_secured_days", "자재 확보까지", Kind.INT, True, "일"),
            Column("fabrication_start_days", "제작 착수까지", Kind.INT, True, "일"),
            Column("lead_time_days", "입고까지", Kind.INT, True, "일"),
            Column("entered_ordered", "발주일(확인)", Kind.DATE),
            Column("entered_material_secured", "자재 확보일(확인)", Kind.DATE),
            Column("entered_in_fabrication", "제작 착수일(확인)", Kind.DATE),
            Column("entered_received", "입고일(확인)", Kind.DATE),
            Column("entered_processed", "가공일(확인)", Kind.DATE),
        ),
        needs_rows=False,
    ),
    Sheet(
        "po_lines",
        "발주 품목",
        (
            Column("po_id", "발주번호", Kind.TEXT, True),
            Column("line_no", "품목번호", Kind.INT, True),
            Column("spec_id", "규격ID", Kind.TEXT, True),
            Column("qty", "수량", Kind.FLOAT, True),
            Column("unit_price_krw", "단가", Kind.INT, True, "원"),
            Column("part_ids", "공급 부재", Kind.LIST),
            Column("consumed_by_activity_id", "소비 공정ID", Kind.TEXT),
        ),
        needs_rows=False,
    ),
    Sheet(
        "observations",
        "발주 관측",
        (
            Column("po_id", "발주번호", Kind.TEXT, True),
            Column("status", "상태", Kind.CODE, True, codes=PO_STATUSES),
            Column("observed_on", "관측일", Kind.DATE, True),
        ),
        required=False,
        absent="발주 상태 관측 기록 없음 · 단계는 계획 발주일·간격으로 추정(확인된 진입일이 있으면 그 날짜 사용)",
    ),
    Sheet(
        "activities",
        "공정",
        (
            Column("activity_id", "공정ID", Kind.TEXT, True),
            Column("ship_id", "호선번호", Kind.TEXT, True),
            Column("block_id", "블록ID", Kind.TEXT),  # 이정표는 빈칸
            Column("kind", "공정 종류", Kind.CODE, True, codes=ACTIVITY_KINDS, aliases=ACTIVITY_ALIASES),
            Column("duration_days", "기간", Kind.INT, True, "일"),
            Column("planned_start", "계획 착수일", Kind.DATE, True),
            Column("actual_start", "실적 착수일", Kind.DATE),
            Column("actual_finish", "실적 완료일", Kind.DATE),
            Column("performer", "수행 주체", Kind.TEXT),  # '직영' 또는 작업반ID(빈칸 = 모름)
        ),
    ),
    Sheet(
        "activity_checks",
        "공정 확인",
        (
            Column("activity_id", "공정ID", Kind.TEXT, True),
            Column("state", "확인 상태", Kind.CODE, True, codes=ACTIVITY_CHECKS),
            Column("confirmed_on", "확인일", Kind.DATE, True),
        ),
        required=False,
        absent="공정 현장 확인 기록 없음 · 마지막 확인일은 실적 날짜로만 표시(계산에는 영향 없음)",
        quiet=True,
    ),
    Sheet(
        "precedences",
        "선후행",
        (
            Column("activity_id", "공정ID", Kind.TEXT, True),
            Column("predecessor_id", "선행 공정ID", Kind.TEXT, True),
            Column("lag_days", "지연", Kind.INT, unit="일"),
        ),
        needs_rows=False,
    ),
    Sheet(
        "connections",
        "연결",
        (
            Column("a", "부재 A", Kind.TEXT, True),
            Column("b", "부재 B", Kind.TEXT, True),
            Column("kind", "연결 종류", Kind.CODE, True, codes=CONNECTION_KINDS),
            Column("length_m", "길이", Kind.FLOAT, unit="m"),
        ),
        required=False,
        absent="용접·관통·지지 연결 미확인 · 그 연결로 번지는 영향(이웃 판·용접·관통부)은 '확인 필요'로 표시",
    ),
    Sheet(
        "stock",
        "재고",
        (
            Column("lot_id", "로트ID", Kind.TEXT, True),
            Column("spec_id", "규격ID", Kind.TEXT, True),
            Column("qty", "수량", Kind.FLOAT, True),
            Column("received_date", "입고일", Kind.DATE, True),
            Column("processed", "가공 여부", Kind.BOOL),
            Column("reserved_block_id", "예약 블록ID", Kind.TEXT),
        ),
        required=False,
        absent="재고 미확인 · 재고 충당·잉여 자재 전용 계산 제외(금액이 실제보다 클 수 있음)",
    ),
    Sheet(
        "drawings",
        "도면",
        (
            Column("drawing_no", "도면번호", Kind.TEXT, True),
            Column("revision", "개정", Kind.TEXT, True),
            Column("discipline", "분야", Kind.CODE, True, codes=DISCIPLINES),
            Column("title", "도면명", Kind.TEXT, True),
        ),
    ),
    Sheet(
        "pipe_systems",
        "배관 계통",
        (Column("system", "계통 키", Kind.TEXT, True), Column("name", "계통명", Kind.TEXT, True)),
        required=False,
        absent="배관 계통 이름표 없음 · 계통은 키 그대로 표시",
    ),
)

SHEET_BY_KEY: Mapping[str, Sheet] = MappingProxyType({s.key: s for s in SHEETS})

ID_COLUMNS: Mapping[str, str] = MappingProxyType(
    {
        "ships": "ship_id",
        "zones": "zone_id",
        "blocks": "block_id",
        "specs": "spec_id",
        "parts": "part_id",
        "suppliers": "supplier_id",
        "purchase_orders": "po_id",
        "activities": "activity_id",
        "stock": "lot_id",
        "drawings": "drawing_no",
        "pipe_systems": "system",
        "crews": "crew_id",
    }
)
"""시트마다 행을 가리키는 ID 열."""

REFERENCES: Mapping[str, str] = MappingProxyType(
    {
        "ship_id": "ships",
        "zone_id": "zones",
        "block_id": "blocks",
        "spec_id": "specs",
        "supplier_id": "suppliers",
        "fabricator_id": "suppliers",
        "po_id": "purchase_orders",
        "activity_id": "activities",
        "predecessor_id": "activities",
        "exit_activity_id": "activities",
        "consumed_by_activity_id": "activities",
        "reserved_block_id": "blocks",
        "a": "parts",
        "b": "parts",
        "part_ids": "parts",
        "drawing_no": "drawings",
        "system": "pipe_systems",
    }
)
"""다른 시트의 ID를 가리키는 열 키 → 그 시트(그 시트 자신의 ID 열이면 참조가 아니다 — ID_COLUMNS)."""


def code_value(column: Column, raw: str) -> str | None:
    """코드 열의 값(한글 라벨 또는 계약 값, 공백·하이픈·밑줄·점·대소문자 무시) → 계약 값. 모르면 None."""
    wanted = code_key(raw)
    for value, label in column.codes.items():
        if wanted in (code_key(value), code_key(label), *(code_key(old) for old in column.aliases.get(value, ()))):
            return value
    return None


# ---------- 상태 올리기(바뀌는 시트만, docs/input.md(엑셀 양식) 5절) ----------

STATUS_COLUMNS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "purchase_orders": (
            "po_id",
            "planned_order_date",
            "material_secured_days",
            "fabrication_start_days",
            "lead_time_days",
            *ENTERED_COLUMNS.values(),
        ),
        "observations": ("po_id", "status", "observed_on"),
        "activities": ("activity_id", "actual_start", "actual_finish"),
        "activity_checks": ("activity_id", "state", "confirmed_on"),
    }
)
"""상태 올리기에서 읽는 시트와 열: 발주는 계획 열(납기)·확인된 진입일, 공정은 실적만.
구조(부재·블록·공정 순서)는 읽지 않는다."""
STATUS_REQUIRED = frozenset({"po_id", "activity_id", "status", "observed_on", "state", "confirmed_on"})
"""상태 올리기의 필수 열: ID와 관측·확인 행의 값. 나머지는 빈 칸 = 그 값은 바꾸지 않음."""


def _status_sheet(key: str) -> Sheet:
    base = SHEET_BY_KEY[key]
    keep = STATUS_COLUMNS[key]
    columns = tuple(
        replace(column, required=column.key in STATUS_REQUIRED) for column in base.columns if column.key in keep
    )
    return replace(base, columns=columns, required=False, needs_rows=False, quiet=True)


STATUS_SHEETS: tuple[Sheet, ...] = tuple(_status_sheet(key) for key in STATUS_COLUMNS)
