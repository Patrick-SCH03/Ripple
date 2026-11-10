// 보류 권고의 결재 기간 표시와 인도 임박 띠: 엔진 값(보류 일수·순위·금액)은 그대로, 글만 더한다.
import { describe, expect, it } from 'vitest'
import type { AnalysisResult, ApprovalPlan } from '@/api/client'
import { approvalHoldShort, approvalHoldText } from './approvalHold'
import { DELIVERY_IMMINENT_TEXT, deliveryImminent } from './deliveryImminent'
import { todoText } from './summary'

// 서버(ripple/records/approval.py)가 만든 결재 계획 그대로 — 화면은 규칙·상수를 갖지 않는다
const LONGER = '결재 중(약 6근무일 — 결재 3단계 × 1~2일)에는 보류 유지 가능 · 권고 13일까지 보류 시 공급사 협의 필요'
const plan: Pick<ApprovalPlan, 'holds'> = {
  holds: [
    { po_id: 'PO-0131', outlasts: true, approval_end: '2026-10-28', text: LONGER, short: '결재 중 보류 가능 · 13일까지는 공급사 협의' },
    { po_id: 'PO-0007', outlasts: false, approval_end: '2026-10-28', text: '권고 8일은 결재 기간(약 6근무일 — 결재 3단계 × 1~2일)보다 짧음 · 그 안에 결재를 마쳐야 보류로 손실을 피함', short: '결재 기간보다 짧은 보류' },
  ],
}

describe('결재 기간과 보류 권고(서버 결재 계획 값)', () => {
  it('발주마다 서버 문구 그대로, 결재 계획이 없으면 짐작하지 않음(null)', () => {
    expect(approvalHoldText({ po_id: 'PO-0131' }, plan)).toBe(LONGER)
    expect(approvalHoldShort({ po_id: 'PO-0131' }, plan)).toBe('결재 중 보류 가능 · 13일까지는 공급사 협의')
    expect(approvalHoldShort({ po_id: 'PO-0007' }, plan)).toBe('결재 기간보다 짧은 보류')
    expect(approvalHoldText({ po_id: 'PO-9999' }, plan)).toBeNull()
    expect(approvalHoldText({ po_id: 'PO-0131' }, null)).toBeNull()
  })

  it('할 일 보류 권고 줄: 결재 계획을 주면 결재 기간 한 줄(note), 세부 글은 그대로', () => {
    const advice = {
      po_id: 'PO-0131',
      max_hold_days: 13,
      hold_until: '2026-11-02',
      deadline_after: { kind: 'by_date', last_day: '2026-10-31' },
      avoided: { value: 80_000, low: 80_000, high: 80_000 },
    }
    const deadline = { kind: 'by_date', last_day: '2026-10-31' } as const
    const plain = todoText({ kind: 'hold', advice } as never, deadline)
    const withNote = todoText({ kind: 'hold', advice } as never, deadline, plan as ApprovalPlan)
    expect(plain.note).toBeUndefined()
    expect(withNote.detail).toBe(plain.detail)
    expect(withNote.note).toBe(LONGER)
  })
})

describe('인도 임박 띠', () => {
  const result = (added: number | null) =>
    ({ schedule: { delivery: added === null ? null : { added_delay_days: added } } }) as unknown as Pick<
      AnalysisResult,
      'schedule'
    >

  it('요청안이 인도를 늦추면만 켜짐(계획 인도일은 결과에 없어 쓰지 않음), 계산은 그대로라고', () => {
    expect(deliveryImminent(result(5))).toEqual({
      title: DELIVERY_IMMINENT_TEXT,
      detail: '이 변경으로 인도 5일 지연 · 대안 순위·금액 계산은 그대로',
    })
    expect(deliveryImminent(result(0))).toBeNull()
    expect(deliveryImminent(result(null))).toBeNull()
  })
})
