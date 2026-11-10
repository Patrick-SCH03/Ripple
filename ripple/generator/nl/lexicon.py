"""생성기 전용 문장 사전(nl-lexicon-v2, docs/data.md(생성기) 7-1 사전): 엔진·해석기 사전을 읽지 않는다."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from ripple.config.loaders import read_yaml
from ripple.contracts.base import Frozen

DEFAULT_LEXICON_PATH = Path(__file__).parents[1] / "lexicon.yaml"


class NlLexicon(Frozen):
    version: str = Field(pattern=r"^nl-lexicon-v\d+$")
    kinds: dict[str, tuple[str, ...]]
    blocks: dict[str, tuple[str, ...]]
    systems: dict[str, tuple[str, ...]]
    valves: dict[str, tuple[str, ...]]
    operations: dict[str, tuple[str, ...]]
    intents: dict[str, tuple[str, ...]]
    endings: tuple[str, ...]
    typos: dict[str, tuple[str, ...]]


def load_nl_lexicon(path: Path = DEFAULT_LEXICON_PATH) -> NlLexicon:
    return NlLexicon.model_validate(read_yaml(path))
