"""엑셀 가져오기 계약(docs/input.md(엑셀 양식)): 품질 리포트의 문제 항목과 가져오기 결과 요약, 열 확인(매핑 제안·
덮어쓰기·확정 매핑).

문제마다 시트·행·열을 짚어 사용자가 원본 엑셀에서 바로 고칠 수 있게 한다. 오류가 하나라도 있으면 지도를 만들지
않는다(잘못 읽은 값으로 비용·일정을 계산하지 않게). 경고는 지도를 만들되 가정·확인 필요로 남긴다.

가져오기는 상태 버전 하나를 가진다: 올리면 1, 덮어쓰기(MappingOverrides)·확정 매핑 제출(MappingSubmission)마다 1씩
오르고 그 전의 읽기 결과는 무효가 된다. 확정(ImportVersion)은 지금 버전이고 그 버전에서 오류 없이 만든 지도일 때만
받는다(아니면 409 import_changed) — 고친 열 확인을 반영하지 않은 옛 결과로 지도를 바꾸지 않게.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from .base import Frozen
from .decision import DecisionAnswer


class IssueSeverity(StrEnum):
    ERROR = "error"  # 그대로는 지도를 만들 수 없음
    WARNING = "warning"  # 지도는 만들지만 가정·확인 필요


class IssueCode(StrEnum):
    MISSING_SHEET = "missing_sheet"  # 필수 시트 없음(오류) · 선택 시트 없음(경고, 그 뜻을 적음)
    MISSING_COLUMN = "missing_column"  # 필수 열 없음
    MISSING_VALUE = "missing_value"  # 필수 값 빈칸
    BAD_VALUE = "bad_value"  # 형식·코드가 맞지 않음
    DUPLICATE_ID = "duplicate_id"  # 같은 ID가 두 번
    UNKNOWN_REFERENCE = "unknown_reference"  # 다른 시트에 없는 ID를 가리킴
    INVALID_ROW = "invalid_row"  # 행의 값끼리 맞지 않음(예: 자재 확보 > 입고까지 일수)
    IGNORED_COLUMN = "ignored_column"  # 양식 항목으로 고르지 않은 열(읽지 않음, 경고)
    IGNORED_SHEET = "ignored_sheet"  # 읽지 않기로 한 시트(경고, '양식 안내' 시트 제외)
    DUPLICATE_SHEET = "duplicate_sheet"  # 같은 양식 시트로 읽히는 시트가 둘
    IGNORED_ROW = "ignored_row"  # 머리글 위 제목 행·메모 행(읽지 않음, 경고)


class ImportIssue(Frozen):
    severity: IssueSeverity
    code: IssueCode
    sheet: str | None = None  # 파일의 시트 이름(양식 시트가 없을 때는 양식 시트 이름)
    row: int | None = Field(default=None, ge=1)  # 엑셀 행 번호
    column: str | None = None  # 지정 양식의 열 이름
    file_column: str | None = None  # 파일의 열 머리글(양식과 다르게 적혔을 때 원본에서 찾게)
    message: str = Field(min_length=1)


class ImportSummary(Frozen):
    template_version: str
    file: str
    snapshot_id: str | None = None  # 오류가 있으면 None(지도를 만들지 않음)
    counts: dict[str, int] = Field(default_factory=dict)  # 시트 키 → 읽은 행 수
    missing_sheets: tuple[str, ...] = ()  # 없던 선택 시트(뜻은 문제 항목에)
    issues: tuple[ImportIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return self.snapshot_id is not None


# ---------- 열 매핑(3B 2단계, docs/input.md(엑셀 양식) 2·4절) ----------


class UnitState(StrEnum):
    """제안한 항목에 대한 원본 단위 상태."""

    NOT_NEEDED = "not_needed"  # 항목에 단위가 없고 머리글에도 없음
    # 그 열 머리글의 단위가 같은 차원이거나, 지정 양식 관례(이름이 양식과 같고 단위만 빠짐 → 양식 단위 — 위 줄 묶음·
    # 제목·메모 행에도 단위 표기가 없을 때만)
    CONFIRMED = "confirmed"
    # 단위가 필요한데 모름·바꿀 수 없음, 단위 없는 항목에 단위가 적힘, 또는 단위가 그 열 머리글이 아니라 위 줄 묶음·
    # 제목·메모 행에만 적힘(그 열 것인지 알 수 없음) — 사람이 고름
    UNRESOLVED = "unresolved"


class ColumnMethod(StrEnum):
    """열 항목을 정한 방법."""

    EXACT = "exact"  # 단위를 뺀 머리글이 양식 머리글과 같음(판단 밖, 결정적)
    DECIDED = "decided"  # 판단 계층 열 문(점수기 → 보정 확률 → 문턱·되묻기 집합)
    USER = "user"  # 사람이 열 확인 화면에서 고름


class ColumnMapping(Frozen):
    """파일 열 하나를 어떻게 읽을지: 양식 열 키(None = 읽지 않음)와 원본 단위(None = 단위 없음)."""

    position: int = Field(ge=0)  # 파일 시트의 열 위치(0부터)
    key: str | None = None
    unit: str | None = None  # 원본 단위 표기(ripple.ingest.normalize.UNITS의 키). 양식 단위로의 배율은 서버가 계산
    # 머리글에 적힌 단위를 쓰지 않음(사람이 열 확인에서 정함): 단위 없는 항목에 머리글 단위가 있거나, 머리글과 다른 원본
    # 단위로 읽을 때만 참. 거짓이면 서버는 머리글 단위와 다른 확정 매핑을 오류로 거절한다(빈 단위를 조용히 믿지 않게)
    ignore_unit: bool = False


class SheetMapping(Frozen):
    """파일 시트 하나를 어떻게 읽을지. template이 None이면 읽지 않는다."""

    file_sheet: str
    template: str | None = None  # 양식 시트 키(ripple.ingest.template.SHEETS)
    header_rows: tuple[int, ...] = Field(default=(), max_length=2)  # 머리글 행(엑셀 행 번호, 위에서 아래로)
    columns: tuple[ColumnMapping, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> SheetMapping:
        if self.template is not None and not self.header_rows:
            raise ValueError("읽는 시트에 머리글 행 필요")
        if list(self.header_rows) != sorted(set(self.header_rows)) or any(r < 1 for r in self.header_rows):
            raise ValueError("머리글 행은 1행부터, 위에서 아래 순서로 한 번씩만 가능")
        if len(self.header_rows) == 2 and self.header_rows[1] != self.header_rows[0] + 1:
            raise ValueError("두 줄 머리글은 붙어 있는 두 행만 가능(사이 행을 조용히 빼지 않게)")
        positions = [c.position for c in self.columns]
        if len(positions) != len(set(positions)):
            raise ValueError("같은 열 중복 기입")
        return self


class ConfirmedMapping(Frozen):
    """사용자가 확인한 매핑(열 확인 화면의 '이대로 읽기')."""

    sheets: tuple[SheetMapping, ...]

    @model_validator(mode="after")
    def _unique(self) -> ConfirmedMapping:
        names = [s.file_sheet for s in self.sheets]
        if len(names) != len(set(names)):
            raise ValueError("같은 파일 시트 중복 기입")
        return self


# ---------- 열 확인 화면(제안·덮어쓰기·제출) ----------


class UnitOption(Frozen):
    """고를 수 있는 원본 단위와 양식 단위로의 배율(예: m → mm ×1000)."""

    unit: str = Field(min_length=1)
    factor: float = Field(gt=0)


class TemplateField(Frozen):
    """양식 열 하나(화면의 항목 고르기)."""

    key: str
    header: str  # 양식 머리글(단위 뺌)
    title: str  # 단위를 붙인 머리글(예: '두께(mm)')
    required: bool
    kind: str  # text · int · float · date · bool · code · list
    unit: str = ""  # 양식 단위(없으면 빈 글)
    units: tuple[UnitOption, ...] = ()  # 고를 수 있는 원본 단위(같은 차원)


class TemplateSheet(Frozen):
    key: str
    name: str
    required: bool
    columns: tuple[TemplateField, ...]


class PreviewRow(Frozen):
    """시트 앞 행(머리글 행 고르기용). 값은 글로, 빈칸은 None."""

    row: int = Field(ge=1)
    cells: tuple[str | None, ...]


class ColumnProposal(Frozen):
    """파일 열 하나의 제안."""

    position: int = Field(ge=0)
    letter: str = Field(min_length=1)  # 엑셀 열 문자(A, B, …)
    header: str | None = None  # 파일 머리글(두 줄이면 합친 이름)
    samples: tuple[str, ...] = Field(default=(), max_length=3)  # 앞 행 예시 값
    key: str | None = None  # 제안한 양식 열 키(None = 읽지 않음)
    method: ColumnMethod
    answer: DecisionAnswer | None = None  # 판단 계층 답(판단 열만: 확률·되묻기 집합·경로)
    # 원본 단위 표기: 단위 상태가 확인됨이면 그 단위(지정 양식 관례면 양식 단위), 아니면 머리글에서 읽은 단위
    # (사람이 다른 항목을 고를 때 미리 채울 값). 확정 매핑에는 확인됨일 때만 싣는다
    unit: str | None = None
    # 머리글에 실제로 적힌 단위 표기(두 줄 머리글이면 위 줄 묶음 단위까지, 없으면 None). 확정 매핑이 이와 다르면
    # ignore_unit을 실어야 서버가 받는다
    header_unit: str | None = None
    unit_state: UnitState
    factor: float | None = Field(default=None, gt=0)  # 원본 → 양식 단위 배율
    auto: bool = False  # 확인 없이 채움(자동 진행)
    problems: tuple[str, ...] = ()  # 확인할 이유(화면 문구)


class SheetProposal(Frozen):
    """파일 시트 하나의 제안. template이 None이면 읽지 않음."""

    file_sheet: str
    template: str | None = None
    candidates: tuple[str, ...] = ()  # 양식 시트 후보(점수 순)
    certain: bool  # 시트·머리글 행이 확실(아니면 사람이 명시적으로 고름)
    header_rows: tuple[int, ...] = Field(default=(), max_length=2)
    reasons: tuple[str, ...] = ()  # 확실하지 않은 이유
    preview: tuple[PreviewRow, ...] = ()
    columns: tuple[ColumnProposal, ...] = ()
    missing_required: tuple[str, ...] = ()  # 제안에 없는 필수 양식 열 키
    # 열 머리글 밖의 단위 표기(제목·메모 행의 '(단위: 천원)' 등). 있으면 단위 없는 열을 양식 단위로 짐작하지 않는다
    unit_notes: tuple[str, ...] = ()


class MappingProposal(Frozen):
    """엑셀 파일 하나의 매핑 제안(열 확인 화면)."""

    import_id: str = Field(min_length=1)
    file: str
    version: int = Field(ge=1)  # 가져오기 상태 버전
    exact: bool  # 지정 양식 그대로(모든 시트·열이 정확 일치·자동 진행)
    pending: int = Field(ge=0)  # 사람이 확인할 것 수(확실하지 않은 시트 + 자동 진행이 아닌 열)
    sheets: tuple[SheetProposal, ...]
    template: tuple[TemplateSheet, ...]  # 고를 수 있는 양식 시트·열
    policy_version: str  # 열 문 보정 산출물 판(column-vN)
    calibration: str  # 보정 근거 표시(예: 합성 변형 엑셀 기준 보정)
    # 1.22.0 같은 모양(시트·머리글·단위 안내)의 파일로 전에 확정한 매핑.
    # 있으면 화면이 열 확인 없이 이 매핑으로 바로 읽는다
    remembered: ConfirmedMapping | None = None
    remembered_from: str | None = None  # 그 매핑을 확정한 파일 이름


class SheetOverride(Frozen):
    """사람이 정한 시트 상태: template None = 읽지 않음. 머리글 행을 비우면 표 찾기가 그 양식 시트로 다시 찾는다."""

    file_sheet: str
    template: str | None = None
    header_rows: tuple[int, ...] | None = Field(default=None, min_length=1, max_length=2)


class MappingOverrides(Frozen):
    version: int = Field(ge=1)  # 화면이 아는 가져오기 상태 버전(지금 것이 아니면 409)
    sheets: tuple[SheetOverride, ...] = Field(min_length=1)


class MappingSubmission(Frozen):
    version: int = Field(ge=1)
    mapping: ConfirmedMapping


class ImportVersion(Frozen):
    """확정 요청: 화면이 확인한 읽기 결과의 버전."""

    version: int = Field(ge=1)
