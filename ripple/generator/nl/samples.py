"""사례 만들기: 분할마다 사례 번호 시드로 연산을 만들거나(nl_samples) 생성한 ECN을 받아(nl_samples_for_ecns)
문장과 정답을 묶는다."""

from __future__ import annotations

import random
from datetime import date

from ripple.contracts.change import AddPenetration, ChangeIntent, ChangeRequest
from ripple.contracts.dataset import GeneratedEcn, NlSample, NlSplit
from ripple.contracts.domain import ConnectionKind, GraphSnapshot

from ..ecn import BUILDERS, INTENTS, Catalog, home_blocks
from ..io import load_config
from ..rng import sub_rng, weighted
from .lexicon import NlLexicon
from .render import render
from .targets import nonexistent


def _sample(
    snapshot: GraphSnapshot,
    split: NlSplit,
    number: int,
    rng: random.Random,
    change: ChangeRequest,
    as_of: date,
    lexicon: NlLexicon,
    source_ecn_id: str | None = None,
    allow_missing: bool = True,
) -> NlSample:
    parts = {part.part_id: part for part in snapshot.parts}
    blocks = {block.block_id: block.name for block in snapshot.blocks}
    op = change.ops[0]
    if allow_missing and rng.random() < 0.04:
        op = nonexistent(op, rng, parts)
    valves = tuple(s.spec_id for s in snapshot.specs if s.category == "valve")
    if change.intent is None:
        raise ValueError(f"{change.ecn_id}: 생성한 설계변경에는 변경 사유가 있어야 해요")
    text, mentions, form, stated, noise = render(rng, op, change.intent.value, parts, blocks, lexicon, valves)
    final_change = change.model_copy(update={"ops": (op,), "raw_text": text})
    return NlSample(
        sample_id=f"NL-{split.value}-{number:05d}",
        split=split,
        text=text,
        ship_id=change.ship_ids[0],
        as_of=as_of,
        change=final_change,
        mentions=mentions,
        value_form=form,
        intent_stated=stated,
        noise=noise,
        source_ecn_id=source_ecn_id,
    )


def nl_samples(
    snapshot: GraphSnapshot,
    split: NlSplit,
    count: int,
    seed: int,
    as_of: date,
    lexicon: NlLexicon,
) -> tuple[NlSample, ...]:
    if count < 0:
        raise ValueError("count는 0 이상이어야 해요")
    if split in (NlSplit.ECN_DEV, NlSplit.ECN_EVAL):
        raise ValueError("ECN 분할에는 nl_samples_for_ecns를 써야 해요")
    cfg = load_config()
    catalog = Catalog(snapshot, home_blocks(cfg))
    penetrations = {
        frozenset((connection.a, connection.b))
        for connection in snapshot.connections
        if connection.kind is ConnectionKind.PENETRATION
    }
    result: list[NlSample] = []
    for i in range(count):
        rng = sub_rng(seed, "nl", split.value, str(i))
        name = weighted(rng, cfg.ecn.op_mix)
        op, title = BUILDERS[name](rng, catalog)
        while isinstance(op, AddPenetration) and frozenset((op.plate_part_id, op.pipe_part_id)) in penetrations:
            op, title = BUILDERS[name](rng, catalog)
        intent = ChangeIntent(weighted(rng, INTENTS[name]))
        change = ChangeRequest(
            ecn_id=f"ECN-NL-{split.value}-{i:05d}",
            title=title,
            ship_ids=(snapshot.ships[0].ship_id,),
            intent=intent,
            ops=(op,),
        )
        result.append(_sample(snapshot, split, i, rng, change, as_of, lexicon))
    return tuple(result)


def nl_samples_for_ecns(
    snapshot: GraphSnapshot,
    ecns: tuple[GeneratedEcn, ...] | list[GeneratedEcn],
    split: NlSplit,
    seed: int,
    lexicon: NlLexicon,
) -> tuple[NlSample, ...]:
    if split not in (NlSplit.ECN_DEV, NlSplit.ECN_EVAL):
        raise ValueError("ECN 문장에는 ecn_dev 또는 ecn_eval 분할을 써야 해요")
    if any(ecn.split.value != split.value.removeprefix("ecn_") for ecn in ecns):
        raise ValueError("ECN 이력 분할과 문장 분할이 달라요")
    return tuple(
        _sample(
            snapshot,
            split,
            i,
            sub_rng(seed, "nl", split.value, str(i)),
            ecn.change,
            ecn.as_of,
            lexicon,
            ecn.change.ecn_id,
            allow_missing=False,
        )
        for i, ecn in enumerate(ecns)
    )
