import { describe, expect, it } from 'vitest'
import type { Hop, Impact, ImpactReport } from '@/api/client'
import { impactsByEntity, layersOf, outlineOf, summarize, topSeverity } from './ripple'

const hop = (src: string, dst: string, relation: Hop['relation'], rule_id: string): Hop => ({ src, dst, relation, rule_id })

function impact(entity_id: string, impact_type: Impact['impact_type'], severity: Impact['severity'], path: Impact['path'], rule_id: string): Impact {
  return { entity_type: 'part', entity_id, ship_id: 'S-001', impact_type, severity, rule_id, path, note: '' } as Impact
}

// 대상 판 P1 → 이웃 판 P2(테이퍼) → 블록 B2(재작업, 두 단계), P1 → 품목 L1, 고립된 노드 X, 새 연결로만 닿는 E
const report = {
  impacts: [
    impact('B2', 'rework', 'high', [hop('P1', 'P2', 'butt_weld', 'R-T02'), hop('P2', 'B2', 'part_of', 'R-B01')], 'R-B01'),
    impact('L1', 'po_change', 'high', [hop('P1', 'L1', 'supplied_by', 'R-T01')], 'R-T01'),
    impact('L1', 'reorder', 'high', [hop('P1', 'L1', 'supplied_by', 'R-T01')], 'R-T01'),
    impact('P2', 'taper', 'medium', [hop('P1', 'P2', 'butt_weld', 'R-T02')], 'R-T02'),
  ],
  graph: {
    snapshot_id: 'G-1',
    truncated: false,
    nodes: [
      { id: 'P1', type: 'part', label: '판 1', attrs: { role: 'target' }, virtual: false },
      { id: 'P2', type: 'part', label: '판 2', attrs: {}, virtual: false },
      { id: 'B2', type: 'block', label: '블록 2', attrs: {}, virtual: false },
      { id: 'L1', type: 'po_line', label: '품목 1', attrs: {}, virtual: false },
      { id: 'E', type: 'part', label: '끝점', attrs: {}, virtual: false },
      { id: 'X', type: 'part', label: '고립', attrs: {}, virtual: false },
    ],
    edges: [
      { source: 'P1', target: 'P2', relation: 'butt_weld', virtual: false },
      { source: 'P2', target: 'B2', relation: 'part_of', virtual: false },
      { source: 'P1', target: 'L1', relation: 'supplied_by', virtual: false },
      { source: 'L1', target: 'E', relation: 'same_spec', virtual: true },
    ],
  },
} as unknown as ImpactReport

describe('layersOf', () => {
  const layers = layersOf(report)

  it('대상은 0, 경로 단계마다 하나씩 멀어짐', () => {
    expect(layers.get('P1')).toBe(0)
    expect(layers.get('P2')).toBe(1)
    expect(layers.get('L1')).toBe(1)
    expect(layers.get('B2')).toBe(2)
  })

  it('경로에 없지만 연결된 노드는 이웃 + 1, 고립 노드는 마지막 다음', () => {
    expect(layers.get('E')).toBe(2)
    expect(layers.get('X')).toBe(3)
  })

  it('모든 근거 경로에서 도착 노드는 출발 노드보다 멀지 않게 한 단계 이내', () => {
    for (const item of report.impacts) {
      item.path.forEach((h, i) => expect(layers.get(h.dst)).toBeLessThanOrEqual(i + 1))
    }
  })
})

describe('영향 묶기·요약', () => {
  it('엔터티별로 묶고 가장 높은 심각도를 고름', () => {
    const grouped = impactsByEntity(report)
    expect(grouped.get('L1')?.map((i) => i.impact_type)).toEqual(['po_change', 'reorder'])
    expect(topSeverity(grouped.get('P2'))).toBe('medium')
    expect(topSeverity(undefined)).toBeUndefined()
  })

  it('요약은 영향·엔터티·높은 심각도·재작업 블록·발주 변경 품목을 셈', () => {
    const summary = summarize(report)
    expect(summary).toMatchObject({ total: 4, entities: 3, high: 3, reworkBlocks: ['B2'], orderLines: ['L1'] })
    expect(summary.byType.reduce((sum, [, n]) => sum + n, 0)).toBe(4)
  })
})

describe('outlineOf', () => {
  const rows = outlineOf(report)
  const parentOf = (index: number) => {
    for (let i = index - 1; i >= 0; i -= 1) if (rows[i].depth === rows[index].depth - 1) return rows[i].id
    return undefined
  }

  it('그래프의 노드가 한 번씩 나옴', () => {
    expect(rows.map((r) => r.id).sort()).toEqual(report.graph.nodes.map((n) => n.id).sort())
  })

  it('변경 지점이 뿌리, 형제는 심각도 높은 순, 새 연결로만 닿는 노드는 그 연결 아래', () => {
    expect(rows).toEqual([
      { id: 'P1', depth: 0, relation: null, virtual: false },
      { id: 'L1', depth: 1, relation: 'supplied_by', virtual: false },
      { id: 'E', depth: 2, relation: 'same_spec', virtual: true },
      { id: 'P2', depth: 1, relation: 'butt_weld', virtual: false },
      { id: 'B2', depth: 2, relation: 'part_of', virtual: false },
      { id: 'X', depth: 0, relation: null, virtual: false },
    ])
  })

  it('깊이는 한 칸씩만 들어가고, 부모는 변경 지점에 한 단계 더 가깝고 실제로 연결돼 있음', () => {
    const layers = layersOf(report)
    const linked = new Set(report.graph.edges.flatMap((e) => [`${e.source}|${e.target}`, `${e.target}|${e.source}`]))
    rows.forEach((row, i) => {
      if (i === 0) expect(row.depth).toBe(0)
      else expect(row.depth).toBeLessThanOrEqual(rows[i - 1].depth + 1)
      const parent = parentOf(i)
      if (row.depth === 0) {
        expect(row.relation).toBeNull()
        return
      }
      expect(parent).toBeDefined()
      expect(layers.get(parent as string)).toBeLessThan(layers.get(row.id) as number)
      expect(linked.has(`${parent}|${row.id}`)).toBe(true)
    })
  })

  it('같은 보고면 같은 목록(결정적), 영향 순서를 바꿔도 노드 집합과 뿌리는 그대로', () => {
    expect(outlineOf(report)).toEqual(rows)
    const reversed = { ...report, impacts: [...report.impacts].reverse() } as ImpactReport
    const again = outlineOf(reversed)
    expect(again.map((r) => r.id).sort()).toEqual(rows.map((r) => r.id).sort())
    expect(again.filter((r) => r.depth === 0).map((r) => r.id)).toEqual(['P1', 'X'])
  })
})
