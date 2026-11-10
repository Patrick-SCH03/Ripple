"""원문 설계변경 번호 → 기록 ID(ECN_ID_PATTERN을 지키는 단사 변환, 순수 계산).

원문 번호에는 한글·공백·'/'가 올 수 있어 그대로는 기록 ID가 되지 못한다. 영문·숫자·'._-'만 남기고(나머지는 '-'),
원문 번호의 해시 6자를 붙여 다른 원문 번호가 같은 ID로 합쳐지지 않게 한다. 원문은 요청의 source.ecn_ref에 그대로 둔다.
"""

from __future__ import annotations

import hashlib
import re

_NOT_ALLOWED = re.compile(r"[^A-Za-z0-9._-]+")
_LEADING_ECN = re.compile(r"^(?:ECN|ECO|DCN|EC)[-_.]*", re.I)
_BODY_LIMIT = 52
"""'ECN-' + 몸통 + '-' + 해시 6자가 기록 ID 상한(64자) 안에 들도록 자르는 길이."""


def ecn_id_for(ecn_ref: str | None, document_seed: str) -> str:
    """원문 번호가 있으면 그 번호로, 없으면 문서 내용(document_seed)으로 만든 기록 ID."""
    if ecn_ref and ecn_ref.strip():
        ref = ecn_ref.strip().upper()  # same_ref와 같게: 대소문자만 다른 번호는 같은 ID(대문자 번호의 ID는 전과 같음)
        body = _LEADING_ECN.sub("", _NOT_ALLOWED.sub("-", ref)).strip("-._")[:_BODY_LIMIT].strip("-._")
        digest = _digest(ref)
        return f"ECN-{body}-{digest}" if body else f"ECN-REF-{digest}"
    return f"ECN-DOC-{_digest(document_seed)}"


def same_ref(a: str | None, b: str | None) -> bool:
    """같은 원문 번호인가(앞뒤 공백·대소문자 무시, 둘 다 비었으면 같음)."""
    return (a or "").strip().casefold() == (b or "").strip().casefold()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:6]
