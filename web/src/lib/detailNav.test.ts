import { describe, expect, it } from 'vitest'
import type { AnalysisResult } from '@/api/client'
import { currentSection, DETAIL_SECTION_IDS, detailNavItems, hasActions } from './detailNav'

// 조치(todos)를 셀 때 읽는 칸만 둔 결과: 조치 없음
const result = (over: Record<string, unknown> = {}) =>
  ({
    request: { holds: [] },
    timing: { holds: [], reallocations: [] },
    onboard: null,
    cost_lines: [],
    state_basis: [],
    ...over,
  }) as unknown as AnalysisResult

describe('상세 구역 이동 막대', () => {
  it('구역 순서: 판단 요약 → 영향 범위 → 할 일 → 근거 상세, 할 일이 없으면 뺌', () => {
    expect(detailNavItems(result(), true).map((item) => item.id)).toEqual([
      DETAIL_SECTION_IDS.summary,
      DETAIL_SECTION_IDS.impact,
      DETAIL_SECTION_IDS.actions,
      DETAIL_SECTION_IDS.evidence,
    ])
    expect(detailNavItems(result(), false).map((item) => item.label)).toEqual(['판단 요약', '영향 범위', '근거 상세'])
  })

  it('할 일 묶음: 현장 상태나 결재 안내만 있어도 그림, 아무것도 없으면 안 그림', () => {
    expect(hasActions(result(), null)).toBe(false)
    expect(hasActions(result(), '결재선 파트장 → 팀장')).toBe(true)
    expect(hasActions(result({ state_basis: [{}] }), null)).toBe(true)
    expect(detailNavItems(result({ timing: { holds: [{}], reallocations: [] } }), true)[2]?.count).toBe(1)
  })

  it('지금 보는 구역 = 머리가 기준선을 지난 마지막 구역, 끝까지 내리면 마지막 구역', () => {
    const tops = [
      { id: 'a', top: -400 },
      { id: 'b', top: 40 },
      { id: 'c', top: 600 },
    ]
    expect(currentSection(tops, 72, false)).toBe('b')
    expect(currentSection(tops.map((t) => ({ ...t, top: t.top + 500 })), 72, false)).toBe('a')
    expect(currentSection(tops, 72, true)).toBe('c')
    expect(currentSection([], 72, false)).toBeNull()
  })
})
