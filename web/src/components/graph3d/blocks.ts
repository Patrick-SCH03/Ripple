// 영향 지도 → 3D 배치 블록 상태(순수 함수, blocks.test.ts가 검사). 2D 지도와 같은 데이터(분석 결과의 graph·impacts)를 쓴다.
//
// 노드 → 블록(엔진 describe.py가 내는 값 그대로):
// - 블록 노드(type 'block')는 그 블록.
// - 부재처럼 attrs.block_id가 있으면 그 블록.
// - 공정 ID "S-001:T31C:erection"은 가운데 토막이 블록일 때만(구역 출구 "S-001:ZCT:exit"는 블록이 아님).
// 블록마다 그 블록과 구성 엔터티의 영향 중 가장 높은 심각도를 칠하고, 누르면 블록 노드(없으면 가장 심각한 구성원)를 고른다.
import type { GraphNode, Impact, ImpactView, Severity } from '@/api/client'
import { SEVERITY_RANK, codeOf } from '@/lib/labels'
import { TARGET_ROLES, impactsByEntity, roleOf, topSeverity } from '@/lib/ripple'
import { BLOCK_LAYOUT, SHIP_ID, type ViewName, ZONE_VIEW } from './layout'

export interface BlockState {
  /** 블록 코드("B31P"). */
  code: string
  /** 지도의 블록 ID("S-001:B31P"). */
  blockId: string
  /** 그 블록과 구성 엔터티의 영향 중 가장 높은 심각도(영향이 없으면 null). */
  severity: Severity | null
  /** 그 블록과 구성 엔터티의 영향 수. */
  impacts: number
  /** 바꾸는 부재(대상·빼는·새 부재)를 품었나. */
  target: boolean
  /** 지도에 있는 그 블록 노드와 구성 엔터티 ID(이름 순이 아니라 지도 순). */
  members: string[]
  /** 누르면 고를 엔터티: 블록 노드, 없으면 가장 심각한 구성원. 지도에 없으면 null(누를 수 없음). */
  pick: string | null
}

export interface BlockStates {
  /** 배치 표에 있는 블록(코드 → 상태). 지도에 없는 블록도 영향 없음으로 들어 있다. */
  placed: Map<string, BlockState>
  /** 지도에는 있는데 배치 표에 없는 블록(사용자 엑셀 지도 등) — 그리지 않고 따로 목록으로. */
  unplaced: BlockState[]
}

const PLACED_IDS = new Set(BLOCK_LAYOUT.map((block) => `${SHIP_ID}:${block.code}`))

/** 노드가 속한 블록 ID(블록이 아니면 null). blocks = 지도의 블록 노드 ID(공정 ID를 가를 때 쓴다). */
export function blockIdOf(node: GraphNode, blocks: ReadonlySet<string>): string | null {
  if (node.type === 'block') return node.id
  const owner = node.attrs?.block_id
  if (typeof owner === 'string' && owner) return owner
  if (node.type === 'activity') {
    const parts = node.id.split(':')
    if (parts.length >= 3) {
      const parent = parts.slice(0, -1).join(':')
      if (blocks.has(parent) || PLACED_IDS.has(parent)) return parent
    }
  }
  return null
}

function emptyState(blockId: string): BlockState {
  return { code: codeOf(blockId), blockId, severity: null, impacts: 0, target: false, members: [], pick: null }
}

export function blockStates(report: ImpactView): BlockStates {
  const blockNodes = new Set(report.graph.nodes.filter((node) => node.type === 'block').map((node) => node.id))
  const byEntity = impactsByEntity(report)
  const states = new Map<string, BlockState>()
  for (const id of PLACED_IDS) states.set(id, emptyState(id))
  for (const node of report.graph.nodes) {
    const blockId = blockIdOf(node, blockNodes)
    if (!blockId) continue
    const state = states.get(blockId) ?? emptyState(blockId)
    states.set(blockId, state)
    state.members.push(node.id)
    const impacts = byEntity.get(node.id) ?? []
    state.impacts += impacts.length
    const top = topSeverity(impacts)
    if (top && (!state.severity || SEVERITY_RANK[top] > SEVERITY_RANK[state.severity])) state.severity = top
    if (TARGET_ROLES.has(roleOf(node) ?? '')) state.target = true
  }
  for (const state of states.values()) state.pick = pickOf(state, byEntity)
  const placed = new Map<string, BlockState>()
  const unplaced: BlockState[] = []
  for (const [id, state] of states) {
    if (PLACED_IDS.has(id)) placed.set(state.code, state)
    else unplaced.push(state)
  }
  unplaced.sort((a, b) => (a.blockId < b.blockId ? -1 : a.blockId > b.blockId ? 1 : 0))
  return { placed, unplaced }
}

/** 누르면 고를 엔터티: 블록 노드가 지도에 있으면 그것, 없으면 가장 심각한 구성원(같으면 ID 순 첫째). */
function pickOf(state: BlockState, byEntity: ReadonlyMap<string, Impact[]>): string | null {
  if (state.members.includes(state.blockId)) return state.blockId
  const rank = (id: string) => {
    const top = topSeverity(byEntity.get(id))
    return top ? SEVERITY_RANK[top] + 1 : 0
  }
  const sorted = [...state.members].sort((a, b) => rank(b) - rank(a) || (a < b ? -1 : a > b ? 1 : 0))
  return sorted[0] ?? null
}

/** 블록의 이웃(배치 표 이음 기준). */
export function neighboursOf(code: string, adjacency: readonly (readonly [string, string])[]): string[] {
  return adjacency.flatMap(([a, b]) => (a === code ? [b] : b === code ? [a] : [])).sort()
}

/**
 * 처음 시점: 가장 높은 심각도 블록들이 한 구역에 모여 있으면 그 구역(화물창·선미·선수), 여러 구역이거나 영향 블록이 없으면 전체.
 */
export function initialView(placed: ReadonlyMap<string, BlockState>): ViewName {
  const affected = [...placed.values()].filter((state) => state.severity)
  if (affected.length === 0) return 'whole'
  const top = Math.max(...affected.map((state) => SEVERITY_RANK[state.severity as Severity]))
  const zones = new Set(
    affected
      .filter((state) => SEVERITY_RANK[state.severity as Severity] === top)
      .map((state) => BLOCK_LAYOUT.find((block) => block.code === state.code)?.zone),
  )
  const [zone] = [...zones]
  return zones.size === 1 && zone ? ZONE_VIEW[zone] : 'whole'
}
/**
 * 좌현에서 볼까: 영향 블록의 심각도 합이 좌현(코드 끝 P)이 우현(S)보다 크면 좌현 쪽에서 본다 — 가운데 종격벽이 영향 블록이면
 * 불투명해 반대편 이중저·선측을 가리기 때문이다. 같으면 우현(선수가 오른쪽인 관례).
 */
export function portSide(placed: ReadonlyMap<string, BlockState>): boolean {
  let port = 0
  let stbd = 0
  for (const state of placed.values()) {
    const weight = state.severity ? SEVERITY_RANK[state.severity] + 1 : 0
    if (state.code.endsWith('P')) port += weight
    else if (state.code.endsWith('S')) stbd += weight
  }
  return port > stbd
}