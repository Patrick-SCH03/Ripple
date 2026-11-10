import { describe, expect, it } from 'vitest'
import { RELOAD_GAP_MS, shouldReload } from './staleChunks'

describe('shouldReload', () => {
  it('처음이면 새로 고친다', () => {
    expect(shouldReload(null, 1_000)).toBe(true)
  })
  it('방금 새로 고쳤으면 되풀이하지 않는다', () => {
    expect(shouldReload(1_000, 1_000 + RELOAD_GAP_MS)).toBe(false)
  })
  it('한참 지났거나 기록이 망가졌으면 다시 새로 고친다', () => {
    expect(shouldReload(1_000, 2_000 + RELOAD_GAP_MS)).toBe(true)
    expect(shouldReload(Number.NaN, 1_000)).toBe(true)
    expect(shouldReload(5_000, 1_000)).toBe(true) // 시계가 뒤로 감
  })
})
