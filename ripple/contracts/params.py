"""비용 파라미터 계약(params/cost_*.yaml).

YAML은 묶음 아래에 값을 둔다. 값은 value·range를 갖고, status·source·mentor_question은
묶음에서 물려받을 수 있다. 엔진은 점 표기 키(예: "po_cancel_ratio.ordered")로 찾는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from .base import Frozen

_HEADER = ("version", "updated", "currency")
_INHERITED = ("status", "source", "mentor_question")
_LEAF = ("value", "range")


class ParamStatus(StrEnum):
    EVIDENCE = "evidence"  # 근거 있음(출처 필수)
    ASSUMPTION = "assumption"  # 가정
    MENTOR = "mentor"  # 현업 확인값


class Param(Frozen):
    key: str
    value: float
    low: float
    high: float
    status: ParamStatus
    source: str | None = None
    mentor_question: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _in_range(self) -> Param:
        if not self.low <= self.value <= self.high:
            raise ValueError(f"{self.key}: 대표값 {self.value}가 범위 [{self.low}, {self.high}] 밖")
        if self.status is ParamStatus.EVIDENCE and not self.source:
            raise ValueError(f"{self.key}: 근거 있는 값에는 출처 필요")
        return self


class ParamSet(Frozen):
    version: str = Field(pattern=r"^cost-v\d+$")
    updated: date
    currency: Literal["KRW"]
    params: dict[str, Param]

    @classmethod
    def from_tree(cls, doc: Mapping[str, Any]) -> ParamSet:
        params: dict[str, Param] = {}
        for key, node in doc.items():
            if key not in _HEADER:
                _collect(key, node, {}, params)
        return cls.model_validate({**{k: doc.get(k) for k in _HEADER}, "params": params})

    def get(self, key: str) -> Param:
        try:
            return self.params[key]
        except KeyError:
            raise KeyError(f"파라미터 {self.version}에 {key} 없음") from None

    def value(self, key: str) -> float:
        return self.get(key).value

    def group(self, prefix: str) -> dict[str, Param]:
        """묶음 바로 아래 값들을 마지막 키 이름으로 돌려준다."""
        head = f"{prefix}."
        return {k[len(head) :]: p for k, p in self.params.items() if k.startswith(head) and "." not in k[len(head) :]}


def _collect(path: str, node: object, inherited: dict[str, Any], out: dict[str, Param]) -> None:
    if not isinstance(node, Mapping):
        raise ValueError(f"{path}: 값 또는 묶음 필요")
    meta = {**inherited, **{k: node[k] for k in _INHERITED if k in node}}
    if "value" in node:
        extra = set(node) - set(_LEAF) - set(_INHERITED)
        if extra:
            raise ValueError(f"{path}: 알 수 없는 항목 {sorted(extra)}")
        low, high = node["range"]
        out[path] = Param(key=path, value=node["value"], low=low, high=high, **meta)
        return
    for key, child in node.items():
        if key not in _INHERITED:
            _collect(f"{path}.{key}", child, meta, out)
