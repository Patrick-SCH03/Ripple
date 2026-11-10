import { describe, expect, it } from 'vitest'
import type { AnalysisResult } from '@/api/client'
import { marginText, ratioText, riskBasisText, scheduleQuiet, scheduleSummary } from './schedule'
import { exitRiskText } from './summary'

type Schedule = AnalysisResult['schedule']
type Exit = Schedule['zone_exits'][number]

function plus(day: string, days: number): string {
  const date = new Date(`${day}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

const exit = (zone: string, days: number): Exit => ({
  zone_id: `S-001:${zone}`,
  zone_name: '',
  exit_activity_id: `S-001:${zone}:exit`,
  base_date: '2027-01-16',
  new_date: plus('2027-01-16', days),
  delay_days: days,
})

const delivery = (before: number, after: number) => ({
  forecast_delay_before_days: before,
  forecast_delay_after_days: after,
  added_delay_days: after - before,
  permissible: false,
})

type Risk = NonNullable<Schedule['risk']>

function result(rep: Exit[], risk: Partial<Risk> | null, over: Partial<Schedule> = {}) {
  const schedule = {
    added_days_by_activity: {},
    zone_exits: rep,
    max_exit_delay_days: Math.max(0, ...rep.map((e) => e.delay_days)),
    delivery: delivery(0, 0),
    critical_path_before: [],
    critical_path_after: [],
    risk:
      risk === null
        ? null
        : {
            ratios: {},
            zone_exits: [],
            delivery: delivery(0, 0),
            unresolved: [],
            ...risk,
            max_exit_delay_days: Math.max(0, ...(risk.zone_exits ?? []).map((e) => e.delay_days)),
          },
    ...over,
  }
  return { schedule, unresolved: [] } as unknown as Pick<AnalysisResult, 'schedule' | 'unresolved'>
}

describe('일정 요약 — 일정 위험(자재가 늦게 오면)', () => {
  it('대표·위험 출구의 합집합: 대표 0일·위험만 늦는 구역도 행(그대로·0일), 출구 ID 순', () => {
    const summary = scheduleSummary(result([exit('ZER', 4)], { zone_exits: [exit('ZCT', 9), exit('ZER', 6)], ratios: { valve: 3 } }))
    expect(summary.exits.map((row) => [row.exit_activity_id, row.delay_days, row.risk?.delay_days])).toEqual([
      ['S-001:ZCT:exit', 0, 9],
      ['S-001:ZER:exit', 4, 6],
    ])
    expect(summary.exits[0].new_date).toBe(summary.exits[0].base_date)
    expect(summary.risk).toMatchObject({ exitsLater: true, maxExit: 9, basis: ['밸브 × 3'], delivery: null })
  })

  it('위험 = 대표면 위험 칸·줄 없음, 이전 판 결과(위험 없음)는 행의 위험도 없음', () => {
    const same = scheduleSummary(result([exit('ZER', 4)], { zone_exits: [exit('ZER', 4)] }))
    expect(same.risk).toBeNull()
    expect(same.exits[0].risk).toEqual({ new_date: plus('2027-01-16', 4), delay_days: 4 })
    const old = scheduleSummary(result([exit('ZER', 4)], null))
    expect(old.risk).toBeNull()
    expect(old.exits[0].risk).toBeNull()
  })

  it("'일정은 늦어지지 않아요'는 대표·위험 출구·인도 위험·위험 전용 계산 불가가 모두 없을 때만", () => {
    expect(scheduleQuiet(scheduleSummary(result([], {})))).toBe(true)
    expect(scheduleQuiet(scheduleSummary(result([], null)))).toBe(true)
    expect(scheduleQuiet(scheduleSummary(result([], { zone_exits: [exit('ZCT', 9)] })))).toBe(false)
    const riskDelivery = scheduleSummary(result([], { delivery: delivery(0, 6) }))
    expect(riskDelivery.risk?.delivery).toEqual({ before: 0, after: 6, added: 6 })
    expect(scheduleQuiet(riskDelivery)).toBe(false)
    const unknown = scheduleSummary(
      result([], { delivery: null, unresolved: [{ kind: 'delivery', entity_id: 'S-001', reason: '경계 조건이 없는 구역' }] }),
    )
    expect(unknown.risk?.deliveryUnknown).toEqual(['경계 조건이 없는 구역'])
    expect(unknown.deliveryUnknown).toEqual([])
    expect(scheduleQuiet(unknown)).toBe(false)
  })

  it('인도 위험은 대표가 계산됐고 위험이 더 늘 때만, 설명 줄에 늦춘 자재·배율과 대표 기준', () => {
    expect(scheduleSummary(result([], { delivery: delivery(0, 0) })).risk).toBeNull()
    expect(scheduleSummary(result([], { delivery: delivery(0, 6) }, { delivery: null })).risk).toBeNull()
    const both = scheduleSummary(result([], { zone_exits: [exit('ZCT', 5)], ratios: { valve: 3, plate: 1.2 } }))
    expect(both.risk?.basis).toEqual(['판재 × 1.2', '밸브 × 3'])
    const text = riskBasisText(both.risk!)
    expect(text).toContain('판재 × 1.2 · 밸브 × 3')
    expect(text).toContain('비용은 대표 일정 기준')
  })

  it('외자재 운송(1.33.0): 설명 줄도 구역 출구 카드(exitRiskText)와 같은 근거 — 배율 뒤 운송 일수, 선박 가정이면 그 말도', () => {
    const transported = scheduleSummary(
      result([], {
        zone_exits: [exit('ZER', 43)],
        ratios: { valve: 3 },
        transport: [{ mode: 'sea', days: 35, assumed: false }],
      }),
    )
    expect(transported.risk?.basis).toEqual(['밸브 × 3', '운송 선박 35일 포함'])
    expect(riskBasisText(transported.risk!)).toContain('(밸브 × 3 · 운송 선박 35일 포함, 가정)')
    const card = exitRiskText(result([], { zone_exits: [exit('ZER', 43)], ratios: { valve: 3 }, transport: [{ mode: 'sea', days: 35, assumed: false }] }).schedule as Schedule)
    expect(card).toBe(`자재가 늦게 오면 최대 43일(${transported.risk!.basis.join(' · ')})`)
    const assumed = scheduleSummary(
      result([], { zone_exits: [exit('ZER', 43)], ratios: {}, transport: [{ mode: 'sea', days: 35, assumed: true }] }),
    )
    expect(assumed.risk?.basis).toEqual(['운송 선박 35일 포함(방식 없음 → 선박 가정)'])
  })

  it('배율 표기: 소수 둘째 자리까지, 끝 0 없이', () => {
    expect([ratioText(1.2), ratioText(3), ratioText(1.5), ratioText(1.2000000001), ratioText(2.25)]).toEqual([
      '1.2',
      '3',
      '1.5',
      '1.2',
      '2.25',
    ])
  })
})

describe('구역 출구 여유(명세 6-7)', () => {
  it('여유 목록이 없는 이전 판 결과는 빈 목록이고, 여유는 늦어짐으로 세지 않는다', () => {
    const old = scheduleSummary(result([], null))
    expect(old.margins).toEqual([])
    const quiet = scheduleSummary(
      result([], null, { exit_margins: [{ zone_id: 'S-001:ZCT', zone_name: '화물탱크 구역', exit_activity_id: 'S-001:ZCT:exit', margin_days: 10 }] }),
    )
    expect(quiet.margins).toHaveLength(1)
    expect(scheduleQuiet(quiet)).toBe(true)
  })

  it('여유 문장: n일이면 남은 날, 0일이면 하루만 더 늦어도 늦어진다고', () => {
    const where = { zone_id: 'S-001:ZCT', zone_name: '화물탱크 구역', exit_activity_id: 'S-001:ZCT:exit' }
    expect(marginText({ ...where, margin_days: 10 })).toBe('화물탱크 구역 출구까지 여유 10일')
    expect(marginText({ ...where, margin_days: 0 })).toBe('화물탱크 구역 출구까지 여유 없음(하루만 늦어도 지연)')
    expect(marginText({ ...where, zone_name: '', margin_days: 3 })).toBe('ZCT 출구까지 여유 3일')
  })
})