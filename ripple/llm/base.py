"""생성 모델 경계: JSON 하나를 받는 모델 인터페이스와 데이터 모드 차단(docs/domain.md 11절).

DataMode.REAL에서는 이 경계에서 외부 호출을 막는다(모델을 부르기 전에 LlmBlocked). 실데이터·AI Hub 원본은
외부 모델로 보내지 않는다. 키·응답 원문은 로그에 남기지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from ripple.contracts.domain import DataMode

Schema = Mapping[str, object]
Accept = Callable[[object], bool]
"""작업 검사: 모델 응답(JSON)을 그 작업이 받아들일 수 있는가(예: 다시 쓰기의 숫자 검사)."""


class LlmBlocked(RuntimeError):
    """real 모드라 외부 모델 호출을 막았다."""


class LlmUnavailable(RuntimeError):
    """키가 없거나, 시간이 지났거나, 응답이 JSON 형식이 아니다(메시지에 키·원문을 넣지 않는다)."""


@dataclass(frozen=True, slots=True)
class CallRecord:
    """외부 모델 호출 한 번의 기록(측정·비용 집계용). 키·프롬프트·응답 원문은 담지 않는다."""

    provider: str
    model: str
    ok: bool
    error: str  # 실패 종류(예외 이름·HTTP 상태·오류 유형), 성공이면 ""
    latency_s: float
    input_tokens: int | None  # 모르면 None(시간 초과 등)
    output_tokens: int | None  # 생각 토큰 포함


class JsonModel(Protocol):
    name: str

    def generate_json(self, prompt: str, schema: Schema, timeout_s: float) -> object: ...


class RoutedModel(Protocol):
    """작업별 경로를 가진 모델(ripple.llm.route.Router). 작업 이름과 작업 검사를 받는다."""

    name: str

    def generate_routed(self, task: str, prompt: str, schema: Schema, accept: Accept | None) -> object: ...


class Guarded:
    """데이터 모드 경계. real 모드면 안쪽 모델을 부르지 않는다. calls는 실제로 보낸 호출 수."""

    def __init__(self, inner: JsonModel | RoutedModel | None, data_mode: DataMode) -> None:
        self._inner = inner
        self.data_mode = data_mode
        self.calls = 0

    @property
    def name(self) -> str:
        return self._inner.name if self._inner is not None else "none"

    @property
    def usable(self) -> bool:
        return self._inner is not None and self.data_mode is DataMode.SYNTHETIC

    def generate_json(
        self,
        prompt: str,
        schema: Schema,
        timeout_s: float = 10.0,
        *,
        task: str = "default",
        accept: Accept | None = None,
    ) -> object:
        """경로가 있는 모델이면 작업 이름·작업 검사를 넘기고(시간은 경로가 정함), 아니면 한 번 부르고 검사한다."""
        if self.data_mode is not DataMode.SYNTHETIC:
            raise LlmBlocked("real 모드 — 외부 모델 호출 안 함")
        if self._inner is None:
            raise LlmUnavailable("외부 모델 미설정")
        self.calls += 1
        if hasattr(self._inner, "generate_routed"):
            return self._inner.generate_routed(task, prompt, schema, accept)
        data = self._inner.generate_json(prompt, schema, timeout_s)
        if accept is not None and not accept(data):
            raise LlmUnavailable("응답이 작업 검사 미통과")
        return data
