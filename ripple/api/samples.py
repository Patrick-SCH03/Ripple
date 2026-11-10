"""화면의 샘플 설계변경: 지도 옆 ecn_dev.jsonl에서 연산 종류마다 영향이 풍부한 사례를 고르고,
목록에 보일 요약(기본 요청 = 기준일에 확정·보류 없음을 분석한 판정·추가손실 0 마감일·총변경비용·블록)을 붙인다."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.base import Frozen
from ripple.contracts.change import CHANGE_OP_TYPES
from ripple.contracts.dataset import GeneratedEcn
from ripple.contracts.domain import GraphSnapshot
from ripple.contracts.params import ParamSet
from ripple.contracts.result import Amount, VerdictLevel, ZeroLossDeadline
from ripple.contracts.rulebook import RuleBook
from ripple.contracts.workspace import SnapshotInfo
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.overlay import ChangeView
from ripple.engine.propagate import RequestError, propagate

from .deps import AppContext

OP_ORDER: tuple[str, ...] = tuple(str(t.model_fields["op"].default) for t in CHANGE_OP_TYPES)

DEMO_ECNS: tuple[str, ...] = ("ECN-D-0119", "ECN-D-0045", "ECN-D-0130")
"""시연용으로 고른 설계변경(데모 3 '두께 vs 보강재 대안 + 시점', 팀 데모 시나리오, 외자재 운송). 연산마다 규칙이 많은
사례를 고르는 기본 선정에 없으면 끝에 덧붙인다. ECN-D-0119 = 보강재 추가안이 크게 싸고 출구 지연도 없음,
ECN-D-0045 = 확정을 미루는 날짜·발주 보류에 따라 최저 비용 조합이 바뀜, ECN-D-0130 = 평형수 버터플라이 밸브를 외자재
게이트 밸브(VL-GATE-DN200-10K, 선박 운송)로 — 기본 요청의 일정 위험에 운송 일수(schedule.risk.transport)가 붙는
시연 건(샘플 가운데 유일)."""


class SampleSummary(Frozen):
    """목록용 요약: 샘플의 기본 요청(확정일 = 기준일, 보류 없음)을 분석한 값. 상세에서 조건을 바꿔도 그대로다."""

    analysis_id: str
    verdict: VerdictLevel
    deadline: ZeroLossDeadline  # 추가손실 0 마감일(기준일부터 D-n)
    total: Amount  # 기준일에 확정할 때의 총변경비용
    blocks: tuple[str, ...]  # 바뀌는 부재가 속한 블록 ID(ID 순)


class Sample(Frozen):
    """요청을 그대로 POST /api/impacts에 보낼 수 있는 샘플."""

    ecn_id: str
    title: str
    op: str
    rules: tuple[str, ...]  # 이 요청에서 영향을 내는 규칙(미리 계산)
    request: AnalysisRequest
    summary: SampleSummary | None = None  # 기본 요청의 분석 요약(분석이 거부되면 없음)


def read_ecns(path: Path) -> tuple[GeneratedEcn, ...]:
    """생성기 출력의 설계변경 이력(ecn_dev.jsonl). 파일이 없으면 빈 묶음."""
    if not path.exists():
        return ()
    lines = path.read_text(encoding="utf-8").splitlines()
    return tuple(GeneratedEcn.model_validate_json(line) for line in lines if line.strip())


def pick_samples(
    index: GraphIndex, ecns: Iterable[GeneratedEcn], rulebook: RuleBook, per_op: int = 2
) -> tuple[Sample, ...]:
    """연산 종류마다 영향을 내는 규칙이 많은 순(같으면 영향 수, ECN 번호 순)으로 per_op건, 그 뒤에 데모 사례."""
    ranked: dict[str, list[tuple[int, int, str, Sample]]] = {}
    demos: dict[str, Sample] = {}
    for ecn in ecns:
        request = AnalysisRequest(change=ecn.change, as_of=ecn.as_of)
        try:
            result = propagate(index, request, rulebook)
        except RequestError:
            continue
        rules = tuple(sorted({i.rule_id for i in result.impacts}))
        op = ecn.change.ops[0].op
        sample = Sample(ecn_id=ecn.change.ecn_id, title=ecn.change.title, op=op, rules=rules, request=request)
        ranked.setdefault(op, []).append((-len(rules), -len(result.impacts), ecn.change.ecn_id, sample))
        if ecn.change.ecn_id in DEMO_ECNS:
            demos[ecn.change.ecn_id] = sample
    picked = [item[-1] for op in OP_ORDER for item in sorted(ranked.get(op, []))[:per_op]]
    chosen = {s.ecn_id for s in picked}
    picked += [demos[ecn_id] for ecn_id in DEMO_ECNS if ecn_id in demos and ecn_id not in chosen]
    return tuple(picked)


def summarize(
    index: GraphIndex, request: AnalysisRequest, rulebook: RuleBook, params: ParamSet
) -> SampleSummary | None:
    """요청을 분석한 목록용 요약. 요청이 지도와 맞지 않으면 None."""
    try:
        result = analyze(index, request, rulebook, params)
    except RequestError:
        return None
    view = ChangeView(index, request.change)
    targets = view.targets(tuple(planned.name for planned in view.ops))
    blocks = sorted({block for block in (view.block_of(part) for part in targets) if block is not None})
    return SampleSummary(
        analysis_id=result.analysis_id,
        verdict=result.verdict.level,
        deadline=result.timing.deadline,
        total=result.total,
        blocks=tuple(blocks),
    )


def with_summaries(
    samples: tuple[Sample, ...], index: GraphIndex, rulebook: RuleBook, params: ParamSet
) -> tuple[Sample, ...]:
    """앱 시작 때 한 번: 샘플마다 기본 요청의 분석 요약을 붙인다(요청마다 다시 계산하지 않음)."""
    return tuple(s.model_copy(update={"summary": summarize(index, s.request, rulebook, params)}) for s in samples)


class SampleShelf:
    """작업 공간 세대마다 붙이는 샘플. 기본 지도(생성기 출력 옆 ecn_dev.jsonl, 실시간 시연 세계면 그날 만든 이력)와
    그 지도에서 상태만 갱신한 지도에만 둔다(구조가 같아 같은 요청이 그대로 맞는다). 지도마다 한 번 계산해 둔다."""

    def __init__(self, context: AppContext) -> None:
        self._context = context
        self._cached: dict[str, tuple[Sample, ...]] = {}
        self.ecns: tuple[GeneratedEcn, ...] | None = None  # 실시간 시연 세계의 이력(없으면 지도 파일 옆 파일)

    def of(
        self, default: GraphSnapshot | None, snapshot: GraphSnapshot, info: SnapshotInfo, index: GraphIndex
    ) -> tuple[Sample, ...]:
        if default is None:
            return ()
        root = info.update.lineage_root if info.update else snapshot.snapshot_id
        if root != default.snapshot_id:
            return ()
        cached = self._cached.get(snapshot.snapshot_id)
        if cached is None:
            context = self._context
            ecns = (
                self.ecns
                if self.ecns is not None
                else read_ecns(context.settings.snapshot_path.parent / "ecn_dev.jsonl")
            )
            picked = pick_samples(index, ecns, context.rulebook)
            cached = with_summaries(picked, index, context.rulebook, context.params)
            self._cached[snapshot.snapshot_id] = cached
        return cached
