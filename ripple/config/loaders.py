"""규칙표·파라미터·강도 규칙·판단 계층·해석기 사전 YAML을 읽어 계약 모델로 만든다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ripple.contracts.contacts import ContactBook
from ripple.contracts.decision import DecisionConfig
from ripple.contracts.lexicon import Lexicon
from ripple.contracts.params import ParamSet
from ripple.contracts.rulebook import RuleBook
from ripple.contracts.strength import StrengthRules
from ripple.contracts.translation import Glossary


def read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: 최상위가 키-값 묶음 아님")
    return data


def load_rulebook(path: Path) -> RuleBook:
    return RuleBook.model_validate(read_yaml(path))


def load_params(path: Path) -> ParamSet:
    return ParamSet.from_tree(read_yaml(path))


def load_strength(path: Path) -> StrengthRules:
    return StrengthRules.model_validate(read_yaml(path))


def load_decision_config(path: Path) -> DecisionConfig:
    return DecisionConfig.model_validate(read_yaml(path))


def load_lexicon(path: Path) -> Lexicon:
    return Lexicon.model_validate(read_yaml(path))


def load_contacts(path: Path) -> ContactBook:
    """시연용 가상 연락처(합성 지도 전용). 이메일이 예약 도메인이 아니면 계약 검증이 거부한다."""
    return ContactBook.model_validate(read_yaml(path))


def load_glossary(path: Path) -> Glossary:
    """현장 통보문 번역 초안의 언어별 문장·용어집(1.36.0). 언어마다 빠진 문장·용어가 있으면 계약 검증이 거부한다."""
    return Glossary.model_validate(read_yaml(path))
