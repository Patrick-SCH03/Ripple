"""백테스트가 쓰는 엔진 입력 묶음과 판(docs/backtest.md 5절): 규칙표·비용 파라미터·생성기 설정·백테스트 기본값.

결과 파일에 판을 적는다 — 엔진·규칙·파라미터·생성기 설정이 바뀌면 같은 사례를 다시 돌려 견주기 위해서다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ripple.config.loaders import load_params, load_rulebook
from ripple.config.settings import Settings
from ripple.contracts.base import CONTRACT_VERSION
from ripple.contracts.params import ParamSet
from ripple.contracts.rulebook import RuleBook
from ripple.engine import ENGINE_VERSION
from ripple.generator.config import GeneratorConfig
from ripple.generator.io import load_config

from .defaults import BacktestDefaults, load_defaults


@dataclass(frozen=True, slots=True)
class Engine:
    rulebook: RuleBook
    params: ParamSet
    generator: GeneratorConfig
    defaults: BacktestDefaults

    @classmethod
    def load(cls, settings: Settings | None = None, defaults: BacktestDefaults | None = None) -> Engine:
        """설정 기본 경로의 규칙표·파라미터(환경 변수는 보지 않음), 생성기 설정, 백테스트 기본값."""
        found = settings or Settings.from_env({})
        return cls(
            rulebook=load_rulebook(found.rules_path),
            params=load_params(found.params_path),
            generator=load_config(),
            defaults=defaults or load_defaults(),
        )

    def versions(self) -> tuple[tuple[str, str], ...]:
        return (
            ("엔진", ENGINE_VERSION),
            ("계약", CONTRACT_VERSION),
            ("전파 규칙", self.rulebook.version),
            ("비용 파라미터", self.params.version),
            ("생성기 설정", self.generator.version),
            ("백테스트 기본값", self.defaults.version),
        )
