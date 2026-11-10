"""앱이 한 번 읽어 두고 요청마다 쓰는 것들."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ripple.config.loaders import (
    load_contacts,
    load_decision_config,
    load_glossary,
    load_lexicon,
    load_params,
    load_rulebook,
    load_strength,
)
from ripple.config.settings import Settings
from ripple.contracts.contacts import ContactBook
from ripple.contracts.decision import DecisionConfig
from ripple.contracts.lexicon import Lexicon
from ripple.contracts.params import ParamSet
from ripple.contracts.rulebook import RuleBook
from ripple.contracts.strength import StrengthRules
from ripple.contracts.translation import Glossary
from ripple.explain.translate import glossary_problems
from ripple.ingest.fields import FieldDictionary, default_fields
from ripple.ingest.proposal import ColumnModel


@dataclass(frozen=True, slots=True)
class AppContext:
    settings: Settings
    rulebook: RuleBook
    params: ParamSet
    decision: DecisionConfig
    lexicon: Lexicon
    strength: StrengthRules
    columns: ColumnModel  # 엑셀 열 문 보정 산출물(params/column_v1.yaml)
    fields: FieldDictionary  # 엑셀 필드 사전(rules/excel_fields.yaml)
    contacts: ContactBook  # 알림 메일의 시연용 가상 연락처(합성 지도에만 붙인다)
    glossary: Glossary  # 1.36.0 현장 통보문 번역 초안(작업반 메일, 외부 AI 없음 — 데이터 모드와 무관)

    @classmethod
    def load(cls, settings: Settings) -> AppContext:
        return cls(
            settings=settings,
            rulebook=load_rulebook(settings.rules_path),
            params=load_params(settings.params_path),
            decision=load_decision_config(settings.decision_path),
            lexicon=load_lexicon(settings.lexicon_path),
            strength=load_strength(settings.strength_path),
            columns=ColumnModel.of(load_decision_config(settings.column_path)),
            fields=default_fields(),
            contacts=load_contacts(settings.contacts_path),
            glossary=_glossary(settings),
        )


def _glossary(settings: Settings) -> Glossary:
    glossary = load_glossary(settings.glossary_path)
    problems = glossary_problems(glossary)
    if problems:
        raise ValueError(f"{settings.glossary_path}: 번역 문장 불완전 — {'; '.join(problems[:5])}")
    return glossary


def get_context(request: Request) -> AppContext:
    context = request.app.state.context
    if not isinstance(context, AppContext):
        raise RuntimeError("앱 컨텍스트 준비 전")
    return context
