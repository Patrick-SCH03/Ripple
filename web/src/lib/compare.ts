// 바뀐 점(가정 계산 전후): 보류 적용·빼기나 대안으로 다시 분석했을 때, 바로 전 결과와 새 결과의 판정·총비용·마감일·
// 일정 지연을 나란히 보인다. 숫자는 두 분석 결과 필드에서만 오고, 여기서는 고르고 좋아짐·나빠짐만 가른다.
import type { AnalysisResult, VerdictLevel, ZeroLossDeadline } from '@/api/client'
import { daysBetween, formatDay } from './format'
import { VERDICT_NAMES } from './labels'
import { formatMoney } from './money'
import { deadlineText } from './summary'

export type Direction = 'better' | 'worse' | 'same'

export interface ChangeRow {
  id: 'verdict' | 'total' | 'deadline' | 'later' | 'erection' | 'exit' | 'delivery'
  label: string
  before: string
  after: string
  /** 사람이 읽는 차이(예: '−320만 원', '+7일'). 같으면 비움. */
  delta?: string
  direction: Direction
}

const SEVERITY: Record<VerdictLevel, number> = { approve: 0, review: 1, warn: 2 }

function direction(before: number, after: number, lowerIsBetter = true): Direction {
  if (before === after) return 'same'
  return after < before === lowerIsBetter ? 'better' : 'worse'
}

/** 마감일의 여유 일수(클수록 좋음): 오늘 확정 = 0, 기간 안 손실 없음 = 탐색 끝까지 + 1. */
function slack(deadline: ZeroLossDeadline, asOf: string): number {
  if (deadline.kind === 'confirm_now') return 0
  const days = daysBetween(asOf, deadline.last_day) ?? 0
  return deadline.kind === 'none_in_horizon' ? days + 1 : days
}

function signedDays(days: number): string {
  return `${days > 0 ? '+' : '−'}${Math.abs(days)}일`
}

function signedMoney(won: number): string {
  return `${won > 0 ? '+' : '−'}${formatMoney(Math.abs(won))}`
}

/**
 * 판정 줄은 늘 내고, 나머지는 값이 달라진 줄만 낸다(같은 값은 결정에 보탬이 없음 — DESIGN.md 2절).
 * 두 결과가 다른 설계변경이면 비교하지 않는다(빈 목록).
 */
export function compareResults(before: AnalysisResult, after: AnalysisResult): ChangeRow[] {
  if (before.request.change.ecn_id !== after.request.change.ecn_id) return []
  const rows: ChangeRow[] = []
  const v0 = before.verdict.level
  const v1 = after.verdict.level
  rows.push({
    id: 'verdict',
    label: '판정',
    before: VERDICT_NAMES[v0],
    after: VERDICT_NAMES[v1],
    direction: direction(SEVERITY[v0], SEVERITY[v1]),
  })
  const t0 = before.total.value
  const t1 = after.total.value
  if (t0 !== t1) {
    rows.push({
      id: 'total',
      label: '총변경비용',
      before: formatMoney(t0),
      after: formatMoney(t1),
      delta: signedMoney(t1 - t0),
      direction: direction(t0, t1),
    })
  }
  const d0 = before.timing.deadline
  const d1 = after.timing.deadline
  const s0 = slack(d0, before.request.as_of)
  const s1 = slack(d1, after.request.as_of)
  if (d0.kind !== d1.kind || d0.last_day !== d1.last_day) {
    const delta = d0.kind === 'by_date' && d1.kind === 'by_date' && s0 !== s1 ? signedDays(s1 - s0) : undefined
    rows.push({
      id: 'deadline',
      label: '결정 기한',
      before: deadlineText(d0),
      after: deadlineText(d1),
      delta,
      direction: direction(s0, s1, false),
    })
  }
  const later = laterLoss(before, after)
  if (later) rows.push(later)
  // 후행 설치 전환(명세 6-8): 두 결과 모두 선택지가 있으면 그 블록의 탑재 지연(지금 값)을 견준다 — 구역 출구가 같아도
  // 탑재가 앞당겨지는 것이 후행 설치의 효과라서
  const r0 = before.onboard?.erection_delay_now_days
  const r1 = after.onboard?.erection_delay_now_days
  if (r0 != null && r1 != null && r0 !== r1) {
    rows.push({
      id: 'erection',
      label: '후행 설치 대상 블록 탑재 지연',
      before: `${r0}일`,
      after: `${r1}일`,
      delta: signedDays(r1 - r0),
      direction: direction(r0, r1),
    })
  }
  const e0 = before.schedule.max_exit_delay_days
  const e1 = after.schedule.max_exit_delay_days
  if (e0 !== e1) {
    rows.push({
      id: 'exit',
      label: '구역 출구 최대 지연',
      before: `${e0}일`,
      after: `${e1}일`,
      delta: signedDays(e1 - e0),
      direction: direction(e0, e1),
    })
  }
  const l0 = before.schedule.delivery?.added_delay_days ?? 0
  const l1 = after.schedule.delivery?.added_delay_days ?? 0
  if (l0 !== l1) {
    rows.push({
      id: 'delivery',
      label: '늘어난 인도 지연',
      before: `${l0}일`,
      after: `${l1}일`,
      delta: signedDays(l1 - l0),
      direction: direction(l0, l1),
    })
  }
  return rows
}

/**
 * 미뤄 확정할 때: 두 곡선에서 그날 확정할 때 총비용이 가장 크게 다른 날(같으면 이른 날)의 총비용 전 → 후.
 * 보류는 오늘 확정 비용을 바꾸지 않고 '그때까지 미루면 생길 손실'을 줄이므로 이 줄이 보류의 효과를 보인다. 추가손실(각자 오늘
 * 대비)이 아니라 총비용으로 견주어 대안처럼 오늘 비용이 다른 비교에서도 같은 기준이다. 곡선이 같으면 null.
 */
function laterLoss(before: AnalysisResult, after: AnalysisResult): ChangeRow | null {
  const base = new Map(before.timing.curve.map((point) => [point.confirm_on, point.total.value]))
  let best: { day: string; from: number; to: number } | null = null
  for (const point of after.timing.curve) {
    const from = base.get(point.confirm_on)
    // 오늘(기준일) 확정은 총변경비용 줄이 이미 보인다
    if (from === undefined || point.confirm_on === after.request.as_of) continue
    const to = point.total.value
    if (to !== from && (!best || Math.abs(to - from) > Math.abs(best.to - best.from))) {
      best = { day: point.confirm_on, from, to }
    }
  }
  if (!best) return null
  return {
    id: 'later',
    label: `${formatDay(best.day)}에 확정하면 총비용`,
    before: formatMoney(best.from),
    after: formatMoney(best.to),
    delta: signedMoney(best.to - best.from),
    direction: direction(best.from, best.to),
  }
}

/** 띠 제목 한 줄: 나아진 것·나빠진 것 수로 요약. */
export function changeHeadline(rows: readonly ChangeRow[]): string {
  const better = rows.filter((row) => row.direction === 'better').length
  const worse = rows.filter((row) => row.direction === 'worse').length
  if (better > 0 && worse === 0) return '나아짐'
  if (worse > 0 && better === 0) return '나빠짐'
  if (better === 0 && worse === 0) return '판단 변화 없음'
  return '나아짐·나빠짐 함께'
}
