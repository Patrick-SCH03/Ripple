"""규칙표·비용 파라미터·판단 계층 목표값의 성질."""

from __future__ import annotations

import re
import typing
from itertools import pairwise

from harness import Checker

from ripple.config.loaders import load_decision_config, load_params, load_rulebook
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.change import OP_NAMES
from ripple.contracts.decision import GATE_TOPICS, DecisionTopic, GateKind
from ripple.contracts.domain import BLOCK_STAGE_ORDER, PO_STATUS_ORDER, ActivityKind, MaterialCategory
from ripple.contracts.params import ParamStatus
from ripple.contracts.result import ImpactType


def run(c: Checker) -> None:
    settings = Settings.from_env({})
    _rules(c, settings)
    _params(c, settings)
    _decision(c, settings)


def _rules(c: Checker, settings: Settings) -> None:
    c.section("규칙표")
    book = load_rulebook(settings.rules_path)
    c.check("규칙표가 계약대로 읽힘(ID 중복·연산 이름·관계·영향 검사 포함)", len(book.rules) >= 10, book.version)
    produced = {effect for rule in book.rules for effect in rule.effect}
    c.check("모든 영향 종류를 내는 규칙이 있음", produced == set(ImpactType), set(ImpactType) - produced)
    fallback = next(r for r in book.rules if r.is_fallback)
    c.check("연결이 끊긴 경로는 모든 연산에서 '확인 필요'", set(fallback.ops) == OP_NAMES and fallback.id == "R-X01")
    t02 = book.get("R-T02").settings["threshold_mm"]
    c.check(
        "R-T02: 두꺼운 판의 두께 차 문턱이 얇은 판 이상", t02["thin_plate_gt_10mm"] >= t02["thin_plate_le_10mm"] > 0
    )
    c.check("없는 규칙 ID를 찾으면 오류", c.raises(lambda: book.get("R-Z99"), KeyError))


def _params(c: Checker, settings: Settings) -> None:
    c.section("비용 파라미터")
    params = load_params(settings.params_path)
    c.check("파라미터가 계약대로 읽힘(대표값 범위·근거 출처 검사 포함)", len(params.params) >= 30, params.version)

    cancel = params.group("po_cancel_ratio")
    c.check("발주 취소비 구간이 발주 단계와 1:1", set(cancel) == {s.value for s in PO_STATUS_ORDER})
    ratios = [cancel[s.value].value for s in PO_STATUS_ORDER]
    c.check("발주가 진행될수록 취소비 대표값이 줄지 않음", all(a <= b for a, b in pairwise(ratios)), ratios)
    c.check("미발주 취소비는 0", ratios[0] == 0 and cancel["not_ordered"].high == 0)

    rework = params.group("rework_multiplier")
    c.check("재작업 배수가 블록 단계와 1:1", set(rework) == {s.value for s in BLOCK_STAGE_ORDER})
    multipliers = [rework[s.value].value for s in BLOCK_STAGE_ORDER]
    c.check(
        "블록 단계가 진행될수록 재작업 배수가 줄지 않음", all(a <= b for a, b in pairwise(multipliers)), multipliers
    )
    c.check("탑재 후 재작업 배수가 가장 큼", multipliers[-1] == max(multipliers))

    hours = params.group("base_work_hours_per_t")
    block_kinds = {k.value for k in ActivityKind if k is not ActivityKind.MILESTONE}
    c.check("원 작업 공수가 블록 공정과 1:1", set(hours) == block_kinds, set(hours) ^ block_kinds)
    lead = params.group("lead_time_days")
    categories = set(typing.get_args(MaterialCategory))
    c.check("표준 리드타임이 자재 분류와 1:1", set(lead) == categories, set(lead) ^ categories)
    ld = params.group("liquidated_damages")
    c.check("지체상금 기본값은 근거 있는 값", all(p.status is ParamStatus.EVIDENCE for p in ld.values()))

    questions = _mentor_question_numbers()
    used = {p.mentor_question for p in params.params.values() if p.mentor_question is not None}
    c.check("파라미터가 가리키는 멘토 질문이 질문지에 있음", used <= questions, used - questions)
    c.check("없는 파라미터 키를 찾으면 오류", c.raises(lambda: params.get("steel.gold"), KeyError))


def _decision(c: Checker, settings: Settings) -> None:
    c.section("판단 계층 목표값")
    # 합격 기준을 보기 전에 고정한 목표값 v0(보정 산출물 v1은 같은 목표값을 쓴다, tests/checks/nl_eval.py)
    config = load_decision_config(PROJECT_ROOT / "params" / "decision_v0.yaml")
    targets = config.targets
    c.check("목표값이 계약대로 읽힘", config.version == "decision-v0")
    c.check("모든 문에 오류율 상한이 있음", set(targets.epsilon) == set(GateKind))
    c.check("요청 문 오류율 상한은 0.03", targets.epsilon[GateKind.REQUEST] == 0.03)
    covered = [topic for topics in GATE_TOPICS.values() for topic in topics]
    c.check("모든 판단 주제가 정확히 한 문에 속함", sorted(covered) == sorted(DecisionTopic))
    c.check("포함률 목표 0.95", abs(1 - targets.alpha - 0.95) < 1e-12)
    c.check("자동 진행 비율 수준은 오름차순", all(a < b for a, b in pairwise(targets.coverage_levels)))
    c.check("사전 등록 목표값 파일에는 보정 산출물이 없음", config.topics == () and config.gates == ())


def _mentor_question_numbers() -> set[int]:
    text = (PROJECT_ROOT / "docs" / "data.md").read_text(encoding="utf-8")
    part = text[text.index("\n## 현업 확인 질문\n") :]
    return {int(n) for n in re.findall(r"^#### Q(\d+)\.", part, flags=re.MULTILINE)}
