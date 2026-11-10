import { describe, expect, it, vi } from 'vitest'
import { LG_QUERY, mediaStore } from './media'

/** 손으로 바꾸는 미디어 쿼리 목록(쿼리마다 하나, 바뀌면 change 알림). */
function fakeMedia(initial: Record<string, boolean>) {
  const state = { ...initial }
  const listeners = new Map<string, Set<() => void>>()
  const match = (query: string) => ({
    get matches() {
      return state[query] ?? false
    },
    addEventListener: (_: string, fn: () => void) => void (listeners.get(query) ?? listeners.set(query, new Set()).get(query)!).add(fn),
    removeEventListener: (_: string, fn: () => void) => void listeners.get(query)?.delete(fn),
  })
  const set = (query: string, value: boolean) => {
    state[query] = value
    for (const fn of listeners.get(query) ?? []) fn()
  }
  const count = (query: string) => listeners.get(query)?.size ?? 0
  return { match: match as unknown as Parameters<typeof mediaStore>[1], set, count }
}

describe('mediaStore', () => {
  it('값은 창 폭 숫자가 아니라 쿼리 결과(matches) — CSS와 같은 출처', () => {
    const media = fakeMedia({ [LG_QUERY]: false })
    const store = mediaStore(LG_QUERY, media.match)
    // innerWidth가 1024로 반올림돼도(브라우저 확대 110%, 실제 1023.6px) CSS lg가 아니면 lg가 아니다
    expect(store.getSnapshot()).toBe(false)
    media.set(LG_QUERY, true)
    expect(store.getSnapshot()).toBe(true)
  })

  it('쿼리 결과가 바뀌면 알리고, 그때 값도 새 결과', () => {
    const media = fakeMedia({ [LG_QUERY]: true })
    const store = mediaStore(LG_QUERY, media.match)
    const seen: boolean[] = []
    const unsubscribe = store.subscribe(() => seen.push(store.getSnapshot()))
    media.set(LG_QUERY, false)
    media.set(LG_QUERY, true)
    expect(seen).toEqual([false, true])
    unsubscribe()
    expect(media.count(LG_QUERY)).toBe(0)
    media.set(LG_QUERY, false)
    expect(seen).toEqual([false, true])
  })

  it('다른 쿼리의 바뀜에는 반응하지 않음', () => {
    const media = fakeMedia({ [LG_QUERY]: false, '(min-width: 48rem)': false })
    const onChange = vi.fn()
    mediaStore(LG_QUERY, media.match).subscribe(onChange)
    media.set('(min-width: 48rem)', true)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('matchMedia가 없으면 늘 거짓, 구독·해지도 오류 없음', () => {
    const store = mediaStore(LG_QUERY, () => null)
    expect(store.getSnapshot()).toBe(false)
    expect(() => store.subscribe(() => undefined)()).not.toThrow()
  })
})
