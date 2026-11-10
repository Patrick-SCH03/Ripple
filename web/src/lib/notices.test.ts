import { describe, expect, it } from 'vitest'
import type { AuditEntry } from '@/api/client'
import { noticeKey, noticeLine, noticeNote, noticeStates } from './notices'

const actor = { login_id: 'kim', name: '김담당', role: 'member' as const, dev: false }
const entry = (seq: number, step: 'sent' | 'acknowledged' | 'replied', on: string, recipient = 'SUP-VL1'): AuditEntry =>
  ({
    seq,
    at: '2026-10-21T01:00:00Z',
    actor,
    action: 'notice',
    ecn_id: 'ECN-1',
    revision: 1,
    record_id: 'R-0000000000000001',
    detail: {
      from_state: 'analyzed',
      to_state: 'analyzed',
      notice: { target: 'supplier', recipient_id: recipient, step, on, note: null },
    },
    prev: '0'.repeat(64),
    digest: '1'.repeat(64),
  }) as AuditEntry

describe('통보 기록 모으기', () => {
  it('받는 쪽마다 단계별 마지막 날짜, 통보가 아닌 줄은 무시, 순번 순으로 나중 줄이 이김', () => {
    const record = { ...entry(1, 'sent', '2026-10-20'), action: 'record' } as AuditEntry
    const states = noticeStates([
      entry(4, 'sent', '2026-10-21'),
      record,
      entry(2, 'sent', '2026-10-19'),
      entry(3, 'replied', '2026-10-20', 'SUP-ST1'),
    ])
    expect(states.get(noticeKey('supplier', 'SUP-VL1'))).toEqual({ sent: '2026-10-21' })
    expect(states.get(noticeKey('supplier', 'SUP-ST1'))).toEqual({ replied: '2026-10-20' })
    expect(states.size).toBe(2)
  })

  it('한 줄 상태: 없음 · 보낸 뒤 경과일 · 마지막 단계만', () => {
    expect(noticeLine(undefined, '2026-10-24')).toBe('통보 기록 없음')
    expect(noticeLine({ sent: '2026-10-21' }, '2026-10-24')).toBe('보냄 10월 21일(수) · 3일째 수령 확인 없음')
    expect(noticeLine({ sent: '2026-10-24' }, '2026-10-24')).toBe('보냄 10월 24일(토)')
    expect(noticeLine({ sent: '2026-10-21', replied: '2026-10-23' }, '2026-10-24')).toBe('회신 받음 10월 23일(금)')
  })

  it('이력 메모는 받는 쪽·단계·날짜·메모', () => {
    const log = { target: 'supplier' as const, recipient_id: 'SUP-VL1', step: 'replied' as const, on: '2026-10-23', note: '중지 확인' }
    expect(noticeNote(log, '협력사')).toBe('협력사 SUP-VL1 · 회신 받음 10월 23일(금) — 중지 확인')
  })
})
