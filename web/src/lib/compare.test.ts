import { describe, expect, it } from 'vitest'
import type { AnalysisResult } from '@/api/client'
import { changeHeadline, compareResults } from './compare'

const amount = (value: number) => ({ value, low: value, high: value })

function result(over: Record<string, unknown> = {}): AnalysisResult {
  const base = {
    request: { as_of: '2026-10-20', holds: [], change: { ecn_id: 'ECN-1' } },
    verdict: { level: 'warn', reasons: [] },
    total: amount(12_000_000),
    schedule: { zone_exits: [], max_exit_delay_days: 4, delivery: { added_delay_days: 0 } },
    timing: { deadline: { kind: 'by_date', last_day: '2026-10-21' }, holds: [], reallocations: [], curve: [] },
  }
  return { ...base, ...over } as unknown as AnalysisResult
}

describe('바뀐 점(가정 계산 전후)', () => {
  it('보류로 판정·비용·마감일·출구 지연이 나아지면 줄마다 나아짐과 차이', () => {
    const before = result()
    const after = result({
      verdict: { level: 'review', reasons: [] },
      total: amount(8_800_000),
      schedule: { zone_exits: [], max_exit_delay_days: 0, delivery: { added_delay_days: 0 } },
      timing: { ...before.timing, deadline: { kind: 'by_date', last_day: '2026-10-28' } },
    })
    const rows = compareResults(before, after)
    expect(rows.map((row) => row.id)).toEqual(['verdict', 'total', 'deadline', 'exit'])
    expect(rows[0]).toMatchObject({ before: '경고', after: '검토 필요', direction: 'better' })
    expect(rows[1]).toMatchObject({ delta: '−320만원', direction: 'better' })
    expect(rows[2]).toMatchObject({ delta: '+7일', direction: 'better' })
    expect(rows[3]).toMatchObject({ before: '4일', after: '0일', delta: '−4일', direction: 'better' })
    expect(changeHeadline(rows)).toBe('나아짐')
  })

  it('후행 설치 전환: 두 결과 모두 선택지가 있으면 대상 블록 탑재 지연을 견줘 비용 증가와 함께 보임', () => {
    const option = (now: number) => ({ onboard: { erection_delay_now_days: now } })
    const before = result(option(21))
    const after = result({ ...option(1), total: amount(12_153_000) })
    const rows = compareResults(before, after)
    expect(rows.map((row) => row.id)).toEqual(['verdict', 'total', 'erection'])
    expect(rows[2]).toMatchObject({ before: '21일', after: '1일', delta: '−20일', direction: 'better' })
    expect(changeHeadline(rows)).toBe('나아짐·나빠짐 함께')
    // 한쪽에만 선택지가 있으면 견주지 않는다
    expect(compareResults(before, result()).map((row) => row.id)).toEqual(['verdict'])
  })

  it('판정 줄은 늘 내고, 같은 값의 줄은 내지 않음', () => {
    const rows = compareResults(result(), result())
    expect(rows).toEqual([{ id: 'verdict', label: '판정', before: '경고', after: '경고', direction: 'same' }])
    expect(changeHeadline(rows)).toBe('판단 변화 없음')
  })

  it('나빠지면 나빠짐, 섞이면 함께 있다고', () => {
    const before = result({ verdict: { level: 'review', reasons: [] } })
    const worse = compareResults(before, result({ total: amount(15_000_000) }))
    expect(worse.map((row) => row.direction)).toEqual(['worse', 'worse'])
    expect(changeHeadline(worse)).toBe('나빠짐')
    const mixed = compareResults(before, result({ verdict: { level: 'approve', reasons: [] }, total: amount(15_000_000) }))
    expect(changeHeadline(mixed)).toBe('나아짐·나빠짐 함께')
  })

  it('마감일 종류가 바뀌면 일수 차이 없이 좋아짐·나빠짐만(오늘 < 날짜 < 기간 안 없음)', () => {
    const now = result({ timing: { ...result().timing, deadline: { kind: 'confirm_now', last_day: '2026-10-20' } } })
    const free = result({ timing: { ...result().timing, deadline: { kind: 'none_in_horizon', last_day: '2026-12-19' } } })
    const toDate = compareResults(now, result()).find((row) => row.id === 'deadline')
    expect(toDate).toMatchObject({ before: '오늘', direction: 'better' })
    expect(toDate?.delta).toBeUndefined()
    expect(compareResults(free, result()).find((row) => row.id === 'deadline')).toMatchObject({
      after: '10월 21일(수)',
      direction: 'worse',
    })
  })

  it('보류처럼 오늘 비용은 같아도 미뤄 확정할 때 총비용이 줄면 가장 크게 준 날을 보임', () => {
    const curve = (losses: number[]) =>
      losses.map((loss, i) => ({
        confirm_on: `2026-10-${20 + i}`,
        total: amount(12_000_000 + loss),
        additional_loss: amount(loss),
        max_exit_delay_days: 0,
        events: [],
      }))
    const now = { kind: 'confirm_now', last_day: '2026-10-20' }
    const before = result({ timing: { ...result().timing, deadline: now, curve: curve([0, 500_000, 1_665_950, 3_593_300]) } })
    const after = result({ timing: { ...result().timing, deadline: now, curve: curve([0, 500_000, 1_546_600, 3_593_300]) } })
    const rows = compareResults(before, after)
    expect(rows.map((row) => row.id)).toEqual(['verdict', 'later'])
    expect(rows[1]).toMatchObject({
      label: '10월 22일(목)에 확정하면 총비용',
      before: '1,367만원',
      after: '1,355만원',
      delta: '−12만원',
      direction: 'better',
    })
    expect(changeHeadline(rows)).toBe('나아짐')
  })

  it('대안처럼 오늘 비용이 달라도 같은 날 총비용으로 견줌(각자 오늘 대비 추가손실로 보지 않음)', () => {
    const point = (day: string, total: number, loss: number) => ({
      confirm_on: day,
      total: amount(total),
      additional_loss: amount(loss),
      max_exit_delay_days: 0,
      events: [],
    })
    const before = result({
      total: amount(10_000_000),
      timing: { ...result().timing, curve: [point('2026-10-20', 10_000_000, 0), point('2026-10-25', 14_000_000, 4_000_000)] },
    })
    // 대안: 오늘 비용은 크지만 곡선이 평평 — 추가손실로는 '나아짐'이지만 같은 날 총비용은 15백만 > 14백만이라 나빠짐.
    // 오늘(기준일)은 총변경비용 줄이 보이므로 이 줄은 그 뒤 날짜에서 고른다
    const after = result({
      total: amount(15_000_000),
      timing: { ...result().timing, curve: [point('2026-10-20', 15_000_000, 0), point('2026-10-25', 15_000_000, 0)] },
    })
    const later = compareResults(before, after).find((row) => row.id === 'later')
    expect(later).toMatchObject({ label: '10월 25일(일)에 확정하면 총비용', delta: '+100만원', direction: 'worse' })
  })

  it('인도 지연이 늘면 나빠짐, 다른 설계변경끼리는 비교하지 않음', () => {
    const late = result({ schedule: { zone_exits: [], max_exit_delay_days: 4, delivery: { added_delay_days: 12 } } })
    expect(compareResults(result(), late).find((row) => row.id === 'delivery')).toMatchObject({
      delta: '+12일',
      direction: 'worse',
    })
    const other = result({ request: { ...result().request, change: { ecn_id: 'ECN-2' } } })
    expect(compareResults(result(), other)).toEqual([])
  })
})
