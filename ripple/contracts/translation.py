"""현장 통보문 번역 초안 계약(1.36.0, docs/records.md(통보) 6절).

결재 뒤 사내 협력사 작업반에 보내는 통보 메일(사전 점검 P-06)을 한국어 원문과 함께 다른 언어로 보여 준다.
번역은 외부 AI 없이 결정적이다: 서버 글 템플릿 ID마다 언어별 문장(Glossary.sentences)에 값을 끼우고, 엔터티 이름의
조선 용어는 고정 용어집(Glossary.terms)으로 바꾼다. 용어집에 없는 말과 자유 문장(변경 제목)은 한국어 원문 그대로 둔다.
언어를 더하려면 데이터 파일(params/glossary_v1.yaml)의 languages에 코드 하나와 모든 문장·용어에 그 언어 값을 넣는다.
"""

from __future__ import annotations

import re

from pydantic import Field, model_validator

from .base import Frozen
from .explain import RenderedText, quantity_expressions

LANGUAGE_CODE = r"^[a-z]{2,3}$"
SLOT = re.compile(r"\{(\d+)\}")


class LanguageSpec(Frozen):
    """번역 언어 하나: 그 언어로 쓴 이름(언어 고르기 단추)·번역본 머리 표기 문장·원문 유지 표시."""

    name: str = Field(min_length=1, max_length=40)  # 'English', 'Tiếng Việt'
    notice: str = Field(min_length=1, max_length=400)  # 번역 초안이고 원문이 우선한다는 그 언어 문장
    original_mark: str = Field(min_length=1, max_length=40)  # 원문 그대로 둔 자유 문장 앞 표시('[Korean]')


class Glossary(Frozen):
    """언어별 문장 템플릿 + 고정 용어집(데이터 파일 하나). 문장·용어마다 모든 언어 값이 있어야 한다."""

    version: str
    notice_ko: str = Field(min_length=1, max_length=400)  # 번역본 머리의 한국어 문장(합니다체)
    languages: dict[str, LanguageSpec] = Field(min_length=1)
    sentences: dict[str, dict[str, str]]  # 템플릿 ID·머리 키 → 언어 → 문장({0} 자리는 한국어 템플릿과 같은 수)
    metrics: dict[str, dict[str, str]]  # 수치 키 → 언어 → 라벨
    terms: dict[str, dict[str, str]]  # 한국어 조선 용어 → 언어 → 번역(파일 순서가 '주요 용어' 순서)

    @model_validator(mode="after")
    def _complete(self) -> Glossary:
        codes = set(self.languages)
        bad = sorted(code for code in codes if not re.match(LANGUAGE_CODE, code))
        if bad:
            raise ValueError(f"언어 코드는 영문 소문자 2~3자: {', '.join(bad)}")
        problems: list[str] = []
        for section, table in (("sentences", self.sentences), ("metrics", self.metrics), ("terms", self.terms)):
            for key, texts in table.items():
                missing = sorted(codes - set(texts))
                extra = sorted(set(texts) - codes)
                if missing or extra:
                    problems.append(f"{section}.{key}: 빠진 언어 {missing} · 없는 언어 {extra}")
                empty = sorted(code for code, text in texts.items() if not text.strip())
                if empty:
                    problems.append(f"{section}.{key}: 빈 값 {empty}")
        for key, texts in (*self.sentences.items(), *self.metrics.items()):
            numbers = sorted(code for code, text in texts.items() if quantity_expressions(SLOT.sub(" ", text)))
            if numbers:
                problems.append(f"{key}: 문장에 숫자 불가(값은 자리로만) {numbers}")
        if problems:
            raise ValueError("용어집 불완전: " + "; ".join(problems[:5]))
        return self


class MailTranslation(Frozen):
    """메일 초안 한 통의 번역 초안(1.36.0). 문단·블록은 한국어 원문과 하나씩 맞고(같은 템플릿 ID·수치 키·엔터티)
    끝에 '주요 용어' 문단 하나를 더 둔다. 숫자·블록 번호·날짜 값은 원문과 같다(날짜는 YYYY-MM-DD)."""

    language: str = Field(pattern=LANGUAGE_CODE)
    language_name: str = Field(min_length=1, max_length=40)
    notice: str = Field(min_length=1, max_length=400)  # 그 언어로 쓴 번역 초안 표기
    notice_ko: str = Field(min_length=1, max_length=400)  # 한국어 표기(합니다체)
    subject: str = Field(min_length=1, max_length=300)
    salutation: str = Field(min_length=1, max_length=200)
    reference_label: str = Field(min_length=1, max_length=40)
    reference: str = Field(min_length=1, max_length=600)
    paragraphs: tuple[RenderedText, ...] = Field(min_length=1, max_length=21)
    sign_off: str = Field(min_length=1, max_length=60)
    sender: str | None = None
    untranslated: tuple[str, ...] = ()  # 용어집에 없어 한국어 그대로 둔 말(나온 순서, 중복 없음)
