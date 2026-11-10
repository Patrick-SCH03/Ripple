"""참조 추출: 문장에서 부재 코드·블록 단서·부재 종류 단어·번호를 찾아 부재 표현(Mention)을 만든다.

- 부재 코드('T31C-PL-007'·'PL-007'·'VLCS-001')는 그 자체로 부재 하나를 가리킨다.
- 종류 단어('판'·'PL'·'밸브')에 붙은 번호('판 7'·'7번 판'·'판 3, 5번'·'스풀 4~5번')는 번호마다 표현 하나다.
  범위는 사이 번호까지 모두 펼친다. 거꾸로이거나 MAX_RANGE개를 넘는 범위는 양 끝만 남기지 않고
  읽지 못한 표현(unread)으로 돌려 확인받는다(번호 읽기는 part_numbers).
  번호 없는 종류 단어는 이름만으로 가리키는 표현이다('펌프룸 글로브 밸브'). 단 '로·으로'가 붙은 것
  ('볼 밸브로')은 바꿀 규격의 설명이라 표현이 아니다(targets에 따로 모은다).
- 블록 단서(블록 코드, 화물탱크 번호 '3번 탱크', 이름 단어 '횡격벽', 좌우, 배관 계통)는 뒤따르는 표현들에
  이어진다. 표현 뒤에 새 단서가 나오면 새 문맥이다.
표현의 위치(start·end)는 그 부재를 구별하는 조각(번호·코드·이름)이고, 값 추출은 참조가 차지한 자리를 뺀다.
사전 별칭 찾기(정확·오타 허용)는 aliases, 만든 값의 모양은 ref_types에 있다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from ripple.contracts.domain import PartKind
from ripple.contracts.lexicon import Lexicon

from .aliases import Hit, find_aliases, find_tagged, fuzzy_aliases
from .part_numbers import numbers_after, numbers_before
from .ref_types import Context, Cue, CueKind, Mention, References, Role, TargetDescription
from .specs import find_spec_tokens
from .text import Span, free
from .vocab import MapVocabulary

__all__ = ["find_references"]


_COT = re.compile(
    r"(?:(?:No)\.?\s?|#)?(?P<n>\d)\s?(?:번+\s?)?(?:C\.?O\.?T|코트|화물\s?탱크|카고\s?탱크|탱크)", re.IGNORECASE
)
_STANDALONE = re.compile(r"(?:(?:#|No\.?\s?|NO\.?\s?)(?P<a>\d{1,3})|(?<![\d.])(?P<b>\d{1,3})\s?번(?!째))")
_TARGET_MARK = re.compile(r"\s?(?:으로|로)")
_CODE = re.compile(
    r"(?<![A-Za-z0-9])(?:(?P<ship>S-\d{3}):)?(?:(?P<block>[A-Za-z]\d{2}[A-Za-z])[\s\-_]?)?"
    r"(?P<prefix>[A-Za-z]{2,4})[\-_]?(?P<num>\d{1,4})(?![A-Za-z0-9.])"
)
_BLOCK_CODE = re.compile(r"(?<![A-Za-z0-9\-])(?P<code>[A-Za-z]\d{2}[A-Za-z])(?![A-Za-z0-9])")


@dataclass(frozen=True, slots=True)
class _Numbered:
    hit: Hit | None  # 종류 단어(번호만 있으면 None)
    span: Span
    number: int
    listed: bool


_Token = Cue | Mention | Hit | _Numbered


def find_references(text: str, vocab: MapVocabulary, lexicon: Lexicon, ship_ids: Sequence[str]) -> References:
    specs = find_spec_tokens(text, vocab)
    occupied: list[Span] = [t.span for t in specs]
    codes = [m for m in _codes(text, vocab, ship_ids) if free(m.span, occupied)]
    occupied.extend(m.span for m in codes)
    cues = _block_codes(text, vocab, ship_ids, occupied)
    occupied.extend((c.start, c.end) for c in cues)
    cots = [Cue(m.start(), m.end(), "cot", m.group("n")) for m in _COT.finditer(text) if free(m.span(), occupied)]
    cues.extend(cots)
    occupied.extend((c.start, c.end) for c in cots)
    kind_hits = _kind_hits(text, vocab, lexicon, occupied, cues)
    numbered, bare, targets, unread = _numbered_hits(text, kind_hits, codes, occupied)

    tokens: list[tuple[int, int, _Token]] = [(c.start, 0, c) for c in cues]
    tokens += [(m.start, 1, m) for m in codes]
    tokens += [(n.hit.start if n.hit and n.hit.start < n.span[0] else n.span[0], 1, n) for n in numbered]
    tokens += [(h.start, 1, h) for h in bare]
    tokens += [(h.start, 2, h) for h in targets]
    tokens.sort(key=lambda t: (t[0], t[1]))
    mentions, descriptions = _walk(text, [t for _, _, t in tokens], {id(h) for h in targets}, vocab, lexicon, ship_ids)
    return References(
        mentions=tuple(sorted(mentions, key=lambda m: m.start)),
        cues=tuple(sorted(cues, key=lambda c: c.start)),
        occupied=tuple(sorted(occupied)),
        kind_words=tuple(kind_hits),
        targets=tuple(descriptions),
        specs=tuple(specs),
        unread=tuple(dict.fromkeys(unread)),
    )


def _walk(
    text: str,
    tokens: Sequence[_Token],
    target_ids: set[int],
    vocab: MapVocabulary,
    lexicon: Lexicon,
    ship_ids: Sequence[str],
) -> tuple[list[Mention], list[TargetDescription]]:
    """원문 순서의 조각을 따라가며 문맥(블록 단서)을 이어 붙여 표현과 바꿀 규격 설명을 만든다."""
    mentions: list[Mention] = []
    descriptions: list[TargetDescription] = []
    context = Context()
    consumed = False
    for token in tokens:
        if isinstance(token, Cue):
            if consumed:
                context, consumed = Context(), False
            context = _with_cue(context, token)
            continue
        if isinstance(token, Hit) and id(token) in target_ids:
            start = context.start if context.valve_type else token.start
            descriptions.append(
                TargetDescription(PartKind(token.value), context.valve_type, (start or token.start, token.end))
            )
            context = replace(context, valve_type=None)
            continue
        fresh, consumed = not consumed, True
        if isinstance(token, Mention):
            mention = replace(token, context=context, block_ids=token.block_ids or _blocks(context, vocab, ship_ids))
        elif isinstance(token, Hit):
            mention = _bare_mention(text, token, context, vocab, ship_ids, fresh)
        else:
            mention = _numbered_mention(text, token, context, vocab, ship_ids, fresh)
        fuzzy = (
            context.fuzzy
            or (isinstance(token, Hit) and token.fuzzy)
            or (isinstance(token, _Numbered) and token.hit is not None and token.hit.fuzzy)
        )
        mentions.append(replace(mention, role=_role(text, mention, lexicon), fuzzy=fuzzy))
        if not (isinstance(token, _Numbered) and token.listed):
            context = replace(context, valve_type=None)
    return mentions, descriptions


def _kind_hits(text: str, vocab: MapVocabulary, lexicon: Lexicon, occupied: list[Span], cues: list[Cue]) -> list[Hit]:
    known_words = vocab.block_name_words() | {"좌", "우"}
    tables: list[tuple[CueKind, dict[str, tuple[str, ...]]]] = [
        ("word", {w: a for w, a in lexicon.block_words.items() if w in known_words}),
        ("system", {s: a for s, a in lexicon.systems.items() if s in vocab.systems}),
        ("valve_type", {v: a for v, a in lexicon.valve_types.items() if v in vocab.valve_types}),
    ]
    kinds = {k.value: a for k, a in lexicon.part_kinds.items() if k in vocab.kinds}
    # 위치 표와 종류 표를 한 번에 맞춰 긴 별칭이 먼저 자리를 잡는다(같은 길이면 위치 표 먼저):
    # 계통 'C/S'의 'S'를 우현이, 종류 '서포트'의 '포트'를 좌현(port)이 먼저 잡지 않게
    tagged: list[tuple[CueKind | Literal["kind"], dict[str, tuple[str, ...]], bool]] = [
        *((k, t, False) for k, t in tables),
        ("kind", kinds, True),
    ]
    kind_hits: list[Hit] = []
    for hit, kind in find_tagged(text, tagged, occupied):
        if kind == "kind":
            kind_hits.append(hit)
        else:
            cues.append(_cue(hit, kind))
        occupied.append((hit.start, hit.end))
    # 오타 허용은 정확 일치가 끝난 뒤, 연산·의도·방향·치수 단서 자리는 피한다('보강'이 '보강재'의 오타가 아님)
    protected = [*occupied, *_cue_spans(text, lexicon, [(h.start, h.end) for h in kind_hits])]
    # 모든 표를 한 번에 비교해 덩어리마다 가장 가까운(같으면 더 긴) 별칭 하나만 고른다('레이트' → 플레이트)
    combined = {f"{kind}|{name}": aliases for kind, table in tables for name, aliases in table.items()}
    combined.update({f"kind|{name}": aliases for name, aliases in kinds.items()})
    fuzzy_kinds = []
    for hit in fuzzy_aliases(text, combined, protected):
        table_kind, name = hit.value.split("|", 1)
        if table_kind == "kind":
            fuzzy_kinds.append(Hit(hit.start, hit.end, name, fuzzy=True))
        else:
            cues.append(_cue(Hit(hit.start, hit.end, name, fuzzy=True), table_kind))  # type: ignore[arg-type]
        occupied.append((hit.start, hit.end))
    return sorted([*kind_hits, *fuzzy_kinds], key=lambda h: h.start)


def _numbered_hits(
    text: str, kind_hits: list[Hit], codes: list[Mention], occupied: list[Span]
) -> tuple[list[_Numbered], list[Hit], list[Hit], list[tuple[Span, str]]]:
    numbered: list[_Numbered] = []
    bare: list[Hit] = []
    targets: list[Hit] = []
    unread: list[tuple[Span, str]] = []
    for hit in kind_hits:
        seen = len(unread)
        found = numbers_after(text, hit.end, occupied, unread) or numbers_before(text, hit.start, occupied, unread)
        occupied.extend(span for span, _ in unread[seen:])  # 읽지 못한 범위의 번호를 따로 표현으로 만들지 않는다
        if found:
            numbered += [_Numbered(hit, span, n, listed) for span, n, listed in found]
            occupied.extend(span for span, _, _ in found)
        elif _TARGET_MARK.match(text, hit.end):
            targets.append(hit)
        elif not any(
            _near(hit, m.span) and m.kind is not None and m.kind.value == hit.value for m in codes
        ) and not any(_near(hit, n.span) and (n.hit is None or n.hit.value == hit.value) for n in numbered):
            bare.append(hit)
    for match in _STANDALONE.finditer(text):
        if free(match.span(), occupied):
            numbered.append(_Numbered(None, match.span(), int(match.group("a") or match.group("b")), False))
            occupied.append(match.span())
    return numbered, bare, targets, unread


def _cue(hit: Hit, kind: CueKind) -> Cue:
    if kind == "word" and hit.value in ("좌", "우"):
        return Cue(hit.start, hit.end, "side", "P" if hit.value == "좌" else "S", hit.fuzzy)
    return Cue(hit.start, hit.end, kind, hit.value, hit.fuzzy)


def _cue_spans(text: str, lexicon: Lexicon, kinds: Sequence[Span]) -> list[Span]:
    """연산·의도·방향·치수 단서 자리(정확 일치). 의도 단서는 종류 단어 자리를 피한다('보강재'의 '보강')."""
    spans = [(h.start, h.end) for h in find_aliases(text, lexicon.ops)]
    spans += [(h.start, h.end) for h in find_aliases(text, {i.value: a for i, a in lexicon.intents.items()}, kinds)]
    spans += [(h.start, h.end) for h in find_aliases(text, {"up": lexicon.increase, "down": lexicon.decrease})]
    spans += [(h.start, h.end) for h in find_aliases(text, {str(k): a for k, a in lexicon.dimensions.items()})]
    return spans


def _near(hit: Hit, span: Span, gap: int = 3) -> bool:
    return -gap <= hit.start - span[1] <= gap or -gap <= span[0] - hit.end <= gap


def _codes(text: str, vocab: MapVocabulary, ship_ids: Sequence[str]) -> list[Mention]:
    found = []
    for match in _CODE.finditer(text):
        prefix = match.group("prefix").upper()
        if prefix not in vocab.prefix_kind:
            continue
        number = int(match.group("num"))
        block_code = (match.group("block") or "").upper() or None
        ships = [match.group("ship")] if match.group("ship") else list(ship_ids)
        part_id = None
        blocks: set[str] = set()
        for ship in ships:
            if block_code:
                block = vocab.block_by_code.get((ship, block_code))
                if block:
                    blocks.add(block)
                part_id = part_id or vocab.by_code.get((ship, block_code, prefix, number))
        context = Context(
            block=next(iter(blocks)) if len(blocks) == 1 else None, system=vocab.prefix_system.get(prefix)
        )
        found.append(
            Mention(
                start=match.start(),
                end=match.end(),
                text=match.group(0),
                kind=vocab.prefix_kind[prefix],
                number=number,
                code=f"{block_code + '-' if block_code else ''}{prefix}-{number:03d}",
                part_id=part_id,
                context=context,
                block_ids=frozenset(blocks),
                phrase=match.span(),
            )
        )
    return found


def _block_codes(text: str, vocab: MapVocabulary, ship_ids: Sequence[str], occupied: Sequence[Span]) -> list[Cue]:
    found = []
    for match in _BLOCK_CODE.finditer(text):
        code = match.group("code").upper()
        blocks = [vocab.block_by_code[(s, code)] for s in ship_ids if (s, code) in vocab.block_by_code]
        if len(blocks) == 1 and free(match.span(), occupied):
            found.append(Cue(match.start(), match.end(), "block", blocks[0]))
    return found


def _with_cue(context: Context, cue: Cue) -> Context:
    start = cue.start if context.start is None else context.start
    if cue.fuzzy:
        context = replace(context, fuzzy=True)
    if cue.kind == "block":
        return replace(context, block=cue.value, start=start)
    if cue.kind == "cot":
        return replace(context, cot=int(cue.value), start=start)
    if cue.kind == "word":
        return replace(context, words=context.words | {cue.value}, start=start)
    if cue.kind == "side":
        return replace(context, side=cue.value, start=start)
    if cue.kind == "system":
        return replace(context, system=cue.value, start=start)
    return replace(context, valve_type=cue.value, start=start)


def _blocks(context: Context, vocab: MapVocabulary, ship_ids: Sequence[str]) -> frozenset[str]:
    """문맥 단서와 맞는 블록. 단서가 하나도 없으면 빈 집합(모름)."""
    if context.block is not None:
        return frozenset({context.block})
    if not context.has_block_cue and context.system is None:
        return frozenset()
    found = set()
    for block_id, entry in vocab.blocks.items():
        if entry.block.ship_id not in ship_ids:
            continue
        if context.cot is not None and entry.cot != context.cot:
            continue
        if not context.words <= entry.words:
            continue
        if context.side is not None and entry.side != context.side:
            continue
        if context.system is not None and block_id not in vocab.system_blocks.get(context.system, set()):
            continue
        found.add(block_id)
    return frozenset(found)


def _system_blocks(
    blocks: frozenset[str], context: Context, kind: PartKind | None, number: int | None, vocab: MapVocabulary
) -> frozenset[str]:
    """계통 단서만으로 블록이 여럿일 때(계통이 블록 경계를 넘음, 생성기 v3): 그 계통·종류·번호 부재가 있는 블록,
    없으면 그 계통·종류 부재가 가장 많은 블록(주 블록 — 지도에 없는 번호도 주 블록에서 찾는다)."""
    if context.system is None or context.block is not None or kind is None or len(blocks) < 2:
        return blocks

    def count(block_id: str, exact: bool) -> int:
        return sum(
            1
            for e in vocab.by_block.get(block_id, ())
            if e.part.system == context.system and e.part.kind is kind and (not exact or e.number == number)
        )

    exact = frozenset(b for b in blocks if number is not None and count(b, True))
    if exact:
        return exact
    most = max(count(b, False) for b in blocks)
    return frozenset(b for b in blocks if count(b, False) == most) if most else blocks


def _numbered_mention(
    text: str, token: _Numbered, context: Context, vocab: MapVocabulary, ship_ids: Sequence[str], fresh: bool
) -> Mention:
    hit = token.hit
    starts = [s for s in (context.start if fresh else None, hit.start if hit else None, token.span[0]) if s is not None]
    ends = [e for e in (hit.end if hit else None, token.span[1]) if e is not None]
    kind = PartKind(hit.value) if hit is not None else None
    return Mention(
        start=token.span[0],
        end=token.span[1],
        text=text[token.span[0] : token.span[1]],
        kind=kind,
        number=token.number,
        code=None,
        part_id=None,
        context=context,
        block_ids=_system_blocks(_blocks(context, vocab, ship_ids), context, kind, token.number, vocab),
        phrase=(min(starts), max(ends)),
        listed=token.listed,
    )


def _bare_mention(
    text: str, hit: Hit, context: Context, vocab: MapVocabulary, ship_ids: Sequence[str], fresh: bool
) -> Mention:
    start = context.start if fresh and context.start is not None else hit.start
    return Mention(
        start=hit.start,
        end=hit.end,
        text=text[hit.start : hit.end],
        kind=PartKind(hit.value),
        number=None,
        code=None,
        part_id=None,
        context=context,
        block_ids=_system_blocks(_blocks(context, vocab, ship_ids), context, PartKind(hit.value), None, vocab),
        phrase=(start, hit.end),
    )


def _role(text: str, mention: Mention, lexicon: Lexicon) -> Role | None:
    """표현 바로 뒤(또는 앞)의 역할 단서. '~에'는 위치(at)."""
    after = text[mention.phrase[1] : mention.phrase[1] + 12]
    before = text[max(0, mention.phrase[0] - 6) : mention.phrase[0]]
    for role, cues in lexicon.roles.items():
        if role in ("crosses", "attach") and any(cue in after for cue in cues):
            return role
        if role == "crosses" and any(cue in before for cue in cues):
            return role
    if after.lstrip().startswith("에"):
        return "at"
    for role, cues in lexicon.roles.items():
        if role == "remove" and (any(cue in after for cue in cues) or any(cue in before for cue in cues)):
            return "remove"
        if role == "add" and any(cue in before for cue in cues):
            return "add"
    return None
