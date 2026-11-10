import { describe, expect, it } from 'vitest'
import { LatestGate } from './latest'

describe('LatestGate', () => {
  it('새 요청을 시작하면 이전 요청은 최신이 아니고 중단됨', () => {
    const gate = new LatestGate()
    const first = gate.begin()
    const second = gate.begin()
    expect(gate.isLatest(first)).toBe(false)
    expect(first.signal.aborted).toBe(true)
    expect(gate.isLatest(second)).toBe(true)
    expect(second.signal.aborted).toBe(false)
  })

  it('늦게 끝난 이전 응답은 결과를 덮어쓰지 않음(응답 순서 역전)', async () => {
    const gate = new LatestGate()
    let shown = ''
    const run = async (label: string, delay: number) => {
      const ticket = gate.begin()
      await new Promise((resolve) => setTimeout(resolve, delay))
      if (gate.isLatest(ticket)) shown = label
    }
    await Promise.all([run('A', 30), run('B', 5)])
    expect(shown).toBe('B')
  })
})
