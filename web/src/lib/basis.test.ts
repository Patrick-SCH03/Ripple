import { describe, expect, it } from 'vitest'
import type { SnapshotInfo } from '@/api/client'
import { DEFAULT_HORIZON_DAYS } from './assistant'
import { basisContext, basisNote, defaultBasis, todayKst } from './basis'

const info = (extra: Partial<SnapshotInfo> = {}): SnapshotInfo => ({
  snapshot_id: 'G-0000000000000002',
  name: 'plant.xlsx',
  origin: 'excel_import',
  data_mode: 'real',
  default: false,
  counts: { ships: 2, blocks: 14, parts: 800, purchase_orders: 100, activities: 120 },
  ship_ids: ['S-001', 'S-002'],
  status_date: '2026-10-20',
  ...extra,
})

describe('분석 기준(가져온 지도)', () => {
  it('오늘은 한국 시간 날짜(UTC 15시 = 다음 날 0시)', () => {
    expect(todayKst(new Date('2026-10-08T14:59:00Z'))).toBe('2026-10-08')
    expect(todayKst(new Date('2026-10-08T15:00:00Z'))).toBe('2026-10-09')
  })

  it('기본값: 지도의 호선 전부 · 기준일 = 자료 기준일(없으면 오늘)', () => {
    expect(defaultBasis(info(), '2026-10-08')).toEqual({ shipIds: ['S-001', 'S-002'], asOf: '2026-10-20' })
    expect(defaultBasis(info({ status_date: null }), '2026-10-08').asOf).toBe('2026-10-08')
  })

  it('기준일이 자료 기준일과 다르면 계산이 어떻게 달라지는지 알림(같으면 없음)', () => {
    const data = info()
    expect(basisNote({ shipIds: ['S-001'], asOf: '2026-10-20' }, data)).toBeNull()
    expect(basisNote({ shipIds: ['S-001'], asOf: '2026-10-25' }, data)).toContain('계획 간격으로 추정')
    expect(basisNote({ shipIds: ['S-001'], asOf: '2026-10-10' }, data)).toContain('기준일 이후 상태 기록은 제외')
    expect(basisNote({ shipIds: ['S-001'], asOf: '2026-10-10' }, info({ status_date: null }))).toContain('상태 기록')
  })

  it('비서 맥락: 호선이 없거나 날짜가 비면 보내지 않음, 확정일은 기준일(비움)·탐색 기간 기본', () => {
    expect(basisContext({ shipIds: [], asOf: '2026-10-20' })).toBeNull()
    expect(basisContext({ shipIds: ['S-001'], asOf: '' })).toBeNull()
    expect(basisContext({ shipIds: ['S-001'], asOf: '2026-10-20' })).toEqual({
      ship_ids: ['S-001'],
      as_of: '2026-10-20',
      confirm_on: null,
      horizon_days: DEFAULT_HORIZON_DAYS,
    })
  })
})
