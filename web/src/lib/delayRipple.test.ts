// 지연 파급 비용(1.32.0): 총액 밖 줄 · 0원일 때 이유 · 옛 기록은 줄 없음 · 카드 한 줄 · 하루 비용 근거는 값이 같을 때만.
import { describe, expect, it } from 'vitest'
import type { AnalysisResult, CostFactor } from '@/api/client'
import { DELAY_RIPPLE_SCOPE, delayRippleLine, delayRippleView, versionAtLeast } from './delayRipple'
import { keyNumbers } from './summary'
import { briefingText } from './briefing'

const amount = (value: number, low = value, high = value) => ({ value, low, high })

const daily = (value: number): CostFactor => ({
  label: '지연 하루 파급 비용(작업반 대기·재배치)',
  unit: '원/일',
  value,
  low: value / 2,
  high: value * 2,
  status: 'assumption',
  keys: ['delay_ripple.cost_per_day_krw'],
})

function result(over: Record<string, unknown> = {}): AnalysisResult {
  const base = {
    versions: { contract: '1.32.0' },
    request: { as_of: '2026-10-20', holds: [], change: { ecn_id: 'ECN-1', title: '판 두께' } },
    verdict: { level: 'warn', reasons: [] },
    total: amount(43_337_303),
    cost_lines: [],
    schedule: {
      zone_exits: [
        { zone_id: 'S-001:ZCT', zone_name: '화물탱크 구역', exit_activity_id: 'S-001:ZCT:exit', base_date: '2026-11-01', new_date: '2026-11-04', delay_days: 3 },
      ],
      max_exit_delay_days: 3,
      delivery: { added_delay_days: 0, forecast_delay_before_days: 0, forecast_delay_after_days: 0 },
    },
    timing: { deadline: { kind: 'by_date', last_day: '2026-10-31' }, holds: [], reallocations: [], curve: [] },
    delay_ripple: {
      amount: amount(12_000_000, 6_000_000, 24_000_000),
      days: 3,
      exit_delay_days: 3,
      delivery_overlap_days: 0,
      factors: [daily(4_000_000)],
    },
  }
  return { ...base, ...over } as unknown as AnalysisResult
}

describe('지연 파급 비용 줄', () => {
  it('금액: 대표·범위 · 계산식 한 줄(지연 일수 × 하루 비용) · 하루 비용 근거(현업 확인 상수)', () => {
    const view = delayRippleView(result())!
    expect(view.kind).toBe('amount')
    expect(view.value).toBe('1,200만원')
    expect(view.range).toBe('600만~2,400만원')
    expect(view.formula).toBe('지연 일수 3일 × 하루 비용 400만원')
    expect(view.overlap).toBeNull()
    expect(view.basis).toBe('현업 확인 상수 80 MH/일 × 5만원/MH로 계산한 가정')
  })

  it('인도 지연과 겹쳐 뺀 날이 있으면 그 안내, 하루 비용이 현업 확인 상수와 다르면 근거 문장을 쓰지 않음', () => {
    const ripple = { amount: amount(9_000_000), days: 3, exit_delay_days: 5, delivery_overlap_days: 2, factors: [daily(3_000_000)] }
    const view = delayRippleView(result({ delay_ripple: ripple }))!
    expect(view.overlap).toBe('인도 지연과 겹친 2일은 지체상금에 포함되어 제외')
    expect(view.basis).toBeNull()
  })

  it('0원: 숨기지 않고 이유(구역 출구가 밀리지 않음 · 밀린 날이 모두 인도 지연)', () => {
    const quiet = { zone_exits: [], max_exit_delay_days: 0, delivery: { added_delay_days: 0 } }
    expect(delayRippleView(result({ delay_ripple: null, schedule: quiet }))).toMatchObject({
      kind: 'zero',
      value: '0원',
      reason: '구역 출구 지연 없음 · 0원',
    })
    const overlapped = { ...result().schedule, delivery: { added_delay_days: 3 } }
    expect(delayRippleView(result({ delay_ripple: null, schedule: overlapped }))?.reason).toBe(
      '지연일 모두 인도 지연 · 지체상금에 포함되어 0원',
    )
  })

  it('이 판(1.32.0)을 계산하지 않은 옛 기록은 줄 없음', () => {
    expect(delayRippleView(result({ delay_ripple: null, versions: { contract: '1.31.0' } }))).toBeNull()
    expect(delayRippleView(result({ delay_ripple: undefined, versions: { contract: '1.9.0' } }))).toBeNull()
    expect(versionAtLeast('1.32.0', '1.32.0')).toBe(true)
    expect(versionAtLeast('1.33.1', '1.32.0')).toBe(true)
    expect(versionAtLeast('1.4.0', '1.32.0')).toBe(false)
  })

  it('총변경비용에 더하지 않음: 카드·요약 복사의 총액은 결과 총액 그대로, 구역 출구 카드에 총액 밖 한 줄', () => {
    const cards = keyNumbers(result())
    expect(cards.find((card) => card.id === 'total')?.value).toBe('4,334만원')
    expect(cards.find((card) => card.id === 'exit')?.outside).toBe('지연 파급 비용 1,200만원(가정 · 총액 밖)')
    expect(delayRippleLine(result({ delay_ripple: null }))).toBeNull()
    const text = briefingText(result())
    expect(text).toContain('총변경비용: 4,334만원')
    expect(text).toContain('구역 출구 최대 지연: 3일(지연 파급 비용 1,200만원(가정 · 총액 밖))')
    expect(DELAY_RIPPLE_SCOPE).toContain('판정·결정 기한·대안 비교')
  })
})
