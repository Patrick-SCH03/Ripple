// 지연 파급 비용(계약 1.32.0, docs/engine.md(비용·일정) 4-11): 구역 출구가 실제로 지연되어(일수 = 구역 출구 지연 − 늘어난 인도 지연)
// 작업반이 기다리거나 다른 일로 옮겨 드는 간접비(가정). 지체상금 노출 금액처럼 총변경비용 밖의 참고 금액이라 판정·결정 기한·대안 비교에 쓰지 않는다.
// 숫자는 결과의 delay_ripple 필드 그대로이고, 여기서는 표기·0원일 때의 이유만 고른다(새 계산 없음).
import type { AnalysisResult, CostFactor } from '@/api/client'
import { formatMoney, formatRange } from './money'

type Ripple = NonNullable<AnalysisResult['delay_ripple']>

/** 지연 파급 비용을 계산하는 계약 판(이보다 앞 판의 기록은 이 줄을 그리지 않는다 — 계산하지 않았으므로). */
const DELAY_RIPPLE_CONTRACT = '1.32.0'

/** 하루 비용의 근거(현업 확인 상수): 하루 투입 80 MH × 5만원/MH. 결과의 하루 비용과 같을 때만 적는다. */
const DAILY_BASIS = { hours: 80, rate: 50_000, text: '현업 확인 상수 80 MH/일 × 5만원/MH로 계산한 가정' }

/** 쓰지 않는 곳 안내(화면·리포트 공통). */
export const DELAY_RIPPLE_SCOPE = '총변경비용에 더하지 않음 · 판정·결정 기한·대안 비교에도 미반영'

export interface DelayRippleView {
  /** 금액이 있음 · 0원(공정이 밀리지 않거나 밀린 날이 모두 인도 지연과 겹침). */
  kind: 'amount' | 'zero'
  value: string
  range: string | null
  /** 0원일 때 이유 한 줄. */
  reason: string | null
  /** 계산 한 줄: '지연 일수 67일 × 하루 비용 400만원'. */
  formula: string | null
  /** 인도 지연과 겹쳐 뺀 날 안내(겹친 날이 있을 때만). */
  overlap: string | null
  /** 하루 비용 가정값(범위·근거 상태 칩용). */
  factors: CostFactor[]
  /** 하루 비용의 근거 문장(결과의 하루 비용이 현업 확인 상수와 같을 때만). */
  basis: string | null
}

/** 'a.b.c' 판 비교: a ≥ b. 숫자가 아닌 조각은 0으로 본다. */
export function versionAtLeast(version: string, least: string): boolean {
  const parts = (text: string) => text.split('.').map((part) => Number.parseInt(part, 10) || 0)
  const [a, b] = [parts(version), parts(least)]
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    const diff = (a[i] ?? 0) - (b[i] ?? 0)
    if (diff !== 0) return diff > 0
  }
  return true
}

function amountView(ripple: Ripple): DelayRippleView {
  const { amount, days, delivery_overlap_days: overlap, factors } = ripple
  const daily = factors.find((factor) => factor.unit === '원/일')
  const perDay = daily ? `하루 비용 ${formatMoney(daily.value)}` : '하루 비용'
  return {
    kind: 'amount',
    value: formatMoney(amount.value),
    range: amount.low === amount.high ? null : formatRange(amount.low, amount.high),
    reason: null,
    formula: `지연 일수 ${days}일 × ${perDay}`,
    overlap: overlap > 0 ? `인도 지연과 겹친 ${overlap}일은 지체상금에 포함되어 제외` : null,
    factors: [...factors],
    basis: daily && daily.value === DAILY_BASIS.hours * DAILY_BASIS.rate ? DAILY_BASIS.text : null,
  }
}

/**
 * 비용 탭·리포트의 '총액 밖' 줄. 이 판을 계산하지 않은 옛 기록이면 null(줄을 그리지 않음).
 * 금액이 없으면 줄을 숨기지 않고 0원과 이유를 적는다: 구역 출구가 밀리지 않으면 '구역 출구가 밀리지 않아', 밀렸지만 그 날이
 * 모두 인도 지연이면 '지체상금에서 세어'.
 */
export function delayRippleView(result: Pick<AnalysisResult, 'delay_ripple' | 'schedule' | 'versions'>): DelayRippleView | null {
  if (result.delay_ripple) return amountView(result.delay_ripple)
  // 판을 모르는 결과(검사용 조각 등)도 옛 기록처럼 줄을 그리지 않는다
  if (!versionAtLeast(result.versions?.contract ?? '', DELAY_RIPPLE_CONTRACT)) return null
  const exit = result.schedule.max_exit_delay_days ?? 0
  return {
    kind: 'zero',
    value: formatMoney(0),
    range: null,
    reason: exit > 0 ? '지연일 모두 인도 지연 · 지체상금에 포함되어 0원' : '구역 출구 지연 없음 · 0원',
    formula: null,
    overlap: null,
    factors: [],
    basis: null,
  }
}

/** 핵심 수치(구역 출구 카드)·요약 복사의 한 줄: 금액이 있을 때만. */
export function delayRippleLine(result: Pick<AnalysisResult, 'delay_ripple'>): string | null {
  const ripple = result.delay_ripple
  return ripple ? `지연 파급 비용 ${formatMoney(ripple.amount.value)}(가정 · 총액 밖)` : null
}
