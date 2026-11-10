"""Claude 어댑터(Messages API를 httpx로 직접). 구조화 출력(output_config.format json_schema)만 쓰고
재시도는 하지 않는다(실패하면 경로가 다음 모델로 넘긴다).

키는 환경 변수 ANTHROPIC_API_KEY(없으면 저장소 루트 .env)에서만 읽는다. 오류 메시지·기록에는 실패 종류만 남긴다
(키·프롬프트·응답 원문 없음). 숫자·판정은 엔진만 만든다 — 이 모델은 고르기·다시 쓰기만.
"""

from __future__ import annotations

import copy
import json
import os
import time
from collections import deque
from collections.abc import Mapping
from pathlib import Path

import httpx

from ripple.config.settings import PROJECT_ROOT

from .base import CallRecord, LlmUnavailable, Schema
from .env import read_dotenv

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-5-5"
# 5.5 모델은 적응형 생각이 기본이고 생각 토큰도 max_tokens에 들어간다(Haiku 5.5 설명 고르기 한 번에 생각 477토큰 실측).
# 답은 짧아도 생각할 자리를 남긴다. 끝나지 않으면(max_tokens) 실패로 본다.
MAX_TOKENS = 8192
# output_config.effort(없으면 모델 기본: Haiku·Opus 5.5 medium, Sonnet 5.5 high)
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def strict_schema(schema: Schema) -> dict[str, object]:
    """Claude 구조화 출력용: 모든 object에 additionalProperties: false(필수). 원본은 바꾸지 않는다."""

    def visit(node: object) -> object:
        if isinstance(node, dict):
            out = {key: visit(value) for key, value in node.items()}
            if out.get("type") == "object":
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [visit(item) for item in node]
        return node

    result = visit(copy.deepcopy(dict(schema)))
    assert isinstance(result, dict)
    return result


class ClaudeModel:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        client: httpx.Client | None = None,
        effort: str | None = None,
    ) -> None:
        if effort is not None and effort not in EFFORTS:
            raise ValueError(f"effort는 {', '.join(EFFORTS)} 중 하나 · 받은 값 {effort!r}")
        self._key = api_key
        self._client = client or httpx.Client()
        self.model = model
        self.effort = effort
        self.name = f"{model}@{effort}" if effort else model
        self.records: deque[CallRecord] = deque(maxlen=500)

    @classmethod
    def from_env(
        cls,
        model: str = DEFAULT_MODEL,
        effort: str | None = None,
        env: Mapping[str, str] | None = None,
        dotenv: Path | None = None,
    ) -> ClaudeModel | None:
        values = dict(read_dotenv(dotenv or PROJECT_ROOT / ".env"))
        values.update(os.environ if env is None else env)
        key = values.get("ANTHROPIC_API_KEY", "").strip()
        return cls(api_key=key, model=model, effort=effort) if key else None

    def generate_json(self, prompt: str, schema: Schema, timeout_s: float) -> object:
        output: dict[str, object] = {"format": {"type": "json_schema", "schema": strict_schema(schema)}}
        if self.effort is not None:
            output["effort"] = self.effort
        body = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": output,
        }
        headers = {"x-api-key": self._key, "anthropic-version": API_VERSION, "content-type": "application/json"}
        started = time.perf_counter()
        usage: dict[str, object] = {}
        try:
            try:
                response = self._client.post(API_URL, headers=headers, json=body, timeout=timeout_s)
            except httpx.HTTPError as error:  # 네트워크·시간 초과: 키나 원문을 메시지에 넣지 않는다
                raise LlmUnavailable(f"Claude 호출 실패({type(error).__name__})") from None
            if response.status_code != 200:
                raise LlmUnavailable(f"Claude 호출 실패(HTTP {response.status_code} {_error_type(response)})")
            data = response.json()
            if not isinstance(data, dict):
                raise LlmUnavailable("Claude 응답 형식 불일치")
            usage = data.get("usage") or {}
            if data.get("stop_reason") != "end_turn":
                raise LlmUnavailable(f"Claude 응답 미완료({data.get('stop_reason')})")
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                raise LlmUnavailable("Claude 응답이 JSON 아님") from None
        except LlmUnavailable as error:
            self._record(False, str(error), started, usage)
            raise
        except ValueError:  # 응답 본문이 JSON이 아님
            self._record(False, "body", started, usage)
            raise LlmUnavailable("Claude 응답 본문 읽기 실패") from None
        self._record(True, "", started, usage)
        return parsed

    def _record(self, ok: bool, error: str, started: float, usage: Mapping[str, object]) -> None:
        def count(*keys: str) -> int | None:
            values = [usage.get(k) for k in keys]
            numbers = [v for v in values if isinstance(v, int)]
            return sum(numbers) if numbers else None

        self.records.append(
            CallRecord(
                provider="claude",
                model=self.name,
                ok=ok,
                error=error,
                latency_s=time.perf_counter() - started,
                input_tokens=count("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"),
                output_tokens=count("output_tokens"),
            )
        )


def _error_type(response: httpx.Response) -> str:
    """오류 응답의 유형만(메시지 원문은 넣지 않는다)."""
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return ""
    kind = error.get("type")
    return str(kind) if isinstance(kind, str) else ""
