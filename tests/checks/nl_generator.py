"""자연어 생성기의 정답, 조각, 분포와 결정성을 검사한다."""

from __future__ import annotations

from collections import Counter
from itertools import combinations
from time import perf_counter

from harness import Checker

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.change import AddPart, AddPenetration, RemovePart, ReroutePipe
from ripple.contracts.dataset import NlSample, NlSplit
from ripple.engine.index import GraphIndex
from ripple.engine.validate import validate_request
from ripple.generator.build import generate
from ripple.generator.io import load_config
from ripple.generator.nl import load_nl_lexicon, nl_samples, nl_samples_for_ecns


def _part_values(sample: NlSample) -> Counter[str]:
    op = sample.change.ops[0]
    ids: list[str] = []
    if isinstance(op, AddPart):
        if op.attach_to_part_id:
            ids.append(op.attach_to_part_id)
    elif isinstance(op, ReroutePipe):
        ids.extend((*op.removed_part_ids, *op.crosses_part_ids))
    elif isinstance(op, AddPenetration):
        ids.extend((op.plate_part_id, op.pipe_part_id))
    elif isinstance(op, RemovePart):
        ids.extend(op.part_ids)
    else:
        ids.extend(op.part_ids)
    return Counter(ids)


def run(c: Checker) -> None:
    c.section("자연어 생성기: 결정성·정답·조각·분포")
    cfg = load_config()
    generated = generate(cfg)
    lexicon = load_nl_lexicon()
    snapshot = generated.snapshot
    small = nl_samples(snapshot, NlSplit.TRAIN, 50, cfg.seed, cfg.scenario_date, lexicon)
    large = nl_samples(snapshot, NlSplit.TRAIN, 80, cfg.seed, cfg.scenario_date, lexicon)
    again = nl_samples(snapshot, NlSplit.TRAIN, 50, cfg.seed, cfg.scenario_date, lexicon)

    def encoded(samples: tuple[NlSample, ...]) -> bytes:
        return b"".join(s.model_dump_json().encode("utf-8") + b"\n" for s in samples)

    c.check("같은 입력의 JSON 바이트가 같음", encoded(small) == encoded(again))
    c.check("50건은 80건의 접두부", encoded(small) == encoded(large[:50]))
    split_texts = {
        split: {sample.text for sample in nl_samples(snapshot, split, 500, cfg.seed, cfg.scenario_date, lexicon)}
        for split in (NlSplit.TRAIN, NlSplit.TEMPERATURE, NlSplit.SELECTION, NlSplit.TAU, NlSplit.SET, NlSplit.EVAL)
    }
    overlap = max(len(split_texts[left] & split_texts[right]) / 500 for left, right in combinations(split_texts, 2))
    c.check("모든 일반 분할 쌍의 문장 겹침 5% 미만", overlap < 0.05, overlap)

    started = perf_counter()
    samples = nl_samples(snapshot, NlSplit.TAU, 2000, cfg.seed, cfg.scenario_date, lexicon)
    elapsed = perf_counter() - started
    print(f"  2,000건 생성: {elapsed:.3f}초")
    c.check("2,000건 생성 10초 이내", elapsed <= 10, elapsed)
    index = GraphIndex(snapshot)
    part_ids = {p.part_id for p in snapshot.parts}
    issues: list[str] = []
    absent = 0
    for sample in samples:
        missing = [m.value for m in sample.mentions if not m.exists]
        if missing:
            absent += 1
        problems = validate_request(index, AnalysisRequest(change=sample.change, as_of=sample.as_of))
        if (not missing and problems) or (
            missing and not all(any(str(value) in p for p in problems) for value in missing)
        ):
            issues.append(f"{sample.sample_id}: {problems}")
        if not sample.mentions or any(not sample.text[m.start : m.end] for m in sample.mentions):
            issues.append(f"{sample.sample_id}: 빈 조각")
        actual = Counter(
            str(m.value)
            for m in sample.mentions
            if m.slot
            in {
                "part_ids",
                "removed_part_ids",
                "crosses_part_ids",
                "plate_part_id",
                "pipe_part_id",
                "attach_to_part_id",
            }
        )
        if actual != _part_values(sample):
            issues.append(f"{sample.sample_id}: 부재 조각 {actual} != {_part_values(sample)}")
        if any(m.value in part_ids for m in sample.mentions if not m.exists):
            issues.append(f"{sample.sample_id}: 없는 대상이 지도에 있음")
        if sample.value_form in ("absolute", "from_to"):
            for mention in sample.mentions:
                if (
                    mention.slot in {"to_mm", "to_value", "diameter_mm"}
                    and isinstance(mention.value, float)
                    and f"{mention.value:g}" not in sample.text[mention.start : mention.end]
                ):
                    issues.append(f"{sample.sample_id}: 값 조각에 결과 수치 없음")
        if any(
            str(mention.value) not in sample.text[mention.start : mention.end]
            for mention in sample.mentions
            if mention.slot in {"to_grade", "spec_id", "added_spool_spec_ids"}
            or (
                mention.slot == "to_spec_id"
                and "밸브로" not in sample.text[mention.start : mention.end]
                and not sample.text[mention.start : mention.end].endswith("K로")
                and "DN" not in sample.text[mention.start : mention.end]
            )
        ):
            issues.append(f"{sample.sample_id}: 강종·규격 조각 불일치")
        intent_mentions = [m for m in sample.mentions if m.slot == "intent"]
        if len(intent_mentions) != int(sample.intent_stated) or any(
            sample.change.intent is None or m.value != sample.change.intent.value for m in intent_mentions
        ):
            issues.append(f"{sample.sample_id}: 사유 조각 불일치")
        if sample.change.raw_text != sample.text or sample.change.ship_ids != (sample.ship_id,):
            issues.append(f"{sample.sample_id}: 요청 원문·호선 불일치")
    c.check("정답 검증·조각·원문 일치", not issues, issues[:5])
    c.check("없는 대상 비율 2~7%", 0.02 <= absent / len(samples) <= 0.07, absent)
    intents = sum(s.intent_stated for s in samples) / len(samples)
    c.check("사유 표기 비율 60~80%", 0.60 <= intents <= 0.80, intents)
    c.check("연산 8종", len({s.change.ops[0].op for s in samples}) == 8)
    op_counts = Counter(s.change.ops[0].op for s in samples)
    c.check(
        "연산 비율은 설정 분포에서 각 3%p 이내",
        all(abs(op_counts[name] / len(samples) - weight) <= 0.03 for name, weight in cfg.ecn.op_mix.items()),
        op_counts,
    )
    c.check("값 표현 5종", {s.value_form for s in samples} == {"absolute", "from_to", "delta", "ratio", "none"})
    c.check(
        "잡음 6종",
        {n for s in samples for n in s.noise}
        == {
            "typo",
            "spacing",
            "order",
            "abbreviation",
            "case",
            "stale_before",
        },
    )
    dev_ecns = [ecn for ecn in generated.ecns if ecn.split.value == "dev"]
    eval_ecns = [ecn for ecn in generated.ecns if ecn.split.value == "eval"]
    history = nl_samples_for_ecns(snapshot, dev_ecns, NlSplit.ECN_DEV, cfg.seed, lexicon)
    history += nl_samples_for_ecns(snapshot, eval_ecns, NlSplit.ECN_EVAL, cfg.seed, lexicon)
    c.check(
        "ECN 문장은 원 연산·ID와 출처를 보존",
        all(
            s.source_ecn_id == e.change.ecn_id and s.change.ops == e.change.ops and s.change.ecn_id == e.change.ecn_id
            for s, e in zip(history, generated.ecns, strict=True)
        ),
    )
    history_problems = [
        (sample.sample_id, problems)
        for sample in history
        if (problems := validate_request(index, AnalysisRequest(change=sample.change, as_of=sample.as_of)))
    ]
    c.check("ECN 문장 정답도 지도 검증 통과", not history_problems, history_problems[:3])
