// 파급 그래프 모델(순수 함수, graphModel.test.ts가 성질을 검사한다): 카드 묶음 + 단계 고정 배치.
//
// - 단계(layersOf) = 열. 변경 지점이 맨 왼쪽, 파급은 왼쪽 → 오른쪽.
// - 한 열의 카드가 maxColumn을 넘을 때만, 같은 종류 · 대표 영향 · 심각도 무리(영향 없는 연결 부재끼리도)를
//   큰 것부터 묶음 카드로 접는다(2개 이상). 작은 그래프는 하나하나 그대로 보인다. 변경 지점은 묶지 않는다.
// - 간선은 카드 쌍마다 하나로 합치고, 단계가 낮은 쪽 → 높은 쪽으로 돌린다.
// - 배치는 dagre(rankdir LR)에 단계를 순위로 강제(minlen = 단계 차이)하고, 열 안 순서만 교차가 적게 맡긴다.
import dagre from '@dagrejs/dagre'
import type { Impact, ImpactView, ImpactType, Severity } from '@/api/client'
import type { GraphCard } from './graphCards'
import { SEVERITY_RANK } from './labels'
import { impactsByEntity, layersOf, roleOf } from './ripple'

// 카드 크기 252×90: 큰 글자 기본(11-03, 제목 18px 두 줄 · 메타 17px + 심각도 배지)이 잘리거나 겹치지 않게(전에는 228×76)
const CARD = { width: 252, height: 90, groupHeight: 98, rankGap: 72, nodeGap: 12 } as const
export const MAX_COLUMN = 6

export { cardText, type GraphCard, isGroup } from './graphCards'

export interface GraphLink {
  id: string
  source: string
  target: string
  relation: string
  virtual: boolean
  /** 합쳐진 원래 간선 수. */
  count: number
}

export interface GraphModel {
  cards: GraphCard[]
  links: GraphLink[]
  /** 노드 ID → 그 노드를 그리는 카드 ID(묶였으면 묶음 ID). */
  cardOf: Map<string, string>
}

/** 대표 영향: 가장 높은 심각도의 영향(같으면 보고서 순서 첫째). */
function representative(impacts: readonly Impact[] | undefined): { impact: ImpactType; severity: Severity } | null {
  let best: { impact: ImpactType; severity: Severity } | null = null
  for (const impact of impacts ?? []) {
    if (!best || SEVERITY_RANK[impact.severity] > SEVERITY_RANK[best.severity]) {
      best = { impact: impact.impact_type, severity: impact.severity }
    }
  }
  return best
}

export function graphModel(
  report: ImpactView,
  expanded: ReadonlySet<string> = new Set(),
  maxColumn: number = MAX_COLUMN,
): GraphModel {
  const layers = layersOf(report)
  const byEntity = impactsByEntity(report)
  const nodes = new Map(report.graph.nodes.map((node) => [node.id, node]))
  const layer = (id: string) => layers.get(id) ?? 0
  const top = (id: string) => representative(byEntity.get(id))

  const groupKey = (id: string): string | null => {
    const node = nodes.get(id)
    if (!node || roleOf(node)) return null
    const best = top(id)
    return `group:${layer(id)}:${node.type}:${best?.impact ?? 'none'}:${best?.severity ?? 'none'}`
  }

  // 열마다 넘칠 때만 큰 무리부터 접는다
  const byLayer = new Map<number, string[]>()
  for (const node of report.graph.nodes) byLayer.set(layer(node.id), [...(byLayer.get(layer(node.id)) ?? []), node.id])
  const folded = new Map<string, string>()
  for (const ids of byLayer.values()) {
    let count = ids.length
    const sets = new Map<string, string[]>()
    for (const id of ids) {
      const key = groupKey(id)
      if (key) sets.set(key, [...(sets.get(key) ?? []), id])
    }
    const largest = [...sets.entries()]
      .filter(([key, members]) => members.length >= 2 && !expanded.has(key))
      .sort((a, b) => b[1].length - a[1].length || (a[0] < b[0] ? -1 : 1))
    for (const [key, members] of largest) {
      if (count <= maxColumn) break
      for (const id of members) folded.set(id, key)
      count -= members.length - 1
    }
  }

  const cardOf = new Map<string, string>()
  const cards: Omit<GraphCard, 'x' | 'y' | 'width' | 'height'>[] = []
  const made = new Set<string>()
  for (const node of report.graph.nodes) {
    const key = folded.get(node.id)
    const best = top(node.id)
    if (key) {
      cardOf.set(node.id, key)
      if (made.has(key)) continue
      made.add(key)
      const members = report.graph.nodes.filter((n) => folded.get(n.id) === key).map((n) => n.id).sort()
      cards.push({
        id: key,
        members,
        layer: layer(node.id),
        type: node.type,
        impact: best?.impact ?? null,
        severity: best?.severity ?? null,
        role: null,
        virtual: members.every((m) => nodes.get(m)?.virtual),
      })
      continue
    }
    cardOf.set(node.id, node.id)
    cards.push({
      id: node.id,
      members: [node.id],
      layer: layer(node.id),
      type: node.type,
      impact: best?.impact ?? null,
      severity: best?.severity ?? null,
      role: roleOf(node) ?? null,
      virtual: node.virtual,
    })
  }

  const layerOf = new Map(cards.map((card) => [card.id, card.layer]))
  const merged = new Map<string, GraphLink>()
  for (const edge of report.graph.edges) {
    let source = cardOf.get(edge.source)
    let target = cardOf.get(edge.target)
    if (!source || !target || source === target) continue
    if ((layerOf.get(source) ?? 0) > (layerOf.get(target) ?? 0)) [source, target] = [target, source]
    const id = `${source}->${target}`
    const found = merged.get(id)
    if (found) {
      found.count += 1
      found.virtual &&= edge.virtual
    } else merged.set(id, { id, source, target, relation: edge.relation, virtual: edge.virtual, count: 1 })
  }
  const links = [...merged.values()].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))

  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: CARD.nodeGap, ranksep: CARD.rankGap, marginx: 0, marginy: 0 })
  g.setDefaultEdgeLabel(() => ({}))
  const sorted = [...cards].sort((a, b) => a.layer - b.layer || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
  for (const card of sorted) {
    g.setNode(card.id, { width: CARD.width, height: card.members.length > 1 ? CARD.groupHeight : CARD.height })
  }
  for (const link of links) {
    const span = (layerOf.get(link.target) ?? 0) - (layerOf.get(link.source) ?? 0)
    if (span > 0) g.setEdge(link.source, link.target, { minlen: span })
  }
  // 간선이 없는 열도 제자리에 오도록 열마다 첫 카드를 보이지 않는 사슬로 잇는다
  const firstOf = new Map<number, string>()
  for (const card of sorted) if (!firstOf.has(card.layer)) firstOf.set(card.layer, card.id)
  const columns = [...firstOf.keys()].sort((a, b) => a - b)
  for (let i = 1; i < columns.length; i += 1) {
    const from = firstOf.get(columns[i - 1]) as string
    const to = firstOf.get(columns[i]) as string
    if (!g.hasEdge(from, to)) g.setEdge(from, to, { minlen: columns[i] - columns[i - 1], weight: 0 })
  }
  dagre.layout(g)
  const placed = sorted.map((card) => {
    const at = g.node(card.id)
    return { ...card, x: at.x - at.width / 2, y: at.y - at.height / 2, width: at.width, height: at.height }
  })
  return { cards: placed, links, cardOf }
}

export interface MainPaths {
  /** 주요 경로에 놓인 카드(변경 지점 → 가장 심각한 영향까지). */
  cards: Set<string>
  /** 그 경로의 간선 ID. */
  links: Set<string>
  /** 경로 끝: 가장 심각한 영향을 받는 카드(지도에서 맥동). */
  peaks: Set<string>
}

/**
 * 주요 경로: 가장 높은 심각도의 영향마다 근거 경로(hop)를 카드로 옮겨 모은다. 지도에서 흐르는 간선·맥동·'주요 경로만'
 * 강조에 쓴다. 묶음 카드 안의 엔터티는 그 묶음 카드로, 간선 방향은 graphModel처럼 낮은 단계 → 높은 단계.
 */
export function mainPaths(report: ImpactView, model: GraphModel): MainPaths {
  const found: MainPaths = { cards: new Set(), links: new Set(), peaks: new Set() }
  const top = Math.max(0, ...report.impacts.map((impact) => SEVERITY_RANK[impact.severity]))
  if (top === 0) return found
  const layer = new Map(model.cards.map((card) => [card.id, card.layer]))
  const known = new Set(model.links.map((link) => link.id))
  for (const impact of report.impacts) {
    if (SEVERITY_RANK[impact.severity] !== top) continue
    const end = model.cardOf.get(impact.entity_id)
    if (end) {
      found.cards.add(end)
      found.peaks.add(end)
    }
    for (const hop of impact.path) {
      let source = model.cardOf.get(hop.src)
      let target = model.cardOf.get(hop.dst)
      if (!source || !target) continue
      found.cards.add(source).add(target)
      if (source === target) continue
      if ((layer.get(source) ?? 0) > (layer.get(target) ?? 0)) [source, target] = [target, source]
      const id = `${source}->${target}`
      if (known.has(id)) found.links.add(id)
    }
  }
  return found
}

/** 카드들이 차지하는 너비·높이(배치 좌표 기준). */
export function boundsOf(cards: readonly GraphCard[]): { width: number; height: number } {
  if (cards.length === 0) return { width: 0, height: 0 }
  const left = Math.min(...cards.map((card) => card.x))
  const top = Math.min(...cards.map((card) => card.y))
  const right = Math.max(...cards.map((card) => card.x + card.width))
  const bottom = Math.max(...cards.map((card) => card.y + card.height))
  return { width: right - left, height: bottom - top }
}

export interface MapLayoutOptions {
  /** 이 폭보다 좁은 판은 늘 위아래. */
  minWidth: number
  /** 위아래 배치에서 그래프 칸 비율, 옆 배치에서 그래프 칸 비율. */
  graphShare: number
  sideShare: number
  /** 그래프 칸 위 도구 막대 높이. */
  toolbar: number
}

export const MAP_LAYOUT: MapLayoutOptions = { minWidth: 1100, graphShare: 0.66, sideShare: 0.7, toolbar: 44 }

/**
 * 영향 지도 판에서 근거를 그래프 옆(horizontal)에 둘지 아래(vertical)에 둘지: 맞춤 보기 배율(여백 5%씩, 최대 1)을 두 배치로 견줘
 * 옆 배치가 거의 같거나 크면(95% 이상) 옆 — 근거가 스크롤 없이 함께 보인다. 왼쪽 → 오른쪽으로 긴 사슬은 위아래가 카드를 크게 보인다.
 */
export function mapOrientation(
  panel: { width: number; height: number },
  graph: { width: number; height: number },
  options: MapLayoutOptions = MAP_LAYOUT,
): 'horizontal' | 'vertical' {
  if (panel.width < options.minWidth || graph.width <= 0 || graph.height <= 0) return 'vertical'
  const fit = (width: number, height: number) => Math.min(1, width / (graph.width * 1.1), height / (graph.height * 1.1))
  const below = fit(panel.width, panel.height * options.graphShare - options.toolbar)
  const beside = fit(panel.width * options.sideShare, panel.height - options.toolbar)
  return beside >= below * 0.95 ? 'horizontal' : 'vertical'
}

/** 그래프 칸 높이를 그래프 모양에 맞출 때 맞춤 보기 그림 위아래에 두는 여백(px). */
const MAP_FIT_GAP = 32

/**
 * 위아래 배치의 그래프 칸 높이(px, 도구 막대 포함): 폭에 맞춘 맞춤 보기 배율(여백 5%씩, 최대 1)로 그린 그래프 높이 + 도구 막대 +
 * 여백을 [min, max]로 자른다. 옆으로 긴 사슬이 높은 판 가운데 작게 떠 위아래가 비지 않게(11-03 '공백이 심함').
 */
export function mapGraphHeight(
  width: number,
  graph: { width: number; height: number },
  limits: { min: number; max: number },
  toolbar: number = MAP_LAYOUT.toolbar,
): number {
  if (width <= 0 || graph.width <= 0 || graph.height <= 0) return limits.max
  // 폭에 맞춘 배율이 읽기 하한보다 작으면 하한으로 그린다(옆으로 넘치는 부분은 끌어서 본다 — readableViewport)
  const zoom = Math.min(1, Math.max(MAP_READ_ZOOM, width / (graph.width * 1.1)))
  const needed = Math.ceil(graph.height * 1.1 * zoom) + toolbar + MAP_FIT_GAP
  return Math.max(limits.min, Math.min(limits.max, needed))
}

/**
 * 첫 화면 영향 지도의 읽기 하한 배율(11-03 현직자 — 고령 숙련 인력이 읽는 큰 글자): 큰 글자 기본의 카드 제목 18px × 0.72 ≈ 13px,
 * 메타 17px × 0.72 ≈ 12.2px. 맞춤 보기가 이보다 작아지는 긴 사슬은 이 배율로 변경 지점(왼쪽)부터 보이고, 나머지는 끌어서 보거나 '전체 보기'.
 */
export const MAP_READ_ZOOM = 0.72

/** 넘쳐서 변경 지점 쪽에 붙일 때 판 가장자리와 그래프 사이 여백(화면 px). */
export const MAP_READ_EDGE = 16

export interface MapViewport {
  x: number
  y: number
  zoom: number
  /** 읽기 하한 때문에 그래프 전체가 판에 다 들어오지 않음(→ '전체 보기' 단추). */
  overflow: boolean
}

/**
 * 읽을 수 있는 맞춤 보기: 맞춤 보기 배율(여백 5%씩, 최대 1)이 읽기 하한 이상이면 그대로 가운데, 아니면 하한 배율로 그리되
 * 넘치는 축은 그래프의 왼쪽(변경 지점) · 위에 붙인다(가운데로 두면 변경 지점이 판 밖으로 잘림). 넘치지 않는 축은 가운데.
 * bounds = 카드들이 차지하는 사각형(배치 좌표).
 */
export function readableViewport(
  panel: { width: number; height: number },
  bounds: { x: number; y: number; width: number; height: number },
  minZoom: number = MAP_READ_ZOOM,
): MapViewport {
  if (panel.width <= 0 || panel.height <= 0 || bounds.width <= 0 || bounds.height <= 0) {
    return { x: 0, y: 0, zoom: 1, overflow: false }
  }
  const fit = Math.min(1, panel.width / (bounds.width * 1.1), panel.height / (bounds.height * 1.1))
  const zoom = Math.max(fit, Math.min(1, minZoom))
  const place = (size: number, start: number, extent: number) => {
    const drawn = extent * zoom
    // 여백(5%씩 또는 가장자리 여백)까지 들어가면 가운데, 아니면 시작 쪽 가장자리에 붙인다
    const fits = drawn * 1.1 <= size + 0.5 || drawn + 2 * MAP_READ_EDGE <= size
    return fits ? (size - drawn) / 2 - start * zoom : MAP_READ_EDGE - start * zoom
  }
  return {
    x: place(panel.width, bounds.x, bounds.width),
    y: place(panel.height, bounds.y, bounds.height),
    zoom,
    overflow: zoom > fit + 1e-9,
  }
}

/** 카드들이 차지하는 사각형(배치 좌표, 왼쪽 위 포함). 카드가 없으면 0. */
export function cardRect(cards: readonly GraphCard[]): { x: number; y: number; width: number; height: number } {
  if (cards.length === 0) return { x: 0, y: 0, width: 0, height: 0 }
  const x = Math.min(...cards.map((card) => card.x))
  const y = Math.min(...cards.map((card) => card.y))
  return { x, y, ...boundsOf(cards) }
}
export type Direction = 'left' | 'right' | 'up' | 'down'

/** 방향키 탐색: from에서 그 방향에 있는 카드 중 가장 가까운 것(주축 거리 + 2 × 옆 거리). 없으면 null. */
export function nearestInDirection(cards: readonly GraphCard[], from: string, direction: Direction): string | null {
  const origin = cards.find((card) => card.id === from)
  if (!origin) return null
  const center = (card: GraphCard) => ({ x: card.x + card.width / 2, y: card.y + card.height / 2 })
  const o = center(origin)
  let best: { id: string; score: number } | null = null
  for (const card of cards) {
    if (card.id === from) continue
    const c = center(card)
    const dx = c.x - o.x
    const dy = c.y - o.y
    const [main, side] =
      direction === 'left' ? [-dx, dy] : direction === 'right' ? [dx, dy] : direction === 'up' ? [-dy, dx] : [dy, dx]
    if (main <= 1) continue
    const score = main + 2 * Math.abs(side)
    if (!best || score < best.score || (score === best.score && card.id < best.id)) best = { id: card.id, score }
  }
  return best?.id ?? null
}
