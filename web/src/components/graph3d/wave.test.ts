import { describe, expect, it } from 'vitest'
import type { ImpactView } from '@/api/client'
import { blockStates } from './blocks'
import { ADJACENCY } from './layout'
import { FLASH_SECONDS, WAVE, busy, flashGlow, ringAt, waveGlow, wavePhase, wavePlan } from './wave'

type Node = { id: string; type: string; attrs?: Record<string, string | number | boolean | null> }
type Hop = [string, string]

function view(nodes: Node[], impacts: { entity_id: string; severity: string; path?: Hop[] }[], edges: Hop[] = []): ImpactView {
  return {
    analysis_id: 'A-1',
    graph: {
      nodes: nodes.map((n) => ({ virtual: false, attrs: {}, label: n.id, ...n })),
      edges: edges.map(([source, target]) => ({ source, target, relation: 'butt_weld', virtual: false })),
      snapshot_id: 'G-1',
      truncated: false,
    },
    impacts: impacts.map((i) => ({
      impact_type: 'rework',
      rule_id: 'R1',
      ...i,
      path: (i.path ?? []).map(([src, dst]) => ({ src, dst, relation: 'butt_weld', rule_id: 'R1' })),
    })),
  } as unknown as ImpactView
}

const plan = (report: ImpactView) => wavePlan(report, blockStates(report).placed, ADJACENCY)

// ECN-D-0119 모양: B31P 판(대상) → 맞대기 용접 → L31C 판 → L31C 재작업. B31P 공정 지연은 긴 경로 끝(단계 8)이지만 B31P 블록은 0
const d0119 = view(
  [
    { id: 'S-001:B31P', type: 'block' },
    { id: 'S-001:L31C', type: 'block' },
    { id: 'S-001:B31P-PL-005', type: 'part', attrs: { block_id: 'S-001:B31P', role: 'target' } },
    { id: 'S-001:L31C-PL-007', type: 'part', attrs: { block_id: 'S-001:L31C' } },
    { id: 'S-001:B31P:erection', type: 'activity' },
  ],
  [
    { entity_id: 'S-001:B31P', severity: 'high', path: [['S-001:B31P-PL-005', 'S-001:B31P']] },
    { entity_id: 'S-001:L31C-PL-007', severity: 'medium', path: [['S-001:B31P-PL-005', 'S-001:L31C-PL-007']] },
    { entity_id: 'S-001:L31C', severity: 'high', path: [['S-001:B31P-PL-005', 'S-001:L31C-PL-007'], ['S-001:L31C-PL-007', 'S-001:L31C']] },
    { entity_id: 'S-001:B31P:erection', severity: 'high', path: [['S-001:B31P-PL-005', 'X1'], ['X1', 'X2'], ['X2', 'S-001:B31P:erection']] },
  ],
)

describe('물결 순서', () => {
  it('결과의 근거 경로대로: 바꾸는 부재 블록이 0, 경로로 이어진 블록이 다음', () => {
    const result = plan(d0119)
    expect(result.basis).toBe('path')
    expect([...result.steps].sort()).toEqual([
      ['B31P', 0],
      ['L31C', 1],
    ])
    expect(result.origins).toEqual(['B31P'])
    expect(result.flows).toEqual([{ from: 'B31P', to: 'L31C' }])
  })

  it('블록 하나뿐이면(ECN-D-0173 B31S) 흐름 없이 그 블록만', () => {
    const one = view(
      [
        { id: 'S-001:B31S', type: 'block' },
        { id: 'S-001:B31S-PL-004', type: 'part', attrs: { block_id: 'S-001:B31S', role: 'target' } },
      ],
      [{ entity_id: 'S-001:B31S', severity: 'high', path: [['S-001:B31S-PL-004', 'S-001:B31S']] }],
    )
    const result = plan(one)
    expect([...result.steps]).toEqual([['B31S', 0]])
    expect(result.flows).toEqual([])
  })

  it('블록 홉 순서(바꾸는 블록 → 1차 → 2차): 같은 블록 안 긴 경로는 단계를 늘리지 않는다', () => {
    const chain = view(
      [
        { id: 'S-001:B31P-PL-005', type: 'part', attrs: { block_id: 'S-001:B31P', role: 'target' } },
        { id: 'S-001:B31P-PL-004', type: 'part', attrs: { block_id: 'S-001:B31P' } },
        { id: 'S-001:S31P-PL-001', type: 'part', attrs: { block_id: 'S-001:S31P' } },
        { id: 'S-001:D31C-PL-001', type: 'part', attrs: { block_id: 'S-001:D31C' } },
      ],
      [
        { entity_id: 'S-001:S31P-PL-001', severity: 'medium', path: [['S-001:B31P-PL-005', 'S-001:B31P-PL-004'], ['S-001:B31P-PL-004', 'S-001:S31P-PL-001']] },
        { entity_id: 'S-001:D31C-PL-001', severity: 'high', path: [['S-001:B31P-PL-005', 'S-001:B31P-PL-004'], ['S-001:B31P-PL-004', 'S-001:S31P-PL-001'], ['S-001:S31P-PL-001', 'S-001:D31C-PL-001']] },
      ],
    )
    expect(Object.fromEntries(plan(chain).steps)).toEqual({ B31P: 0, S31P: 1, D31C: 2 })
  })

  it('빈 단계는 당겨 붙인다(단계 값이 0·3이어도 0·1)', () => {
    const gap = view(
      [
        { id: 'S-001:B31P-PL-005', type: 'part', attrs: { block_id: 'S-001:B31P', role: 'target' } },
        { id: 'S-001:S31P-PL-001', type: 'part', attrs: { block_id: 'S-001:S31P' } },
      ],
      [
        { entity_id: 'S-001:B31P-PL-005', severity: 'low' },
        { entity_id: 'S-001:S31P-PL-001', severity: 'low', path: [['S-001:B31P-PL-005', 'a'], ['a', 'b'], ['b', 'S-001:S31P-PL-001']] },
      ],
    )
    expect([...plan(gap).steps].sort()).toEqual([
      ['B31P', 0],
      ['S31P', 1],
    ])
  })

  it('경로가 없으면 보수적 규칙: 바꾸는 부재 블록 → 이음 이웃 → 이음으로 닿지 않는 나머지', () => {
    const noPath = view(
      [
        { id: 'S-001:B31P-PL-005', type: 'part', attrs: { block_id: 'S-001:B31P', role: 'target' } },
        { id: 'S-001:L31C', type: 'block' },
        { id: 'S-001:D31C', type: 'block' },
        { id: 'S-001:F11C', type: 'block' },
      ],
      [
        { entity_id: 'S-001:L31C', severity: 'high' },
        { entity_id: 'S-001:D31C', severity: 'low' },
        { entity_id: 'S-001:F11C', severity: 'low' },
      ],
    )
    const result = plan(noPath)
    expect(result.basis).toBe('adjacency')
    // B31P(대상) 0 → L31C(이음 1) → D31C(이음 2) → F11C(선수, 이음으로 닿지 않음) 맨 끝
    expect([...result.steps].sort()).toEqual([
      ['B31P', 0],
      ['D31C', 2],
      ['F11C', 3],
      ['L31C', 1],
    ])
    expect(result.flows).toEqual([
      { from: 'B31P', to: 'L31C' },
      { from: 'L31C', to: 'D31C' },
    ])
  })

  it('경로도 바꾸는 부재 블록도 없으면 모든 영향 블록이 함께 한 번(순서를 말하지 않음)', () => {
    const none = view(
      [
        { id: 'S-001:B31P', type: 'block' },
        { id: 'S-001:F11C', type: 'block' },
      ],
      [
        { entity_id: 'S-001:B31P', severity: 'high' },
        { entity_id: 'S-001:F11C', severity: 'low' },
      ],
    )
    const result = plan(none)
    expect(result.basis).toBe('none')
    expect([...result.steps.values()]).toEqual([0, 0])
    expect(result.flows).toEqual([])
  })

  it('영향이 없으면 물결 없음', () => {
    const result = plan(view([], []))
    expect(result.steps.size).toBe(0)
    expect(result.duration).toBe(0)
  })

  it('한 바퀴 시간 = 마지막 단계 시작 + 밝아짐 + 어두워짐, 다음 물결까지 쉼', () => {
    const result = plan(d0119)
    expect(result.duration).toBeCloseTo(Math.max(WAVE.step + WAVE.rise + WAVE.fade, WAVE.ring))
    expect(result.period).toBeCloseTo(result.duration + WAVE.rest)
  })
})

describe('물결 밝기', () => {
  it('차례 전에는 0, 밝아졌다가 끝나면 0으로 돌아온다', () => {
    expect(waveGlow(1, 0.2)).toBe(0)
    expect(waveGlow(0, WAVE.rise)).toBeCloseTo(1)
    expect(waveGlow(0, WAVE.rise + WAVE.fade + 0.01)).toBe(0)
    for (let t = 0; t <= 4; t += 0.05) {
      const value = waveGlow(0, t)
      expect(value).toBeGreaterThanOrEqual(0)
      expect(value).toBeLessThanOrEqual(1)
    }
  })

  it('뒤 단계일수록 늦게 가장 밝다', () => {
    const peak = (step: number) => {
      let best = 0
      let at = 0
      for (let t = 0; t <= 5; t += 0.01) {
        const value = waveGlow(step, t)
        if (value > best) [best, at] = [value, t]
      }
      return at
    }
    expect(peak(1)).toBeGreaterThan(peak(0))
    expect(peak(2) - peak(1)).toBeCloseTo(WAVE.step, 1)
  })

  it('반복 주기 안의 시간, 시작 전은 음수 그대로', () => {
    expect(wavePhase(-0.5, 8)).toBe(-0.5)
    expect(wavePhase(9, 8)).toBeCloseTo(1)
  })

  it('고리는 퍼지면서 옅어지고 끝나면 없음', () => {
    expect(ringAt(-0.1)).toBeNull()
    expect(ringAt(WAVE.ring + 0.01)).toBeNull()
    const early = ringAt(WAVE.ring * 0.3)
    const late = ringAt(WAVE.ring * 0.9)
    expect(early && late && late.scale > early.scale).toBe(true)
    expect(early && late && late.opacity < early.opacity).toBe(true)
  })

  it('물결 한 바퀴·강조 맥동 중에만 바쁨(쉬는 동안은 잠)', () => {
    const result = plan(d0119)
    const clock = { waveStart: 10, flashStart: -Infinity }
    expect(busy(clock, result, 9)).toBe(false)
    expect(busy(clock, result, 10 + result.duration / 2)).toBe(true)
    expect(busy(clock, result, 10 + result.duration + 1)).toBe(false)
    expect(busy(clock, result, 10 + result.period + 0.1)).toBe(true)
    expect(busy({ waveStart: 10, flashStart: 30 }, result, 30 + FLASH_SECONDS / 2)).toBe(true)
    expect(busy({ waveStart: 10, flashStart: 30 }, plan(view([], [])), 30 + FLASH_SECONDS + 0.1)).toBe(false)
  })

  it('강조 맥동은 한 번 밝아졌다 0으로', () => {
    expect(flashGlow(0)).toBeCloseTo(0)
    expect(flashGlow(FLASH_SECONDS / 2)).toBeCloseTo(1)
    expect(flashGlow(FLASH_SECONDS)).toBeCloseTo(0)
    expect(flashGlow(FLASH_SECONDS + 0.1)).toBe(0)
  })
})
