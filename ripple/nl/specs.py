"""규격 표기 찾기와 결정적 해석: 규격 ID('VL-BALL-DN100-16K')와 부분 표기('HP200x10'·'DN200'·'16K').

규격은 지도의 규격 목록으로만 정한다(사전 밖 규격을 만들지 않는다). 부분 표기는 바꾸는 속성만 적은
것('볼 밸브로'·'16K로')이라 지금 규격의 나머지 속성과 합쳐 지도에서 찾고, 하나로 정해질 때만 결정적이다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ripple.contracts.domain import MaterialSpec

from .text import Span, free
from .vocab import MapVocabulary

_PROFILE = re.compile(r"(?<![A-Za-z0-9])HP\s?(?P<h>\d{3})\s?[xX×*]\s?(?P<t>\d{1,2})(?![0-9])", re.IGNORECASE)
_DN = re.compile(r"(?<![A-Za-z0-9])DN\s?(?P<dn>\d{2,3})(?![0-9])", re.IGNORECASE)
_CLASS = re.compile(r"(?<![A-Za-z0-9.])(?P<k>\d{1,2})\s?K(?![A-Za-z0-9])")
_SCHEDULE = re.compile(r"(?<![A-Za-z0-9])(?:SCH\s?|S)(?P<s>\d{2,3})(?![A-Za-z0-9])", re.IGNORECASE)
_COUNT = re.compile(r"\s?(?:[x×*]\s?(?P<a>\d{1,2})(?![\d.])|(?P<b>\d{1,2})\s?(?:개|EA|ea|본|pcs|PCS))")
_VALVE_ID = re.compile(r"^VL-(?P<type>[A-Z]+)-DN(?P<dn>\d+)-(?P<k>\d+K)$")
_SECTION_ID = re.compile(r"^(?P<profile>HP\d+x\d+)-(?P<grade>[A-Z0-9]+)$")
_SPOOL_ID = re.compile(r"^SP-DN(?P<dn>\d+)-S(?P<s>\d+)$")


@dataclass(frozen=True, slots=True)
class SpecToken:
    start: int
    end: int
    spec_id: str | None  # 규격 ID를 그대로 썼으면 그 규격
    attrs: dict[str, str] = field(default_factory=dict)  # 부분 표기 속성: profile·dn·pclass·sch·grade
    count: int | None = None  # 바로 뒤 개수('3개')

    @property
    def span(self) -> Span:
        return (self.start, self.end)


def find_spec_tokens(text: str, vocab: MapVocabulary, occupied: Sequence[Span] = ()) -> list[SpecToken]:
    """규격 ID를 먼저(긴 것부터), 그다음 부분 표기를 찾는다. 겹치지 않는다."""
    taken = list(occupied)
    found: list[SpecToken] = []
    for spec_id in sorted(vocab.specs, key=len, reverse=True):
        parts = re.split(r"[\-_]", spec_id)
        pattern = r"(?<![A-Za-z0-9])" + r"[\s\-_]?".join(re.escape(p) for p in parts) + r"(?![A-Za-z0-9])"
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            if free(match.span(), taken):
                found.append(_with_count(text, SpecToken(match.start(), match.end(), spec_id)))
                taken.append(match.span())
    for regex, name in ((_PROFILE, "profile"), (_DN, "dn"), (_CLASS, "pclass"), (_SCHEDULE, "sch")):
        for match in regex.finditer(text):
            if not free(match.span(), taken):
                continue
            if name == "profile":
                value = f"HP{match.group('h')}x{match.group('t')}"
            else:
                value = match.group(match.lastgroup or "")
            attrs = {name: value if name != "pclass" else f"{value}K"}
            found.append(_with_count(text, SpecToken(match.start(), match.end(), None, attrs)))
            taken.append(match.span())
    return sorted(found, key=lambda t: t.start)


def _with_count(text: str, token: SpecToken) -> SpecToken:
    match = _COUNT.match(text, token.end)
    if not match:
        return token
    count = int(match.group("a") or match.group("b"))
    return SpecToken(token.start, match.end(), token.spec_id, token.attrs, count)


def valve_attrs(spec: MaterialSpec) -> dict[str, str] | None:
    """밸브 규격 ID에서 종류·구경·압력 등급(생성기·지정 양식 형식일 때)."""
    match = _VALVE_ID.match(spec.spec_id)
    if not match:
        return None
    return {"valve_type": match.group("type").lower(), "dn": match.group("dn"), "pclass": match.group("k")}


def section_attrs(spec: MaterialSpec) -> dict[str, str] | None:
    match = _SECTION_ID.match(spec.spec_id)
    return {"profile": match.group("profile"), "grade": match.group("grade")} if match else None


def spool_attrs(spec: MaterialSpec) -> dict[str, str] | None:
    match = _SPOOL_ID.match(spec.spec_id)
    return {"dn": match.group("dn"), "sch": match.group("s")} if match else None


@dataclass(frozen=True, slots=True)
class SpecChoice:
    """규격 해석 결과: 하나로 정해지면 spec_id, 아니면 후보(비면 못 찾음)."""

    spec_id: str | None
    candidates: tuple[str, ...]
    span: Span | None
    reason: str | None = None


def resolve_valve_target(
    vocab: MapVocabulary,
    tokens: Sequence[SpecToken],
    current_spec_id: str | None,
    new_valve_type: str | None,
    part_phrases: Sequence[Span] = (),
) -> SpecChoice:
    """장비 사양 변경의 바꿀 규격: 규격 ID를 썼으면 그것, 아니면 지금 규격 + 바꾼 속성으로 지도에서 찾는다.

    구경·압력 등급('DN200'·'10K')은 자리로 역할을 나눈다. 대상 부재 표현의 구절 안('DN100 글로브 밸브 1번')에
    적은 것은 그 부재의 지금 규격 설명이라 지금 규격과 맞아야 하고, 그 밖('DN200 10K 체크 밸브로'·'구경은 DN200
    유지')은 바꿀 규격의 조건이다(어순과 상관없이).
    규격 ID와 함께 적은 조건·밸브 종류 설명('체크 밸브로')이 바꿀 규격과 어긋나면 하나로 정하지 않는다
    (규격 ID만 믿고 버리지 않는다).
    """
    attributes = [t for t in tokens if t.spec_id is None and t.attrs.keys() & {"dn", "pclass"}]
    described = [t for t in attributes if any(start <= t.start and t.end <= end for start, end in part_phrases)]
    conditions = [t for t in attributes if t not in described]
    current = vocab.specs.get(current_spec_id or "")
    base = valve_attrs(current) if current is not None else None
    if any(base is not None and any(base.get(k) != v for k, v in _pairs(t)) for t in described):
        others = tuple(sorted(s.spec_id for s in vocab.specs.values() if s.category == "valve"))
        return SpecChoice(None, others, described[0].span, "부재를 설명한 구경·압력 등급이 지도의 지금 규격과 다름")
    explicit = [t for t in tokens if t.spec_id and vocab.specs[t.spec_id].category == "valve"]
    if explicit:
        return _explicit_valve(vocab, explicit, conditions, current_spec_id, new_valve_type)
    return _valve_by_attributes(vocab, conditions, base, current_spec_id, new_valve_type)


def _explicit_valve(
    vocab: MapVocabulary,
    explicit: Sequence[SpecToken],
    conditions: Sequence[SpecToken],
    current_spec_id: str | None,
    new_valve_type: str | None,
) -> SpecChoice:
    """규격 ID를 적었을 때: 지금 규격과 다른 것 하나. 함께 적은 조건과 어긋나면 맞는 후보를 더해 묻는다."""
    targets = [t for t in explicit if t.spec_id != current_spec_id] or explicit
    ids = tuple(dict.fromkeys(t.spec_id for t in targets if t.spec_id))
    span = (targets[0].start, targets[0].end)
    if len(ids) > 1:
        return SpecChoice(None, ids, span, "바꿀 규격 여럿")
    stated = [pair for t in conditions for pair in _pairs(t)]
    if _conflicts(vocab, ids[0], stated, new_valve_type):
        wanted = {**dict(stated), **({"valve_type": new_valve_type} if new_valve_type else {})}
        fitting = _valves_with(vocab, wanted)
        reason = "규격 ID와 어긋나는 구경·압력 등급·밸브 종류 있음"
        return SpecChoice(None, tuple(dict.fromkeys([*ids, *fitting])), span, reason)
    return SpecChoice(ids[0], ids, span)


def _valve_by_attributes(
    vocab: MapVocabulary,
    conditions: Sequence[SpecToken],
    base: dict[str, str] | None,
    current_spec_id: str | None,
    new_valve_type: str | None,
) -> SpecChoice:
    """규격 ID 없이 속성만 적었을 때: 지금 규격(base) + 바꾼 속성으로 지도에서 하나를 찾는다."""
    changes = dict(pair for t in conditions for pair in _pairs(t))
    if new_valve_type:
        changes["valve_type"] = new_valve_type
    spans = [t.span for t in conditions]
    attr_span = (min(s[0] for s in spans), max(s[1] for s in spans)) if spans else None
    if not changes:
        valves = [s for s in vocab.specs.values() if s.category == "valve"]
        return SpecChoice(
            None, tuple(sorted(s.spec_id for s in valves if s.spec_id != current_spec_id)), None, "바꿀 규격 없음"
        )
    if base is None:
        loose = _valves_with(vocab, changes)
        return SpecChoice(None, tuple(loose), attr_span, "지금 규격 불명 · 바꿀 규격 하나로 특정 불가")
    matches = _valves_with(vocab, {**base, **changes})
    if len(matches) == 1 and matches[0] != current_spec_id:
        return SpecChoice(matches[0], tuple(matches), attr_span)
    near = _valves_with(vocab, changes)
    reason = "입력한 속성에 맞는 규격이 지도에 없음" if not near else "입력한 속성에 맞는 규격 여럿"
    return SpecChoice(None, tuple(near), attr_span, reason)


def _valves_with(vocab: MapVocabulary, wanted: Mapping[str, str]) -> list[str]:
    """속성(종류·구경·압력 등급)이 모두 맞는 밸브 규격 ID(정렬)."""
    return sorted(
        s.spec_id
        for s in vocab.specs.values()
        if s.category == "valve"
        and (attrs := valve_attrs(s)) is not None
        and all(attrs.get(k) == v for k, v in wanted.items())
    )


def _pairs(token: SpecToken) -> list[tuple[str, str]]:
    return [(k, v) for k, v in token.attrs.items() if k in ("dn", "pclass")]


def _conflicts(
    vocab: MapVocabulary, target_id: str, stated: Sequence[tuple[str, str]], new_valve_type: str | None
) -> bool:
    """규격 ID로 정한 바꿀 규격과 함께 적은 조건(구경·압력 등급·밸브 종류)이 어긋나는가."""
    target = valve_attrs(vocab.specs[target_id]) or {}
    if any(target.get(key) != value for key, value in stated):
        return True
    return new_valve_type is not None and target.get("valve_type") != new_valve_type


def resolve_section(vocab: MapVocabulary, tokens: Sequence[SpecToken], grade: str | None) -> SpecChoice:
    """부재 추가의 형강 규격: 규격 ID, 또는 'HP200x10' + 강종(문장에 없으면 후보 여럿)."""
    explicit = [t for t in tokens if t.spec_id and vocab.specs[t.spec_id].category == "section"]
    if explicit:
        ids = tuple(dict.fromkeys(t.spec_id for t in explicit if t.spec_id))
        span = explicit[0].span
        return SpecChoice(ids[0], ids, span) if len(ids) == 1 else SpecChoice(None, ids, span, "규격 여럿")
    profiles = [t for t in tokens if "profile" in t.attrs]
    if not profiles:
        return SpecChoice(None, (), None, "더할 부재 규격 없음")
    token = profiles[0]
    profile = token.attrs["profile"].upper().replace("X", "x")
    found = sorted(
        s.spec_id
        for s in vocab.specs.values()
        if (attrs := section_attrs(s)) is not None and attrs["profile"].upper() == profile.upper()
    )
    if grade is not None:
        exact = [i for i in found if i.endswith(f"-{grade}")]
        if len(exact) == 1:
            return SpecChoice(exact[0], tuple(exact), token.span)
    if len(found) == 1:
        return SpecChoice(found[0], tuple(found), token.span)
    return SpecChoice(None, tuple(found), token.span, "강종 미정 · 규격 후보 여럿" if found else "지도에 없는 형강")


def resolve_spools(
    vocab: MapVocabulary, tokens: Sequence[SpecToken]
) -> tuple[tuple[str, ...], Span | None, str | None]:
    """더하는 스풀 규격 목록(개수만큼 반복): 스풀 규격 ID 또는 DN 표기(지도에서 하나일 때)."""
    specs: list[str] = []
    spans: list[Span] = []
    for token in tokens:
        spec_id = token.spec_id
        if spec_id is None and "dn" in token.attrs:
            same = [
                s.spec_id
                for s in vocab.specs.values()
                if (attrs := spool_attrs(s)) is not None and attrs["dn"] == token.attrs["dn"]
            ]
            if len(same) != 1:
                return (), token.span, "그 구경의 스풀 규격 하나로 특정 불가"
            spec_id = same[0]
        if spec_id is None or vocab.specs[spec_id].category != "pipe":
            continue
        specs.extend([spec_id] * (token.count or 1))
        spans.append(token.span)
    span = (min(s[0] for s in spans), max(s[1] for s in spans)) if spans else None
    return tuple(specs), span, None
