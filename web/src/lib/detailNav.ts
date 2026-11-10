// 상세 구역 이동 막대의 계산(DESIGN.md 2절): 구역 목록 · 건수 · 지금 보는 구역.
import type { AnalysisResult } from '@/api/client'
import { todos } from '@/lib/summary'

export interface DetailNavItem {
  id: string
  label: string
  /** 이름 옆 작은 숫자(건수). 0·없음이면 쓰지 않는다. */
  count?: number
}

/** 구역 id: 막대·카드·시연 대본이 같은 값을 쓴다. */
export const DETAIL_SECTION_IDS = {
  summary: 'detail-summary',
  impact: 'detail-impact',
  actions: 'detail-actions',
  evidence: 'detail-evidence',
} as const

/** 할 일 구역의 조치 묶음에 그릴 것이 있는가(조치·현장 상태·결재 안내 중 하나라도). */
export function hasActions(result: AnalysisResult, approval: string | null): boolean {
  return todos(result).length > 0 || (result.state_basis ?? []).length > 0 || approval !== null
}

/** 막대 항목. 할 일 구역이 없으면(조치·현장 상태·사전 점검·결재 안내 모두 없음) 빼고, 할 일 건수는 조치 수. */
export function detailNavItems(result: AnalysisResult, hasActions: boolean): DetailNavItem[] {
  return [
    { id: DETAIL_SECTION_IDS.summary, label: '판단 요약' },
    { id: DETAIL_SECTION_IDS.impact, label: '영향 범위' },
    ...(hasActions ? [{ id: DETAIL_SECTION_IDS.actions, label: '할 일', count: todos(result).length }] : []),
    { id: DETAIL_SECTION_IDS.evidence, label: '근거 상세' },
  ]
}

/** 스크롤 칸 안에서 머리가 기준선(막대 아래)을 지난 마지막 구역 = 지금 보는 구역. 끝까지 내리면 마지막 구역. */
export function currentSection(
  tops: readonly { id: string; top: number }[],
  line: number,
  atBottom: boolean,
): string | null {
  if (tops.length === 0) return null
  if (atBottom) return tops[tops.length - 1]!.id
  let current = tops[0]!.id
  for (const { id, top } of tops) if (top <= line) current = id
  return current
}
