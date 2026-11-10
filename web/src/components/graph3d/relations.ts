// 3D 블록 사이 관계(순수 함수, relations.test.ts가 검사): 분석 결과의 근거 경로(impacts[].path)를 블록 단위로 접어
// '어느 블록에서 어느 블록으로 번졌나'를 화살표로 그린다. 지어내지 않는다 — 경로에 실제로 있는 연결만 쓴다.
//
// - 경로의 노드 → 블록(blocks.ts blockIdOf). 블록이 바뀌는 곳이 블록 사이 관계 하나. 블록이 없는 노드(도면·발주 품목·재고)를
//   거쳐 다른 블록으로 갔으면 그 노드 종류로 이름 짓는다(도면 → '같은 도면', 발주 품목 → '같은 발주').
// - 홉: 바꾸는 부재 블록 0, 경로를 따라 블록이 바뀔 때마다 +1(영향마다 가장 작은 값). 경로가 블록 없는
//   노드(도면 등)에서 시작하면 처음 닿는 블록은 바꾸는 블록이 아닌 한 1. 물결 순서·'1차·2차' 칩에 쓴다.
// - 화살표: 주요 경로(2D와 같은 기준 — 가장 높은 심각도 영향의 경로, lib/graphModel mainPaths)의 블록 사이 관계만, 최대
//   MAX_LINKS개. 주요 경로에 블록 사이 관계가 없으면 그다음 심각도 단계에서.
import type { GraphNode, ImpactView, Severity } from '@/api/client'
import { RELATION_NAMES, SEVERITY_RANK } from '@/lib/labels'
import { TARGET_ROLES, roleOf } from '@/lib/ripple'
import { type BlockState, blockIdOf } from './blocks'

/** 화살표 상한(엉키지 않게). */
export const MAX_LINKS = 8

/**
 * 관계 종류 → 업무 용어(화살표 가운데 이름표). 키는 계약 Relation 열거형 + 블록 없는 노드를 거친 관계(via_*) +
 * 탑재 공정끼리의 선후행(erection_precedes).
 */
const LINK_NAMES: Record<string, string> = {
  butt_weld: '맞대기 용접',
  fillet_weld: '필릿 용접',
  penetration: '배관 관통',
  pipe_joint: '배관 연결',
  support: '배관 지지',
  precedes: '공정 선행',
  erection_precedes: '탑재 선행',
  consumed_by: '자재 소비',
  same_spec: '같은 규격',
  via_drawing: '같은 도면',
  via_po_line: '같은 발주',
  via_po: '같은 발주',
  via_stock: '같은 재고',
}

/** 곳 수를 세는 물리적 이음(용접·배관). 공정 선후행·자재 소비·같은 규격·블록 없는 노드 경유는 이음이 아니라 세지 않는다. */
const JOINT_KINDS = new Set(['butt_weld', 'fillet_weld', 'penetration', 'pipe_joint', 'support'])

export function linkName(kind: string): string {
  return LINK_NAMES[kind] ?? RELATION_NAMES[kind] ?? kind
}

export interface BlockLink {
  /** `${from}>${to}`. */
  key: string
  from: string
  to: string
  /** 관계 종류(LINK_NAMES 키, 나온 순서). */
  kinds: string[]
  /** 이 블록 쌍을 잇는 서로 다른 물리적 이음 수(JOINT_KINDS 관계의 블록 경계 엔터티 쌍 — 탑재 선행·경유는 세지 않음). */
  count: number
  /** 도착 블록 영향 단계(화살표 색). */
  severity: Severity | null
  /** 이름표 글('맞대기 용접 2곳'). */
  label: string
}

export interface RelationPlan {
  /** 그릴 화살표(출발 홉 → 코드 순). */
  links: BlockLink[]
  /** 블록 코드 → 홉(0 = 바꾸는 블록). 배치 표 블록만. */
  hops: Map<string, number>
  /** 영향마다 경로를 블록으로 접은 사슬(배치 표 블록 코드, 같은 사슬은 하나). 초점 모드에 쓴다. */
  chains: string[][]
}

interface Crossing {
  from: string
  to: string
  kind: string
  /** 경계 엔터티 쌍(같은 연결을 두 번 세지 않게). */
  pair: string
  rank: number
}

/** 블록 경계를 건넌 hop 묶음의 관계 종류: 블록 없는 노드를 거쳤으면 그 종류, 아니면 그 연결 종류(탑재끼리 선후행은 따로). */
function kindOf(hops: readonly { src: string; dst: string; relation: string }[], nodes: ReadonlyMap<string, GraphNode>): string {
  for (const hop of hops.slice(0, -1)) {
    const type = nodes.get(hop.dst)?.type
    if (type && `via_${type}` in LINK_NAMES) return `via_${type}`
  }
  const first = hops[0]
  const last = hops[hops.length - 1]
  if (first.relation === 'precedes' && first.src.endsWith(':erection') && last.dst.endsWith(':erection')) return 'erection_precedes'
  return first.relation
}

export function relationPlan(report: ImpactView, placed: ReadonlyMap<string, BlockState>, max: number = MAX_LINKS): RelationPlan {
  const nodes = new Map(report.graph.nodes.map((node) => [node.id, node]))
  const blockNodes = new Set(report.graph.nodes.filter((node) => node.type === 'block').map((node) => node.id))
  const placedIds = new Map([...placed.values()].map((state) => [state.blockId, state.code]))
  const blockOf = (id: string): string | null => {
    const node = nodes.get(id)
    if (node) return blockIdOf(node, blockNodes)
    // 지도에 없는 ID라도 배치 표 블록 ID 자체면 그 블록
    return placedIds.has(id) ? id : null
  }
  const hopIds = new Map<string, number>()
  const lower = (blockId: string, hop: number) => {
    if (hop < (hopIds.get(blockId) ?? Infinity)) hopIds.set(blockId, hop)
  }
  const changed = new Set<string>()
  for (const node of report.graph.nodes) {
    if (!TARGET_ROLES.has(roleOf(node) ?? '')) continue
    const own = blockIdOf(node, blockNodes)
    if (own) {
      changed.add(own)
      lower(own, 0)
    }
  }
  const crossings: Crossing[] = []
  const chains = new Map<string, string[]>()
  for (const impact of report.impacts) {
    const rank = SEVERITY_RANK[impact.severity]
    if (impact.path.length === 0) {
      const own = blockOf(impact.entity_id)
      if (own) lower(own, 0)
      continue
    }
    let current = blockOf(impact.path[0].src)
    let hop = 0
    let via: (typeof impact.path)[number][] = []
    if (current) lower(current, 0)
    const chain = current ? [current] : []
    for (const step of impact.path) {
      const next = blockOf(step.dst)
      if (next === null) {
        via.push(step)
        continue
      }
      if (current === null || next === current) {
        if (current === null) {
          // 경로 첫 노드에 블록이 없었다(도면 등에서 시작): 처음 닿은 블록은 바꾸는 블록이 아니면 이미 한 번 번진 것(홉 1)
          hop = changed.has(next) ? 0 : 1
          lower(next, hop)
          chain.push(next)
        }
        current = next
        via = []
        continue
      }
      const hops = [...via, step]
      hop += 1
      lower(next, hop)
      crossings.push({ from: current, to: next, kind: kindOf(hops, nodes), pair: `${hops[0].src}|${step.dst}`, rank })
      chain.push(next)
      current = next
      via = []
    }
    const codes = chain.filter((id) => placedIds.has(id)).map((id) => placedIds.get(id) as string)
    if (codes.length > 1) chains.set(codes.join('>'), codes)
  }
  const hops = new Map<string, number>()
  for (const [id, hop] of hopIds) {
    const code = placedIds.get(id)
    if (code) hops.set(code, hop)
  }

  // 그릴 관계: 배치 표 블록끼리, 가장 높은 심각도 단계부터 관계가 있는 첫 단계(주요 경로)
  const drawable = crossings.filter((c) => placedIds.has(c.from) && placedIds.has(c.to))
  const ranks = [...new Set(drawable.map((c) => c.rank))].sort((a, b) => b - a)
  const shown = new Set(drawable.filter((c) => c.rank === ranks[0]).map((c) => `${c.from}>${c.to}`))
  const grouped = new Map<string, { from: string; to: string; kinds: string[]; pairs: Map<string, Set<string>> }>()
  for (const c of drawable) {
    const key = `${c.from}>${c.to}`
    if (!shown.has(key)) continue
    const entry = grouped.get(key) ?? { from: c.from, to: c.to, kinds: [], pairs: new Map<string, Set<string>>() }
    grouped.set(key, entry)
    if (!entry.kinds.includes(c.kind)) entry.kinds.push(c.kind)
    if (JOINT_KINDS.has(c.kind)) entry.pairs.set(c.kind, (entry.pairs.get(c.kind) ?? new Set<string>()).add(c.pair))
  }
  const links = [...grouped.values()]
    .map((entry): BlockLink => {
      const from = placedIds.get(entry.from) as string
      const to = placedIds.get(entry.to) as string
      const count = [...entry.pairs.values()].reduce((sum, pairs) => sum + pairs.size, 0)
      // 곳 수는 물리적 이음 종류마다 그 이름 뒤에('맞대기 용접 2곳'), 탑재 선행·경유 관계는 이름만
      const label = entry.kinds
        .map((kind) => {
          const n = entry.pairs.get(kind)?.size ?? 0
          return n > 1 ? `${linkName(kind)} ${n}곳` : linkName(kind)
        })
        .join(' · ')
      return { key: `${from}>${to}`, from, to, kinds: entry.kinds, count, severity: placed.get(to)?.severity ?? null, label }
    })
    .sort((a, b) => (hops.get(a.from) ?? 0) - (hops.get(b.from) ?? 0) || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))
    .slice(0, max)
  return { links, hops, chains: [...chains.values()] }
}

/** 블록 홉 이름('1차' · '2차' …, 바꾸는 블록·홉 없음은 null). */
export function hopName(hop: number | undefined): string | null {
  return hop && hop > 0 ? `${hop}차` : null
}

export interface FocusPath {
  /** 남길 화살표 키. */
  links: Set<string>
  /** 남길 블록(흐리게 하지 않음). */
  blocks: Set<string>
}

/**
 * 초점 모드(목록·3D에서 블록을 골랐을 때): 그 블록까지 오는 사슬의 화살표만 남긴다. 고른 블록이 사슬의 시작(바꾸는 블록)이면
 * 거기서 나가는 1차 화살표. 사슬에 없는 블록이면 화살표는 모두 흐리게(블록은 고른 블록만 남김).
 */
export function focusPath(plan: Pick<RelationPlan, 'links' | 'chains'>, code: string): FocusPath {
  const drawn = new Set(plan.links.map((link) => link.key))
  const links = new Set<string>()
  const blocks = new Set([code])
  for (const chain of plan.chains) {
    const at = chain.indexOf(code)
    if (at < 0) continue
    const end = at === 0 ? Math.min(1, chain.length - 1) : at
    for (let i = 0; i < end; i += 1) {
      const key = `${chain[i]}>${chain[i + 1]}`
      if (!drawn.has(key)) continue
      links.add(key)
      blocks.add(chain[i]).add(chain[i + 1])
    }
  }
  return { links, blocks }
}

export interface SeamPlan {
  /** `${a}|${b}`(코드 순). */
  key: string
  a: string
  b: string
  /** 영향이 건너간 이음(물결 단계가 다른 이웃) — 도착 블록 단계 색 굵은 선 + 맥동. 아니면 바꾸는 블록의 이음면(맥동 없는 선). */
  strong: boolean
  /** 선 색: 굵은 선은 뒤 단계 블록, 나머지는 바꾸는 블록의 영향 단계. */
  severity: Severity | null
}

/**
 * 강조할 용접 이음면(맞닿은 이웃 블록 쌍만 — touching): 영향이 건너간 이음(flows)은 굵게, 바꾸는 부재 블록과 맞닿은 나머지
 * 이음면은 옅게. 맞닿지 않는 쌍(펌프룸 ↔ No.3 횡격벽)은 면이 없어 뺀다.
 */
export function seamPlan(
  flows: readonly { from: string; to: string }[],
  placed: ReadonlyMap<string, BlockState>,
  adjacency: readonly (readonly [string, string])[],
  touching: (a: string, b: string) => boolean,
): SeamPlan[] {
  const seams = new Map<string, SeamPlan>()
  const keyOf = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`)
  for (const flow of flows) {
    if (!touching(flow.from, flow.to)) continue
    const key = keyOf(flow.from, flow.to)
    seams.set(key, { key, a: flow.from, b: flow.to, strong: true, severity: placed.get(flow.to)?.severity ?? null })
  }
  for (const [a, b] of adjacency) {
    const origin = placed.get(a)?.target ? placed.get(a) : placed.get(b)?.target ? placed.get(b) : null
    if (!origin || !touching(a, b)) continue
    const key = keyOf(a, b)
    if (!seams.has(key)) seams.set(key, { key, a, b, strong: false, severity: origin.severity })
  }
  return [...seams.values()].sort((x, y) => (x.key < y.key ? -1 : 1))
}

export type Point = readonly [number, number, number]

/**
 * 화살표 곡선의 제어점: 두 끝 가운데 위로, 갑판(deck)과 두 끝 중 높은 쪽보다 lift만큼(10m + 수평 거리가 길수록 조금 더, 상한 30m).
 * 선체 위로 휘어 넘어가 다른 블록·라벨과 덜 겹친다.
 */
export function arcControl(from: Point, to: Point, deck: number): Point {
  const horizontal = Math.hypot(to[0] - from[0], to[2] - from[2])
  const lift = Math.min(30, 10 + horizontal * 0.12)
  return [(from[0] + to[0]) / 2, Math.max(from[1], to[1], deck) + lift, (from[2] + to[2]) / 2]
}

/** 2차 베지어 곡선 위 점(t 0~1). */
export function bezierAt(from: Point, control: Point, to: Point, t: number): Point {
  const u = 1 - t
  const at = (i: 0 | 1 | 2) => u * u * from[i] + 2 * u * t * control[i] + t * t * to[i]
  return [at(0), at(1), at(2)]
}

/** 끝점에서 곡선 방향(단위 벡터) — 화살촉 방향. */
export function arrowDirection(control: Point, to: Point): Point {
  const d: Point = [to[0] - control[0], to[1] - control[1], to[2] - control[2]]
  const length = Math.hypot(...d) || 1
  return [d[0] / length, d[1] / length, d[2] / length]
}
