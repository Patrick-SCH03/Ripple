// 영향 보고 → 화면 계산(순수 함수, ripple.test.ts가 성질을 검사한다).
import type { GraphNode, Impact, ImpactView, ImpactType, Severity } from '@/api/client'
import { SEVERITY_RANK } from './labels'

export const TARGET_ROLES = new Set(['target', 'removed', 'new'])

/** 노드마다 변경 지점에서 몇 단계 떨어졌는지(파급 애니메이션 순서).
 *
 * 대상 부재는 0. 근거 경로의 i번째 단계 도착 노드는 i+1 중 가장 작은 값. 경로에 없는 노드(새 연결의 끝점 등)는
 * 그래프 연결을 따라 가장 가까운 단계 + 1. 어디에도 닿지 않으면 마지막 단계 + 1.
 */
export function layersOf(report: ImpactView): Map<string, number> {
  const layers = new Map<string, number>()
  const lower = (id: string, layer: number) => {
    const current = layers.get(id)
    if (current === undefined || layer < current) layers.set(id, layer)
  }
  for (const node of report.graph.nodes) if (TARGET_ROLES.has(roleOf(node) ?? '')) lower(node.id, 0)
  for (const impact of report.impacts) {
    if (impact.path.length === 0) lower(impact.entity_id, 0)
    impact.path.forEach((hop, i) => {
      lower(hop.src, i)
      lower(hop.dst, i + 1)
    })
  }
  const neighbours = new Map<string, string[]>()
  for (const edge of report.graph.edges) {
    neighbours.set(edge.source, [...(neighbours.get(edge.source) ?? []), edge.target])
    neighbours.set(edge.target, [...(neighbours.get(edge.target) ?? []), edge.source])
  }
  const queue = [...layers.keys()].sort((a, b) => (layers.get(a) ?? 0) - (layers.get(b) ?? 0))
  while (queue.length > 0) {
    const id = queue.shift() as string
    for (const next of neighbours.get(id) ?? []) {
      if (!layers.has(next)) {
        layers.set(next, (layers.get(id) ?? 0) + 1)
        queue.push(next)
      }
    }
  }
  const last = Math.max(0, ...layers.values())
  for (const node of report.graph.nodes) if (!layers.has(node.id)) layers.set(node.id, last + 1)
  return layers
}

export function roleOf(node: GraphNode): string | undefined {
  const role = node.attrs?.role
  return typeof role === 'string' ? role : undefined
}

/** 엔터티 ID → 그 엔터티의 영향(키 순 그대로). */
export function impactsByEntity(report: ImpactView): Map<string, Impact[]> {
  const found = new Map<string, Impact[]>()
  for (const impact of report.impacts) found.set(impact.entity_id, [...(found.get(impact.entity_id) ?? []), impact])
  return found
}

/** 노드의 가장 높은 심각도(영향이 없으면 undefined). */
export function topSeverity(impacts: Impact[] | undefined): Severity | undefined {
  let top: Severity | undefined
  for (const impact of impacts ?? []) {
    if (top === undefined || SEVERITY_RANK[impact.severity] > SEVERITY_RANK[top]) top = impact.severity
  }
  return top
}

export interface Summary {
  total: number
  entities: number
  byType: [ImpactType, number][]
  high: number
  reworkBlocks: string[]
  orderLines: string[]
}

/** 요약 카드: 영향 수, 엔터티 수, 종류별 수(많은 순), 높은 심각도 수, 재작업 블록, 발주 변경 품목. */
export function summarize(report: ImpactView): Summary {
  const counts = new Map<ImpactType, number>()
  for (const impact of report.impacts) counts.set(impact.impact_type, (counts.get(impact.impact_type) ?? 0) + 1)
  const byType = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  const ids = (type: ImpactType) =>
    [...new Set(report.impacts.filter((i) => i.impact_type === type).map((i) => i.entity_id))].sort()
  return {
    total: report.impacts.length,
    entities: new Set(report.impacts.map((i) => i.entity_id)).size,
    byType,
    high: report.impacts.filter((i) => i.severity === 'high').length,
    reworkBlocks: ids('rework'),
    orderLines: ids('po_change'),
  }
}

/** 들여쓴 영향 목록의 한 줄. relation·virtual은 부모에서 이 노드로 오는 연결(뿌리면 null·false). */
export interface OutlineRow {
  id: string
  depth: number
  relation: string | null
  virtual: boolean
}

/** 들여쓴 영향 목록: 파급 그래프의 글 대안(좁은 화면·화면 낭독기).
 *
 * 그래프의 노드가 한 번씩 나온다. 부모는 근거 경로에서 바로 앞 노드(변경 지점에 한 단계 더 가까운 것),
 * 경로에 없으면 그래프에서 한 단계 가까운 이웃(ID 순 첫째). 부모가 없으면 뿌리(변경 지점, 고립 노드).
 * 형제는 심각도 높은 순 → 이름 순, 뿌리는 단계 순 → 이름 순.
 */
export function outlineOf(report: ImpactView): OutlineRow[] {
  const layers = layersOf(report)
  const layer = (id: string) => layers.get(id) ?? 0
  const nodes = new Map(report.graph.nodes.map((node) => [node.id, node]))
  const edgeBetween = new Map<string, { relation: string; virtual: boolean }>()
  for (const edge of report.graph.edges) {
    for (const key of [`${edge.source}|${edge.target}`, `${edge.target}|${edge.source}`]) {
      if (!edgeBetween.has(key)) edgeBetween.set(key, { relation: edge.relation, virtual: edge.virtual })
    }
  }

  const parent = new Map<string, { id: string; relation: string; virtual: boolean }>()
  for (const impact of report.impacts) {
    for (const hop of impact.path) {
      if (parent.has(hop.dst) || !nodes.has(hop.dst) || !nodes.has(hop.src) || layer(hop.src) >= layer(hop.dst)) continue
      parent.set(hop.dst, { id: hop.src, relation: hop.relation, virtual: edgeBetween.get(`${hop.src}|${hop.dst}`)?.virtual ?? false })
    }
  }
  const neighbours = new Map<string, string[]>()
  for (const edge of report.graph.edges) {
    neighbours.set(edge.source, [...(neighbours.get(edge.source) ?? []), edge.target])
    neighbours.set(edge.target, [...(neighbours.get(edge.target) ?? []), edge.source])
  }
  for (const id of nodes.keys()) {
    if (parent.has(id)) continue
    const closer = (neighbours.get(id) ?? []).filter((n) => nodes.has(n) && layer(n) === layer(id) - 1).sort()[0]
    const edge = closer === undefined ? undefined : edgeBetween.get(`${closer}|${id}`)
    if (closer !== undefined && edge) parent.set(id, { id: closer, ...edge })
  }

  const severity = impactsByEntity(report)
  const rank = (id: string) => SEVERITY_RANK[topSeverity(severity.get(id)) ?? 'info'] + (severity.has(id) ? 1 : 0)
  const label = (id: string) => nodes.get(id)?.label ?? id
  const byName = (a: string, b: string) => label(a).localeCompare(label(b), 'ko') || (a < b ? -1 : a > b ? 1 : 0)
  const children = new Map<string, string[]>()
  for (const [child, link] of parent) children.set(link.id, [...(children.get(link.id) ?? []), child])
  for (const list of children.values()) list.sort((a, b) => rank(b) - rank(a) || byName(a, b))
  const roots = [...nodes.keys()].filter((id) => !parent.has(id)).sort((a, b) => layer(a) - layer(b) || byName(a, b))

  const rows: OutlineRow[] = []
  const stack = [...roots].reverse().map((id) => ({ id, depth: 0 }))
  while (stack.length > 0) {
    const { id, depth } = stack.pop() as { id: string; depth: number }
    const link = parent.get(id)
    rows.push({ id, depth, relation: link?.relation ?? null, virtual: link?.virtual ?? false })
    for (const child of [...(children.get(id) ?? [])].reverse()) stack.push({ id: child, depth: depth + 1 })
  }
  return rows
}
