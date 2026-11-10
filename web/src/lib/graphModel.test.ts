import { describe, expect, it } from 'vitest'
import type { Hop, Impact, ImpactReport } from '@/api/client'
import {
  boundsOf,
  cardRect,
  type GraphCard,
  graphModel,
  isGroup,
  mainPaths,
  MAP_READ_EDGE,
  MAP_READ_ZOOM,
  MAX_COLUMN,
  mapGraphHeight,
  mapOrientation,
  nearestInDirection,
  readableViewport,
} from './graphModel'

describe('영향 지도 판 배치(근거를 옆에 둘까 아래에 둘까)', () => {
  const monitor = { width: 1566, height: 984 }
  it('판이 좁으면 늘 위아래', () => {
    expect(mapOrientation({ width: 1000, height: 984 }, { width: 400, height: 300 })).toBe('vertical')
  })
  it('옆으로 긴 사슬은 위아래(카드가 더 크게), 작거나 세로로 긴 그래프는 옆', () => {
    expect(mapOrientation(monitor, { width: 2168, height: 300 })).toBe('vertical')
    expect(mapOrientation(monitor, { width: 1328, height: 600 })).toBe('vertical')
    expect(mapOrientation(monitor, { width: 700, height: 600 })).toBe('horizontal')
    expect(mapOrientation(monitor, { width: 600, height: 900 })).toBe('horizontal')
  })
  it('카드가 없으면 위아래, 둘레는 카드 좌표의 바깥 경계', () => {
    expect(mapOrientation(monitor, { width: 0, height: 0 })).toBe('vertical')
    const card = (x: number, y: number) => ({ x, y, width: 208, height: 64 }) as GraphCard
    expect(boundsOf([card(0, 0), card(280, 140)])).toEqual({ width: 488, height: 204 })
    expect(boundsOf([])).toEqual({ width: 0, height: 0 })
  })
})

const hop = (src: string, dst: string, relation: Hop['relation'], rule_id: string): Hop => ({ src, dst, relation, rule_id })

function impact(entity_id: string, impact_type: Impact['impact_type'], severity: Impact['severity'], path: Hop[]): Impact {
  return { entity_type: 'part', entity_id, ship_id: 'S-001', impact_type, severity, rule_id: 'R-T02', path, note: '' } as Impact
}

/** 변경 지점 T 하나에 맞대기 판 taper개(테이퍼, 보통) + 필릿 부재 weld개(용접 재검토, 낮음) + 블록(재작업, 높음) + 영향 없는 연결 부재 context개. */
function fan(taper: number, weld: number, context: number): ImpactReport {
  const nodes: { id: string; type: string; label: string; attrs: Record<string, unknown>; virtual: boolean }[] = [
    { id: 'T', type: 'part', label: '바꾸는 판', attrs: { role: 'target' }, virtual: false },
  ]
  const edges: { source: string; target: string; relation: string; virtual: boolean }[] = []
  const impacts: Impact[] = []
  const add = (id: string, type: string, relation: Hop['relation']) => {
    nodes.push({ id, type, label: id, attrs: {}, virtual: false })
    edges.push({ source: 'T', target: id, relation, virtual: false })
  }
  for (let i = 0; i < taper; i += 1) {
    add(`P${i}`, 'part', 'butt_weld')
    impacts.push(impact(`P${i}`, 'taper', 'medium', [hop('T', `P${i}`, 'butt_weld', 'R-T02')]))
  }
  for (let i = 0; i < weld; i += 1) {
    add(`S${i}`, 'part', 'fillet_weld')
    impacts.push(impact(`S${i}`, 'weld_recheck', 'low', [hop('T', `S${i}`, 'fillet_weld', 'R-T03')]))
  }
  add('B', 'block', 'part_of')
  impacts.push(impact('B', 'rework', 'high', [hop('T', 'B', 'part_of', 'R-B01')]))
  for (let i = 0; i < context; i += 1) add(`C${i}`, 'part', 'pipe_joint')
  // 2단계 노드 하나: 블록의 도면
  nodes.push({ id: 'D', type: 'drawing', label: '도면', attrs: {}, virtual: false })
  edges.push({ source: 'B', target: 'D', relation: 'drawn_in', virtual: false })
  impacts.push(impact('D', 'drawing_revision', 'low', [hop('T', 'B', 'part_of', 'R-D01'), hop('B', 'D', 'drawn_in', 'R-D01')]))
  return { impacts, graph: { snapshot_id: 'G', truncated: false, nodes, edges } } as unknown as ImpactReport
}

const column = (cards: GraphCard[], layer: number) => cards.filter((card) => card.layer === layer)

function checkGeometry(cards: GraphCard[]) {
  const xs = new Map<number, Set<number>>()
  for (const card of cards) xs.set(card.layer, new Set([...(xs.get(card.layer) ?? []), Math.round(card.x)]))
  const ordered = [...xs.entries()].sort((a, b) => a[0] - b[0])
  for (const [, set] of ordered) expect(set.size).toBe(1)
  ordered.forEach(([, set], i) => {
    if (i > 0) expect([...set][0]).toBeGreaterThan([...ordered[i - 1][1]][0])
  })
  cards.forEach((a, i) =>
    cards.forEach((b, j) => {
      if (j <= i) return
      const apart = a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y
      expect(apart, `${a.id} · ${b.id}`).toBe(true)
    }),
  )
}

describe('영향 지도 그래프 칸 높이(위아래 배치)', () => {
  const limits = { min: 240, max: 520 }
  it('옆으로 긴 사슬은 폭에 맞춘 그림 높이 + 도구 막대 + 여백까지만(판 가운데 위아래 공백 없음)', () => {
    // 1100 × 300 사슬을 1000 폭에 맞추면 배율 1000/1210(읽기 하한 0.72 위) → 그림 높이 약 273 + 막대 44 + 여백 32
    expect(mapGraphHeight(1000, { width: 1100, height: 300 }, limits)).toBe(Math.ceil(300 * 1.1 * (1000 / 1210)) + 44 + 32)
    expect(mapGraphHeight(1000, { width: 1100, height: 300 }, limits, 80)).toBe(Math.ceil(300 * 1.1 * (1000 / 1210)) + 80 + 32)
  })
  it('폭 맞춤 배율이 읽기 하한보다 작은 긴 사슬은 하한 배율의 그림 높이(옆으로 넘치는 부분은 끌어서)', () => {
    // 1700 × 300을 1000 폭에 맞추면 0.535 → 하한 0.72의 그림 높이
    expect(mapGraphHeight(1000, { width: 1700, height: 300 }, limits)).toBe(Math.ceil(300 * 1.1 * MAP_READ_ZOOM) + 44 + 32)
  })
  it('최소·최대로 자르고, 배율은 1을 넘지 않음', () => {
    expect(mapGraphHeight(1000, { width: 3000, height: 100 }, limits)).toBe(240)
    expect(mapGraphHeight(1000, { width: 400, height: 900 }, limits)).toBe(520)
    // 작은 그래프는 키우지 않는다(배율 1): 300 높이 → 330 + 44 + 32
    expect(mapGraphHeight(1000, { width: 300, height: 300 }, limits)).toBe(406)
  })
  it('잴 수 없으면 최대', () => {
    expect(mapGraphHeight(0, { width: 300, height: 300 }, limits)).toBe(520)
    expect(mapGraphHeight(800, { width: 0, height: 0 }, limits)).toBe(520)
  })
})

describe('읽을 수 있는 맞춤 보기(영향 지도 첫 화면)', () => {
  const panel = { width: 1000, height: 300 }
  it('다 들어가면 맞춤 보기 그대로(가운데, 배율 1 이하), 넘침 아님', () => {
    const view = readableViewport(panel, { x: 0, y: 0, width: 600, height: 200 })
    expect(view.zoom).toBe(1)
    expect(view.overflow).toBe(false)
    expect(view.x).toBe((1000 - 600) / 2)
    expect(view.y).toBe((300 - 200) / 2)
  })
  it('긴 사슬: 배율은 읽기 하한 아래로 내려가지 않고, 변경 지점(왼쪽)이 판 왼쪽 가장자리에 붙음', () => {
    const bounds = { x: 40, y: 10, width: 3000, height: 200 }
    const view = readableViewport(panel, bounds)
    expect(view.zoom).toBe(MAP_READ_ZOOM)
    expect(view.overflow).toBe(true)
    // 화면 x = 배치 x × 배율 + view.x → 그래프 왼쪽 끝이 가장자리 여백 자리
    expect(bounds.x * view.zoom + view.x).toBe(MAP_READ_EDGE)
    // 세로는 들어가므로 가운데
    expect(bounds.y * view.zoom + view.y).toBeCloseTo((300 - 200 * MAP_READ_ZOOM) / 2)
    // 카드 글자(큰 글자 기본 — 제목 18px · 메타 17px)가 화면에서 12px 이상
    expect(17 * view.zoom).toBeGreaterThanOrEqual(12)
  })
  it('세로로도 넘치면 위에 붙인다', () => {
    const view = readableViewport({ width: 400, height: 200 }, { x: 0, y: -50, width: 2000, height: 900 })
    expect(view.zoom).toBe(MAP_READ_ZOOM)
    expect(-50 * view.zoom + view.y).toBe(MAP_READ_EDGE)
  })
  it('맞춤 배율이 하한 이상이면 하한을 쓰지 않음(맞춤이 더 크면 그대로)', () => {
    const view = readableViewport(panel, { x: 0, y: 0, width: 1000, height: 100 })
    expect(view.zoom).toBeCloseTo(1000 / 1100)
    expect(view.overflow).toBe(false)
  })
  it('잴 수 없으면 원래 배율, 넘침 아님', () => {
    expect(readableViewport({ width: 0, height: 0 }, { x: 0, y: 0, width: 10, height: 10 })).toEqual({ x: 0, y: 0, zoom: 1, overflow: false })
    expect(cardRect([])).toEqual({ x: 0, y: 0, width: 0, height: 0 })
  })
  it('cardRect: 카드 바깥 경계의 왼쪽 위와 크기', () => {
    const card = (x: number, y: number) => ({ x, y, width: 208, height: 64 }) as GraphCard
    expect(cardRect([card(20, -10), card(300, 140)])).toEqual({ x: 20, y: -10, width: 488, height: 214 })
  })
})

describe('주요 경로(가장 심각한 영향까지의 근거 경로)', () => {
  it('높음 영향의 경로 카드·간선만 담고, 끝 카드는 맥동 대상', () => {
    const report = fan(2, 2, 1)
    const model = graphModel(report)
    const main = mainPaths(report, model)
    expect([...main.cards].sort()).toEqual(['B', 'T'])
    expect([...main.links]).toEqual(['T->B'])
    expect([...main.peaks]).toEqual(['B'])
    for (const id of main.links) expect(model.links.some((link) => link.id === id)).toBe(true)
  })
  it('높음이 없으면 그다음 심각도가 주요, 영향이 없으면 빈 모음', () => {
    const report = fan(2, 1, 0)
    const onlyMedium = { ...report, impacts: report.impacts.filter((i) => i.severity !== 'high') } as typeof report
    const main = mainPaths(onlyMedium, graphModel(onlyMedium))
    expect([...main.peaks].sort()).toEqual(['P0', 'P1'])
    const none = { ...report, impacts: [] } as typeof report
    expect(mainPaths(none, graphModel(none)).cards.size).toBe(0)
  })
  it('묶음 안의 엔터티는 묶음 카드로 옮겨 간선이 실제 그려진 것과 맞음', () => {
    const report = fan(8, 5, 3)
    const model = graphModel(report)
    const main = mainPaths(report, model)
    for (const id of main.cards) expect(model.cards.some((card) => card.id === id)).toBe(true)
    for (const id of main.links) expect(model.links.some((link) => link.id === id)).toBe(true)
  })
})

describe('graphModel', () => {
  it('작은 그래프는 묶지 않음(카드 = 노드)', () => {
    const report = fan(2, 2, 0)
    const { cards } = graphModel(report)
    expect(cards.map((c) => c.id).sort()).toEqual(report.graph.nodes.map((n) => n.id).sort())
    expect(cards.some((c) => isGroup(c.id))).toBe(false)
    checkGeometry(cards)
  })

  it('열이 넘치면 큰 무리부터 묶어 열을 기준 이하로, 노드는 하나도 잃지 않음', () => {
    const report = fan(8, 5, 3)
    const { cards, cardOf } = graphModel(report)
    expect(column(cards, 1).length).toBeLessThanOrEqual(MAX_COLUMN)
    const members = cards.flatMap((c) => c.members).sort()
    expect(members).toEqual(report.graph.nodes.map((n) => n.id).sort())
    for (const node of report.graph.nodes) expect(cards.find((c) => c.id === cardOf.get(node.id))?.members).toContain(node.id)
    const groups = cards.filter((c) => isGroup(c.id))
    expect(groups.map((g) => [g.impact, g.members.length])).toContainEqual(['taper', 8])
    expect(groups.every((g) => g.members.length >= 2 && g.role === null)).toBe(true)
    checkGeometry(cards)
  })

  it('변경 지점은 묶지 않고, 묶음을 펼치면 구성원이 다시 카드가 됨', () => {
    const report = fan(8, 5, 3)
    const first = graphModel(report)
    expect(first.cards.find((c) => c.members.includes('T'))?.id).toBe('T')
    const taper = first.cards.find((c) => c.impact === 'taper') as GraphCard
    const opened = graphModel(report, new Set([taper.id]))
    for (const member of taper.members) expect(opened.cardOf.get(member)).toBe(member)
    checkGeometry(opened.cards)
  })

  it('간선: 카드 쌍마다 하나, 자기 자신으로 가지 않고 단계가 낮은 쪽 → 높은 쪽, 합친 수 보존', () => {
    const report = fan(8, 5, 3)
    const { cards, links, cardOf } = graphModel(report)
    const layer = new Map(cards.map((c) => [c.id, c.layer]))
    expect(new Set(links.map((l) => l.id)).size).toBe(links.length)
    for (const link of links) {
      expect(link.source).not.toBe(link.target)
      expect(layer.get(link.source) as number).toBeLessThanOrEqual(layer.get(link.target) as number)
    }
    const crossing = report.graph.edges.filter((e) => cardOf.get(e.source) !== cardOf.get(e.target)).length
    expect(links.reduce((sum, l) => sum + l.count, 0)).toBe(crossing)
  })

  it('같은 보고면 같은 모델(결정적)', () => {
    const report = fan(8, 5, 3)
    expect(JSON.stringify(graphModel(report).cards)).toBe(JSON.stringify(graphModel(report).cards))
  })
})

describe('nearestInDirection', () => {
  const card = (id: string, x: number, y: number): GraphCard =>
    ({ id, x, y, width: 100, height: 40, members: [id], layer: 0, type: 'part', impact: null, severity: null, role: null, virtual: false }) as GraphCard
  const grid = [card('a', 0, 0), card('b', 200, 0), card('c', 200, 80), card('d', 0, 80), card('e', 400, 40)]

  it('그 방향의 가장 가까운 카드, 끝이면 null', () => {
    expect(nearestInDirection(grid, 'a', 'right')).toBe('b')
    expect(nearestInDirection(grid, 'a', 'down')).toBe('d')
    expect(nearestInDirection(grid, 'c', 'left')).toBe('d')
    expect(nearestInDirection(grid, 'b', 'right')).toBe('e')
    expect(nearestInDirection(grid, 'a', 'left')).toBeNull()
    expect(nearestInDirection(grid, 'a', 'up')).toBeNull()
    expect(nearestInDirection(grid, 'zz', 'up')).toBeNull()
  })

  it('모든 카드에 닿을 수 있음(방향키만으로)', () => {
    const seen = new Set(['a'])
    const queue = ['a']
    while (queue.length > 0) {
      const id = queue.shift() as string
      for (const direction of ['left', 'right', 'up', 'down'] as const) {
        const next = nearestInDirection(grid, id, direction)
        if (next && !seen.has(next)) {
          seen.add(next)
          queue.push(next)
        }
      }
    }
    expect([...seen].sort()).toEqual(grid.map((c) => c.id).sort())
  })
})
