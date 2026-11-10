import { describe, expect, it } from 'vitest'
import { diffLines } from './mapDiff'

describe('상태 갱신 미리보기 줄', () => {
  it('단계 변화 · 납기 전후 · 공정 실적, 확인만은 줄에 없음', () => {
    expect(
      diffLines({
        status_changed: [{ po_id: 'PO-0131', before: 'in_fabrication', after: 'received' }],
        plan_changed: [{ po_id: 'PO-0042', field: 'lead_time_days', before: 32, after: 39 }],
        activities: [{ activity_id: 'S-001:B31P:assembly', started: '2026-10-20', finished: null }],
        confirmed_only: 3,
      }),
    ).toEqual(['PO-0131 제작 → 입고', 'PO-0042 입고까지(납기) 32일 → 39일', 'B31P 대조립 실제 착수 10월 20일(화)'])
  })

  it('처음 관측한 발주와 계획 발주일 변경', () => {
    expect(
      diffLines({
        status_changed: [{ po_id: 'PO-1', before: null, after: 'ordered' }],
        plan_changed: [{ po_id: 'PO-1', field: 'planned_order_date', before: '2026-10-01', after: '2026-10-08' }],
        activities: [],
        confirmed_only: 0,
      }),
    ).toEqual(['PO-1 기록 없음 → 발주', 'PO-1 계획 발주일 10월 1일(목) → 10월 8일(목)'])
  })
})
