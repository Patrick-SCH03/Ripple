"""설명·알림 초안 계약: 수치 블록과 글 템플릿 블록(docs/domain.md 10절, 합격 기준 E4).

LLM은 수치도 글도 직접 쓰지 않는다. 고를 수 있는 것은 두 가지다.
- 수치 블록: METRICS의 키 하나(목록 수치는 엔터티 ID까지). 렌더러가 그 키의 고정 라벨·단위·문장 틀로
  결과 필드의 값을 쓴다. 수치에 다른 이름을 붙일 자리가 없다.
- 템플릿 블록: 서버의 글 템플릿 ID 하나와 엔터티 자리에 넣을 ID. 템플릿 문장은 숫자·수량 표현이 없는
  고정 문장이고(TextBlock 검증), 부재·블록·발주는 {{e:<ID>}}로만 가리킨다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import Frozen


class MetricUnit(StrEnum):
    KRW = "krw"
    DAYS = "days"
    DATE = "date"
    COUNT = "count"


class MetricSpec(Frozen):
    label: str  # 렌더러가 붙이는 고정 이름
    unit: MetricUnit
    per_entity: bool = False  # 목록 항목이면 엔터티 ID로 고른다


METRICS: Mapping[str, MetricSpec] = MappingProxyType(
    {
        "cost.total": MetricSpec(label="총변경비용", unit=MetricUnit.KRW),
        "cost.line": MetricSpec(label="항목 비용", unit=MetricUnit.KRW, per_entity=True),
        "timing.base_cost": MetricSpec(label="기본 변경비용", unit=MetricUnit.KRW),
        "timing.deadline": MetricSpec(label="결정 기한", unit=MetricUnit.DATE),
        "schedule.max_exit_delay": MetricSpec(label="구역 출구 예상 최대 지연", unit=MetricUnit.DAYS),
        "schedule.delivery_delay": MetricSpec(label="이 변경으로 늘어난 예상 인도 지연", unit=MetricUnit.DAYS),
        "impacts.count": MetricSpec(label="영향 항목 수", unit=MetricUnit.COUNT),
        "hold.max_days": MetricSpec(label="발주 보류 가능 기간", unit=MetricUnit.DAYS, per_entity=True),
        "hold.until": MetricSpec(label="보류 유지 가능 기한", unit=MetricUnit.DATE, per_entity=True),
        "hold.avoided": MetricSpec(label="보류로 피하는 손실", unit=MetricUnit.KRW, per_entity=True),
        "alternative.total": MetricSpec(label="대안 총비용", unit=MetricUnit.KRW, per_entity=True),
        "recommendation.total": MetricSpec(label="추천 조합 총비용", unit=MetricUnit.KRW),
    }
)

ENTITY_REF = re.compile(r"\{\{e:([^{}\s]+)\}\}")

_NATIVE = "한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|스무|스물|서른|마흔|쉰|예순|일흔|여든|아흔"
_NATIVE_COUNTERS = "개|번|명|장|달|주|해|배|가지|건|척|시간|차례|군데|곳|대|줄|톤|살"
_SINO_DIGITS = "일이삼사오육칠팔구"
_SINO_UNITS = "원|일|개월|개|주|년|배|톤|건|척|명|퍼센트|프로|차|회|번|층|시간|밀리|미터|센티|킬로"
_QUANTITY_WORDS = (
    "하루|이틀|사흘|나흘|닷새|엿새|이레|여드레|아흐레|열흘|보름|절반|반나절|갑절|곱절"
    "|첫째|둘째|셋째|넷째|다섯째|한두|두세|서너|수십|수백|수천|수만|수억|몇십|몇백|몇천|퍼센트"
)
QUANTITY_EXPRESSION = re.compile(
    rf"(?<![가-힣])(?:{_NATIVE})\s?(?:{_NATIVE_COUNTERS})"  # 한 번, 두 배, 세 개, 열 장
    rf"|(?<![가-힣])[{_SINO_DIGITS}]*[십백천만억][{_SINO_DIGITS}십백천만억조]*\s?(?:{_SINO_UNITS})"  # 삼십 일, 천만 원
    rf"|(?<![가-힣])[{_SINO_DIGITS}]{{2,}}\s?(?:{_SINO_UNITS})"  # 이삼 일
    rf"|{_QUANTITY_WORDS}"
    r"|%"
)
"""글에서 수량을 뜻하는 한글 표현(아라비아 숫자는 따로 본다). 서버 템플릿과 E4 검출기가 쓴다."""


def quantity_expressions(text: str) -> tuple[str, ...]:
    """숫자(전각 포함)와 한글 수사·수량 표현 조각. 엔터티 참조({{e:ID}})는 빼고 본다."""
    bare = ENTITY_REF.sub(" ", text)
    digits = tuple(ch for ch in bare if ch.isdigit())
    return digits + tuple(m.group(0) for m in QUANTITY_EXPRESSION.finditer(bare))


class MetricBlock(Frozen):
    kind: Literal["metric"] = "metric"
    metric: str
    entity_id: str | None = None

    @model_validator(mode="after")
    def _known_metric(self) -> MetricBlock:
        spec = METRICS.get(self.metric)
        if spec is None:
            raise ValueError(f"없는 수치 키: {self.metric}")
        if spec.per_entity != (self.entity_id is not None):
            raise ValueError(f"{self.metric}: 엔터티 ID {'필요' if spec.per_entity else '불가'}")
        return self


class TextBlock(Frozen):
    """숫자·수량 표현이 없는 글. 서버 글 템플릿은 모두 이 검증을 통과해야 한다."""

    kind: Literal["text"] = "text"
    text: str = Field(min_length=1, max_length=400)

    @model_validator(mode="after")
    def _no_numbers(self) -> TextBlock:
        bare = ENTITY_REF.sub("", self.text)
        if "{{" in bare or "}}" in bare:
            raise ValueError("엔터티 참조는 {{e:<ID>}} 형식 필요")
        found = quantity_expressions(self.text)
        if found:
            raise ValueError(f"글 블록에 숫자·수량 표현 불가: {', '.join(found[:3])}")
        return self

    def entity_ids(self) -> tuple[str, ...]:
        return tuple(ENTITY_REF.findall(self.text))


class TemplateBlock(Frozen):
    """서버 글 템플릿 하나. entities는 템플릿의 엔터티 자리({0}, {1} …) 순서대로다."""

    kind: Literal["template"] = "template"
    template_id: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")
    entities: tuple[str, ...] = ()


ExplanationBlock = Annotated[MetricBlock | TemplateBlock, Field(discriminator="kind")]


class Explanation(Frozen):
    """고른 블록 목록(렌더링 전). LLM이 고르거나(llm) 기본 순서를 쓴다(template)."""

    blocks: tuple[ExplanationBlock, ...] = Field(min_length=1, max_length=40)
    source: Literal["llm", "template"]


class TextPart(Frozen):
    """블록 글의 조각: 엔터티 이름(화면의 근거 칩), 값(수치 블록의 숫자 표기), 그 밖의 글.

    화면은 조각만으로 칩과 값 강조를 그린다(글에서 이름·숫자를 다시 찾지 않는다).
    """

    text: str = Field(min_length=1)
    entity_id: str | None = None
    value: bool = False

    @model_validator(mode="after")
    def _one_role(self) -> TextPart:
        if self.entity_id is not None and self.value:
            raise ValueError("조각은 엔터티 이름과 값 중 하나만 가능")
        return self


class RenderedBlock(Frozen):
    """화면에 보이는 블록 하나. 수치 블록이면 metric, 템플릿 블록이면 template_id가 있다.

    parts를 이으면 text다. 엔터티 조각은 이 블록의 entity_ids 안에 있고, 값 조각은 수치 블록에만 있다.
    parts가 비면 글 하나로 본다.
    """

    kind: Literal["metric", "text"]
    text: str = Field(min_length=1)
    metric: str | None = None
    template_id: str | None = None
    entity_ids: tuple[str, ...] = ()
    parts: tuple[TextPart, ...] = ()

    @model_validator(mode="after")
    def _source(self) -> RenderedBlock:
        if (self.kind == "metric") != (self.metric is not None) or (self.kind == "text") != (
            self.template_id is not None
        ):
            raise ValueError("수치 블록은 수치 키, 글 블록은 템플릿 ID 필요")
        if not self.parts:
            return self
        if "".join(p.text for p in self.parts) != self.text:
            raise ValueError("조각을 이은 글과 블록 글 불일치")
        strangers = sorted({p.entity_id for p in self.parts if p.entity_id} - set(self.entity_ids))
        if strangers:
            raise ValueError(f"블록 엔터티에 없는 조각: {', '.join(strangers)}")
        if self.kind == "text" and any(p.value for p in self.parts):
            raise ValueError("값 조각은 수치 블록에만 가능")
        return self


class RenderedText(Frozen):
    blocks: tuple[RenderedBlock, ...] = Field(min_length=1, max_length=40)
    source: Literal["llm", "template"]

    def text(self) -> str:
        return " ".join(block.text for block in self.blocks)
