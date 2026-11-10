"""합성 지도와 한국어 설계변경 문장을 분할별 JSONL로 쓴다."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ripple.contracts.dataset import NlSplit
from ripple.generator.build import generate
from ripple.generator.io import DEFAULT_OUTPUT_ROOT, load_config
from ripple.generator.nl import load_nl_lexicon, nl_samples, nl_samples_for_ecns

DEFAULT_COUNTS = {
    NlSplit.TRAIN: 2000,
    NlSplit.TEMPERATURE: 1500,
    NlSplit.SELECTION: 500,
    NlSplit.TAU: 2000,
    NlSplit.SET: 1500,
    NlSplit.EVAL: 1500,
    NlSplit.ECN_DEV: 200,
    NlSplit.ECN_EVAL: 100,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="한국어 설계변경 문장 생성")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_ROOT)
    for split, default in DEFAULT_COUNTS.items():
        parser.add_argument(f"--{split.value.replace('_', '-')}", type=int, default=default)
    args = parser.parse_args(argv)
    cfg = load_config()
    generated = generate(cfg, args.seed)
    lexicon = load_nl_lexicon()
    folder = args.out / str(generated.seed) / "nl"
    folder.mkdir(parents=True, exist_ok=True)
    for split in NlSplit:
        count = int(getattr(args, split.value))
        if count < 0:
            parser.error(f"{split.value}: 0 이상이어야 해요")
        if split in (NlSplit.ECN_DEV, NlSplit.ECN_EVAL):
            source = [e for e in generated.ecns if e.split.value == split.value.removeprefix("ecn_")]
            if count > len(source):
                parser.error(f"{split.value}: ECN {len(source)}건보다 많이 요청했어요")
            samples = nl_samples_for_ecns(generated.snapshot, source[:count], split, generated.seed, lexicon)
        else:
            samples = nl_samples(generated.snapshot, split, count, generated.seed, cfg.scenario_date, lexicon)
        path = folder / f"{split.value}.jsonl"
        path.write_text("".join(sample.model_dump_json() + "\n" for sample in samples), encoding="utf-8", newline="\n")
        print(f"{path.resolve()}: {len(samples)}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
