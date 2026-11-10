// 대안 탭 계산(docs/engine.md(대안)): 판정 이름, 대안 줄 순서, 권고 문장, 날짜별 최저 비용 대안 문장, 연산 요약.
// 숫자는 모두 분석 결과 필드에서 온다(DESIGN.md 10절).
import type { AnalysisRequest, AnalysisResult } from '@/api/client'
import { formatDay } from './format'
import { formatMoney } from './money'

type Alternative = AnalysisResult['alternatives'][number]
type Span = AnalysisResult['cheapest_by_date'][number]
type Eligibility = Alternative['eligibility']['status']
type ChangeOp = Alternative['ops'][number]

export const REQUEST_ALT = 'ALT-REQ'

/**
 * 대안 결과를 기억하는 키: 분석 ID + 변경 사유. 분석 ID는 대안을 끈 분석이라 사유가 빠져 있는데(분석 뒤 사유를 기록해도
 * 같음), 대안 판정은 사유에 따라 달라 사유가 바뀌면 다시 계산해야 한다.
 */
export function alternativesKey(result: Pick<AnalysisResult, 'analysis_id' | 'request'>): string {
  return `${result.analysis_id}|${result.request.change.intent ?? 'none'}`
}

/**
 * 엔진이 대안을 만들 수 있는 요청인가(engine/alternatives/templates `plan`과 같은 조건): 연산 하나 · 판 두께·강종·보강재 추가 ·
 * 변경 사유가 강도 보강이거나 없음. 아니면 권고 대안 띠가 대안 포함 분석(기본 분석을 통째로 한 번 더)을 보내지 않는다.
 */
export function mayHaveAlternatives(request: Pick<AnalysisRequest, 'change'>): boolean {
  const { ops, intent } = request.change
  return (
    ops.length === 1 &&
    ['thickness', 'grade', 'add_part'].includes(ops[0].op) &&
    (intent == null || intent === 'strength')
  )
}

export const ELIGIBILITY_NAMES: Record<Eligibility, string> = {
  meets: '충족(예비)',
  short: '부족',
  designer: '설계자 확인',
}

export const ELIGIBILITY_TONES: Record<Eligibility, 'success' | 'danger' | 'warning'> = {
  meets: 'success',
  short: 'danger',
  designer: 'warning',
}

/** 표 순서: 요청안 → 충족(순위) → 부족·설계자 확인(총액 작은 순). */
export function sortedAlternatives(alternatives: readonly Alternative[]): Alternative[] {
  const rest = alternatives.filter((a) => a.alt_id !== REQUEST_ALT)
  const ranked = rest.filter((a) => a.rank != null).sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0))
  const others = rest
    .filter((a) => a.rank == null)
    .sort((a, b) => a.total.value - b.total.value || a.alt_id.localeCompare(b.alt_id))
  const request = alternatives.filter((a) => a.alt_id === REQUEST_ALT)
  return [...request, ...ranked, ...others]
}

/** 대안을 보일 게 있는가(요청안 하나뿐이면 '대안 없음' 안내). */
export function hasAlternatives(result: Pick<AnalysisResult, 'alternatives'>): boolean {
  return result.alternatives.length > 1
}

/** 판정 근거 한 줄: 요청안 대비 강도 여유 비율. 판정하지 않은 대안은 null. */
export function ratioText(alternative: Alternative): string | null {
  const ratio = alternative.eligibility.ratio_vs_request
  if (ratio == null || alternative.alt_id === REQUEST_ALT) return null
  return `요청안 대비 강도 여유 ${ratio.toFixed(2)}배`
}

export interface Headline {
  title: string
  detail: string
}

/** 권고 카드: 최저 비용 조합과 요청안 대비 차이, 그 대안을 언제까지 확정하면 되는지. */
export function recommendationHeadline(result: Pick<AnalysisResult, 'alternatives' | 'recommendation'>): Headline | null {
  const rec = result.recommendation
  if (!rec) return null
  const chosen = result.alternatives.find((a) => a.alt_id === rec.alt_id)
  const request = result.alternatives.find((a) => a.alt_id === REQUEST_ALT)
  if (!chosen || !request) return null
  const holds =
    rec.holds.length > 0 ? ` · 발주 ${rec.holds.map((h) => `${h.po_id} ${h.hold_days}일`).join('·')} 보류 포함` : ''
  if (chosen.alt_id === REQUEST_ALT) {
    return {
      title: '요청안이 최저가',
      detail: `${formatDay(rec.confirm_on)} 확정 시 ${formatMoney(rec.total.value)}${holds}`,
    }
  }
  const base = request.best_total ?? request.total
  const saving = base.value - rec.total.value
  return {
    title: `${chosen.label}`,
    detail:
      `${formatDay(rec.confirm_on)} 확정 시 ${formatMoney(rec.total.value)} · ` +
      `요청안(${formatMoney(base.value)})보다 ${formatMoney(saving)} 적음${holds}`,
  }
}

/** 확정일을 기준일보다 늦게 잡았을 때: 그 전에는 확정할 수 없다고 보고 그날부터 골랐다는 안내. 아니면 null. */
export function earliestText(request: Pick<AnalysisRequest, 'as_of' | 'confirm_on'>): string | null {
  if (!request.confirm_on || request.confirm_on <= request.as_of) return null
  return `${formatDay(request.confirm_on)} 전 확정 불가로 보고 그날부터 최저가 조합 선택`
}

/** 대안의 추가손실 0 마감일 문장(그 금액을 언제까지 지킬 수 있는지). */
export function keepUntilText(alternative: Pick<Alternative, 'deadline'>): string | null {
  const deadline = alternative.deadline
  if (!deadline) return null
  if (deadline.kind === 'confirm_now') return '오늘 확정해야 이 금액'
  if (deadline.kind === 'none_in_horizon') return `${formatDay(deadline.last_day)}까지 늦게 확정해도 금액 그대로`
  return `${formatDay(deadline.last_day)}까지 확정 시 금액 그대로`
}

/**
 * 권고 카드의 마감일 문장: 권고 확정일이 그 대안의 추가손실 0 마감일 안일 때만. 확정 가능일이 마감일 뒤면
 * ('10월 30일 전에는 확정할 수 없다'인데 '10월 23일까지 확정하면 그대로') 앞뒤가 맞지 않아 뺀다.
 */
export function recommendationKeepText(result: Pick<AnalysisResult, 'alternatives' | 'recommendation'>): string | null {
  const rec = result.recommendation
  const chosen = rec ? result.alternatives.find((a) => a.alt_id === rec.alt_id) : undefined
  if (!rec || !chosen?.deadline || rec.confirm_on > chosen.deadline.last_day) return null
  return keepUntilText(chosen)
}

/**
 * 날짜별 최저 비용 대안 구간의 제목. 구간은 요청에 넣은 보류만 두고(대안의 보류 권고는 더하지 않고) 계산하므로,
 * 보류를 넣었으면 그 보류를 적는다('보류 적용'을 누른 뒤 '보류 없이'라고 하면 틀린 말이 된다).
 */
export function spanTitle(request: Pick<AnalysisRequest, 'holds'>): string {
  if (request.holds.length === 0) return '보류 없이 확정을 미루면'
  return `넣은 보류(${request.holds.map((h) => `발주 ${h.po_id} ${h.hold_days}일`).join('·')}) 그대로 확정을 미루면`
}

/** 날짜별 최저 비용 대안 구간 문장. 구간이 하나면 null(확정을 미뤄도 최저 비용 대안이 같음). */
export function spanSentences(
  spans: readonly Span[],
  labelOf: (altId: string) => string,
): string[] | null {
  if (spans.length < 2) return null
  return spans.map((span, i) => {
    const name = labelOf(span.alt_id)
    const money = formatMoney(span.total.value)
    if (i === 0) return `${formatDay(span.end)}까지 확정 시 ${name} 최저가(기준일 ${money})`
    if (i === spans.length - 1) return `${formatDay(span.start)}부터 ${name} 최저가(${money}부터)`
    return `${formatDay(span.start)}~${formatDay(span.end)} ${name} 최저가(${money}부터)`
  })
}

/** 짧은 대안 이름: 요청안은 '요청안', 나머지는 라벨의 괄호 앞. */
export function shortName(alternative: Pick<Alternative, 'alt_id' | 'label'>): string {
  if (alternative.alt_id === REQUEST_ALT) return '요청안'
  const cut = alternative.label.indexOf('(')
  return cut > 0 ? alternative.label.slice(0, cut) : alternative.label
}

/** 연산 한 줄 요약(펼침 안, 현장 말). */
export function opText(op: ChangeOp): string {
  switch (op.op) {
    case 'thickness':
      return `판 ${op.part_ids.length}장 두께 ${op.from_mm} → ${op.to_mm}mm`
    case 'grade':
      return `${op.part_ids.length}개 강종 ${op.from_grade} → ${op.to_grade}`
    case 'add_part':
      return `보강재 ${op.spec_id} ${op.qty}t 추가`
    default:
      return op.op
  }
}

/** '이 대안으로 분석 보기': 요청의 연산만 대안 연산으로 바꾸고 제목에 대안 이름을 붙인다(대안 판정은 끔). */
export function requestFor(request: AnalysisRequest, alternative: Pick<Alternative, 'ops' | 'label'>): AnalysisRequest {
  return {
    ...request,
    include_alternatives: false,
    change: { ...request.change, title: `${request.change.title} — 대안: ${alternative.label}`, ops: alternative.ops },
  }
}
