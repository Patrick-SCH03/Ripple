# 손 계산 정답 사례 양식

단계 관문(`docs/evaluation.md` 2절)과 의미 정확도(E1 30건)에 쓰는 사례다. 1단계는 관문 10건과 E1 경계 사례 20건을 합친 30건이다.

**엔진 코드를 보지 않고** 계산한다. 계산은 엔진을 보지 않는 계산자(AI 모델)가 문서·규칙표·파라미터·사례 원자료만 있는 별도 폴더에서 하고, 사람이 검토·승인한다.
사례는 `eval/gate_cases/<단계>/<사례 ID>.yaml`에 두고, 계약은 `ripple/contracts/evaluation.py`다. 계산자에게는 판정 방향이 드러날 수
있는 제목·`focus`를 지운 사례 입력(제목 = 번호)을 준다 — 무엇이 바뀌는지는 연산과 확정일에 모두 있다.

- 1단계(영향 탐색): 영향의 빠짐없는 전체 집합과 계산하지 못한 이유.
- 2단계(비용·일정·확정 시점): 비용 줄·총액·계산하지 못한 이유, 구역 출구·인도 지연, 추가손실 0 마감일과 그날·다음 날 총액, 발주
  보류 권고, 요약 판정. 1단계 영향 집합은 2단계에서 채점하지 않는다(비용 줄 ID가 영향에서 나오므로 금액이 있는 영향은 줄로 확인된다).
- 3단계(대안 비교, `docs/engine.md`(대안)): 대안 목록(템플릿·연산), 판정(상태·비율), 대안별 총액·구역 출구 지연·마감일, 최적
  조합(확정일·보류·총액)·순위, 권고, 날짜별 최저 비용 대안 구간(대안·시작일·끝일·시작일 총액), 만들지 않은 대안과 이유. 비용 줄은
  적지 않는다(대안마다의 2단계 계산은 작업지에 근거로).

## 작성 규칙

1. 입력은 생성기 시드 하나로 만든 지도(스냅샷 ID를 적는다)와 변경 요청 하나다. 사례 입력의 연산은 계약의 모든 필드(기본값이 있는 필드 포함)를 적어 둔 것이라, 새 부재 임시 ID의 연산 정규형(`docs/engine.md`(전파) 3절)에 그대로 쓴다.
2. 계산 근거는 `docs/engine.md`의 전파 편, 비용·일정 편(2단계 비용·일정·확정 시점), 대안 편(3단계 대안), `docs/domain.md`(상태·계산 규칙), `rules/propagation.yaml`, `rules/strength.yaml`(3단계), `params/cost_v1.yaml`만 쓴다. 엔진 코드·엔진 출력은 보지 않는다. 2단계의 기준 일정(CPM)도 엔진이 계산한 것을 받지 않고 원자료(공정·선후행·실적)로 직접 계산한다.
3. 금액은 시나리오 셋(최소·대표·최대, `docs/engine.md`(비용·일정) 2절)으로 계산하고 줄마다 원 단위로 반올림한다. 관문 기준은 금액(대표값·최소·최대 각각) ±1%(작은 금액은 ±1원 바닥), 일정 ±0일이다.
4. 계산 주체(모델·실행 폴더)와 날짜, 검토·승인한 사람을 적는다.
5. 1단계 `expected.impacts`는 그 사례의 **빠짐없는 전체 정답 집합**이다(엔터티·영향 종류·규칙 ID). 정답 집합에 없는 엔진 출력은 모두 오탐으로 센다. `forbidden_impacts`는 특히 확인하려는 오탐을 적는 강조용 목록이다.
6. 계산이 엔진과 다르면 먼저 사례와 엔진 중 무엇이 틀렸는지 가른다. 사례를 고치면 처음 계산과 고친 근거를 사례 `notes`와 작업지에 남긴다.
7. `expected.unresolved`는 계산하지 못한 이유(종류·엔터티)의 전체 집합이다. 관문은 이 집합도 엔진과 같아야 통과한다(1·2단계).
8. 2단계 `expected.cost_lines`는 확정일 평가의 비용 줄 **전체 집합**이다(줄 ID = `docs/engine.md`(비용·일정) 4절 형식).
   - 빠진 줄·더한 줄은 불일치이고, 줄마다 금액과 판단 불가 표시(`determinacy`)를 비교한다.
   - 보류 권고는 발주·보류 가능 기간·보류 기한·보류 뒤 마감일을 비교한다(피하는 손실 금액은 비교하지 않음).
   - 판정은 수준과 이유 문장 집합(`docs/engine.md`(비용·일정) 8-4 문장 그대로)을 비교한다.
9. 3단계 `expected.alternatives`는 요청안(`ALT-REQ`)을 포함한 대안의 **전체 집합**이다.
   - 대안마다 연산(정규형: ID 정렬, 보강재 qty는 t 소수 셋째 자리)·범위 축소·판정 상태·판정 비율(±0.001)·총액(대표값·최소·최대
     ±1%)·구역 출구 지연(±0일)·마감일·최적 조합(충족 대안만: 확정일·보류 행동·총액)·순위를 비교한다.
   - 권고(1위의 최적 조합과 같아야 함)·날짜별 구간·만들지 않은 대안과 이유(`no_upper_grade`·`no_reference_stiffener`·`missing_data`·`invalid_on_map`)를 비교한다.
   - 설계자 확인·부족 대안도 총액·지연·마감일은 채점한다.
10. 관문 통과는 **수정 뒤 재채점에서 필수 사례 모두 통과 + 앞 단계 관문 회귀 통과**일 때만이다. 불일치마다 원인 판정(사례·엔진·명세 중 무엇이 틀렸나)과 수정 기록을 남기지만, 그것이 관문 통과를 대신하지 않는다.

## 도구(`scripts/gate_cases.py`, `--stage 1|2|3`, 기본 1)

1. `prepare <작업 폴더> --stage N`: 사례 입력(`eval/gate_cases/<N>/inputs/`)을 만들고, 계산자용 작업 폴더에 명세·규칙표·파라미터·지도(`snapshot.json`과 CSV)·사례 입력·할 일(README)만 넣는다.
   - 엔진 코드와 엔진이 계산한 일정은 넣지 않는다.
   - 사례 입력은 결정적으로 고른다: 1단계 `ripple/eval/gate_inputs.py`, 2단계 `ripple/eval/cost_gate_inputs.py`, 3단계 `ripple/eval/alt_gate_inputs.py`(3단계는 데모 사례의 블록을 쓰지 않는다).
   - 넣는 글(명세·규칙·파라미터·할 일)에 사례 번호·ECN 번호·대상 부재 ID·(3단계) 엔진 금액이나 지도의 실제 ID(예시는 자리 표시만)가 있거나, 사례 입력에 규칙 ID가 있으면 멈춘다(`ripple/eval/leaks.py`).
2. 계산자가 작업 폴더의 `expected/<사례 ID>.yaml`(기대값)과 `worksheets/<사례 ID>.md`(근거, 명세 모호 목록)를 쓴다.
3. `assemble <작업 폴더> --by "<계산 주체>" --stage N`: 입력과 기대값을 합쳐 `eval/gate_cases/<N>/<사례 ID>.yaml`로 쓰고(`checked_by`는 비워 둠), 작업지를 `eval/gate_cases/<N>/worksheets/`로 옮겨 둔다.
   - 작업지 폴더는 지우지 않고, 작업 폴더의 `worksheets/SUMMARY.md`가 없으면 아무것도 쓰지 않는다.
   - 일부 사례만 다시 계산했으면 `--cases <사례 ID>,<사례 ID> --summary SUMMARY-<이름>.md`로 그 사례만 쓴다(다른 사례의 계산 주체·날짜·요약은 그대로).
4. 사람이 사례를 검토·승인하면 `checked_by`를 채운다.
5. `score --stage N [--approved-only]`: 엔진으로 계산해 채점하고 관문에 미달하면 종료 코드 1.
   - 1단계: 판정 단위 재현율·정밀도와 엔터티 단위 F1(where-used 기준선 대비).
   - 2단계: 사례마다 불일치 항목 목록이고 13건 모두 통과해야 관문 통과다(노출 금액·선상 설치 선택지·지연 파급 비용 칸 포함 — `docs/engine.md`(비용·일정) 4-6·6-8·4-11, `ripple/eval/cost_metrics.py`).
   - 3단계: 사례마다 불일치 항목 목록이고 5건 모두 통과해야 관문 통과다(`ripple/eval/alt_metrics.py`).
6. `restamp --stage N`: 생성기가 바뀌어 지도 ID만 달라졌을 때 사례·사례 입력의 지도 ID 한 줄만 지금 지도로 바꾼다(기대값·계산
   주체·날짜는 그대로). 지도 ID를 뺀 입력이 사례 입력 생성기와 하나라도 다르면 아무것도 쓰지 않고 종료 코드 1이다(그 사례는
   1~3으로 다시 계산). 이어서 `score`로 값이 그대로인지 본다 — 하나라도 다르면 기대값을 고치지 않고 독립 재계산한다.

## 양식(1단계)

```yaml
case_id: G1-000            # 단계-번호(예시는 모두 자리 표시)
stage: 1                   # 관문 단계(1·2·3)
title: "XXXX 블록 판 두께 12 → 14mm"
snapshot:
  generator_seed: 20261020
  snapshot_id: G-xxxxxxxxxxxxxxxx
request:                   # ripple/contracts/analysis.py의 AnalysisRequest 형식
  change:
    ecn_id: GC-000
    title: "횡격벽 하단 판 두께 증가"
    ship_ids: [S-001]
    intent: strength
    ops:
      - {op: thickness, part_ids: ["S-001:XXXX-PL-0001"], from_mm: 12, to_mm: 14}
  as_of: 2026-10-20
  horizon_days: 60
expected:
  impacts:                 # 빠짐없는 전체 정답 집합(엔터티 ID, 영향 종류, 규칙 ID)
    - {entity_id: "PO-0000#1", impact_type: po_change, rule_id: R-T01}
    - {entity_id: "PO-0000#1", impact_type: reorder, rule_id: R-T01}
    - {entity_id: "S-001:XXXX", impact_type: rework, rule_id: R-B01}
  forbidden_impacts:       # 특히 확인하려는 오탐(강조용, 선택)
    - {entity_id: "S-001:YYYY", impact_type: rework}
  unresolved:              # 계산하지 못한 이유의 전체 집합(종류, 엔터티)
    - {kind: po_state, entity_id: "PO-0000#1"}
computed_by: "<계산 주체 모델> (엔진 코드 미열람, <실행 폴더>)"
computed_on: 2026-10-10
checked_by: "검토·승인한 사람"
notes: ""
```

## 양식(2단계, `expected`만. 값은 자리 표시)

```yaml
expected:
  cost_lines:              # 확정일 평가의 비용 줄 전체(줄 ID 기준)
    - line_id: "R-T01:po_change:PO-0000#1"
      amount: {value_krw: 1000000, low_krw: 700000, high_krw: 1300000}   # 범위가 없으면 low·high 생략
      determinacy: known   # 단계를 몰라 단계 구간으로 계산했으면 state_unknown
      formula: "취소·변경률 × 수량 × 단가(손 계산 근거)"
  total: {value_krw: 1000000, low_krw: 700000, high_krw: 1300000}
  unresolved: []
  timing:
    zone_exit_delays: {"S-001:ZXX": 5}      # 출구 지연이 0보다 큰 구역만
    delivery_added_days: 0                  # D_after − D_before. 계산 불가면 null
    delivery_exposure: null                 # 허용 지연(선주 요청, 명세 4-6)의 노출 금액 {value_krw, low_krw, high_krw}. 아니면 null
    delay_ripple: null                      # 지연 파급 비용(명세 4-11, 총액 밖) {value_krw, low_krw, high_krw}. 실제로 밀린 날이 없으면 null
    onboard: null                           # 선상 설치 선택지(명세 6-8). 없으면 null, 있으면 아래 형식
    # onboard: {direction: to_on_board, block_ids: ["S-001:XXXX"], part_ids: ["NEW:…:1"], on_board_days: 1,
    #           total_change: {value_krw: 153000, low_krw: 21600, high_krw: 360000},   # 다른 방식 − 지금
    #           erection_delay_now_days: 21, erection_delay_then_days: 1, exit_delay_now_days: 0, exit_delay_then_days: 0,
    #           delivery_added_now_days: 0, delivery_added_then_days: 0}
    deadline: {kind: by_date, last_day: 2026-11-01}
    deadline_total: {value_krw: 1000000}    # C(마감일). 기간 안 추가손실이 없으면 탐색 마지막 날
    next_day_total: {value_krw: 1200000}    # C(마감일 + 1). none_in_horizon이면 생략
    holds:
      - {po_id: PO-0000, max_hold_days: 10, hold_until: 2026-10-30, deadline_after: {kind: by_date, last_day: 2026-11-08}}
  verdict:
    level: review
    reasons: ["발주된 자재 변경·취소 필요"]
```

## 양식(3단계, `expected`만. 값은 자리 표시)

```yaml
expected:
  alternatives:
    alternatives:            # 요청안 포함 대안 전체
      - alt_id: ALT-REQ
        ops: [{op: thickness, part_ids: ["S-001:X-PL-0009"], from_mm: 12.0, to_mm: 13.5}]
        eligibility: {status: meets, ratio_vs_request: 1.0}
        total: {value_krw: 1000000, low_krw: 700000, high_krw: 1300000}
        max_exit_delay_days: 0
        deadline: {kind: by_date, last_day: 2026-11-01}
        best: {confirm_on: 2026-10-20, holds: [], total: {value_krw: 1000000, low_krw: 700000, high_krw: 1300000}}
        rank: 2
        formula: "요청안(비교 기준)"
      - alt_id: ALT-T2
        ops: [{op: grade, part_ids: ["S-001:X-PL-0009"], from_grade: AH32, to_grade: AH36}]
        eligibility: {status: short, ratio_vs_request: 0.9}
        total: {value_krw: 500000}
        max_exit_delay_days: 0
        deadline: {kind: none_in_horizon, last_day: 2026-12-19}
        best: null           # 충족이 아니면 최적 조합·순위 없음
        rank: null
        formula: "G_alt / G_req = …"
    recommendation: {alt_id: ALT-T1, confirm_on: 2026-10-20, holds: [], total: {value_krw: 800000}}
    cheapest_by_date:
      - {alt_id: ALT-T1, start: 2026-10-20, end: 2026-12-19, total: {value_krw: 800000}}
    omitted:
      - {alt_id: ALT-T5, reason: missing_data}
```
