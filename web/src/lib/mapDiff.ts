// 상태 갱신으로 바뀌는 것(MapDiff)을 한 줄씩(상태 올리기 미리보기, docs/domain.md 12절): 단계 변화 · 납기(계획 열) 전후 ·
// 공정 실적. 값이 그대로인 확인은 줄로 싣지 않고 개수만 따로 보인다.
import type { UpdatePreview } from '@/api/client'
import { formatDay } from './format'
import { PO_STATUS_NAMES, activityName } from './labels'

type MapDiff = UpdatePreview['diff']

const PLAN_NAMES: Record<string, string> = {
  planned_order_date: '계획 발주일',
  material_secured_days: '자재 확보까지',
  fabrication_start_days: '제작 착수까지',
  lead_time_days: '입고까지(납기)',
}

function planValue(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '없음'
  return typeof value === 'number' ? `${value}일` : formatDay(value)
}

export function diffLines(diff: MapDiff): string[] {
  const lines: string[] = []
  for (const change of diff.status_changed ?? []) {
    const before = change.before ? PO_STATUS_NAMES[change.before] : '기록 없음'
    lines.push(`${change.po_id} ${before} → ${PO_STATUS_NAMES[change.after]}`)
  }
  for (const change of diff.plan_changed ?? []) {
    lines.push(`${change.po_id} ${PLAN_NAMES[change.field] ?? change.field} ${planValue(change.before)} → ${planValue(change.after)}`)
  }
  for (const change of diff.activities ?? []) {
    const parts = [
      change.started && `실제 착수 ${formatDay(change.started)}`,
      change.finished && `실제 완료 ${formatDay(change.finished)}`,
    ].filter(Boolean)
    lines.push(`${activityName(change.activity_id)} ${parts.join(' · ')}`)
  }
  return lines
}
