// 상세 첫 화면의 핵심 수치 순서와 '이미 발주된 품목' 카드(DESIGN.md 6절, 현직자가 가장 먼저 보는 것은
// 결정 기한과 발주 완료 품목). 숫자는 분석 결과의 발주 영향(발주 품목 영향)과 그 비용 줄의 확정일 단계(inputs.stage)에서만
// 센다 — 새 계산 없음. 비용 탭 '발주 조치'(lib/poActions)와 같은 단계 값을 쓴다.
import type { AnalysisResult } from '@/api/client'
import { PO_STATUS_NAMES, PO_STATUS_ORDER } from './labels'
import { keyNumbers, type KeyNumber } from './summary'

/** 단계 한 묶음: 단계 코드(모르면 null) · 이름 · 품목 수. */
export interface OrderedStage {
  stage: string | null
  label: string
  count: number
}

export interface OrderedItems {
  /** 확정일에 이미 발주가 나간(미발주가 아닌) 품목 수. 단계를 모르는 품목은 넣지 않는다. */
  ordered: number
  /** 단계별 건수: 많이 진행된 단계부터(늦을수록 손실이 큰 쪽이 앞). */
  stages: OrderedStage[]
  /** 확정일 단계를 판단하지 못한 품목 수. */
  unknown: number
}

/** 발주 품목 → 확정일 단계(그 품목 비용 줄의 inputs.stage). 줄이 없거나 단계가 없으면 null. */
function stageOf(result: AnalysisResult, lineId: string): string | null {
  for (const line of result.cost_lines) {
    const stage = line.inputs.stage
    if (line.entity_id === lineId && typeof stage === 'string') return stage
  }
  return null
}

/** 기존 발주를 바꾸는 영향(변경·취소 · 새 규격 발주). 보류 권고(po_hold)는 아직 발주 전인 품목에도 붙어 세지 않는다. */
const ORDER_IMPACTS = new Set(['po_change', 'reorder'])

/** 이 변경이 바꾸는 발주 품목(발주 변경·취소 · 새 규격 발주 영향)을 확정일 단계로 센다. 그런 영향이 없으면 null. */
export function orderedItems(result: AnalysisResult): OrderedItems | null {
  const touched = result.impacts.filter((i) => i.entity_type === 'po_line' && ORDER_IMPACTS.has(i.impact_type))
  const ids = [...new Set(touched.map((i) => i.entity_id))]
  if (ids.length === 0) return null
  const counts = new Map<string, number>()
  let unknown = 0
  for (const id of ids) {
    const stage = stageOf(result, id)
    if (stage === null) unknown += 1
    else if (stage !== 'not_ordered') counts.set(stage, (counts.get(stage) ?? 0) + 1)
  }
  const rank = (stage: string) => {
    const at = PO_STATUS_ORDER.indexOf(stage)
    return at < 0 ? PO_STATUS_ORDER.length : at
  }
  const stages = [...counts.entries()]
    .sort(([a], [b]) => rank(b) - rank(a) || a.localeCompare(b))
    .map(([stage, count]) => ({ stage, label: PO_STATUS_NAMES[stage] ?? stage, count }))
  const ordered = stages.reduce((sum, s) => sum + s.count, 0)
  return { ordered, stages, unknown }
}

/** '이미 발주된 품목' 카드: 발주가 나간 품목이나 단계를 모르는 품목이 있을 때만(모두 미발주면 내지 않음). */
export function orderedCard(result: AnalysisResult): KeyNumber | null {
  const items = orderedItems(result)
  if (!items || (items.ordered === 0 && items.unknown === 0)) return null
  return {
    id: 'ordered',
    label: '이미 발주된 품목',
    value: `${items.ordered}건`,
    detail: items.stages.length > 0 ? items.stages.map((s) => `${s.label} ${s.count}`).join(' · ') : undefined,
    caution: items.unknown > 0 ? `발주 단계 판단 불가 ${items.unknown}건` : undefined,
    tone: 'neutral',
  }
}

/**
 * 상세 첫 화면의 핵심 수치 순서: 결정 기한 → 이미 발주된 품목 → 총변경비용 → 구역 출구 → 인도.
 * 리포트·검토 요청 창·요약 복사는 keyNumbers 순서 그대로 쓴다(값은 같다).
 */
export function detailNumbers(result: AnalysisResult): KeyNumber[] {
  const cards = keyNumbers(result)
  const deadline = cards.filter((card) => card.id === 'deadline')
  const ordered = orderedCard(result)
  return [...deadline, ...(ordered ? [ordered] : []), ...cards.filter((card) => card.id !== 'deadline')]
}
