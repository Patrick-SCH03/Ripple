import { describe, expect, it } from 'vitest'
import type { ImpactView } from '@/api/client'
import { RELATION_NAMES } from '@/lib/labels'
import { blockStates } from './blocks'
import { ADJACENCY, jointOf } from './layout'
import { MAX_LINKS, arcControl, arrowDirection, bezierAt, focusPath, hopName, linkName, relationPlan, seamPlan } from './relations'

type Node = { id: string; type: string; attrs?: Record<string, string | number | boolean | null> }
type Hop = [string, string, string?]

function view(nodes: Node[], impacts: { entity_id: string; severity: string; path?: Hop[] }[]): ImpactView {
  return {
    analysis_id: 'A-1',
    graph: { nodes: nodes.map((n) => ({ virtual: false, attrs: {}, label: n.id, ...n })), edges: [], snapshot_id: 'G-1', truncated: false },
    impacts: impacts.map((i) => ({
      impact_type: 'rework',
      rule_id: 'R1',
      ...i,
      path: (i.path ?? []).map(([src, dst, relation]) => ({ src, dst, relation: relation ?? 'butt_weld', rule_id: 'R1' })),
    })),
  } as unknown as ImpactView
}

const plan = (report: ImpactView, max?: number) => relationPlan(report, blockStates(report).placed, max)
const part = (id: string, block: string, role?: string): Node => ({ id: `S-001:${id}`, type: 'part', attrs: { block_id: `S-001:${block}`, ...(role ? { role } : {}) } })

// ECN-D-0119 모양(실제 분석 결과): B31P 판 두 장이 L31C 판과 맞대기 용접 → L31C 재작업(높음)·테이퍼(보통)·도면(낮음)
const d0119 = view(
  [
    { id: 'S-001:B31P', type: 'block' },
    { id: 'S-001:L31C', type: 'block' },
    part('B31P-PL-005', 'B31P', 'target'),
    part('B31P-PL-007', 'B31P', 'target'),
    part('L31C-PL-007', 'L31C'),
    part('L31C-PL-005', 'L31C'),
    { id: 'DWG-L31C-H01@A', type: 'drawing' },
    { id: 'PO-0037#1', type: 'po_line' },
  ],
  [
    { entity_id: 'S-001:B31P', severity: 'high', path: [['S-001:B31P-PL-005', 'S-001:B31P', 'part_of']] },
    { entity_id: 'S-001:L31C', severity: 'high', path: [['S-001:B31P-PL-005', 'S-001:L31C-PL-007'], ['S-001:L31C-PL-007', 'S-001:L31C', 'part_of']] },
    { entity_id: 'DWG-L31C-H01@A', severity: 'low', path: [['S-001:B31P-PL-005', 'S-001:L31C-PL-007'], ['S-001:L31C-PL-007', 'DWG-L31C-H01@A', 'drawn_in']] },
    { entity_id: 'S-001:L31C-PL-005', severity: 'medium', path: [['S-001:B31P-PL-007', 'S-001:L31C-PL-005']] },
    { entity_id: 'PO-0037#1', severity: 'high', path: [['S-001:B31P-PL-005', 'PO-0037#1', 'supplied_by']] },
  ],
)

describe('블록 사이 관계(경로에 있는 연결만)', () => {
  it('0119: B31P → L31C 맞대기 용접 하나, 서로 다른 연결 2곳을 센다, 색은 도착 블록 단계', () => {
    const result = plan(d0119)
    expect(result.links).toEqual([
      { key: 'B31P>L31C', from: 'B31P', to: 'L31C', kinds: ['butt_weld'], count: 2, severity: 'high', label: '맞대기 용접 2곳' },
    ])
    expect([...result.hops].sort()).toEqual([
      ['B31P', 0],
      ['L31C', 1],
    ])
    expect(result.chains).toEqual([['B31P', 'L31C']])
  })

  it('블록 하나뿐이면(0173 모양) 화살표 없음 · 홉 0만', () => {
    const one = view(
      [{ id: 'S-001:B31S', type: 'block' }, part('B31S-PL-004', 'B31S', 'target'), part('B31S-PL-001', 'B31S')],
      [
        { entity_id: 'S-001:B31S', severity: 'high', path: [['S-001:B31S-PL-004', 'S-001:B31S', 'part_of']] },
        { entity_id: 'S-001:B31S-PL-001', severity: 'medium', path: [['S-001:B31S-PL-004', 'S-001:B31S-PL-001']] },
      ],
    )
    const result = plan(one)
    expect(result.links).toEqual([])
    expect([...result.hops]).toEqual([['B31S', 0]])
  })

  it('블록 없는 노드(도면·발주 품목)를 거쳐 다른 블록으로 가면 그 종류로 이름(같은 도면 · 같은 발주)', () => {
    const shared = view(
      [part('B31P-PL-001', 'B31P', 'target'), part('S31P-PL-001', 'S31P'), part('D31C-PL-001', 'D31C'), { id: 'DWG-1', type: 'drawing' }, { id: 'PO-1#1', type: 'po_line' }],
      [
        { entity_id: 'S-001:S31P-PL-001', severity: 'low', path: [['S-001:B31P-PL-001', 'DWG-1', 'drawn_in'], ['DWG-1', 'S-001:S31P-PL-001', 'drawn_in']] },
        { entity_id: 'S-001:D31C-PL-001', severity: 'low', path: [['S-001:B31P-PL-001', 'PO-1#1', 'supplied_by'], ['PO-1#1', 'S-001:D31C-PL-001', 'supplied_by']] },
      ],
    )
    const labels = Object.fromEntries(plan(shared).links.map((link) => [link.key, link.label]))
    expect(labels).toEqual({ 'B31P>D31C': '같은 발주', 'B31P>S31P': '같은 도면' })
  })

  it('탑재 공정끼리 선후행은 탑재 선행, 사슬을 따라 홉이 늘어난다(1차 · 2차)', () => {
    const chain = view(
      [part('B31S-PL-001', 'B31S', 'target'), { id: 'S-001:B31S:erection', type: 'activity' }, { id: 'S-001:S31S:erection', type: 'activity' }, { id: 'S-001:L31C:erection', type: 'activity' }],
      [
        {
          entity_id: 'S-001:L31C:erection',
          severity: 'high',
          path: [
            ['S-001:B31S-PL-001', 'S-001:B31S:erection', 'consumed_by'],
            ['S-001:B31S:erection', 'S-001:S31S:erection', 'precedes'],
            ['S-001:S31S:erection', 'S-001:L31C:erection', 'precedes'],
          ],
        },
      ],
    )
    const result = plan(chain)
    expect(result.links.map((link) => [link.key, link.label])).toEqual([
      ['B31S>S31S', '탑재 선행'],
      ['S31S>L31C', '탑재 선행'],
    ])
    expect(Object.fromEntries(result.hops)).toEqual({ B31S: 0, S31S: 1, L31C: 2 })
    expect([1, 2].map(hopName)).toEqual(['1차', '2차'])
    expect(hopName(0)).toBeNull()
    expect(hopName(undefined)).toBeNull()
  })

  it('곳 수는 물리적 이음(용접·배관)만: 탑재 선행·같은 도면 경유는 이름만 싣고 세지 않는다', () => {
    const mixed = view(
      [
        { id: 'S-001:B31P', type: 'block' },
        { id: 'S-001:L31C', type: 'block' },
        part('B31P-PL-005', 'B31P', 'target'),
        part('B31P-PL-007', 'B31P', 'target'),
        part('L31C-PL-007', 'L31C'),
        part('L31C-PL-005', 'L31C'),
        { id: 'S-001:B31P:erection', type: 'activity' },
        { id: 'S-001:L31C:erection', type: 'activity' },
        { id: 'DWG-1', type: 'drawing' },
      ],
      [
        {
          entity_id: 'S-001:L31C:erection',
          severity: 'high',
          path: [
            ['S-001:B31P-PL-005', 'S-001:B31P:erection', 'consumed_by'],
            ['S-001:B31P:erection', 'S-001:L31C:erection', 'precedes'],
          ],
        },
        { entity_id: 'S-001:L31C-PL-007', severity: 'high', path: [['S-001:B31P-PL-005', 'S-001:L31C-PL-007']] },
        { entity_id: 'S-001:L31C-PL-005', severity: 'high', path: [['S-001:B31P-PL-007', 'S-001:L31C-PL-005']] },
        { entity_id: 'S-001:L31C', severity: 'high', path: [['S-001:B31P-PL-007', 'DWG-1', 'drawn_in'], ['DWG-1', 'S-001:L31C-PL-005', 'drawn_in']] },
      ],
    )
    const [link] = plan(mixed).links
    expect(link.kinds).toEqual(['erection_precedes', 'butt_weld', 'via_drawing'])
    expect(link.count).toBe(2)
    expect(link.label).toBe('탑재 선행 · 맞대기 용접 2곳 · 같은 도면')
  })

  it('경로 첫 노드에 블록이 없으면(도면에서 시작) 처음 닿는 블록은 바꾸는 블록이 아닌 한 홉 1', () => {
    const fromDrawing = view(
      [part('B31P-PL-001', 'B31P', 'target'), part('S31P-PL-001', 'S31P'), part('L31C-PL-001', 'L31C'), { id: 'DWG-1', type: 'drawing' }],
      [
        { entity_id: 'S-001:L31C-PL-001', severity: 'high', path: [['DWG-1', 'S-001:S31P-PL-001', 'drawn_in'], ['S-001:S31P-PL-001', 'S-001:L31C-PL-001']] },
        { entity_id: 'S-001:B31P-PL-001', severity: 'low', path: [['DWG-1', 'S-001:B31P-PL-001', 'drawn_in'], ['S-001:B31P-PL-001', 'S-001:S31P-PL-001']] },
      ],
    )
    expect(Object.fromEntries(plan(fromDrawing).hops)).toEqual({ B31P: 0, S31P: 1, L31C: 2 })
  })

  it('주요 경로(가장 높은 심각도)의 관계만, 없으면 다음 단계에서 · 상한 개수', () => {
    const mixed = view(
      [part('B31P-PL-001', 'B31P', 'target'), part('S31P-PL-001', 'S31P'), part('L31C-PL-001', 'L31C')],
      [
        { entity_id: 'S-001:B31P-PL-001', severity: 'high' },
        { entity_id: 'S-001:S31P-PL-001', severity: 'medium', path: [['S-001:B31P-PL-001', 'S-001:S31P-PL-001']] },
        { entity_id: 'S-001:L31C-PL-001', severity: 'low', path: [['S-001:B31P-PL-001', 'S-001:L31C-PL-001', 'fillet_weld']] },
      ],
    )
    expect(plan(mixed).links.map((link) => link.key)).toEqual(['B31P>S31P'])
    expect(plan(mixed, 0).links).toEqual([])
    expect(MAX_LINKS).toBeLessThanOrEqual(8)
  })

  it('배치 표에 없는 블록으로 가는 관계는 그리지 않는다', () => {
    const away = view(
      [part('B31P-PL-001', 'B31P', 'target'), part('X99C-PL-001', 'X99C')],
      [{ entity_id: 'S-001:X99C-PL-001', severity: 'high', path: [['S-001:B31P-PL-001', 'S-001:X99C-PL-001']] }],
    )
    expect(plan(away).links).toEqual([])
  })

  it('관계 이름은 계약 관계 종류마다 있다(없는 이름은 만들지 않음)', () => {
    for (const relation of Object.keys(RELATION_NAMES)) expect(linkName(relation)).toBeTruthy()
    expect(linkName('butt_weld')).toBe('맞대기 용접')
    expect(linkName('penetration')).toBe('배관 관통')
  })
})

describe('초점 모드', () => {
  const chain = { links: [{ key: 'B31S>S31S' }, { key: 'S31S>L31C' }] as never[], chains: [['B31S', 'S31S', 'L31C']] }

  it('고른 블록까지 오는 화살표만', () => {
    expect([...focusPath(chain, 'S31S').links]).toEqual(['B31S>S31S'])
    expect([...focusPath(chain, 'L31C').links]).toEqual(['B31S>S31S', 'S31S>L31C'])
    expect([...focusPath(chain, 'L31C').blocks].sort()).toEqual(['B31S', 'L31C', 'S31S'])
  })

  it('바꾸는 블록을 고르면 나가는 1차 화살표, 사슬 밖 블록은 화살표 없음', () => {
    expect([...focusPath(chain, 'B31S').links]).toEqual(['B31S>S31S'])
    const off = focusPath(chain, 'F11C')
    expect(off.links.size).toBe(0)
    expect([...off.blocks]).toEqual(['F11C'])
  })
})

describe('용접 이음면', () => {
  it('0119: B31P ↔ L31C는 굵게(도착 블록 색), B31P와 맞닿은 나머지 이음면은 바꾸는 블록 색, 맞닿지 않는 쌍은 뺀다', () => {
    const placed = blockStates(d0119).placed
    const seams = seamPlan([{ from: 'B31P', to: 'L31C' }, { from: 'P11C', to: 'T31C' }], placed, ADJACENCY, (a, b) => jointOf(a, b) !== undefined)
    expect(seams.map((seam) => [seam.key, seam.strong, seam.severity])).toEqual([
      ['B31P|B31S', false, 'high'],
      ['B31P|L31C', true, 'high'],
      ['B31P|S31P', false, 'high'],
      ['B31P|T31C', false, 'high'],
    ])
  })
})

describe('곡선', () => {
  it('제어점은 가운데, 갑판과 두 끝보다 위', () => {
    const control = arcControl([10, 2, -12], [20, 20, 0], 23)
    expect(control[0]).toBe(15)
    expect(control[2]).toBe(-6)
    expect(control[1]).toBeGreaterThan(23)
    expect(arcControl([0, 0, 0], [1000, 0, 0], 23)[1]).toBe(53)
  })

  it('곡선 양 끝은 두 점, 화살촉은 끝으로 향하는 단위 벡터', () => {
    const from = [0, 0, 0] as const
    const to = [10, 0, 0] as const
    const control = arcControl(from, to, 5)
    expect(bezierAt(from, control, to, 0)).toEqual(from)
    expect(bezierAt(from, control, to, 1)).toEqual(to)
    expect(bezierAt(from, control, to, 0.5)[1]).toBeGreaterThan(5)
    const d = arrowDirection(control, to)
    expect(Math.hypot(...d)).toBeCloseTo(1)
    expect(d[1]).toBeLessThan(0)
  })
})
