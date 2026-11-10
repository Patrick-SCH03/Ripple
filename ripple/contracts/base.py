"""모든 계약 모델이 공유하는 기반."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.config import JsonDict

CONTRACT_VERSION = "1.37.0"


class Frozen(BaseModel):
    """계약 모델의 기반: 만든 뒤 바뀌지 않고, 정의되지 않은 필드는 거부한다. 실수는 유한한 값만 받는다
    (JSON의 Infinity·NaN은 계산에서 서버 오류가 되므로 검증에서 422로 막는다)."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


def omittable(*names: str) -> Callable[[JsonDict, type[Any]], None]:
    """json_schema_extra: 비면 직렬화에서 빠지는 필드를 응답 스키마에서 필수도 기본값도 아니게 둔다(화면 타입이
    '없을 수 있음'(?)으로 나오게 — 기본값이 있으면 openapi-typescript가 늘 있는 필드로 만든다)."""

    def edit(schema: JsonDict, _: type[Any]) -> None:
        required = schema.get("required")
        if isinstance(required, list):
            schema["required"] = [name for name in required if name not in names]
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for name in names:
                field = properties.get(name)
                if isinstance(field, dict):
                    field.pop("default", None)

    return edit
