// 엑셀 가져오기 품질 리포트를 화면 줄로(docs/input.md(엑셀 양식) 2절): 오류 먼저, 그다음 경고. 줄마다 시트 · 행 · 열을 앞에 두어
// 원본 엑셀에서 바로 찾게 한다. 길면 앞의 몇 줄만 보이고 나머지는 개수로.
import type { ImportIssue, ImportSummary, SnapshotInfo } from '@/api/client'

export interface IssueLine {
  where: string
  message: string
}

export interface Report {
  errors: IssueLine[]
  warnings: IssueLine[]
}

/** 원본 엑셀에서 찾을 위치: 파일 시트 · 행 · 파일 머리글(양식 열 이름과 다르면 파일에 적힌 이름). */
export function issueWhere(issue: ImportIssue): string {
  const column = issue.file_column ?? issue.column ?? null
  const parts = [issue.sheet ? `'${issue.sheet}' 시트` : null, issue.row ? `${issue.row}행` : null, column]
  return parts.filter(Boolean).join(' · ') || '파일'
}

export function reportOf(summary: ImportSummary): Report {
  const line = (issue: ImportIssue): IssueLine => ({ where: issueWhere(issue), message: issue.message })
  return {
    errors: summary.issues.filter((i) => i.severity === 'error').map(line),
    warnings: summary.issues.filter((i) => i.severity === 'warning').map(line),
  }
}

/** 앞에서 limit줄과 남은 개수. */
export function head<T>(items: T[], limit: number): { shown: T[]; rest: number } {
  return { shown: items.slice(0, limit), rest: Math.max(0, items.length - limit) }
}

/** 지도에 든 것: 호선 · 블록 · 부재 · 발주 · 공정 수. */
export function countsText(info: SnapshotInfo): string {
  const c = info.counts
  const n = (value: number) => value.toLocaleString('ko-KR')
  return `호선 ${n(c.ships)} · 블록 ${n(c.blocks)} · 부재 ${n(c.parts)} · 발주 ${n(c.purchase_orders)} · 공정 ${n(c.activities)}`
}
