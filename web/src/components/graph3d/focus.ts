// 엔터티 → 3D 이동 대상(순수 함수, focus.test.ts가 검사). 영향 목록·근거 패널·명령 팔레트에서 엔터티를 고르면 3D가
// 그 블록으로 날아가 맞추고(블록 하나), 블록을 정할 수 없으면 카메라를 두고 관련 블록만 잠깐 강조한다.
//
// 1. 블록이 정해지는 엔터티 — 2D와 같은 규칙(blocks.ts blockIdOf): 블록 노드 · `block_id` 속성(부재) · 블록 공정
//    ("S-001:B31P:erection"). 재고는 `reserved_block_id`(예약한 블록).
// 2. 자기 블록 속성이 없는 도면·발주 품목·발주·재고는 분석 결과 지도의 연결(drawn_in · supplied_by · consumed_by 등)을 따라
//    가장 가까운 단계(1단계, 없으면 2단계)에서 블록이 정해지는 이웃의 블록을 모은다. 하나면 그 블록, 여럿이면 관련 블록 강조.
// 3. 그 밖(구역·호선·구역 출구 같은 마일스톤)은 블록 하나로 정하지 않는다 — 이웃 블록이 있으면 강조만, 없으면 '배치 위치 없음'.
// 배치 표에 없는 블록(사용자 엑셀 지도 등)은 그릴 자리가 없으니 대상에서 뺀다.
import type { GraphNode, ImpactView } from '@/api/client'
import { codeOf } from '@/lib/labels'
import { blockIdOf } from './blocks'
import { BLOCK_LAYOUT, SHIP_ID } from './layout'

export type FocusTarget =
  /** 그 블록으로 카메라 이동 + 강조. */
  | { kind: 'block'; code: string }
  /** 블록 하나로 정할 수 없음 — 카메라는 그대로, 관련 블록(코드 순)만 잠깐 강조. */
  | { kind: 'blocks'; codes: string[] }
  /** 배치 위치 없음. */
  | { kind: 'none' }

const PLACED_IDS = new Set(BLOCK_LAYOUT.map((block) => `${SHIP_ID}:${block.code}`))
/** 자기 블록 속성은 없지만 연결로 블록 하나가 정해질 수 있는 종류. */
const INFERRED = new Set(['drawing', 'po_line', 'po', 'stock'])
const NONE: FocusTarget = { kind: 'none' }

/** 노드 자체로 정해지는 블록 ID(blockIdOf + 재고 예약 블록). */
function ownBlock(node: GraphNode, blocks: ReadonlySet<string>): string | null {
  const own = blockIdOf(node, blocks)
  if (own) return own
  const reserved = node.attrs?.reserved_block_id
  return typeof reserved === 'string' && reserved ? reserved : null
}

/** 연결을 따라 가장 가까운 단계(최대 2단계)에서 블록이 정해지는 이웃들의 배치 표 블록 코드(코드 순). */
function nearbyBlocks(report: ImpactView, start: string, blocks: ReadonlySet<string>): string[] {
  const nodes = new Map(report.graph.nodes.map((node) => [node.id, node]))
  const links = new Map<string, string[]>()
  for (const edge of report.graph.edges) {
    links.set(edge.source, [...(links.get(edge.source) ?? []), edge.target])
    links.set(edge.target, [...(links.get(edge.target) ?? []), edge.source])
  }
  const seen = new Set([start])
  let frontier = [start]
  for (let depth = 0; depth < 2 && frontier.length > 0; depth += 1) {
    const found = new Set<string>()
    const next: string[] = []
    for (const id of frontier) {
      for (const other of links.get(id) ?? []) {
        if (seen.has(other)) continue
        seen.add(other)
        const node = nodes.get(other)
        const block = node ? ownBlock(node, blocks) : null
        if (block) found.add(block)
        else next.push(other)
      }
    }
    const placed = [...found].filter((id) => PLACED_IDS.has(id)).map(codeOf)
    if (found.size > 0) return [...new Set(placed)].sort()
    frontier = next
  }
  return []
}

export function focusOf(report: ImpactView, id: string | null): FocusTarget {
  if (!id) return NONE
  const blocks = new Set(report.graph.nodes.filter((node) => node.type === 'block').map((node) => node.id))
  const node = report.graph.nodes.find((n) => n.id === id)
  if (!node) return PLACED_IDS.has(id) ? { kind: 'block', code: codeOf(id) } : NONE
  const own = ownBlock(node, blocks)
  if (own) return PLACED_IDS.has(own) ? { kind: 'block', code: codeOf(own) } : NONE
  const near = nearbyBlocks(report, id, blocks)
  if (near.length === 0) return NONE
  if (near.length === 1 && INFERRED.has(node.type)) return { kind: 'block', code: near[0] }
  return { kind: 'blocks', codes: near }
}

/** 고른 엔터티의 블록 코드(블록 하나로 정해질 때만 — 외곽선·이음면·좁은 화면 요약에 쓴다). */
export function selectedBlock(report: ImpactView, selected: string | null): string | null {
  const target = focusOf(report, selected)
  return target.kind === 'block' ? target.code : null
}

/** 블록을 정할 수 없을 때의 짧은 안내(명사형). */
export function focusNotice(target: FocusTarget): string | null {
  if (target.kind === 'none') return '배치 위치 없음'
  if (target.kind === 'blocks') return `배치 위치 여러 블록 · ${target.codes.join(' · ')}`
  return null
}
