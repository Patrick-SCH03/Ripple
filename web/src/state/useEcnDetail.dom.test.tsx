// @vitest-environment jsdom
// 상세 다시 읽기: 기록·검토 직후 다른 설계변경을 열었다가 결재 상태 목록을 다시 읽기 전에 돌아와도
// 방금 기록한 설계변경이 '기록 전'(상세 없음)으로 보이지 않는다 — 다시 읽으라고 한 설계변경을 ECN별로 기억해, 목록에
// 아직 없어도 읽는다. 목록이 따라잡거나 상세가 404(기록 없음)면 잊어 404를 되풀이하지 않는다.
import { act, useEffect } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, type EcnDetail } from '@/api/client'
import { useEcnDetail, type EcnDetailState, type Listed } from './useEcnDetail'
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const A = 'ECN-D-0119'
const B = 'ECN-D-0043'
const C = 'ECN-D-0067'

const mounted: Root[] = []
afterEach(() => {
  for (const root of mounted.splice(0)) act(() => root.unmount())
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

const detailOf = (id: string) => ({ status: { ecn_id: id, version: 1 }, audit: [] }) as unknown as EcnDetail

/** 서버: records에 있는 설계변경만 상세가 있고(없으면 404), hold에 있으면 응답을 붙잡아 둔다(직접 풀기 전까지). */
function server(records: Set<string>) {
  const held = new Map<string, () => void>()
  const hold = new Set<string>()
  const calls: string[] = []
  vi.spyOn(api, 'ecn').mockImplementation((id: string) => {
    calls.push(id)
    const answer = () =>
      records.has(id) ? Promise.resolve(detailOf(id)) : Promise.reject(new ApiError('기록이 없어요', 404))
    if (!hold.has(id)) return answer()
    return new Promise<EcnDetail>((resolve, reject) => {
      held.set(id, () => answer().then(resolve, reject))
    })
  })
  return { calls, hold, release: (id: string) => held.get(id)?.() }
}

function Probe({ ecnId, listed, onState }: { ecnId: string; listed: Listed; onState: (state: EcnDetailState) => void }) {
  const state = useEcnDetail(ecnId, listed, false, () => {}, () => {})
  useEffect(() => onState(state))
  return null
}

function mount() {
  let state: EcnDetailState | null = null
  const keep = (next: EcnDetailState) => {
    state = next
  }
  const root = createRoot(document.body.appendChild(document.createElement('div')))
  mounted.push(root)
  const show = async (ecnId: string, listed: Listed) => {
    await act(async () => root.render(<Probe ecnId={ecnId} listed={listed} onState={keep} />))
  }
  return { show, state: () => state!, reload: async () => act(async () => state!.reloadDetail()) }
}

describe('기록 직후 다른 설계변경을 열었다 돌아오기(목록을 다시 읽기 전)', () => {
  it('다시 읽기가 끝난 뒤 다른 설계변경을 열었다 돌아와도 방금 기록한 설계변경의 상세를 읽는다', async () => {
    const records = new Set([B])
    const { calls } = server(records)
    const view = mount()
    await view.show(A, 'absent')
    expect(view.state().detail).toBeNull() // 기록 전 = 읽지 않음
    expect(calls).toEqual([])
    records.add(A) // 기록 저장
    await view.reload()
    expect(view.state().detail?.status.ecn_id).toBe(A)
    await view.show(B, 'listed')
    expect(view.state().detail?.status.ecn_id).toBe(B)
    await view.show(A, 'absent') // 목록은 아직 옛것(A 없음)
    expect(view.state().detail?.status.ecn_id).toBe(A)
    expect(calls).toEqual([A, B, A])
  })

  it('다시 읽기가 끝나기 전에 다른 설계변경을 열었다 돌아와도 읽는다(늦게 온 앞 응답은 버림)', async () => {
    const records = new Set([B])
    const { calls, hold, release } = server(records)
    const view = mount()
    await view.show(A, 'absent')
    records.add(A)
    hold.add(A)
    await view.reload() // A 다시 읽는 중
    await view.show(B, 'listed')
    await act(async () => release(A)) // 앞 응답이 늦게 옴 — B 화면에 섞이지 않음
    expect(view.state().detail?.status.ecn_id).toBe(B)
    hold.delete(A)
    await view.show(A, 'absent')
    expect(view.state().detail?.status.ecn_id).toBe(A)
    expect(calls).toEqual([A, B, A])
  })

  it('목록이 따라잡으면 잊고(그 뒤 목록에 없으면 읽지 않음), 다시 읽은 상세가 404면 잊어 404를 되풀이하지 않는다', async () => {
    const records = new Set([B])
    const { calls } = server(records)
    const view = mount()
    await view.show(A, 'absent')
    records.add(A)
    await view.reload()
    await view.show(A, 'listed') // 목록이 따라잡음
    records.delete(A) // 그 뒤 기록이 사라짐(작업 공간 초기화 등)
    await view.show(B, 'listed')
    await view.show(A, 'absent')
    expect(view.state().detail).toBeNull()
    expect(calls).toEqual([A, A, B])

    await view.show(C, 'absent')
    await view.reload() // 기록 저장이 실패했어도 다시 읽기 → 404
    expect(view.state().detail).toBeNull()
    await view.show(B, 'listed')
    await view.show(C, 'absent')
    expect(view.state().detail).toBeNull()
    expect(calls).toEqual([A, A, B, C, B])
  })
})
