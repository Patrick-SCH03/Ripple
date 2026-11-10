"""합성 지도와 ECN에서 독립적으로 한국어 요청 문장과 조각 정답을 만든다(docs/data.md(생성기) 7절).

모듈: lexicon(생성기 문장 사전) · pieces(문장 조각) · targets(대상 표기) · values(값 표기) · render(문장 조립) ·
samples(분할별 사례).
"""

from .lexicon import NlLexicon, load_nl_lexicon
from .samples import nl_samples, nl_samples_for_ecns

__all__ = ["NlLexicon", "load_nl_lexicon", "nl_samples", "nl_samples_for_ecns"]
