"""관문 사례 도구(docs/gate_cases.md). 단계는 --stage 1(영향 탐색, 기본값)·2(비용·일정·확정 시점)·3(대안 비교).

  prepare <작업 폴더> [--stage N]
        사례 입력(1단계 30건 = 관문 10 + E1 경계 20, 2단계 13건, 3단계 5건)을 eval/gate_cases/<N>/inputs/에 쓰고,
        계산자용 작업 폴더를 만든다
        (명세·규칙표·파라미터·지도·사례 입력만. 엔진 코드와 엔진이 계산한 일정은 넣지 않는다). 작업 폴더의 사례 입력은
        제목·focus를 지운 사본이다. 전달하는 명세·규칙·파라미터에 사례의 ECN 번호·대상 부재 ID·(3단계) 엔진 금액이
        있거나, 지도의 실제 ID(예시도 자리 표시만)나 사례 입력에 규칙 ID가 있으면 멈춘다(계산자가 답이나 판정 방향을
        미리 보지 않게)
  assemble <작업 폴더> --by "<계산 주체>" [--stage N] [--cases <사례 ID>,… --summary SUMMARY-<이름>.md]
        작업 폴더의 expected/<사례>.yaml을 입력과 합쳐 eval/gate_cases/<N>/<사례>.yaml로 쓰고,
        작업지(worksheets/*.md)를 eval/gate_cases/<N>/worksheets/로 옮겨 둔다. 작업지 폴더는 지우지 않는다.
        --cases면 그 사례만 쓰고(다른 사례의 계산 주체·날짜는 그대로), 요약은 --summary 이름으로 둔다
  score [--stage N] [--approved-only]
        사례를 엔진으로 계산해 채점한다(1단계 재현율·정밀도와 where-used 기준선, 2단계 금액·일정·확정 시점·판정,
        3단계 대안·판정·대안별 금액·일정·최적 조합·권고·날짜별 구간). 관문 미달이면 종료 코드 1
  restamp [--stage N]
        생성기가 바뀌어 지도 ID만 달라졌을 때: 사례(eval/gate_cases/<N>/<사례>.yaml)와 사례 입력(inputs/)의
        snapshot_id 한 줄만 지금 생성기 지도 ID로 바꾼다(기대값·계산 주체·날짜는 그대로). 지도 ID를 뺀 입력이 사례
        입력 생성기와 하나라도 다르면 아무것도 쓰지 않고 종료 코드 1(입력이 바뀐 사례는 다시 계산해야 하므로).
        바꾼 파일과 옛 ID → 새 ID를 출력한다. 값이 그대로인지는 이어서 score로 본다

실행: uv run python scripts/gate_cases.py prepare <폴더> --stage 2
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from ripple.config.loaders import load_params, load_rulebook, load_strength
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.analysis import AnalysisRequest
from ripple.contracts.domain import GraphSnapshot
from ripple.contracts.evaluation import CaseExpectation, GateCase, GateCaseInput
from ripple.contracts.result import AnalysisResult
from ripple.contracts.rulebook import RuleBook
from ripple.engine.analyze import analyze
from ripple.engine.index import GraphIndex
from ripple.engine.propagate import impact_report
from ripple.eval.alt_gate_inputs import alt_gate_inputs
from ripple.eval.alt_metrics import score_alt_case
from ripple.eval.cost_gate_inputs import cost_gate_inputs
from ripple.eval.cost_metrics import CostCaseScore, score_cost_case, score_cost_gate
from ripple.eval.gate_inputs import gate_inputs
from ripple.eval.impact_metrics import score_case, score_gate
from ripple.eval.leaks import blind, find_leaks, hint_leaks, map_ids, needles
from ripple.generator.build import generate
from ripple.generator.io import load_config, write_outputs

GATE_DIR = PROJECT_ROOT / "eval" / "gate_cases"
SUMMARY_NAME = re.compile(r"SUMMARY(-[0-9A-Za-z가-힣._-]+)?\.md")
"""작업지 폴더의 요약 이름: 사례 작업지(<사례 ID>.md)와 겹치지 않고 Windows에서도 쓸 수 있는 이름만."""

TASK_1 = """# 관문 사례 손 계산(1단계 영향 탐색)

이 폴더만 보고 계산한다. **이 폴더 밖의 파일·저장소·인터넷은 보지 않는다.** 엔진 구현을 추측하지 말고 명세대로 계산한다.

## 할 일
`cases/`의 사례마다, `docs/engine.md`의 전파 편(전파 명세)·`docs/domain.md`(상태 규칙 3·4절)·
`rules/propagation.yaml`(규칙표)를 그대로 적용해 엔진이 내야 할 결과를 계산한다. 아래 '명세 N절'은 전파 편의 절이다.

1. **영향의 빠짐없는 전체 집합**: (엔터티 ID, 영향 종류, 규칙 ID). 정답 집합에 없는 출력은 모두 오탐으로 세므로
   빠뜨리지도, 더하지도 않는다. 규칙 R-S01·R-H01·R-L01은 1단계에서 계산하지 않는다(내지 않음).
2. **계산하지 못한 이유의 전체 집합**: (종류, 엔터티 ID) — 명세 7절(po_state·block_stage·connection).
3. 확인하고 싶은 오탐이 있으면 `forbidden_impacts`에 적는다(선택).

데이터는 `data/snapshot.json`(전체 지도, 원본)이고 `data/*.csv`는 보기 편한 사본이다. 판정일 = 확정일(없으면 기준일).
발주 품목·블록 단계는 docs/domain.md 3·4절로 판정일에 계산한다(확인된 진입일·관측·계획 간격·기준일 뒤 근거 제외 등).
사례 제목은 번호뿐이고, 무엇이 바뀌는지는 연산(`request.change.ops`)과 확정일에 모두 있다.
스크립트를 써도 되지만 이 폴더 안의 자료와 명세만 근거로 한다.

## 출력
- `expected/<사례 ID>.yaml`:
  ```yaml
  impacts:
    - {entity_id: "PO-0000#1", impact_type: po_change, rule_id: R-T01}
  unresolved:
    - {kind: po_state, entity_id: "PO-0000#1"}
  forbidden_impacts: []
  ```
- `worksheets/<사례 ID>.md`: 규칙마다 어떤 자료(부재·연결·발주·공정 행)에서 왜 그 영향이 나오는지(또는 안 나오는지),
  판정일 단계 계산 과정. **명세가 모호하거나 두 가지로 읽히는 곳은 '명세 모호'로 따로 적고**, 고른 해석과 이유를 적는다.
- 마지막에 `worksheets/SUMMARY.md`: 사례별 영향 수, 명세 모호 목록, 확신이 낮은 판정.
"""

TASK_2 = """# 관문 사례 손 계산(2단계 비용·일정·확정 시점)

이 폴더만 보고 계산한다. **이 폴더 밖의 파일·저장소·인터넷은 보지 않는다.** 엔진 구현을 추측하지 말고 명세대로 계산한다.

## 할 일
`cases/`의 사례마다 분석 결과(`AnalysisResult`)가 내야 할 비용·일정·확정 시점·요약 판정을 계산한다.

- 근거: `docs/engine.md`의 비용·일정 편(비용·일정·확정 시점 명세, 중심)과 전파 편(영향 전파 — 비용 줄은 판정일의
  영향에서 나온다), `docs/domain.md`(상태 함수 3·4절, 추가손실 0 마감일 7절), `rules/propagation.yaml`(규칙표),
  `params/cost_v1.yaml`(비용 파라미터). `docs/gate_cases.md`는 사례 양식이다. 아래 '명세 N절'은 비용·일정 편의 절이다.
- **기준 일정(CPM, 명세 6-2)은 주어지지 않는다.** `data/`의 공정·선후행(지연 일수)·기간·실적으로 직접 계산한다.
  상태 함수의 공정 착수일은 이 기준 일정의 착수일 ES⁰다(명세 1절).
- 금액은 시나리오 셋(최소·대표·최대, 명세 2절)으로 계산하고 줄마다 원 단위로 반올림한다(0.5는 0에서 먼 쪽).
- 확정일 = 요청의 `confirm_on`(없으면 기준일 `as_of`). 비용 줄·일정·판정은 확정일 평가, 곡선은 기준일부터
  `horizon_days`일 뒤까지 하루씩이다. 사례 제목은 번호뿐이고, 무엇이 바뀌는지는 연산과 확정일에 모두 있다.
- 요청의 변경 원인(`request.change.cause`, 선주 요청이면 허용 지연 4-6)과 의장품 선상 설치(`request.outfit_on_board`,
  6-3·6-8)도 결과를 바꾼다.
- 블록 공정은 소조립 → 판넬조립 → 대조립 → 선행의장 → 선행도장 → PE → 탑재다. 블록 재작업(4-4)은 블록 난이도
  계수(블록의 형상·의장품 수·전장품 수)와 공정마다 수행 주체(직영·작업반·모름)의 단가로 계산하고, 작업반이 맡은 몫은
  작업반 줄(4-4-1)로 나눈다. 선행도장 이후 단계의 재작업에는 도장 뒤 고정 항목(4-4-2)이 붙는다.
  지연 파급 비용(4-11)은 총액 밖에 따로 적는다.

데이터는 `data/snapshot.json`(전체 지도, 원본)이고 `data/*.csv`는 보기 편한 사본이다. 스크립트를 써도 되지만
이 폴더 안의 자료와 명세만 근거로 한다.

## 출력
- `expected/<사례 ID>.yaml` — 형식(값은 자리 표시일 뿐이다):
  ```yaml
  cost_lines:            # 확정일 평가의 비용 줄 전체(줄 ID는 명세 4절 형식). 빠뜨리지도, 더하지도 않는다
    - line_id: "R-T01:po_change:PO-0000#1"
      amount: {value_krw: 1000, low_krw: 800, high_krw: 1500}   # 범위가 없으면 low_krw·high_krw를 생략
      determinacy: known   # 단계를 몰라 가능한 단계 구간으로 계산했으면 state_unknown(명세 2절)
      formula: "산식과 넣은 값"
  total: {value_krw: 1000, low_krw: 800, high_krw: 1500}
  unresolved:            # 계산하지 못한 이유 전체(명세 9절): 종류·엔터티
    - {kind: po_state, entity_id: "PO-0000#1"}
  timing:
    zone_exit_delays: {"S-001:ZXX": 3}    # 확정일 평가에서 구역 출구 지연이 0보다 큰 구역만(없으면 {})
    delivery_added_days: 0                # 늘어난 인도 지연 D_after − D_before(일). 계산 불가면 null(명세 6-4)
    delivery_exposure: null               # 허용 지연(변경 원인 선주 요청, 명세 4-6)이면 노출 금액
    # ↑ {value_krw, low_krw, high_krw}, 아니면 null
    delay_ripple: null                    # 지연 파급 비용(명세 4-11, 총액 밖) {value_krw, low_krw, high_krw}
    # ↑ 구역 출구가 실제로 밀린 날이 없으면 null
    onboard: null                         # 선상 설치 선택지(명세 6-8)가 있으면 아래 형식, 없으면 null
    # onboard: {direction: to_on_board, block_ids: ["S-001:XXXX"], part_ids: ["NEW:…:1"], on_board_days: 1,
    #           total_change: {value_krw: 1000, low_krw: 800, high_krw: 1500},   # 다른 방식 총액 − 지금 총액
    #           erection_delay_now_days: 0, erection_delay_then_days: 0, exit_delay_now_days: 0,
    #           exit_delay_then_days: 0, delivery_added_now_days: 0, delivery_added_then_days: 0}
    deadline: {kind: by_date, last_day: 2026-01-01}   # 추가손실 0 마감일: confirm_now / by_date / none_in_horizon
    # ↑ last_day는 모든 종류에 적는다(confirm_now = 기준일, none_in_horizon = 탐색 마지막 날)
    deadline_total: {value_krw: 1000, low_krw: 800, high_krw: 1500}   # 마감일 당일 확정 총액 C(마감일), 범위까지.
    # ↑ none_in_horizon이면 탐색 마지막 날 총액
    next_day_total: {value_krw: 1200, low_krw: 900, high_krw: 1800}   # 마감일 다음 날 총액(범위까지).
    # ↑ none_in_horizon이면 이 키를 쓰지 않는다
    holds:                                # 발주 보류 권고 전체(명세 8-3). 없으면 []
      - po_id: PO-0000
        max_hold_days: 5
        hold_until: 2026-01-01
        deadline_after: {kind: by_date, last_day: 2026-01-01}
  verdict:
    level: review                         # approve / review / warn (명세 8-4)
    reasons: ["…"]                        # 명세 8-4 표의 문장 그대로
  ```
- `worksheets/<사례 ID>.md`: 판정일의 발주 품목·블록 단계(근거 행), 영향 집합, 바뀌는 부재와 영향 중량, 줄마다 산식과
  세 시나리오 값, 기준 일정과 변경 일정(관련 공정의 ES·EF, 관문·자재 제약), 인도 지연, 곡선에서 금액이 바뀌는 날과
  이유, 마감일과 그날·다음 날 총액, 보류 권고(보류 가능 기간·보류 곡선의 마감일), 판정 근거.
  **명세가 모호하거나 두 가지로 읽히는 곳은 '명세 모호'로 따로 적고**, 고른 해석과 이유를 적는다.
- 마지막에 `worksheets/SUMMARY.md`: 사례별 줄 수·총액·마감일·판정, 명세 모호 목록, 확신이 낮은 값.
"""

TASK_3 = """# 관문 사례 손 계산(3단계 대안 비교)

이 폴더만 보고 계산한다. **이 폴더 밖의 파일·저장소·인터넷은 보지 않는다.** 엔진 구현을 추측하지 말고 명세대로 계산한다.

## 할 일
`cases/`의 사례는 대안을 켠 분석 요청(`include_alternatives: true`)이다. 사례마다 분석 결과가 내야 할
대안 비교(대안 목록·판정·대안별 총액·일정·마감일·최적 조합·순위·권고·날짜별 가장 싼 대안·만들지 않은 대안)를 계산한다.

- 근거: `docs/engine.md`의 대안 편(대안·강도 사전검사·최적 조합 명세, 중심), 비용·일정 편(대안마다 요청과 같은
  비용·일정·추가손실 곡선·보류 권고 — 새 부재 제작 공수 C-02 4-1-2 포함), 전파 편(영향 전파와 요청 검증),
  `docs/domain.md`(상태 함수 3·4절, 추가손실 0 마감일 7절), `rules/strength.yaml`(강도 규칙), `rules/propagation.yaml`,
  `params/cost_v1.yaml`. `docs/gate_cases.md`는 사례 양식이다. 아래 '명세 N절'은 대안 편의 절이다.
- **기준 일정(CPM, 비용·일정 편 6-2)은 주어지지 않는다.** `data/`의 공정·선후행·기간·실적으로 직접 계산한다.
- 금액은 시나리오 셋(최소·대표·최대)으로 계산하고 줄마다 원 단위로 반올림한다(0.5는 0에서 먼 쪽). 이번에는 비용 줄을
  적지 않고 대안별 총액·일정으로 적는다(근거는 작업지에).
- 사례 제목은 번호뿐이고, 무엇이 바뀌는지는 연산(`request.change.ops`)과 확정일에 모두 있다.

데이터는 `data/snapshot.json`(전체 지도, 원본)이고 `data/*.csv`는 보기 편한 사본이다. 스크립트를 써도 되지만
이 폴더 안의 자료와 명세만 근거로 한다.

## 출력
- `expected/<사례 ID>.yaml` — 형식(값은 자리 표시일 뿐이다):
  ```yaml
  alternatives:
    alternatives:              # 요청안(ALT-REQ)을 포함한 대안 전체(명세 1·3절). 빠뜨리지도, 더하지도 않는다
      - alt_id: ALT-T1
        ops:                   # 대안 연산(명세 3절, 요청 연산과 같은 형식). 보강재 qty는 t 소수 셋째 자리
          - {op: add_part, block_id: "S-001:XXXX", kind: stiffener, spec_id: "XX", qty: 0.123,
             attach_to_part_id: "S-001:XXXX-PL-001"}
        scope_reduced: false
        eligibility: {status: meets, ratio_vs_request: 1.234}   # meets/short/designer
        # ↑ 비율은 round(ρ, 3), 설계자 확인이면 null
        total: {value_krw: 1000, low_krw: 800, high_krw: 1500}  # 요청의 확정일 총액(범위가 없으면 low·high 생략)
        max_exit_delay_days: 0                                 # 같은 날의 구역 출구 지연 최댓값
        deadline: {kind: by_date, last_day: 2026-01-01}        # 이 대안(요청의 보류)의 추가손실 0 마감일
        # ↑ last_day는 모든 종류에 적는다(confirm_now = 기준일, none_in_horizon = 탐색 마지막 날)
        best:                  # 충족 대안만(아니면 null): 최적 조합(명세 4절) — 확정일·보류 행동·총액
          confirm_on: 2026-01-01
          holds: [{po_id: PO-0000, hold_days: 5}]
          total: {value_krw: 1000, low_krw: 800, high_krw: 1500}
        rank: 1                # 충족 대안만(아니면 null)
        formula: "판정 비율·총액의 계산 근거"
    recommendation: {alt_id: ALT-T1, confirm_on: 2026-01-01, holds: [], total: {value_krw: 1000}}   # 1위의 최적 조합
    cheapest_by_date:          # 날짜별 가장 싼 대안(요청의 보류만), 기준일부터 탐색 마지막 날까지 빈틈없이
      - {alt_id: ALT-REQ, start: 2026-01-01, end: 2026-01-10, total: {value_krw: 1000}}   # total = 시작일 총액
    omitted:                   # 이 요청에 해당하지만 만들지 않은 템플릿과 이유(없으면 [])
      - {alt_id: ALT-T2, reason: no_upper_grade}
      # 이유: no_upper_grade(다음 강종이 없거나 단가 없음) / no_reference_stiffener(기준 보강재 없음) /
      #       missing_data(판의 중량·스팬·간격·수두 같은 값이 없음) / invalid_on_map(대안 연산이 요청 검증을 통과 못 함)
  ```
- `worksheets/<사례 ID>.md`: 템플릿마다 연산 유도(판 면적·패널 수·규격·qty, 두께 올림),
  판정 비율(요청안 이득·대안 이득), 대안마다 2단계 계산 요약(판정일 단계, 영향, 비용 줄과 세 시나리오 값,
  일정과 출구 지연, 곡선에서 금액이 바뀌는 날과 이유, 마감일, 보류 권고), 최적 조합 후보 표(확정일 × 보류 집합의
  대표 총액), 순위·권고, 날짜별 구간의 근거.
  **명세가 모호하거나 두 가지로 읽히는 곳은 '명세 모호'로 따로 적고**, 고른 해석과 이유를 적는다.
- 마지막에 `worksheets/SUMMARY.md`: 사례별 대안·판정·총액·권고, 명세 모호 목록, 확신이 낮은 값.
"""


@dataclass(frozen=True, slots=True)
class Stage:
    number: int
    task: str
    docs: tuple[str, ...]
    build: Callable[[GraphSnapshot, int, date], list[GateCaseInput]]
    rules: tuple[str, ...] = ("propagation.yaml",)

    @property
    def folder(self) -> Path:
        return GATE_DIR / str(self.number)

    @property
    def pattern(self) -> str:
        return f"G{self.number}-*.yaml"


STAGES = {
    1: Stage(1, TASK_1, ("engine.md", "domain.md", "gate_cases.md"), gate_inputs),
    2: Stage(2, TASK_2, ("engine.md", "domain.md", "gate_cases.md"), cost_gate_inputs),
    3: Stage(
        3,
        TASK_3,
        ("engine.md", "domain.md", "gate_cases.md"),
        alt_gate_inputs,
        rules=("propagation.yaml", "strength.yaml"),
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="관문 사례 도구")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("workspace", type=Path)
    assemble = sub.add_parser("assemble")
    assemble.add_argument("workspace", type=Path)
    assemble.add_argument("--by", required=True, help="계산 주체(모델·실행 폴더)")
    assemble.add_argument("--cases", default=None, help="쉼표로 나눈 사례 ID만 조립(다른 사례 파일은 그대로)")
    assemble.add_argument("--summary", default="SUMMARY.md", help="작업 폴더 요약을 둘 이름(일부만 조립하면 필수)")
    score = sub.add_parser("score")
    score.add_argument("--approved-only", action="store_true", help="검토·승인된 사례만")
    restamp = sub.add_parser("restamp")
    for command in (prepare, assemble, score, restamp):
        command.add_argument("--stage", type=int, choices=sorted(STAGES), default=1)
    args = parser.parse_args(argv)
    stage = STAGES[args.stage]
    if args.command == "prepare":
        return _prepare(stage, args.workspace)
    if args.command == "assemble":
        only = None if args.cases is None else [case_id.strip() for case_id in args.cases.split(",") if case_id.strip()]
        return _assemble(stage, args.workspace, args.by, only, args.summary)
    if args.command == "restamp":
        return _restamp(stage)
    return _score(stage, args.approved_only)


def _dump(data: object) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)


def _prepare(stage: Stage, workspace: Path) -> int:
    config = load_config()
    generated = generate(config)
    inputs = stage.build(generated.snapshot, generated.seed, config.scenario_date)
    (stage.folder / "inputs").mkdir(parents=True, exist_ok=True)
    if workspace.exists():
        shutil.rmtree(workspace)
    for sub in ("cases", "expected", "worksheets", "docs", "rules", "params", "data"):
        (workspace / sub).mkdir(parents=True, exist_ok=True)
    for case in inputs:
        text = _dump(case.model_dump(mode="json"))
        (stage.folder / "inputs" / f"{case.case_id}.yaml").write_text(text, encoding="utf-8", newline="\n")
        shown = _dump(blind(case).model_dump(mode="json"))
        (workspace / "cases" / f"{case.case_id}.yaml").write_text(shown, encoding="utf-8", newline="\n")
    for doc in stage.docs:
        shutil.copy(PROJECT_ROOT / "docs" / doc, workspace / "docs" / doc)
    for rule in stage.rules:
        shutil.copy(PROJECT_ROOT / "rules" / rule, workspace / "rules" / rule)
    shutil.copy(PROJECT_ROOT / "params" / "cost_v1.yaml", workspace / "params" / "cost_v1.yaml")
    write_outputs(generated, workspace / "data")
    for leftover in ("ecn_dev.jsonl", "ecn_eval.jsonl"):
        (workspace / "data" / leftover).unlink()
    _extra_tables(generated.snapshot, workspace / "data")
    (workspace / "README.md").write_text(stage.task, encoding="utf-8", newline="\n")
    print(f"사례 입력 {len(inputs)}건 → {stage.folder / 'inputs'}")
    leaks = _leaks(stage, inputs, generated.snapshot, workspace)
    if leaks:
        for leak in leaks:
            print(f"전달본에 사례 정보가 있어요: {leak}")
        print(f"작업 폴더를 계산자에게 주지 마세요(명세에서 지운 뒤 다시 prepare): {workspace}")
        return 1
    print(f"작업 폴더 → {workspace} (지도 {generated.snapshot.snapshot_id}, 전달본 점검 통과)")
    return 0


def _leaks(stage: Stage, inputs: list[GateCaseInput], snapshot: GraphSnapshot, workspace: Path) -> list[str]:
    """계산자에게 주는 글(명세·규칙·파라미터·할 일)에 사례의 ECN 번호·대상 부재 ID, 3단계는 엔진 금액이 있는지,
    작업 폴더의 사례 입력에 규칙 ID가 있는지, 명세 예시에 지도의 실제 ID가 있는지."""
    results: dict[str, AnalysisResult] = {}
    if stage.number == 3:
        settings = Settings.from_env({})
        book, params = load_rulebook(settings.rules_path), load_params(settings.params_path)
        strength = load_strength(settings.strength_path)
        index = GraphIndex(snapshot)
        results = {case.case_id: analyze(index, case.request, book, params, strength) for case in inputs}
    paths = [workspace / "README.md", *(p for sub in ("docs", "rules", "params") for p in (workspace / sub).iterdir())]
    texts = {path.relative_to(workspace).as_posix(): path.read_text(encoding="utf-8") for path in paths}
    shown = (workspace / "cases").iterdir()
    cases = {p.relative_to(workspace).as_posix(): p.read_text(encoding="utf-8") for p in shown}
    return find_leaks(texts, needles(inputs, results) | map_ids(snapshot)) + hint_leaks(cases)


def _extra_tables(snapshot: GraphSnapshot, folder: Path) -> None:
    """snapshot.json에만 있던 표(블록·규격·재고·도면·품목의 부재·부재 중량·선후행·호선·경계 조건, 1.32.0 작업반·공정
    수행 주체, 1.33.0 규격 원산지·운송 방식)를 CSV로도 둔다."""
    tables: dict[str, tuple[tuple[str, ...], list[tuple[object, ...]]]] = {
        "blocks.csv": (
            (
                "block_id",
                "zone_id",
                "name",
                "steel_weight_t",
                "fabricator_id",
                "shape",
                "outfit_items",
                "electric_items",
            ),
            [
                (
                    b.block_id,
                    b.zone_id,
                    b.name,
                    b.steel_weight_t,
                    b.fabricator_id,
                    None if b.shape is None else b.shape.value,
                    b.outfit_items,
                    b.electric_items,
                )
                for b in snapshot.blocks
            ],
        ),
        "crews.csv": (
            ("crew_id", "name", "processes"),
            [(c.crew_id, c.name, " ".join(k.value for k in c.processes)) for c in snapshot.crews],
        ),
        "activity_performers.csv": (
            ("activity_id", "performer"),
            [(a.activity_id, a.performer) for a in snapshot.activities if a.performer is not None],
        ),
        "specs.csv": (
            (
                "spec_id",
                "category",
                "grade",
                "thickness_mm",
                "nominal_diameter_dn",
                "pressure_class",
                "unit",
                "unit_price_krw",
                "std_lead_time_days",
                "origin",
                "transport",
            ),
            [
                (
                    s.spec_id,
                    s.category,
                    s.grade,
                    s.thickness_mm,
                    s.nominal_diameter_dn,
                    s.pressure_class,
                    s.unit,
                    s.unit_price_krw,
                    s.std_lead_time_days,
                    s.origin,
                    s.transport,
                )
                for s in snapshot.specs
            ],
        ),
        "stock.csv": (
            ("lot_id", "spec_id", "qty", "received_date", "processed", "reserved_block_id"),
            [(s.lot_id, s.spec_id, s.qty, s.received_date, s.processed, s.reserved_block_id) for s in snapshot.stock],
        ),
        "drawings.csv": (
            ("drawing_id", "drawing_no", "revision", "discipline"),
            [(d.drawing_id, d.drawing_no, d.revision, d.discipline) for d in snapshot.drawings],
        ),
        "line_parts.csv": (
            ("line_id", "part_id"),
            [(li.line_id, p) for li in snapshot.po_lines for p in li.part_ids],
        ),
        "part_weights.csv": (("part_id", "weight_kg"), [(p.part_id, p.weight_kg) for p in snapshot.parts]),
        "precedences.csv": (
            ("activity_id", "predecessor_id", "lag_days"),
            [(a.activity_id, p.activity_id, p.lag_days) for a in snapshot.activities for p in a.predecessors],
        ),
        "ships.csv": (
            ("ship_id", "contract_price_krw", "delivery_date", "ld_grace_days", "ld_rate_per_day", "ld_max_days"),
            [
                (
                    s.ship_id,
                    s.contract_price_krw,
                    s.delivery_date,
                    s.ld_terms.grace_days if s.ld_terms else None,
                    s.ld_terms.rate_per_day_of_price if s.ld_terms else None,
                    s.ld_terms.max_days if s.ld_terms else None,
                )
                for s in snapshot.ships
            ],
        ),
        "boundaries.csv": (
            ("zone_id", "exit_activity_id", "float_to_delivery_days", "forecast_delivery_delay_days"),
            [
                (b.zone_id, b.exit_activity_id, b.float_to_delivery_days, b.forecast_delivery_delay_days)
                for b in snapshot.boundaries
            ],
        ),
    }
    for name, (header, rows) in tables.items():
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
        (folder / name).write_text("﻿" + buffer.getvalue(), encoding="utf-8")


def _assemble(
    stage: Stage, workspace: Path, by: str, only: list[str] | None = None, summary: str = "SUMMARY.md"
) -> int:
    """고른 사례(없으면 전부)의 기대값·작업지가 있고 계약 검증을 통과할 때만 한꺼번에 쓴다(기대값과 계산 근거가
    다른 판으로 섞이지 않게). 하나라도 빠지거나 틀리면 아무것도 쓰지 않는다. 작업지 폴더는 지우지 않고 쓴 사례의
    작업지와 요약만 덮는다 — 다른 사례의 계산 기록·요약이 남는다. 일부만 조립하면 요약 이름을 따로 정한다(전체 요약을
    덮지 않게)."""
    cases: list[GateCase] = []
    problems: list[str] = []
    paths = sorted((stage.folder / "inputs").glob(stage.pattern))
    if not SUMMARY_NAME.fullmatch(summary):
        problems.append(f"요약 이름은 SUMMARY.md나 SUMMARY-<이름>.md(글자·숫자·._-)여야 해요: {summary}")
    if only is not None:
        if not only:
            problems.append("--cases에 사례 ID가 없어요(전체를 조립하려면 --cases를 빼 주세요)")
        known = {path.stem for path in paths}
        problems += [f"사례 입력이 없어요: {case_id}" for case_id in only if case_id not in known]
        paths = [path for path in paths if path.stem in set(only)]
        if summary.casefold() == "summary.md":
            problems.append("일부만 조립할 때는 --summary로 요약 이름을 정해 주세요(전체 요약을 덮지 않게)")
    if not (workspace / "worksheets" / "SUMMARY.md").is_file():  # 없으면 옛 요약이 새 결과와 섞여 남는다
        problems.append(f"요약이 없어요: {workspace / 'worksheets' / 'SUMMARY.md'}")
    for path in paths:
        case_input = GateCaseInput.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        result = workspace / "expected" / path.name
        sheet = workspace / "worksheets" / f"{case_input.case_id}.md"
        if not result.exists():
            problems.append(f"기대값이 없어요: {result}")
        if not sheet.exists():
            problems.append(f"작업지가 없어요: {sheet}")
        if not result.exists():
            continue
        try:
            expected = CaseExpectation.model_validate(yaml.safe_load(result.read_text(encoding="utf-8")) or {})
            cases.append(
                GateCase(**case_input.model_dump(), expected=expected, computed_by=by, computed_on=date.today())
            )
        except ValueError as error:
            problems.append(f"{case_input.case_id} 기대값이 계약과 맞지 않아요: {error}")
    if not cases and not problems:
        problems.append(f"사례 입력이 없어요: {stage.folder / 'inputs'}")
    if problems:
        for problem in problems:
            print(problem)
        print("아무것도 쓰지 않았어요")
        return 1
    for case in cases:
        (stage.folder / f"{case.case_id}.yaml").write_text(
            _dump(case.model_dump(mode="json")), encoding="utf-8", newline="\n"
        )
    source, target = workspace / "worksheets", stage.folder / "worksheets"
    target.mkdir(parents=True, exist_ok=True)
    names = (
        [f"{case.case_id}.md" for case in cases]
        if only is not None
        else [sheet.name for sheet in sorted(source.glob("*.md")) if sheet.name != "SUMMARY.md"]
    )
    for name in names:
        shutil.copy(source / name, target / name)
    shutil.copy(source / "SUMMARY.md", target / summary)
    names.append(summary)
    print(f"사례 {len(cases)}건, 작업지 {len(names)}개를 썼어요 → {stage.folder}")
    return 0


SNAPSHOT_LINE = re.compile(r"^(\s+snapshot_id: )(G-[0-9a-f]{16})$", re.MULTILINE)
"""사례·사례 입력 YAML의 지도 ID 줄(snapshot: 아래 한 줄)."""


def _restamp(stage: Stage) -> int:
    """사례·사례 입력의 지도 ID만 지금 생성기 지도로 바꾼다.

    지도 ID를 뺀 입력이 사례 입력 생성기와 같을 때만, 모두 함께(하나라도 다르면 아무것도 쓰지 않음).
    """
    config = load_config()
    generated = generate(config)
    new_id = generated.snapshot.snapshot_id
    built = {i.case_id: i for i in stage.build(generated.snapshot, generated.seed, config.scenario_date)}
    paths = [*sorted(stage.folder.glob(stage.pattern)), *sorted((stage.folder / "inputs").glob(stage.pattern))]
    planned: list[tuple[Path, str, str]] = []
    problems: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        case_input = GateCaseInput.model_validate({k: v for k, v in data.items() if k in _INPUT_FIELDS})
        found = SNAPSHOT_LINE.findall(text)
        expected = built.get(case_input.case_id)
        stamped = case_input.model_copy(
            update={"snapshot": case_input.snapshot.model_copy(update={"snapshot_id": new_id})}
        )
        if len(found) != 1:
            problems.append(f"{path.relative_to(stage.folder)}: 지도 ID 줄이 {len(found)}개예요")
        elif expected is None:
            problems.append(f"{path.relative_to(stage.folder)}: 사례 입력 생성기에 없는 사례예요")
        elif stamped != expected:
            problems.append(f"{path.relative_to(stage.folder)}: 지도 ID 말고도 입력이 사례 입력 생성기와 달라요")
        elif found[0][1] != new_id:
            planned.append((path, found[0][1], SNAPSHOT_LINE.sub(rf"\g<1>{new_id}", text, count=1)))
    if problems:
        for problem in problems:
            print(problem)
        print("아무것도 쓰지 않았어요(입력이 바뀐 사례는 prepare·손 계산으로 다시 만들어 주세요)")
        return 1
    for path, old_id, text in planned:
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"{path.relative_to(stage.folder).as_posix()}: {old_id} → {new_id}")
    print(f"{stage.number}단계 사례·입력 {len(paths)}개 중 {len(planned)}개의 지도 ID만 바꿨어요(기대값 그대로)")
    print(f"지금 지도 {new_id} — 값이 그대로인지 score --stage {stage.number}로 확인해 주세요")
    return 0


def _load_cases(stage: Stage, approved_only: bool) -> list[GateCase]:
    cases = [
        GateCase.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")))
        for p in sorted(stage.folder.glob(stage.pattern))
    ]
    return [c for c in cases if c.checked_by or not approved_only]


def _score(stage: Stage, approved_only: bool) -> int:
    cases = _load_cases(stage, approved_only)
    if not cases:
        print("채점할 사례가 없어요")
        return 1
    settings = Settings.from_env({})
    rulebook = load_rulebook(settings.rules_path)
    indexes: dict[int, GraphIndex] = {}

    def index_of(case: GateCase) -> GraphIndex:
        seed = case.snapshot.generator_seed
        if seed not in indexes:
            indexes[seed] = GraphIndex(generate(load_config(), seed).snapshot)
        return indexes[seed]

    params = load_params(settings.params_path)
    # 필수 사례는 사례 입력 생성기(결정적)가 지금 지도로 만드는 입력이다. 저장된 사례의 입력이 그것과 다르면
    # 판정하지 않는다(입력·사례 파일이 함께 지워지거나 손으로 고쳐져도 관문이 줄어들지 않게)
    config = load_config()
    generated = generate(config)
    built = {i.case_id: i for i in stage.build(generated.snapshot, generated.seed, config.scenario_date)}
    drift = tuple(
        f"사례 {case.case_id}의 입력이 사례 입력 생성기와 달라요"
        for case in cases
        if case.case_id in built
        and GateCaseInput.model_validate(case.model_dump(include=_INPUT_FIELDS)) != built[case.case_id]
    )
    required = sorted(built)
    if stage.number == 1:
        return _score_impacts(cases, required, drift, index_of, rulebook, params.version)
    if stage.number == 2:
        return _score_cases(
            cases,
            required,
            drift,
            lambda case: score_cost_case(
                case, analyze(index_of(case), AnalysisRequest.model_validate(case.request), rulebook, params)
            ),
        )
    strength = load_strength(settings.strength_path)
    return _score_cases(
        cases,
        required,
        drift,
        lambda case: score_alt_case(
            case, analyze(index_of(case), AnalysisRequest.model_validate(case.request), rulebook, params, strength)
        ),
    )


_INPUT_FIELDS = set(GateCaseInput.model_fields)


def _report_problems(problems: tuple[str, ...]) -> None:
    for problem in problems:
        print(f"관문 판정 불가: {problem}")


def _score_cases(
    cases: list[GateCase],
    required: list[str],
    drift: tuple[str, ...],
    score: Callable[[GateCase], CostCaseScore],
) -> int:
    """2·3단계: 사례마다 불일치 항목 목록, 필수 사례를 모두 통과해야 관문 통과."""
    gate = score_cost_gate([score(case) for case in cases], required)
    for scored in gate.cases:
        print(f"{scored.case_id:8} {'통과' if scored.passed else f'불일치 {len(scored.mismatches)}'}")
        for mismatch in scored.mismatches:
            print(f"    {mismatch}")
    passed = gate.passed() and not drift
    print(f"\n{sum(s.passed for s in gate.cases)}/{len(gate.cases)}건 통과 — {'관문 통과' if passed else '관문 미달'}")
    _report_problems((*gate.problems, *drift))
    return 0 if passed else 1


def _score_impacts(
    cases: list[GateCase],
    required: list[str],
    drift: tuple[str, ...],
    index_of: Callable[[GateCase], GraphIndex],
    rulebook: RuleBook,
    params_version: str,
) -> int:
    scores = []
    for case in cases:
        index = index_of(case)
        report = impact_report(index, AnalysisRequest.model_validate(case.request), rulebook, params_version)
        scores.append(score_case(case, report, index))
    gate = score_gate(scores, required)
    print(f"{'사례':8} {'재현율':>6} {'정밀도':>6} {'기준선 F1':>9} {'엔진 F1':>7}  놓침/오탐")
    for s in gate.cases:
        flags = "" if s.unresolved_ok and not s.forbidden_hits else " ← 이유·금지 불일치"
        print(
            f"{s.case_id:8} {s.impacts.recall:6.2f} {s.impacts.precision:6.2f} "
            f"{s.baseline.f1:9.2f} {s.entities.f1:7.2f}  {len(s.missed)}/{len(s.extra)}{flags}"
        )
        for key in s.missed:
            print(f"    놓침 {key}")
        for key in s.extra:
            print(f"    오탐 {key}")
    impacts, entities, baseline = gate.pooled("impacts"), gate.pooled("entities"), gate.pooled("baseline")
    print(f"\n판정 단위: 재현율 {impacts.recall:.3f} · 정밀도 {impacts.precision:.3f} ({len(impacts.expected)}건)")
    print(f"엔터티 단위 F1: 엔진 {entities.f1:.3f} · where-used 기준선 {baseline.f1:.3f}")
    plm, second = gate.pooled("plm"), gate.pooled("second_order")
    print(
        f"PLM 수준 기준선(블록·발주·도면) F1 {plm.f1:.3f} · 그 기준선 밖 정답 엔터티(2차 영향) "
        f"{len(second.expected)}개 중 엔진이 찾은 것 {len(second.matched)}개(재현율 {second.recall:.3f})"
    )
    passed = gate.passed() and not drift
    print("관문 통과" if passed else "관문 미달")
    _report_problems((*gate.problems, *drift))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
