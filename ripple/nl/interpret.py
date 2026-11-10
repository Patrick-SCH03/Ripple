"""규칙 기반 해석(docs/input.md(판단 계층) 7절): 문장 하나 → 참조·값·강종·규격·연산·의도·치수 단서.

판단은 하지 않는다. 연산·의도·대상 부재는 판단 계층(ripple.nl.questions + ripple.decide)이 고르고,
나머지 슬롯은 ripple.nl.draft가 결정적 일치로 채운다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ripple.contracts.lexicon import Lexicon

from .aliases import Hit, find_aliases
from .ref_types import References
from .refs import find_references
from .text import normalize
from .value_exprs import ValueExpr, extract_values
from .values import GradeToken, find_grades
from .vocab import MapVocabulary


@dataclass(frozen=True, slots=True)
class Interpretation:
    text: str  # 정규화한 문장(원문과 위치가 같다)
    refs: References
    values: tuple[ValueExpr, ...]
    grades: tuple[GradeToken, ...]
    op_cues: tuple[Hit, ...]  # value = 연산 이름
    intent_cues: tuple[Hit, ...]  # value = 의도
    dimension_cues: tuple[Hit, ...]  # value = 치수 종류
    increase: tuple[Hit, ...]  # 올림 표현
    decrease: tuple[Hit, ...]  # 내림 표현


def interpret(text: str, vocab: MapVocabulary, lexicon: Lexicon, ship_ids: Sequence[str]) -> Interpretation:
    clean = normalize(text)
    refs = find_references(clean, vocab, lexicon, ship_ids)
    grades = tuple(find_grades(clean, lexicon.grades, refs.occupied))
    taken = [*refs.occupied, *((g.start, g.end) for g in grades)]
    values = extract_values(clean, lexicon.increase, lexicon.decrease, taken)
    references = [*((m.start, m.end) for m in refs.mentions), *(t.span for t in refs.specs)]
    kinds = [(h.start, h.end) for h in refs.kind_words]
    return Interpretation(
        text=clean,
        refs=refs,
        values=values,
        grades=grades,
        op_cues=tuple(find_aliases(clean, lexicon.ops, references)),
        intent_cues=tuple(find_aliases(clean, {k.value: v for k, v in lexicon.intents.items()}, kinds)),
        dimension_cues=tuple(find_aliases(clean, {str(k): v for k, v in lexicon.dimensions.items()}, references)),
        increase=tuple(find_aliases(clean, {"up": lexicon.increase}, references)),
        decrease=tuple(find_aliases(clean, {"down": lexicon.decrease}, references)),
    )
