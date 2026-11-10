// 발주 조치 요약(docs/engine.md(비용·일정) 4-10): 분석 결과의 비용 줄·보류 권고를 발주 품목별 '해야 할 조치'로 다시 읽는다.
// 새 계산 없음 — 줄 ID(`규칙:영향 종류:엔터티`)와 inputs.stage, 보류 권고의 line_ids만 쓴다.
import type { AnalysisResult } from '@/api/client'
import { PO_STATUS_NAMES } from '@/lib/labels'

export type PoActionKind = 'change' | 'reduce' | 'reorder' | 'reallocate' | 'stock' | 'hold'

export interface PoAction {
  kind: PoActionKind
  text: string
  amount: number
}

export interface PoActionRow {
  lineId: string
  stage: string | null
  actions: PoAction[]
  total: number
}

const KIND_ORDER: PoActionKind[] = ['change', 'reduce', 'reorder', 'reallocate', 'stock', 'hold']

function stageName(stage: unknown): string | null {
  return typeof stage === 'string' ? (PO_STATUS_NAMES[stage] ?? stage) : null
}

/**
 * 새 규격 발주 줄의 조치 문구: 단계로 가른다(할증 0원은 발주 전일 수도, 재고로 다 채운 것일 수도 있어 금액으로 가르지 않음).
 * 단계를 모르면(판단 불가 줄) 그렇게 적는다.
 */
function reorderText(stage: unknown, value: number): string {
  if (stage === 'not_ordered') return '발주 전 · 규격만 수정해 발주'
  if (typeof stage !== 'string') return '새 규격 다시 발주(확정일 단계 판단 불가)'
  return value > 0 ? '새 규격 긴급 재발주(할증)' : '새 규격 다시 발주(재고로 채워 할증 없음)'
}

/** 발주 품목별 조치 줄(품목 ID 순). 조치가 하나도 없으면 빈 배열. */
export function poActions(result: AnalysisResult): PoActionRow[] {
  const rows = new Map<string, PoActionRow>()
  const row = (lineId: string): PoActionRow => {
    let found = rows.get(lineId)
    if (!found) {
      found = { lineId, stage: null, actions: [], total: 0 }
      rows.set(lineId, found)
    }
    return found
  }
  const add = (lineId: string, action: PoAction, stage?: unknown) => {
    const r = row(lineId)
    r.actions.push(action)
    r.total += action.amount
    r.stage ??= stageName(stage)
  }
  for (const line of result.cost_lines) {
    const [rule, kind, ...rest] = line.line_id.split(':')
    const value = line.amount.value
    if (kind === 'po_change' && (rule === 'R-T01' || rule === 'R-M02')) {
      const text = rule === 'R-T01' ? '기존 발주 변경·취소' : '빼는 부재만큼 발주 감축·취소'
      add(line.entity_id, { kind: rule === 'R-T01' ? 'change' : 'reduce', text, amount: value }, line.inputs.stage)
    } else if (kind === 'reorder') {
      add(line.entity_id, { kind: 'reorder', text: reorderText(line.inputs.stage, value), amount: value }, line.inputs.stage)
    } else if (rule === 'R-M01' && kind === 'handling') {
      const [source, target] = rest
      add(source, { kind: 'reallocate', text: `잉여 자재를 ${target}로 전용`, amount: value })
    } else if (rule === 'R-M01' && kind === 'stock') {
      const [lot] = rest
      add(lot, { kind: 'stock', text: '같은 규격 재고로 새 자재 충당', amount: value })
    }
  }
  for (const hold of result.timing.holds) {
    for (const lineId of hold.line_ids.length > 0 ? hold.line_ids : [hold.po_id]) {
      add(lineId, { kind: 'hold', text: `확정 전까지 최대 ${hold.max_hold_days}일 보류 권고`, amount: 0 })
    }
  }
  for (const r of rows.values()) r.actions.sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind))
  return [...rows.values()].sort((a, b) => a.lineId.localeCompare(b.lineId))
}
