// 비용 구분(계약 1.35.0): 판단 요약 첫 줄 카드·비용 탭 묶음·요약 복사 한 줄이 엔진 구분별 합 그대로인지, 옛 기록은 null인지.
import { describe, expect, it } from 'vitest'
import type { AnalysisResult } from '@/api/client'
import { briefingText } from './briefing'
import {
  costHead,
  costSections,
  crewOf,
  formatHours,
  groupMeta,
  hoursRange,
  laborWorks,
  lineLabel,
  lineMeta,
  splitLine,
} from './costSplit'
import { sortedLines } from './summary'

const amount = (value: number, low = value, high = value) => ({ value, low, high })
const hours = (value: number, low = value, high = value) => ({ value, low, high })

interface LineSpec {
  id: string
  kind?: 'labor' | 'material' | 'damages'
  item?: string
  value: number
  hours?: number
  label?: string
  formula?: string
  inputs?: Record<string, number | string>
}

const line = (spec: LineSpec) => ({
  line_id: spec.id,
  rule_id: spec.id.split(':')[0],
  entity_id: spec.id.split(':').slice(2).join(':'),
  label: spec.label ?? spec.id,
  formula: spec.formula ?? '',
  inputs: spec.inputs ?? {},
  amount: amount(spec.value, Math.round(spec.value / 2), spec.value * 2),
  determinacy: 'known',
  sources: [],
  param_keys: [],
  factors: [],
  ...(spec.kind ? { kind: spec.kind, item: spec.item } : {}),
  ...(spec.hours != null ? { hours: hours(spec.hours, spec.hours / 2, spec.hours * 2) } : {}),
})

const LINES: LineSpec[] = [
  {
    id: 'R-B01:rework:S-001:B31P',
    kind: 'labor',
    item: 'rework',
    value: 27_899_184,
    hours: 557.984,
    label: 'B31P 블록 재작업 — 직영',
  },
  {
    id: 'R-B01:rework:S-001:B31P@CRW-03',
    kind: 'labor',
    item: 'rework',
    value: 6_974_796,
    hours: 139.496,
    label: 'B31P 블록 재작업 — 3작업반 추가 공비',
  },
  { id: 'R-T02:taper:S-001:P1', kind: 'labor', item: 'machining', value: 100_000, hours: 2, label: '판 1 테이퍼 가공' },
  { id: 'R-T02:taper:S-001:P3', kind: 'labor', item: 'machining', value: 100_000, hours: 2, label: '판 3 테이퍼 가공' },
  { id: 'R-T02:taper:S-001:P4', kind: 'labor', item: 'machining', value: 100_000, hours: 2, label: '판 4 테이퍼 가공' },
  { id: 'R-D01:drawing_revision:DWG-1@A', kind: 'labor', item: 'drawing', value: 672_000, hours: 16 },
  {
    id: 'R-T01:po_change:PO-0037#1',
    kind: 'material',
    item: 'po_change',
    value: 1_793_389,
    formula: '취소·변경률 30%(자재 확보) × 수량 12.5t × 단가 478,290원',
    inputs: { qty: 12.5, moved_qty: 0, unit_price: 478_290, stage: 'material_secured' },
  },
  {
    id: 'R-T01:reorder:PO-0037#1',
    kind: 'material',
    item: 'reorder',
    value: 843_948,
    inputs: { bought_value: 5_626_320 },
  },
  {
    id: 'C-01:material:S-001:B31P-PL-007',
    kind: 'material',
    item: 'material_diff',
    value: 632_961,
    formula: '새 4.706t × 1,240,000원 − 원래 4t × 1,240,000원',
    inputs: { qty: 4, unit_price: 1_240_000, new_qty: 4.705882, new_unit_price: 1_240_000 },
  },
]

const SPLIT = {
  labor_hours: hours(719.48, 359.74, 1438.96),
  labor: amount(35_845_980, 17_922_990, 71_691_960),
  material: amount(3_270_298, 1_635_149, 6_540_596),
  material_diff: amount(632_961, 316_481, 1_265_922),
  purchase: amount(2_637_337, 1_318_668, 5_274_674),
  damages: amount(0),
}

function result(specs: LineSpec[] = LINES, split: unknown = SPLIT): AnalysisResult {
  return {
    request: { as_of: '2026-10-26', holds: [], change: { ecn_id: 'ECN-D-0119', title: '판 두께' } },
    verdict: { level: 'review', reasons: [] },
    total: amount(39_116_278, 19_558_139, 78_232_556),
    impacts: [
      {
        entity_type: 'po_line',
        entity_id: 'PO-0037#1',
        ship_id: 'S-001',
        impact_type: 'po_change',
        severity: 'high',
        rule_id: 'R-T01',
        path: [],
        note: '',
      },
    ],
    cost_lines: specs.map(line),
    ...(split ? { cost_split: split } : {}),
    schedule: { zone_exits: [], max_exit_delay_days: 0, delivery: { added_delay_days: 0 } },
    timing: { deadline: { kind: 'by_date', last_day: '2026-11-02' }, holds: [], reallocations: [], curve: [] },
  } as unknown as AnalysisResult
}

describe('공수 표기', () => {
  it('100 이상은 정수(쉼표), 그 아래는 소수 한 자리, 끝 .0은 지움', () => {
    expect(formatHours(806.861)).toBe('807')
    expect(formatHours(1660.719)).toBe('1,661')
    expect(formatHours(21.265)).toBe('21.3')
    expect(formatHours(16)).toBe('16')
    expect(formatHours(0.5)).toBe('0.5')
    expect(hoursRange(243.099, 1660.719)).toBe('243~1,661 MH')
    expect(hoursRange(16, 16)).toBeNull()
  })
})

describe('판단 요약 첫 줄', () => {
  it('추가 공수: 큰 MH = 엔진 공수 합, ≈ 금액 = 공수 금액, 작업 구분은 실제 있는 것만 정해진 순서', () => {
    const head = costHead(result())
    expect(head?.labor).toEqual({
      hours: '719 MH',
      money: '≈ 3,585만원',
      range: '360~1,439 MH',
      works: '재작업 · 가공 · 도면',
    })
  })

  it('추가 재료비: 금액 = 엔진 재료비, 자재 차이 · 구매(있는 구매만), 이미 발주 n건(확정일 단계)', () => {
    const head = costHead(result())
    expect(head?.material).toMatchObject({
      value: '327만원',
      parts: '자재 차이 63만원 · 구매 264만원(발주 변경 · 새 발주)',
      ordered: '이미 발주 1건 · 자재 확보 1',
      caution: null,
    })
  })

  it('총변경비용 한 줄 = 두 금액 합(지체상금이 붙으면 + 지체상금)', () => {
    expect(costHead(result())?.total).toEqual({ value: '3,912만원', range: '1,956만~7,823만원', sum: '공수 + 재료비' })
    const late = costHead(result(LINES, { ...SPLIT, damages: amount(5_000_000) }))
    expect(late?.total.sum).toBe('공수 + 재료비 + 지체상금')
  })

  it('공수 줄이 없으면 공수 카드는 없음(null), 재료비 줄·발주 품목이 없으면 재료비도 없음', () => {
    const onlyMaterial = costHead(result(LINES.filter((l) => l.kind === 'material')))
    expect(onlyMaterial?.labor).toBeNull()
    expect(onlyMaterial?.material).not.toBeNull()
    const drawing = result(LINES.filter((l) => l.item === 'drawing'))
    expect(costHead({ ...drawing, impacts: [] })?.material).toBeNull()
  })

  it('구분이 없는 옛 기록은 null(이전처럼 총변경비용 하나)', () => {
    const old = result(
      LINES.map(({ kind: _kind, item: _item, hours: _hours, ...rest }) => rest),
      null,
    )
    expect(costHead(old)).toBeNull()
    expect(costSections(old, sortedLines(old.cost_lines))).toBeNull()
    expect(splitLine(old)).toBeNull()
  })

  it('작업 구분은 0원 줄을 세지 않는다', () => {
    const zero = [...LINES, { id: 'C-04:after_paint:S-001:B31P', kind: 'labor' as const, item: 'after_paint', value: 0, hours: 0 }]
    expect(laborWorks(result(zero).cost_lines)).toEqual(['재작업', '가공', '도면'])
  })
})

describe('비용 탭 묶음', () => {
  it('공수(소계·MH) → 재료비(자재 차이 · 구매) 순, 소계는 엔진 구분별 합, 묶음 안은 금액 큰 순', () => {
    const r = result()
    const sections = costSections(r, sortedLines(r.cost_lines)) ?? []
    expect(sections.map((s) => s.kind)).toEqual(['labor', 'material'])
    expect(sections[0].subtotal).toEqual(SPLIT.labor)
    expect(sections[0].hours).toEqual(SPLIT.labor_hours)
    expect(sections[0].parts[0].lines.map((l) => l.line_id)).toEqual([
      'R-B01:rework:S-001:B31P',
      'R-B01:rework:S-001:B31P@CRW-03',
      'R-D01:drawing_revision:DWG-1@A',
      'R-T02:taper:S-001:P1',
      'R-T02:taper:S-001:P3',
      'R-T02:taper:S-001:P4',
    ])
    expect(sections[1].subtotal).toEqual(SPLIT.material)
    expect(sections[1].parts.map((p) => [p.title, p.lines.length])).toEqual([
      ['자재 차이', 1],
      ['구매', 2],
    ])
  })

  it('줄 근거: 공수 줄은 MH · 작업반, 재료비 줄은 수량(단위는 계산식) · 단가, 할증은 신규 구매 자재', () => {
    const [direct, crew, , , , , po, reorder, material] = result().cost_lines
    expect(lineMeta(direct)).toBe('558 MH · 직영')
    expect(lineMeta(crew)).toBe('139 MH · 3작업반 추가 공비')
    expect(lineLabel(crew)).toBe('B31P 블록 재작업')
    expect(lineLabel(result().cost_lines[2])).toBe('판 1 테이퍼 가공')
    expect(crewOf(crew)).toBe('3작업반')
    expect(lineMeta(po)).toBe('수량 12.5t · 단가 478,290원/t')
    expect(lineMeta(reorder)).toBe('신규 구매 자재 563만원 × 할증률')
    expect(lineMeta(material)).toBe('수량 4→4.706t · 단가 1,240,000원/t')
  })

  it('묶은 줄의 MH = 줄 공수 합(공수 줄만)', () => {
    const tapers = result().cost_lines.filter((l) => l.item === 'machining')
    expect(groupMeta(tapers)).toBe('6 MH')
    expect(groupMeta(result().cost_lines.filter((l) => l.kind === 'material'))).toBeNull()
  })
})

describe('요약 복사', () => {
  it("총변경비용 다음 줄에 '추가 공수 n MH · 재료비 ○○만원'(결정 도우미와 같은 고정 문장)", () => {
    const text = briefingText(result())
    const lines = text.split('\n')
    const at = lines.findIndex((l) => l.startsWith('총변경비용:'))
    expect(lines[at + 1]).toBe('추가 공수 719 MH · 재료비 327만원')
    expect(briefingText(result(LINES, null))).not.toContain('추가 공수')
  })
})
