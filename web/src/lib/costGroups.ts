// 비용 탭 줄 묶기(DESIGN.md 6절): 같은 규칙의 줄이 여럿이면('판 1 테이퍼 가공' · '판 3 테이퍼 가공' …) 한 줄로 묶어 상세가
// 길어지지 않게 한다 — 묶음 이름은 줄 이름들의 같은 끝말('테이퍼 가공'), 금액은 줄 금액의 합(범위도 합). 숫자는 결과의 줄
// 금액 그대로 더할 뿐 새 계산은 없다. 행 순서는 묶음 합계까지 넣어 다시 금액 큰 순.
import type { CostLine } from '@/api/client'

/** 이 수 이상이면 묶는다(둘은 '직영 · 작업반'처럼 서로 다른 블록 재작업이라 따로 둔다). */
const GROUP_MIN = 3

export interface CostGroup {
  /** 규칙 ID(펼침 상태 열쇠). */
  key: string
  /** 줄 이름들의 같은 끝말. */
  label: string
  lines: CostLine[]
  amount: { value: number; low: number; high: number }
}

export type CostRow = { kind: 'line'; line: CostLine } | { kind: 'group'; group: CostGroup }

/**
 * 이름들의 같은 끝 낱말들('… 판 1 테이퍼 가공', '… 판 5 테이퍼 가공' → '테이퍼 가공'). 한 이름 전체가 끝말이면 그 이름
 * 그대로('도면 개정' 셋 → '도면 개정'). 없으면 ''.
 */
export function commonTail(labels: readonly string[]): string {
  const words = labels.map((label) => label.trim().split(/\s+/))
  const tail: string[] = []
  for (let k = 1; words.every((w) => w.length >= k); k += 1) {
    const word = words[0][words[0].length - k]
    if (!words.every((w) => w[w.length - k] === word)) break
    tail.unshift(word)
  }
  return tail.join(' ')
}

/**
 * 금액 큰 순으로 정렬된 줄 → 표의 행. 같은 규칙(rule_id) 줄이 GROUP_MIN개 이상이고 이름에 같은 끝말이 있으면 한 묶음,
 * 아니면 줄 그대로. 행은 금액(묶음은 합) 큰 순, 묶음 안 줄 순서는 들어온 순서.
 */
export function groupLines(sorted: readonly CostLine[]): CostRow[] {
  const byRule = new Map<string, CostLine[]>()
  for (const line of sorted) byRule.set(line.rule_id, [...(byRule.get(line.rule_id) ?? []), line])
  const rows: CostRow[] = []
  const placed = new Set<string>()
  for (const line of sorted) {
    const same = byRule.get(line.rule_id) ?? [line]
    const label = same.length >= GROUP_MIN ? commonTail(same.map((l) => l.label)) : ''
    if (!label) {
      rows.push({ kind: 'line', line })
      continue
    }
    if (placed.has(line.rule_id)) continue
    placed.add(line.rule_id)
    const sum = (pick: (l: CostLine) => number) => same.reduce((total, l) => total + pick(l), 0)
    rows.push({
      kind: 'group',
      group: {
        key: line.rule_id,
        label,
        lines: same,
        amount: { value: sum((l) => l.amount.value), low: sum((l) => l.amount.low), high: sum((l) => l.amount.high) },
      },
    })
  }
  // 묶음 금액(합)으로 다시 금액 큰 순 — 같으면 들어온 순서(정렬은 안정)
  const value = (row: CostRow) => (row.kind === 'line' ? row.line.amount.value : row.group.amount.value)
  return rows.sort((a, b) => value(b) - value(a))
}
