import { describe, expect, it } from 'vitest'
import type { AnalysisResult, CostLine, HoldAdvice, LineOutlook } from '@/api/client'
import {
  blockDelays,
  evidenceTarget,
  factorText,
  holdFor,
  holdSentence,
  multipleText,
  outlookSentences,
  reworkFactorText,
  reworkFactors,
  shareText,
} from './costDetail'
import { addDays } from './format'

const amount = (value: number, low = value, high = value) => ({ value, low, high })

function line(lineId: string, entityId: string, value: number, outlook: LineOutlook | null = null): CostLine {
  return {
    line_id: lineId,
    rule_id: 'R-T01',
    entity_id: entityId,
    label: lineId,
    formula: '',
    inputs: {},
    amount: amount(value),
    determinacy: 'known',
    sources: [],
    param_keys: [],
    factors: [],
    reason: null,
    outlook,
  }
}

describe('addDays', () => {
  it('달·해·윤년을 넘기고, 형식이 다르면 그대로', () => {
    expect(addDays('2026-10-31', 1)).toBe('2026-11-01')
    expect(addDays('2026-11-01', -1)).toBe('2026-10-31')
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
    expect(addDays('2024-03-01', -1)).toBe('2024-02-29')
    expect(addDays('2026-10-20', 0)).toBe('2026-10-20')
    expect(addDays('오늘', 1)).toBe('오늘')
  })
})

describe('가정값 표기', () => {
  it('비율은 %(부동소수 찌꺼기 없이), 범위도 %', () => {
    expect(factorText({ value: 0.8, low: 0.55, high: 1, unit: '비율' })).toEqual({ value: '80%', range: '55~100%' })
    expect(factorText({ value: 0.0003, low: 0.0002, high: 0.0005, unit: '비율' })).toEqual({
      value: '0.03%',
      range: '0.02~0.05%',
    })
    expect(factorText({ value: 0.07, low: 0.07, high: 0.07, unit: '비율' })).toEqual({ value: '7%', range: null })
  })

  it('원 단위는 세 자리 쉼표와 받은 단위', () => {
    expect(factorText({ value: 50000, low: 40000, high: 60000, unit: '원/시간' })).toEqual({
      value: '50,000원/시간',
      range: '40,000~60,000원/시간',
    })
    expect(factorText({ value: 50000, low: 30000, high: 100000, unit: '원/t' }).range).toBe('30,000~100,000원/t')
  })

  it('그 밖은 소수 셋째 자리까지 끝 0 없이, 최소 = 최대면 범위 없음', () => {
    expect(factorText({ value: 30, low: 19, high: 46, unit: '시간/t' })).toEqual({ value: '30시간/t', range: '19~46시간/t' })
    expect(factorText({ value: 0.15, low: 0.15, high: 0.15, unit: 't' })).toEqual({ value: '0.15t', range: null })
    expect(factorText({ value: 1.5, low: 1, high: 2, unit: '배' })).toEqual({ value: '1.5배', range: '1~2배' })
    expect(factorText({ value: 1234.5678, low: 1000, high: 2000, unit: '일' }).value).toBe('1,234.568일')
  })
})

describe('늦어지면 문장', () => {
  const base = { amount: amount(25_932_600, 8_759_456, 63_621_312) }

  it('금액이 바뀌는 날: 전날까지는 그대로, 그날부터 금액과 차이·단계 변화', () => {
    const outlook: LineOutlook = {
      kind: 'changes',
      on: '2026-10-28',
      amount: amount(38_034_480, 14_522_256, 88_170_840),
      note: '단계 선행의장 → 선행도장',
    }
    expect(outlookSentences({ ...base, outlook })).toEqual([
      '2026-10-27까지 확정 시 지금 금액 그대로',
      '2026-10-28부터 3,803만원 · 1,210만원 늘어남(단계 선행의장 → 선행도장)',
    ])
  })

  it('줄어드는 경우·달을 넘기는 전날', () => {
    const outlook: LineOutlook = { kind: 'changes', on: '2026-11-01', amount: amount(20_000_000) }
    expect(outlookSentences({ ...base, outlook })).toEqual([
      '2026-10-31까지 확정 시 지금 금액 그대로',
      '2026-11-01부터 2,000만원 · 593만원 줄어듦',
    ])
  })

  it('대표값이 같고 범위만 바뀌면 범위로 알림', () => {
    const outlook: LineOutlook = { kind: 'changes', on: '2026-10-25', amount: amount(25_932_600, 0, 70_000_000) }
    expect(outlookSentences({ ...base, outlook })[1]).toBe('2026-10-25부터 금액 범위 0원~7,000만원')
  })

  it('그대로 · 없어짐 · 보지 않음 · 결과에 없음', () => {
    expect(outlookSentences({ ...base, outlook: { kind: 'steady', checked_until: '2026-12-19' } })).toEqual([
      '2026-12-19까지 늦게 확정해도 금액 그대로',
    ])
    expect(outlookSentences({ ...base, outlook: { kind: 'removed', on: '2026-10-21' } })).toEqual([
      '2026-10-20까지 확정 시 지금 금액 그대로',
      '2026-10-21부터 확정 시 이 항목 없어짐',
    ])
    expect(outlookSentences({ ...base, outlook: { kind: 'unchecked' } })).toEqual([
      '확정일 뒤 탐색 기간 없음 · 늦어질 때 미계산',
    ])
    expect(outlookSentences({ ...base, outlook: null })).toEqual([])
  })
})

describe('블록 공정 지연', () => {
  it('그 블록 공정만 공정 순으로(이름이 앞부분만 같은 블록은 빼고)', () => {
    const added = {
      'S-001:B31P:erection': 71,
      'S-001:B31P:pre_outfitting': 7,
      'S-001:B31:assembly': 3,
      'S-001:B31P:pre_painting': 6,
      'S-001:ZCT:exit': 68,
    }
    expect(blockDelays({ entity_id: 'S-001:B31P' }, added)).toEqual([
      { name: '선행의장', days: 7 },
      { name: '선행도장', days: 6 },
      { name: '탑재', days: 71 },
    ])
    expect(blockDelays({ entity_id: 'PO-0037#1' }, added)).toEqual([])
  })
})

describe('보류 권고 · 비중 · 근거', () => {
  const advice: HoldAdvice = {
    po_id: 'PO-0131',
    rule_id: 'R-H01',
    max_hold_days: 12,
    hold_until: '2026-11-01',
    avoided: amount(119_350, 0, 200_000),
    reason: '',
    deadline_after: { kind: 'by_date', last_day: '2026-11-08' },
    line_ids: ['PO-0131#1'],
  }
  const loss = line('R-M02:po_change:PO-0131#1', 'PO-0131#1', 716_100)
  const premium = line('R-T01:reorder:PO-0131#1', 'PO-0131#1', 300_000)
  const other = line('R-T01:po_change:PO-0099#1', 'PO-0099#1', 900_000)
  const sorted = [other, loss, premium]

  it('권고 품목을 가리키는 줄 중 금액 순 첫 줄에만', () => {
    expect(holdFor(loss, sorted, [advice])).toBe(advice)
    expect(holdFor(premium, sorted, [advice])).toBeNull()
    expect(holdFor(other, sorted, [advice])).toBeNull()
    expect(holdFor(loss, sorted, [])).toBeNull()
  })

  it('보류 문장에 발주·기한·최대 일수·줄어드는 금액', () => {
    const text = holdSentence(advice)
    for (const part of ['PO-0131', '2026-11-01까지', '최대 12일', '최대 12만원']) expect(text).toContain(part)
  })

  it('비중은 절감을 뺀 비용 항목 합계 대비, 절감 줄은 따로', () => {
    const saving = line('R-M01:stock:LOT-04:P', 'LOT-04', -1_000_000)
    const all = [other, loss, premium, saving]
    expect(shareText(other, all)).toBe('비용 항목(절감 제외) 합계의 47%')
    expect(shareText(line('x', 'x', 10), [...all, line('x', 'x', 10)])).toBe('비용 항목(절감 제외) 합계의 1% 미만')
    expect(shareText(saving, all)).toBe('절감 항목(총변경비용에서 뺌)')
    expect(shareText(line('z', 'z', 0), all)).toBeNull()
  })

  it('근거: 그래프에 있는 엔터티, 호선은 인도 지연 공정, 없으면 null', () => {
    const result = {
      graph: { nodes: [{ id: 'PO-0131#1' }, { id: 'S-001:delivery' }, { id: 'S-001' }], edges: [] },
      impacts: [{ impact_type: 'delivery_delay', ship_id: 'S-001', entity_id: 'S-001:delivery' }],
    } as unknown as Pick<AnalysisResult, 'graph' | 'impacts'>
    expect(evidenceTarget({ entity_id: 'PO-0131#1' }, result)).toBe('PO-0131#1')
    expect(evidenceTarget({ entity_id: 'S-001' }, result)).toBe('S-001:delivery')
    expect(evidenceTarget({ entity_id: 'PO-0131' }, result)).toBe('PO-0131#1')
    expect(evidenceTarget({ entity_id: 'LOT-04' }, result)).toBeNull()
  })
})

describe('재작업 배수와 난이도 계수(1.32.0, 따로 표시)', () => {
  const multiplier = {
    label: '재작업 배수(선행도장)',
    unit: '배',
    value: 2,
    low: 1.5,
    high: 3,
    status: 'mentor' as const,
    keys: ['rework_multiplier.pre_painting'],
  }
  const difficulty = {
    shape: 'curved' as const,
    shape_factor: 1.3,
    outfit_factor: 1.0231,
    electric_factor: 1.0111,
    cap: 2,
    value: 1.344793,
    capped: false,
  }

  it("배수와 난이도를 곱하지 않고 나란히: '배수 2.0(선행도장) · 난이도 1.34(곡블록 1.3 × 의장 밀도 1.02 × 전장품 1.01)'", () => {
    const factors = reworkFactors({ factors: [multiplier], difficulty })!
    expect(reworkFactorText(factors)).toBe('배수 2.0(선행도장) · 난이도 1.34(곡블록 1.3 × 의장 밀도 1.02 × 전장품 1.01)')
    expect(reworkFactorText(factors)).not.toContain('2.69')
  })

  it('1인 계수는 괄호에서 빼고, 상한을 적용했으면 상한', () => {
    const flat = { ...difficulty, shape: 'flat' as const, shape_factor: 1, outfit_factor: 1.4, electric_factor: 1, value: 1.4 }
    expect(reworkFactorText(reworkFactors({ factors: [multiplier], difficulty: flat })!)).toBe(
      '배수 2.0(선행도장) · 난이도 1.4(의장 밀도 1.4)',
    )
    const capped = { ...difficulty, shape: 'bow_stern' as const, shape_factor: 1.5, outfit_factor: 1.4, value: 2, capped: true }
    expect(reworkFactorText(reworkFactors({ factors: [], difficulty: capped })!)).toBe(
      '난이도 2.0(선수미 블록 1.5 × 의장 밀도 1.4 × 전장품 1.01) · 상한 2.0 적용',
    )
  })

  it('재작업 줄이 아니면 없음, 표기는 소수 둘째 자리(한 자리는 남김)', () => {
    expect(reworkFactors({ factors: [], difficulty: null })).toBeNull()
    expect([multipleText(2), multipleText(0.75), multipleText(1.344793), multipleText(1.3)]).toEqual([
      '2.0',
      '0.75',
      '1.34',
      '1.3',
    ])
  })
})