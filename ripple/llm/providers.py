"""설정 → 외부 생성 모델 경로: 켠 제공자(RIPPLE_LLM) 중 키가 있는 모델로 작업별 경로(params/llm_v1.yaml)를 만든다."""

from __future__ import annotations

from ripple.config.settings import Settings

from .base import JsonModel
from .claude import ClaudeModel
from .quota import FILE_NAME
from .route import Router, build_router


def make_model(provider: str, model: str, effort: str | None = None) -> JsonModel | None:
    """키가 없으면 None(그 제공자는 경로에서 빠진다). effort는 생각 깊이(없으면 모델 기본)."""
    if provider == "claude":
        return ClaudeModel.from_env(model=model, effort=effort)
    raise ValueError(f"모르는 제공자 · {provider!r}")


def router_from_settings(settings: Settings) -> Router | None:
    return build_router(settings.llm_providers, settings.llm_routes_path, make_model, settings.data_dir / FILE_NAME)
