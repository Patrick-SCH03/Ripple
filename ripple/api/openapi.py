"""API 계약(OpenAPI) 렌더링. docs/api/openapi.json이 화면 타입 생성의 원본이다."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI

OPENAPI_PATH = Path("docs") / "api" / "openapi.json"


def render_openapi(app: FastAPI) -> str:
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
