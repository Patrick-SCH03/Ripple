// 파급 그래프 카드의 타입·묶음 판정·문구. 그래프 라이브러리(dagre)가 없어 근거 패널 등 주 묶음에서도 쓴다.
import type { ImpactView, ImpactType, Severity } from '@/api/client'
import { ENTITY_NAMES, IMPACT_NAMES, nameOf, ROLE_NAMES } from './labels'

export interface GraphCard {
  id: string
  /** 묶음이면 구성원 ID(정렬), 아니면 [id]. */
  members: string[]
  layer: number
  type: string
  impact: ImpactType | null
  severity: Severity | null
  role: string | null
  virtual: boolean
  x: number
  y: number
  width: number
  height: number
}

export const isGroup = (id: string): boolean => id.startsWith('group:')

/** 카드 제목과 아래 줄. 묶음은 "대표 영향 · 종류 n개". */
export function cardText(report: ImpactView, card: GraphCard): { title: string; meta: string } {
  const type = nameOf(ENTITY_NAMES, card.type)
  if (isGroup(card.id)) {
    const what = card.impact ? nameOf(IMPACT_NAMES, card.impact) : '영향 없는 연결'
    return { title: `${what} · ${type} ${card.members.length}개`, meta: '묶음' }
  }
  const label = report.graph.nodes.find((n) => n.id === card.id)?.label ?? card.id
  const role = card.role ? ` · ${nameOf(ROLE_NAMES, card.role)}` : ''
  return { title: label, meta: `${type}${role}${card.virtual ? ' · 변경으로 생김' : ''}` }
}
