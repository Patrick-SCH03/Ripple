// 일정 요약(DESIGN.md 6절 일정 탭 · 판단 리포트): 늦어지는 구역 출구 · 늦어지는 공정 · 인도. 숫자는 결과의 schedule 필드 그대로이고,
// 여기서는 고르고 순서만 정한다(일정 탭과 리포트가 같은 줄을 보이게).
// 일정 위험(docs/engine.md(비용·일정) 6-6): 새 자재가 리드타임 범위 끝에 오면 — 대표 일정 옆에 따로 싣는다(비용은 대표 기준, 판정은
// 대표가 안 늦고 위험만 늦을 때 검토 필요 이유 하나). 구역 출구 여유(6-7): 늦어지지 않았지만 여유가 줄어든 출구.
import type { AnalysisResult } from '@/api/client'
import { activityName, materialName, zoneName } from './labels'

type Schedule = AnalysisResult['schedule']
type Risk = NonNullable<Schedule['risk']>

/** 구역 출구 한 줄 = 대표·위험 출구의 합집합(대표 0일·위험만 늦는 구역도 보이게). */
export interface ExitRow {
  zone_id: string
  zone_name?: string
  exit_activity_id: string
  base_date: string
  /** 대표 일정(늦지 않으면 기준 일정과 같은 날·0일). */
  new_date: string
  delay_days: number
  /** 자재가 늦게 오면(일정 위험). 위험이 없는 이전 판 결과면 null. */
  risk: { new_date: string; delay_days: number } | null
}

export interface ScheduleRiskView {
  /** 대표보다 더 늦는 출구가 있는가(일정 탭 '자재가 늦게 오면' 칸). */
  exitsLater: boolean
  /** 위험 일정의 구역 출구 최대 지연. */
  maxExit: number
  /** 위험 일정에서 인도 지연이 대표보다 더 늘면(예상 지연 전·후, 늘어난 일수). */
  delivery: { before: number; after: number; added: number } | null
  /** 위험 일정에서만 인도 지연을 계산하지 못한 이유. */
  deliveryUnknown: string[]
  /** 늦춘 새 자재 '판재 × 1.2'(분류 이름 순) → 외자재 운송 '운송 선박 35일 포함'(구역 출구 카드와 같은 글). */
  basis: string[]
}

export interface ScheduleSummary {
  /** 늦어지는 구역 출구(대표 또는 위험 지연 > 0, 출구 ID 순). */
  exits: ExitRow[]
  /** 늦어지는 공정(구역 출구 공정 제외, 늘어난 일수 큰 순 → 공정 ID 순). */
  activities: { id: string; name: string; days: number }[]
  /** 인도 지연이 바뀌었으면(예상 지연 전·후, 이 변경으로 늘어난 일수). */
  delivery: { before: number; after: number; added: number } | null
  /** 인도 지연을 계산하지 못한 이유(경계 조건 없음 등). */
  deliveryUnknown: string[]
  /** 일정 위험이 대표와 다를 때만(출구·인도·위험 전용 계산 불가). 없거나 대표와 같으면 null. */
  risk: ScheduleRiskView | null
  /** 늦어지지 않았지만 이 변경으로 여유가 줄어든 구역 출구(출구 ID 순). 이전 판 결과면 빈 목록. */
  margins: ExitMarginRow[]
}

export type ExitMarginRow = NonNullable<Schedule['exit_margins']>[number]

/** 여유 한 줄: '화물탱크 구역 출구까지 여유 10일'(0일이면 하루만 더 늦어도 출구가 늦어진다고). */
export function marginText(margin: ExitMarginRow): string {
  const where = `${zoneName(margin)} 출구까지`
  return margin.margin_days > 0 ? `${where} 여유 ${margin.margin_days}일` : `${where} 여유 없음(하루만 늦어도 지연)`
}

/** 배율 표기: 1.2 · 3(소수 둘째 자리까지, 끝 0 없이). */
export function ratioText(ratio: number): string {
  return String(Number(ratio.toFixed(2)))
}

/** 늦춘 새 자재: '판재 × 1.2'(분류 키 순). */
function riskBasis(ratios: Record<string, number> | undefined): string[] {
  return Object.entries(ratios ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([category, ratio]) => `${materialName(category)} × ${ratioText(ratio)}`)
}

const TRANSPORT_NAMES: Record<string, string> = { air: '항공', sea: '선박' }

/** 위험 일정이 더한 외자재 운송(계약 1.33.0): '운송 선박 35일 포함', 방식이 비어 선박으로 가정했으면 그 말도. */
function transportBasis(legs: Risk['transport']): string[] {
  return (legs ?? []).map(
    (leg) => `운송 ${TRANSPORT_NAMES[leg.mode] ?? leg.mode} ${leg.days}일 포함${leg.assumed ? '(방식 없음 → 선박 가정)' : ''}`,
  )
}

/**
 * '자재가 늦게 오면'의 근거: 늦춘 새 자재 배율 → 외자재 운송 일수. 구역 출구 카드(summary.exitRiskText)·일정 탭·리포트의
 * 위험 설명 줄이 같은 글을 쓴다(같은 숫자의 근거가 화면 안에서 둘로 갈리지 않게).
 */
export function scheduleRiskBasis(risk: Risk): string[] {
  return [...riskBasis(risk.ratios), ...transportBasis(risk.transport)]
}

function exitRows(schedule: Schedule): ExitRow[] {
  const risky = new Map((schedule.risk?.zone_exits ?? []).map((exit) => [exit.exit_activity_id, exit]))
  const rows = new Map<string, ExitRow>()
  for (const exit of schedule.zone_exits) {
    if (exit.delay_days <= 0) continue
    const risk = schedule.risk ? (risky.get(exit.exit_activity_id) ?? exit) : null
    rows.set(exit.exit_activity_id, { ...exit, risk: risk && { new_date: risk.new_date, delay_days: risk.delay_days } })
  }
  for (const exit of risky.values()) {
    if (rows.has(exit.exit_activity_id)) continue
    const { new_date: riskDate, delay_days: riskDays, ...where } = exit
    rows.set(exit.exit_activity_id, {
      ...where,
      new_date: where.base_date,
      delay_days: 0,
      risk: { new_date: riskDate, delay_days: riskDays },
    })
  }
  return [...rows.values()].sort((a, b) => a.exit_activity_id.localeCompare(b.exit_activity_id))
}

function riskView(schedule: Schedule, exits: ExitRow[]): ScheduleRiskView | null {
  const risk = schedule.risk
  if (!risk) return null
  const exitsLater = exits.some((row) => row.risk !== null && row.risk.delay_days > row.delay_days)
  const repAdded = schedule.delivery?.added_delay_days ?? 0
  const riskDelivery = risk.delivery
  const delivery =
    riskDelivery && schedule.delivery && riskDelivery.added_delay_days > repAdded
      ? {
          before: riskDelivery.forecast_delay_before_days,
          after: riskDelivery.forecast_delay_after_days,
          added: riskDelivery.added_delay_days,
        }
      : null
  const deliveryUnknown = (risk.unresolved ?? []).filter((u) => u.kind === 'delivery').map((u) => u.reason)
  if (!exitsLater && !delivery && deliveryUnknown.length === 0) return null
  return {
    exitsLater,
    maxExit: risk.max_exit_delay_days ?? 0,
    delivery,
    deliveryUnknown,
    basis: scheduleRiskBasis(risk),
  }
}

export function scheduleSummary(result: Pick<AnalysisResult, 'schedule' | 'unresolved'>): ScheduleSummary {
  const { schedule } = result
  const exitIds = new Set(schedule.zone_exits.map((exit) => exit.exit_activity_id))
  const activities = Object.entries(schedule.added_days_by_activity ?? {})
    .filter(([id, days]) => days > 0 && !exitIds.has(id))
    .sort(([a, x], [b, y]) => y - x || a.localeCompare(b))
    .map(([id, days]) => ({ id, name: activityName(id), days }))
  const delivery = schedule.delivery
  const changed = delivery != null && (delivery.added_delay_days > 0 || delivery.forecast_delay_before_days > 0)
  const exits = exitRows(schedule)
  return {
    exits,
    activities,
    delivery: changed
      ? {
          before: delivery.forecast_delay_before_days,
          after: delivery.forecast_delay_after_days,
          added: delivery.added_delay_days,
        }
      : null,
    deliveryUnknown: result.unresolved.filter((u) => u.kind === 'delivery').map((u) => u.reason),
    risk: riskView(schedule, exits),
    margins: [...(schedule.exit_margins ?? [])],
  }
}

/** 늦어지는 것이 하나도 없는가(일정 탭·리포트의 '일정은 늦어지지 않아요') — 대표·위험·인도 위험 모두 없을 때만.
 * 여유가 줄어든 출구(margins)는 늦어지는 것이 아니라 세지 않는다(문장 아래 따로 보인다). */
export function scheduleQuiet(summary: ScheduleSummary): boolean {
  return (
    summary.exits.length === 0 &&
    summary.activities.length === 0 &&
    summary.delivery === null &&
    summary.deliveryUnknown.length === 0 &&
    summary.risk === null
  )
}

/** 위험 일정의 인도 한 줄. */
export function riskDeliveryText(delivery: NonNullable<ScheduleRiskView['delivery']>): string {
  return `자재가 늦게 오면 예상 인도 지연 ${delivery.before}일 → ${delivery.after}일(이 변경으로 +${delivery.added}일)`
}

/**
 * 일정 수치의 전제: CPM 추정이라 확정된 '지연일'로 읽히지 않게 일정 탭·리포트에 늘 붙인다.
 * 엔진은 자원 제약(인력·정반·크레인)과 납기 변동을 모른다(docs/engine.md(비용·일정) 6절).
 */
export const SCHEDULE_BASIS =
  '일정 = 공정 선후행·자재 리드타임만으로 계산한 추정 · 인력·정반·크레인 등 자원 제약과 납기 변동 미반영'

/** 일정 위험 설명 한 줄: 무엇을 늦춰 본 것인지(늦춘 새 자재·외자재 운송, 없으면 리드타임 범위 끝이라고만). */
export function riskBasisText(risk: ScheduleRiskView): string {
  const what = risk.basis.length > 0 ? `${risk.basis.join(' · ')}, ` : ''
  return `자재가 늦게 오면 = 새 자재 리드타임을 범위 끝으로 잡은 경우(${what}가정) · 비용은 대표 일정 기준 · 이 경우에만 늦으면 판정을 검토 필요로 올림`
}
