import { describe, expect, it } from 'vitest'
import type { ImpactView } from '@/api/client'
import { blockIdOf, blockStates, initialView, neighboursOf, portSide } from './blocks'
import { BLOCK_MARGIN, MAX_DISTANCE_FACTOR, MIN_DISTANCE, blockView, directionOf, fitView, zoomLimits } from './camera'
import { selectedBlock } from './focus'
import { ADJACENCY, BLOCK_LAYOUT, VIEWS } from './layout'

type Node = { id: string; type: string; label: string; attrs?: Record<string, string | number | boolean | null>; virtual?: boolean }

function report(nodes: Node[], impacts: { entity_id: string; severity: string; impact_type?: string }[]): ImpactView {
  return {
    analysis_id: 'A-1',
    graph: { nodes: nodes.map((n) => ({ virtual: false, attrs: {}, ...n })), edges: [], snapshot_id: 'G-1', truncated: false },
    impacts: impacts.map((i) => ({ impact_type: 'rework', path: [], ...i })),
  } as unknown as ImpactView
}

// ECN-D-0119(B31P 판 두께 변경)와 같은 모양 + 공정·구역 출구·배치 표 밖 블록
const sample = report(
  [
    { id: 'S-001:B31P', type: 'block', label: 'B31P No.3 COT 이중저 좌' },
    { id: 'S-001:B31P-PL-002', type: 'part', label: '판 2', attrs: { block_id: 'S-001:B31P', role: 'target' } },
    { id: 'S-001:B31P-PL-001', type: 'part', label: '판 1', attrs: { block_id: 'S-001:B31P' } },
    { id: 'S-001:L31C-PL-005', type: 'part', label: '종격벽 판 5', attrs: { block_id: 'S-001:L31C' } },
    { id: 'S-001:L31C-PL-007', type: 'part', label: '종격벽 판 7', attrs: { block_id: 'S-001:L31C' } },
    { id: 'PO-0037#1', type: 'po_line', label: 'PO-0037 #1' },
    { id: 'DWG-B31P-H01@A', type: 'drawing', label: 'DWG-B31P-H01 개정 A' },
    { id: 'S-001:T31C:erection', type: 'activity', label: 'T31C 탑재' },
    { id: 'S-001:ZCT:exit', type: 'activity', label: 'ZCT 구역 출구' },
    { id: 'S-001:X99P', type: 'block', label: 'X99P 사용자 블록' },
    { id: 'S-002:B31P-PL-001', type: 'part', label: '다른 호선 판', attrs: { block_id: 'S-002:B31P' } },
  ],
  [
    { entity_id: 'S-001:B31P', severity: 'high' },
    { entity_id: 'S-001:B31P-PL-001', severity: 'medium', impact_type: 'taper' },
    { entity_id: 'S-001:L31C-PL-005', severity: 'low', impact_type: 'weld_recheck' },
    { entity_id: 'S-001:L31C-PL-007', severity: 'medium', impact_type: 'taper' },
    { entity_id: 'PO-0037#1', severity: 'high', impact_type: 'po_change' },
    { entity_id: 'S-001:T31C:erection', severity: 'medium', impact_type: 'schedule_delay' },
    { entity_id: 'S-001:ZCT:exit', severity: 'high', impact_type: 'schedule_delay' },
    { entity_id: 'S-001:X99P', severity: 'low' },
  ],
)

describe('노드 → 블록', () => {
  const blocks = new Set(['S-001:B31P'])
  it('블록 노드 · block_id 속성 · 블록 공정만 블록에 속한다', () => {
    const byId = new Map(sample.graph.nodes.map((n) => [n.id, n]))
    const of = (id: string) => blockIdOf(byId.get(id) as ImpactView['graph']['nodes'][number], blocks)
    expect(of('S-001:B31P')).toBe('S-001:B31P')
    expect(of('S-001:B31P-PL-002')).toBe('S-001:B31P')
    expect(of('S-001:T31C:erection')).toBe('S-001:T31C')
    expect(of('S-001:ZCT:exit')).toBeNull()
    expect(of('PO-0037#1')).toBeNull()
    expect(of('DWG-B31P-H01@A')).toBeNull()
  })
})

describe('블록별 가장 강한 영향 단계', () => {
  const { placed, unplaced } = blockStates(sample)

  it('배치 표의 14개 블록이 모두 있다(영향 없는 블록은 단계 없음)', () => {
    expect([...placed.keys()].sort()).toEqual(BLOCK_LAYOUT.map((b) => b.code).sort())
    expect(placed.get('S31P')).toMatchObject({ severity: null, impacts: 0, pick: null, target: false })
  })

  it('블록 노드와 구성 부재의 영향 중 가장 높은 심각도, 영향 수, 바꾸는 부재 표시', () => {
    expect(placed.get('B31P')).toMatchObject({ severity: 'high', impacts: 2, target: true, pick: 'S-001:B31P' })
    expect(placed.get('B31P')?.members).toEqual(['S-001:B31P', 'S-001:B31P-PL-002', 'S-001:B31P-PL-001'])
    expect(placed.get('L31C')).toMatchObject({ severity: 'medium', impacts: 2, target: false })
    expect(placed.get('T31C')).toMatchObject({ severity: 'medium', impacts: 1 })
  })

  it('블록 노드가 없으면 가장 심각한 구성원을 고른다', () => {
    expect(placed.get('L31C')?.pick).toBe('S-001:L31C-PL-007')
    expect(placed.get('T31C')?.pick).toBe('S-001:T31C:erection')
  })

  it('배치 표에 없는 블록(다른 블록 코드·다른 호선)은 따로 거른다', () => {
    expect(unplaced.map((s) => s.blockId)).toEqual(['S-001:X99P', 'S-002:B31P'])
    expect(unplaced[0]).toMatchObject({ code: 'X99P', severity: 'low', pick: 'S-001:X99P' })
    expect(unplaced[1]).toMatchObject({ code: 'B31P', severity: null, pick: 'S-002:B31P-PL-001' })
  })

  it('고른 엔터티의 블록: 블록·부재·공정이면 그 블록, 그 밖·배치 밖이면 없음', () => {
    expect(selectedBlock(sample, 'S-001:B31P-PL-001')).toBe('B31P')
    expect(selectedBlock(sample, 'S-001:B31P')).toBe('B31P')
    expect(selectedBlock(sample, 'S-001:T31C:erection')).toBe('T31C')
    expect(selectedBlock(sample, 'PO-0037#1')).toBeNull()
    expect(selectedBlock(sample, 'S-001:X99P')).toBeNull()
    expect(selectedBlock(sample, null)).toBeNull()
  })

  it('처음 시점: 가장 심각한 블록이 화물창에만 있으면 화물창, 영향이 없으면 전체', () => {
    expect(initialView(placed)).toBe('cargo')
    expect(initialView(blockStates(report([], [])).placed)).toBe('whole')
  })

  it('좌현 영향이 크면 좌현 쪽에서 본다(같거나 없으면 우현)', () => {
    expect(portSide(placed)).toBe(true)
    expect(portSide(blockStates(report([], [])).placed)).toBe(false)
    const starboard = report([{ id: 'S-001:S31S', type: 'block', label: 'S31S' }], [{ entity_id: 'S-001:S31S', severity: 'low' }])
    expect(portSide(blockStates(starboard).placed)).toBe(false)
  })

  it('이웃 블록은 이음 표에서', () => {
    expect(neighboursOf('B31P', ADJACENCY)).toEqual(['B31S', 'L31C', 'S31P', 'T31C'])
    expect(neighboursOf('F31C', ADJACENCY)).toEqual(['F21C'])
  })
})

describe('목록에서 고른 블록으로 이동', () => {
  const bounds: [[number, number, number], [number, number, number]] = [
    [144, 0, -30],
    [176, 2.5, 0],
  ]
  it('좌현 블록은 좌현(−z)에서, 우현 블록은 우현(+z)에서, 가운데 블록은 보던 쪽에서', () => {
    const side = (code: string, mirror: boolean) => {
      const view = blockView(code, bounds, mirror)
      return view ? Math.sign(directionOf(view.azimuth, view.polar)[2]) : 0
    }
    expect(side('B31P', false)).toBe(-1)
    expect(side('B31S', true)).toBe(1)
    expect(side('L31C', true)).toBe(-1)
    expect(side('L31C', false)).toBe(1)
  })

  it('구역 시점의 높이각, 상자는 블록 + 여유, 배치 표 밖이면 없음', () => {
    const view = blockView('B31P', bounds, false)
    expect(view?.polar).toBe(VIEWS.find((v) => v.name === 'cargo')?.polar)
    expect(view?.box[0][0]).toBe(144 - BLOCK_MARGIN)
    expect(view?.box[1][2]).toBe(BLOCK_MARGIN)
    expect(blockView('X99P', bounds, false)).toBeNull()
  })
})

describe('시점 맞춤', () => {
  it('방향: 방위 0·극각 90°는 우현(+z), 극각 0은 바로 위', () => {
    const side = directionOf(0, Math.PI / 2)
    expect(side[2]).toBeCloseTo(1)
    expect(directionOf(0, 0)[1]).toBeCloseTo(1)
  })

  it('상자의 꼭짓점이 모두 시야 안에 들고, 한쪽은 가장자리에 닿는다', () => {
    for (const view of VIEWS) {
      for (const aspect of [0.6, 1.6, 2.4]) {
        const fov = 30
        const { position, target } = fitView(view, fov, aspect, 1)
        const f = [target[0] - position[0], target[1] - position[1], target[2] - position[2]]
        const n = Math.hypot(...f)
        const forward = f.map((v) => v / n)
        const right = [-forward[2], 0, forward[0]].map((v) => v / Math.hypot(forward[0], forward[2]))
        const up = [right[1] * forward[2] - right[2] * forward[1], right[2] * forward[0] - right[0] * forward[2], right[0] * forward[1] - right[1] * forward[0]]
        const tanV = Math.tan((fov * Math.PI) / 360)
        let tightest = 0
        for (const x of [view.box[0][0], view.box[1][0]])
          for (const y of [view.box[0][1], view.box[1][1]])
            for (const z of [view.box[0][2], view.box[1][2]]) {
              const d = [x - position[0], y - position[1], z - position[2]]
              const depth = d[0] * forward[0] + d[1] * forward[1] + d[2] * forward[2]
              const sx = Math.abs(d[0] * right[0] + d[2] * right[2]) / (depth * tanV * aspect)
              const sy = Math.abs(d[0] * up[0] + d[1] * up[1] + d[2] * up[2]) / (depth * tanV)
              expect(depth).toBeGreaterThan(0)
              expect(Math.max(sx, sy)).toBeLessThanOrEqual(1 + 1e-6)
              tightest = Math.max(tightest, sx, sy)
            }
        expect(tightest).toBeGreaterThan(0.99)
      }
    }
  })
})

describe('3D 휠 확대 거리 범위', () => {
  const distanceOf = (aspect: number) => {
    const whole = VIEWS.find((view) => view.name === 'whole')!
    const { position, target } = fitView(whole, 30, aspect)
    return Math.hypot(position[0] - target[0], position[1] - target[1], position[2] - target[2])
  }
  it('상한은 전체 시점 맞춤 거리보다 멀고(배가 남음), 하한은 블록 하나 정도', () => {
    for (const aspect of [0.46, 1, 1.6, 2.4]) {
      const limits = zoomLimits(30, aspect)
      expect(limits.min).toBe(MIN_DISTANCE)
      // 처음 시점(전체)이 범위 안 — 시점 초기화로 늘 돌아갈 수 있음
      expect(limits.max).toBeGreaterThanOrEqual(distanceOf(aspect))
      expect(limits.max).toBeLessThanOrEqual(Math.ceil(distanceOf(aspect) * MAX_DISTANCE_FACTOR))
    }
  })
  it('세로로 긴 화면일수록 상한이 멀다(전체 시점이 멀어지므로)', () => {
    expect(zoomLimits(30, 0.5).max).toBeGreaterThan(zoomLimits(30, 2).max)
  })
})