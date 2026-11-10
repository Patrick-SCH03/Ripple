import { describe, expect, it } from 'vitest'
import type { SnapshotInfo, SnapshotList } from '@/api/client'
import {
  NOTHING_APPLIED,
  activeInfo,
  applyList,
  changeNotice,
  freshnessLines,
  importedWhen,
  mapDetail,
  samplesMap,
} from './workspace'

const info = (id: string, extra: Partial<SnapshotInfo> = {}): SnapshotInfo => ({
  snapshot_id: id,
  name: id === 'G-0000000000000001' ? '기본 합성 지도' : 'plant.xlsx',
  origin: id === 'G-0000000000000001' ? 'generator' : 'excel_import',
  data_mode: id === 'G-0000000000000001' ? 'synthetic' : 'real',
  default: id === 'G-0000000000000001',
  counts: { ships: 1, blocks: 14, parts: 1234, purchase_orders: 100, activities: 120 },
  ship_ids: ['S-001'],
  ...extra,
})

const DEFAULT = 'G-0000000000000001'
const IMPORTED = 'G-0000000000000002'

const list = (active: string, instance: string, generation: number, extra: Partial<SnapshotList> = {}): SnapshotList => ({
  active_snapshot_id: active,
  workspace: `${active}.${instance}.${generation}`,
  instance,
  generation,
  data_mode: active === DEFAULT ? 'synthetic' : 'real',
  llm_external: false,
  today: '2026-10-20',
  items: [info(DEFAULT), info(IMPORTED, { imported_at: '2026-10-08T06:30:00Z' })],
  ...extra,
})

describe('applyList — 늦게 온 목록이 방금 바꾼 작업 공간을 되돌리지 않음', () => {
  it('처음 목록은 적용', () => {
    const next = list(DEFAULT, 'a', 1)
    expect(applyList(NOTHING_APPLIED, next)?.list).toBe(next)
  })

  it('같은 서버 인스턴스에서 세대가 낮은 목록(늦은 응답)은 버리고, 같거나 높으면 적용', () => {
    const state = applyList(NOTHING_APPLIED, list(IMPORTED, 'a', 3))!
    expect(applyList(state, list(DEFAULT, 'a', 2))).toBeNull()
    expect(applyList(state, list(IMPORTED, 'a', 3))?.list?.generation).toBe(3)
    expect(applyList(state, list(DEFAULT, 'a', 4))?.list?.active_snapshot_id).toBe(DEFAULT)
  })

  it('서버가 다시 켜지면(새 인스턴스) 세대가 낮아도 적용하고, 그 뒤 옛 인스턴스의 목록은 받지 않음', () => {
    const before = applyList(NOTHING_APPLIED, list(IMPORTED, 'a', 5))!
    const restarted = applyList(before, list(IMPORTED, 'b', 1))!
    expect(restarted.list?.instance).toBe('b')
    expect(applyList(restarted, list(DEFAULT, 'a', 6))).toBeNull()
    expect(applyList(restarted, list(DEFAULT, 'b', 2))?.list?.active_snapshot_id).toBe(DEFAULT)
  })
})

describe('changeNotice — 작업 공간이 바뀐 까닭 한 줄', () => {
  it('처음 열면 알림 없음, 시작 때 복구 실패가 있으면 그 사유를 경고로', () => {
    expect(changeNotice(null, list(DEFAULT, 'a', 1), 'sync')).toBeNull()
    const failed = list(DEFAULT, 'a', 1, { restore_problem: '최근 사용 지도를 열지 못해 기본 지도로 시작했어요(…)' })
    expect(changeNotice(null, failed, 'sync')).toEqual({ tone: 'warning', text: failed.restore_problem })
  })

  it('같은 토큰이면 없음, 내가 바꾸면 안내, 모르는 사이 바뀌면 경고', () => {
    const before = list(DEFAULT, 'a', 1)
    expect(changeNotice(before, list(DEFAULT, 'a', 1), 'sync')).toBeNull()
    expect(changeNotice(before, list(IMPORTED, 'a', 2), 'switch')).toEqual({
      tone: 'info',
      text: '지도 전환: plant.xlsx',
    })
    const elsewhere = changeNotice(before, list(DEFAULT, 'b', 1), 'sync')
    expect(elsewhere?.tone).toBe('warning')
    expect(elsewhere?.text).toContain('기본 합성 지도')
  })

  it('상태 갱신으로 이어진 지도는 "바꿨어요" 대신 "반영했어요", 기본 지도에서 이어지면 샘플 목록 지도', () => {
    const UPDATED = 'G-0000000000000003'
    const stamp = {
      base_snapshot_id: DEFAULT,
      lineage_root: DEFAULT,
      event_id: 'e1',
      at: '2026-10-11T07:21:41Z',
      by: '김담당',
      origin: 'confirm' as const,
      status_changed: 1,
      plan_changed: 1,
      activities: 0,
      confirmed_only: 0,
    }
    const updated = list(UPDATED, 'a', 2, {
      items: [info(DEFAULT), info(UPDATED, { name: '기본 합성 지도 · 상태 갱신', data_mode: 'synthetic', origin: 'generator', update: stamp })],
    })
    expect(changeNotice(list(DEFAULT, 'a', 1), updated, 'switch')).toEqual({
      tone: 'info',
      text: '상태 반영(바뀐 것 2건) · 같은 조건으로 다시 계산',
    })
    expect(samplesMap(updated, activeInfo(updated))).toBe(true)
    expect(samplesMap(list(IMPORTED, 'a', 1), activeInfo(list(IMPORTED, 'a', 1)))).toBe(false)
  })
})

describe('지도 설명', () => {
  it('활성 지도 정보는 목록에서 ID로 찾음', () => {
    expect(activeInfo(list(IMPORTED, 'a', 2))?.name).toBe('plant.xlsx')
    expect(activeInfo(null)).toBeNull()
  })

  it('기본 지도는 데이터 종류·기본·규모, 가져온 지도는 가져온 때까지', () => {
    const now = new Date(2026, 9, 8, 18, 0)
    expect(mapDetail(info(DEFAULT), now)).toBe('합성 데이터 · 기본 · 블록 14 · 부재 1,234 · 발주 100')
    const at = new Date(2026, 9, 8, 15, 30)
    const imported = info(IMPORTED, { imported_at: at.toISOString() })
    expect(mapDetail(imported, now)).toBe('실제 데이터 · 오늘 15:30 가져옴 · 블록 14 · 부재 1,234 · 발주 100')
    expect(importedWhen(at.toISOString(), new Date(2026, 9, 9, 9, 0))).toBe('10월 8일 15:30')
  })
})

describe('freshnessLines — 자료 날짜', () => {
  it('최신 날짜와 7일 이상 미확인 발주, 없으면 기록 없음', () => {
    expect(
      freshnessLines({ today: '2026-10-20', po_latest: '2026-10-20', open_orders: 45, stale_orders: 12, activity_latest: null }),
    ).toEqual({
      lines: ['발주 상태 최신 10월 20일(화) · 입고 전 45건 중 7일 이상 미확인 발주 12건', '공정 실적 최신 기록 없음'],
      stale: true,
    })
    expect(freshnessLines({ today: '2026-10-20', open_orders: 0, stale_orders: 0 }).stale).toBe(false)
  })
})
