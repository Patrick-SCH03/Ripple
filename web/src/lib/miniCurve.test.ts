import { describe, expect, it } from 'vitest'
import type { CurvePoint, ZeroLossDeadline } from '@/api/client'
import { miniCurve, stepPath, tailDays, xPercent } from './miniCurve'

const amount = (value: number, low = value, high = value) => ({ value, low, high })

/** 기준일 10월 26일부터 하루씩, 그날의 추가손실(대표·최소·최대). */
function curve(losses: [number, number, number][]): CurvePoint[] {
  return losses.map(([value, low, high], i) => ({
    confirm_on: `2026-10-${String(26 + i).padStart(2, '0')}`,
    total: amount(1000 + value, 1000 + low, 1000 + high),
    additional_loss: amount(value, low, high),
    max_exit_delay_days: 0,
    events: [],
  }))
}

const flat = (n: number, then: number, after = 0): [number, number, number][] =>
  Array.from({ length: n }, (_, i) => (i < then ? [0, 0, 0] : [after, after, after]) as [number, number, number])

describe('마감일 카드의 작은 곡선', () => {
  it('기준일부터 마감일 다음 날 계단 뒤 며칠까지, 하루 늦으면 다음 날 추가손실(대표값)', () => {
    const points = flat(30, 8, 12_101_880)
    const deadline: ZeroLossDeadline = { kind: 'by_date', last_day: '2026-11-02' }
    const fixed = curve(points).map((p, i) => ({ ...p, confirm_on: new Date(Date.UTC(2026, 9, 26 + i)).toISOString().slice(0, 10) }))
    const mini = miniCurve(fixed, deadline)!
    expect(mini.deadlineAt).toBe(7)
    expect(mini.stepAt).toBe(8)
    expect(mini.rise).toBe('+1,210만원')
    expect(mini.points).toHaveLength(8 + 1 + tailDays(8))
    expect(mini.points[0]).toEqual({ day: '2026-10-26', loss: 0 })
    expect(mini.max).toBe(12_101_880)
  })

  it("'오늘'(기준일에 확정)이면 마감 자리 0, 대표값이 0이고 최대만 있으면 '최대 +' 금액과 최대값 곡선", () => {
    const points: [number, number, number][] = [[0, 0, 0], [0, 0, 680_000], [0, 0, 680_000], [0, 0, 680_000], [0, 0, 680_000]]
    const mini = miniCurve(curve(points), { kind: 'confirm_now', last_day: '2026-10-26' })!
    expect(mini.deadlineAt).toBe(0)
    expect(mini.rise).toBe('최대 +68만원')
    expect(mini.points.map((p) => p.loss)).toEqual([0, 680_000, 680_000, 680_000, 680_000])
  })

  it('기간 안 없음·다음 날이 곡선 밖·다음 날 손실 없음이면 그리지 않음', () => {
    expect(miniCurve(curve(flat(5, 5)), { kind: 'none_in_horizon', last_day: '2026-10-30' })).toBeNull()
    expect(miniCurve(curve(flat(5, 5)), { kind: 'by_date', last_day: '2026-10-30' })).toBeNull()
    expect(miniCurve(curve(flat(5, 5)), { kind: 'by_date', last_day: '2026-10-28' })).toBeNull()
  })

  it('계단 경로: 그날 값이 그날부터 이어짐(세로선은 그날 자리), 가로 자리는 0~100%', () => {
    const mini = miniCurve(curve(flat(6, 2, 100)), { kind: 'by_date', last_day: '2026-10-27' })!
    expect(stepPath(mini, 100, 20, 0)).toBe('M 0 20 H 20 V 20 H 40 V 0 H 60 V 0 H 80 V 0 H 100 V 0')
    expect(xPercent(mini, mini.deadlineAt)).toBe(20)
    expect(xPercent(mini, mini.points.length - 1)).toBe(100)
  })
})
