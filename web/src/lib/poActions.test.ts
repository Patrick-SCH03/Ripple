import { describe, expect, it } from 'vitest'
import type { AnalysisResult, CostLine, HoldAdvice } from '@/api/client'
import { poActions } from './poActions'

const amount = (value: number) => ({ value, low: value, high: value })

function line(lineId: string, entityId: string, value: number, inputs: Record<string, unknown> = {}): CostLine {
  return {
    line_id: lineId,
    rule_id: lineId.split(':')[0],
    entity_id: entityId,
    label: lineId,
    formula: '',
    inputs: inputs as CostLine['inputs'],
    amount: amount(value),
    determinacy: 'known',
    sources: [],
    param_keys: [],
    factors: [],
    reason: null,
    outlook: null,
  }
}

function result(lines: CostLine[], holds: Partial<HoldAdvice>[] = []): AnalysisResult {
  return { cost_lines: lines, timing: { holds } } as unknown as AnalysisResult
}

describe('발주 조치 요약(명세 4-10)', () => {
  it('규격 변경 품목: 변경·취소 → 재발주 순, 단계 이름, 합계', () => {
    const rows = poActions(
      result([
        line('R-T01:reorder:PO-0001#1', 'PO-0001#1', 200, { stage: 'in_fabrication' }),
        line('R-T01:po_change:PO-0001#1', 'PO-0001#1', 600, { stage: 'in_fabrication' }),
      ]),
    )
    expect(rows).toHaveLength(1)
    expect(rows[0].stage).toBe('제작')
    expect(rows[0].actions.map((a) => a.kind)).toEqual(['change', 'reorder'])
    expect(rows[0].total).toBe(800)
  })

  it('할증 0원이라도 발주 뒤면 재고 충당 문구, 단계를 모르면 판단 불가', () => {
    const [processed] = poActions(result([line('R-T01:reorder:PO-0078#1', 'PO-0078#1', 0, { stage: 'processed' })]))
    expect(processed.stage).toBe('가공')
    expect(processed.actions[0].text).toContain('재고로 채워')
    const [unknown] = poActions(result([line('R-T01:reorder:PO-0079#1', 'PO-0079#1', 500)]))
    expect(unknown.stage).toBeNull()
    expect(unknown.actions[0].text).toContain('판단 불가')
  })

  it('미발주면 재발주 문구가 "규격만 수정해 발주"(할증 0)', () => {
    const [row] = poActions(result([line('R-T01:reorder:PO-0002#1', 'PO-0002#1', 0, { stage: 'not_ordered' })]))
    expect(row.actions[0].text).toContain('규격만 수정해')
    expect(row.stage).toBe('미발주')
  })

  it('빼는 부재 감축, 잉여 자재 전용(출처 품목에), 재고 충당(로트에), 보류 권고(품목마다)', () => {
    const rows = poActions(
      result(
        [
          line('R-M02:po_change:PO-0003#1', 'PO-0003#1', 100, { stage: 'received' }),
          line('R-M01:handling:PO-0003#1:PO-0009#2', 'PO-0009#2', 5),
          line('R-M01:stock:LOT-01:S-001:B11P-PL-001', 'LOT-01', -50),
          line('R-B01:rework:S-001:B11P', 'S-001:B11P', 999),
        ],
        [{ po_id: 'PO-0004', line_ids: ['PO-0004#1', 'PO-0004#2'], max_hold_days: 7 }],
      ),
    )
    expect(rows.map((r) => r.lineId)).toEqual(['LOT-01', 'PO-0003#1', 'PO-0004#1', 'PO-0004#2'])
    const po3 = rows.find((r) => r.lineId === 'PO-0003#1')
    expect(po3?.actions.map((a) => a.kind)).toEqual(['reduce', 'reallocate'])
    expect(po3?.actions[1].text).toContain('PO-0009#2')
    expect(rows.find((r) => r.lineId === 'PO-0004#2')?.actions[0].text).toContain('최대 7일 보류')
  })

  it('발주와 무관한 줄만 있으면 빈 목록', () => {
    expect(poActions(result([line('R-B01:rework:S-001:B11P', 'S-001:B11P', 999)]))).toEqual([])
  })
})
