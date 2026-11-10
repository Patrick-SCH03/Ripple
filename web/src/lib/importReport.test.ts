import { describe, expect, it } from 'vitest'
import type { ImportSummary, SnapshotInfo } from '@/api/client'
import { countsText, head, issueWhere, reportOf } from './importReport'

const summary: ImportSummary = {
  template_version: 'excel-v1',
  file: 'plant.xlsx',
  snapshot_id: null,
  counts: {},
  missing_sheets: ['stock'],
  issues: [
    { severity: 'warning', code: 'missing_sheet', sheet: '재고', message: '재고를 몰라 재고 충당을 계산하지 않아요.' },
    { severity: 'error', code: 'missing_value', sheet: '부재', row: 12, column: '두께(mm)', message: '값이 비었어요.' },
    { severity: 'error', code: 'bad_value', message: '파일 전체 문제' },
    {
      severity: 'error',
      code: 'bad_value',
      sheet: 'BOM',
      row: 5,
      column: '두께',
      file_column: 'THK',
      message: '두께 값이 상식 범위 밖이에요.',
    },
    { severity: 'warning', code: 'ignored_column', sheet: 'BOM', row: 1, file_column: '비고', message: '읽지 않았어요.' },
  ],
}

describe('품질 리포트 줄', () => {
  it('위치는 시트 · 행 · 열 순서, 없으면 파일', () => {
    expect(issueWhere(summary.issues[1]!)).toBe("'부재' 시트 · 12행 · 두께(mm)")
    expect(issueWhere(summary.issues[0]!)).toBe("'재고' 시트")
    expect(issueWhere(summary.issues[2]!)).toBe('파일')
  })

  it('파일 머리글이 양식 열 이름과 다르면 파일에 적힌 이름으로 짚음(무시한 열은 파일 머리글만)', () => {
    expect(issueWhere(summary.issues[3]!)).toBe("'BOM' 시트 · 5행 · THK")
    expect(issueWhere(summary.issues[4]!)).toBe("'BOM' 시트 · 1행 · 비고")
  })

  it('오류와 확인할 것(경고)을 나누고 원래 순서를 지킴', () => {
    const report = reportOf(summary)
    expect(report.errors.map((line) => line.message)).toEqual([
      '값이 비었어요.',
      '파일 전체 문제',
      '두께 값이 상식 범위 밖이에요.',
    ])
    expect(report.warnings).toHaveLength(2)
  })

  it('길면 앞의 몇 줄과 남은 개수', () => {
    expect(head([1, 2, 3, 4, 5], 3)).toEqual({ shown: [1, 2, 3], rest: 2 })
    expect(head([1], 3)).toEqual({ shown: [1], rest: 0 })
  })

  it('지도에 든 것 한 줄(천 단위 쉼표)', () => {
    const info = {
      counts: { ships: 1, blocks: 14, parts: 1234, purchase_orders: 100, activities: 120 },
    } as SnapshotInfo
    expect(countsText(info)).toBe('호선 1 · 블록 14 · 부재 1,234 · 발주 100 · 공정 120')
  })
})
