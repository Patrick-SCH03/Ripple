import { describe, expect, it } from 'vitest'
import type { CostLine } from '@/api/client'
import { commonTail, groupLines } from './costGroups'

const line = (id: string, rule: string, label: string, value: number, low = value, high = value): CostLine =>
  ({ line_id: id, rule_id: rule, label, amount: { value, low, high } }) as unknown as CostLine

describe('비용 줄 묶기', () => {
  it('같은 끝말: 낱말 단위로, 없으면 빈 글', () => {
    expect(commonTail(['No.3 COT 이중저 좌 판 1 테이퍼 가공', '중심선 종격벽 판 5 테이퍼 가공'])).toBe('테이퍼 가공')
    expect(commonTail(['PO-0037#1 발주 변경·취소', 'PO-0040#2 발주 변경·취소'])).toBe('발주 변경·취소')
    expect(commonTail(['판 1 자재비', '판 1 테이퍼 가공'])).toBe('')
    expect(commonTail(['테이퍼 가공', '판 1 테이퍼 가공'])).toBe('테이퍼 가공')
    expect(commonTail(['도면 개정', '도면 개정', '도면 개정'])).toBe('도면 개정')
  })

  it('같은 규칙 3줄 이상 = 한 묶음(합계·범위 합, 행은 묶음 합까지 넣어 금액 큰 순), 2줄 이하·끝말 없음은 줄 그대로 — 행 금액 합 = 줄 금액 합', () => {
    const sorted = [
      line('a', 'R-REWORK', 'B31P 블록 재작업 — 직영', 2790),
      line('b', 'R-REWORK', 'L31C 블록 재작업 — 직영', 172),
      line('g', 'R-DWG', '도면 개정', 20),
      line('c', 'R-TAPER', '판 7 테이퍼 가공', 10, 4, 24),
      line('d', 'R-MAT', '판 2 자재비 차이', 9),
      line('e', 'R-TAPER', '판 1 테이퍼 가공', 10, 4, 24),
      line('f', 'R-TAPER', '종격벽 판 5 테이퍼 가공', 10, 4, 24),
    ]
    const rows = groupLines(sorted)
    expect(rows.map((row) => (row.kind === 'line' ? row.line.line_id : `G:${row.group.label}`))).toEqual([
      'a',
      'b',
      'G:테이퍼 가공',
      'g',
      'd',
    ])
    const group = rows[2].kind === 'group' ? rows[2].group : null
    expect(group?.amount).toEqual({ value: 30, low: 12, high: 72 })
    expect(group?.lines.map((l) => l.line_id)).toEqual(['c', 'e', 'f'])
    const total = (rs: typeof rows) =>
      rs.reduce((sum, row) => sum + (row.kind === 'line' ? row.line.amount.value : row.group.amount.value), 0)
    expect(total(rows)).toBe(sorted.reduce((sum, l) => sum + l.amount.value, 0))
    expect(groupLines([])).toEqual([])
  })
})
