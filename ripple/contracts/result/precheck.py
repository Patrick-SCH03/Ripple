"""설계변경 사전 점검 계약(1.32.0 안에서 추가, docs/engine.md(사전 점검)): 판정과 분리된 확인 항목.

연결 지도에 거는 규칙 검사(3D 형상 검사가 아님)다. 항목은 판정·총액·결정 기한·대안·평가에 들어가지 않는다.
지도에 그 규칙을 볼 정보(칼라·서포트·다른 분야 도면 등)가 없으면 지어내지 않고 '점검 불가' 항목으로 낸다.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Literal

from pydantic import Field, model_validator

from ..base import Frozen
from ..domain import Relation

PrecheckRule = Literal["P-01", "P-02", "P-03", "P-04", "P-05", "P-06"]

PRECHECK_RULE_NAMES: Mapping[str, str] = MappingProxyType(
    {
        "P-01": "설치 시점",
        "P-02": "관통부 정합",
        "P-03": "블록 경계 연결",
        "P-04": "분야 간 도면",
        "P-05": "새 스풀 서포트",
        "P-06": "현장 공유",
    }
)
"""규칙 ID → 규칙 이름(화면·결정 도우미·합성 NCR 유형이 같이 쓴다)."""

UNCHECKED_FINDING = "점검 불가"
PRECHECK_TEXT_MAX = 220
"""항목 글 상한: 결정 도우미가 '사전 점검 <무엇>: <글> 같은 유형 합성 NCR n건(…)'으로 써도 300자 안에 들게."""


class PrecheckLevel(StrEnum):
    """확인 항목의 수준. 결정 도우미는 확인 필요 → 주의 → 점검 불가 순으로 후보에 넣는다."""

    CHECK = "check"  # 확인 필요(빠졌거나 알려야 하는 것 — 설계·현장에 확인)
    CAUTION = "caution"  # 주의(이 변경으로 생기는 작업·제약을 알고 결정)
    UNCHECKED = "unchecked"  # 점검 불가(지도에 그 규칙을 볼 정보가 없음)


EvidenceRelation = Relation | Literal["secondary_drawing", "performed_by"]
"""근거 연결: 지도 관계, 부재 → 다른 분야 도면(secondary_drawing), 공정 → 수행 주체(performed_by)."""


class PrecheckLink(Frozen):
    """근거 연결 하나(엔터티 → 엔터티). virtual = 이 변경이 더하는 연결(변경 후 보기)."""

    src: str = Field(min_length=1)
    dst: str = Field(min_length=1)
    relation: EvidenceRelation
    virtual: bool = False


class PrecheckItem(Frozen):
    """사전 점검 항목 하나: 규칙 · 수준 · 대상 · 근거(연결) · 이 건의 한 줄 · 위험 이유 · 같은 유형 합성 NCR 건수."""

    key: str = Field(min_length=1, max_length=200)  # 결과 안에서 고유('P-02:missing:<판 ID>')
    rule_id: PrecheckRule
    name: str = Field(min_length=1)  # 규칙 이름(PRECHECK_RULE_NAMES)
    finding: str = Field(min_length=1, max_length=40)  # 무엇이 걸렸나(예: 관통부 누락 의심)
    level: PrecheckLevel
    targets: tuple[str, ...] = ()  # 대상 엔터티 ID(부재·블록·공정·도면, 첫 것이 대표)
    evidence: tuple[PrecheckLink, ...] = ()
    text: str = Field(min_length=1, max_length=PRECHECK_TEXT_MAX)  # 이 건에서 본 것(명사형)
    reason: str = Field(min_length=1, max_length=300)  # 위험 이유 한 줄(명사형, 현업 사례 유형 — 숫자 없음)
    ncr_count: int | None = Field(default=None, ge=0)  # 같은 유형 합성 NCR 건수(합성 묶음(시연), 실데이터 모드는 None)

    @model_validator(mode="after")
    def _shape(self) -> PrecheckItem:
        if self.name != PRECHECK_RULE_NAMES[self.rule_id]:
            raise ValueError(f"사전 점검 {self.rule_id} 이름은 '{PRECHECK_RULE_NAMES[self.rule_id]}' 필요")
        if not self.key.startswith(f"{self.rule_id}:"):
            raise ValueError("사전 점검 항목 키는 규칙 ID로 시작 필요")
        if (self.level is PrecheckLevel.UNCHECKED) != (self.finding == UNCHECKED_FINDING):
            raise ValueError(f"'{UNCHECKED_FINDING}'는 점검 불가 수준에만 사용")
        if self.level is not PrecheckLevel.UNCHECKED and not self.targets:
            raise ValueError("점검한 항목에는 대상 필요")
        if any(ch.isdigit() for ch in self.reason):
            raise ValueError("위험 이유 한 줄에 숫자 불가(숫자는 분석 결과 필드에서만)")
        return self


def precheck_order(item: PrecheckItem) -> tuple[str, str]:
    """결과 안의 순서: 규칙 ID → 키(같은 입력이면 같은 순서)."""
    return item.rule_id, item.key
