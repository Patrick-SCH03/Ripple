import { describe, expect, it } from 'vitest'
import type { AnalysisResult } from '@/api/client'
import { detailNumbers, orderedCard, orderedItems } from './ordered'

const amount = (value: number) => ({ value, low: value, high: value })

const impact = (entity_type: string, entity_id: string, impact_type: string) => ({
  entity_type,
  entity_id,
  ship_id: 'S-001',
  impact_type,
  severity: 'high',
  rule_id: 'R-T01',
  path: [],
  note: '',
})

const line = (line_id: string, entity_id: string, stage?: string) => ({
  line_id,
  rule_id: line_id.split(':')[0],
  entity_id,
  label: line_id,
  formula: '',
  inputs: stage ? { stage } : {},
  amount: amount(100),
  determinacy: 'known',
  sources: [],
  param_keys: [],
  factors: [],
})

function result(impacts: unknown[], cost_lines: unknown[]): AnalysisResult {
  return {
    request: { as_of: '2026-10-26', holds: [] },
    total: amount(1_000_000),
    impacts,
    cost_lines,
    schedule: { zone_exits: [], max_exit_delay_days: 0, delivery: { added_delay_days: 0 } },
    timing: { deadline: { kind: 'by_date', last_day: '2026-11-02' }, holds: [], reallocations: [], curve: [] },
  } as unknown as AnalysisResult
}

describe('이미 발주된 품목', () => {
  it('발주 품목 영향을 확정일 단계(그 품목 비용 줄의 단계)로 센다: 많이 진행된 단계부터, 미발주는 빼고', () => {
    const r = result(
      [
        impact('po_line', 'PO-1#1', 'po_change'),
        impact('po_line', 'PO-1#1', 'reorder'),
        impact('po_line', 'PO-2#1', 'po_change'),
        impact('po_line', 'PO-3#1', 'po_change'),
        impact('po_line', 'PO-4#1', 'po_change'),
        impact('block', 'S-001:B31P', 'rework'),
      ],
      [
        line('R-T01:po_change:PO-1#1', 'PO-1#1', 'processed'),
        line('R-T01:reorder:PO-1#1', 'PO-1#1', 'processed'),
        line('R-T01:po_change:PO-2#1', 'PO-2#1', 'in_fabrication'),
        line('R-T01:po_change:PO-3#1', 'PO-3#1', 'in_fabrication'),
        line('R-T01:po_change:PO-4#1', 'PO-4#1', 'not_ordered'),
      ],
    )
    expect(orderedItems(r)).toEqual({
      ordered: 3,
      stages: [
        { stage: 'processed', label: '가공', count: 1 },
        { stage: 'in_fabrication', label: '제작', count: 2 },
      ],
      unknown: 0,
    })
    expect(orderedCard(r)).toMatchObject({ id: 'ordered', value: '3건', detail: '가공 1 · 제작 2', caution: undefined })
  })

  it('단계를 모르는 품목은 따로 주의 한 줄, 발주 품목 영향이 없거나 모두 미발주면 카드 없음', () => {
    const unknown = result([impact('po_line', 'PO-9#1', 'po_change')], [line('R-T01:po_change:PO-9#1', 'PO-9#1')])
    expect(orderedCard(unknown)).toMatchObject({ value: '0건', detail: undefined, caution: '발주 단계 판단 불가 1건' })
    expect(orderedCard(result([impact('block', 'S-001:B31P', 'rework')], []))).toBeNull()
    const notYet = result([impact('po_line', 'PO-4#1', 'po_change')], [line('R-T01:po_change:PO-4#1', 'PO-4#1', 'not_ordered')])
    expect(orderedCard(notYet)).toBeNull()
    // 발주 전 품목의 보류 권고(R-H01)는 비용 줄이 없어도 '판단 불가'로 세지 않는다
    const hold = result([impact('po_line', 'PO-0098#1', 'po_hold')], [])
    expect(orderedItems(hold)).toBeNull()
    expect(orderedCard(hold)).toBeNull()
  })

  it('상세 첫 화면 순서: 결정 기한(마감일) → 이미 발주된 품목 → 총변경비용 → 나머지', () => {
    const r = result([impact('po_line', 'PO-1#1', 'po_change')], [line('R-T01:po_change:PO-1#1', 'PO-1#1', 'received')])
    expect(detailNumbers(r).map((card) => card.id)).toEqual(['deadline', 'ordered', 'total'])
    expect(detailNumbers(result([], [])).map((card) => card.id)).toEqual(['deadline', 'total'])
  })
})
