// 상세를 읽을지: 기록 목록에 없는 설계변경은 GET /api/ecns/{id}를 부르지 않는다(기록 없음 = 404가 뻔해
// 브라우저 콘솔에 빨간 줄만 남는다). 목록을 아직 못 읽었으면 기다리고, 목록을 못 읽으면 읽어 본다.
import { describe, expect, it } from 'vitest'
import type { EcnListItem } from '@/api/client'
import { detailPlan, listedOf } from './useEcnDetail'

const item = (ecnId: string) => ({ status: { ecn_id: ecnId } }) as unknown as EcnListItem
const items = [item('ECN-D-0067'), item('ECN-D-0007')]

describe('listedOf — 목록으로 본 기록 여부', () => {
  it('읽기 전 = pending, 목록에 있음 = listed, 없음 = absent, 목록 읽기 실패 = unknown', () => {
    expect(listedOf('ECN-D-0067', [], false, null)).toBe('pending')
    expect(listedOf('ECN-D-0067', items, true, null)).toBe('listed')
    expect(listedOf('ECN-D-0119', items, true, null)).toBe('absent')
    expect(listedOf('ECN-AI-a9167b-1', items, true, null)).toBe('absent')
    expect(listedOf('ECN-D-0119', items, true, 1)).toBe('unknown')
    expect(listedOf(null, items, true, null)).toBe('absent')
  })
})

describe('detailPlan — 상세를 읽을까', () => {
  it('목록에 없는 설계변경을 처음 열면 읽지 않음(404 없음), 목록에 있거나 모르면 읽음, 목록 전이면 기다림', () => {
    expect(detailPlan('absent', false)).toBe('skip')
    expect(detailPlan('listed', false)).toBe('fetch')
    expect(detailPlan('unknown', false)).toBe('fetch')
    expect(detailPlan('pending', false)).toBe('wait')
  })

  it('같은 설계변경을 다시 읽으라고 했으면(기록·행동 직후 — 목록이 아직 옛것) 목록에 없어도 읽음', () => {
    expect(detailPlan('absent', true)).toBe('fetch')
    expect(detailPlan('pending', true)).toBe('wait')
  })
})
