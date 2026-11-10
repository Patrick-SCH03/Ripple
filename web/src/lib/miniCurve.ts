// 마감일 카드 안의 작은 추가손실 곡선(DESIGN.md 6절): 추가손실 곡선 탭과 같은 데이터(timing.curve의 추가손실)를
// 기준일부터 마감일 다음 날의 계단 조금 뒤까지 자른다. 화면은 이 점을 그대로 그린다(새 계산 없음).
import type { CurvePoint, ZeroLossDeadline } from '@/api/client'
import { formatMoney } from './money'

export interface MiniPoint {
  day: string
  /** 그날 확정할 때의 추가손실(대표값, 창 안이 모두 0이면 최대값). */
  loss: number
}

export interface MiniCurve {
  /** 기준일부터 하루씩. */
  points: MiniPoint[]
  /** 마감일(추가손실 0인 마지막 날)의 자리. '오늘'이면 0. */
  deadlineAt: number
  /** 마감일 다음 날(계단)의 자리. */
  stepAt: number
  /** 하루 늦으면 늘어나는 금액: '+1,210만원', 대표값이 0이고 최대만 있으면 '최대 +68만원'. */
  rise: string
  /** 세로 끝(가장 큰 값). */
  max: number
}

/** 계단 뒤로 더 보이는 날수(계단이 이어진다는 것이 보이게): 3일과 계단까지 날수의 30% 중 큰 쪽. */
export function tailDays(stepAt: number): number {
  return Math.max(3, Math.ceil(stepAt * 0.3))
}

/** 마감일 카드의 작은 곡선. 기간 안 추가손실이 없거나(기간 안 없음) 다음 날이 곡선 밖이면 null. */
export function miniCurve(curve: readonly CurvePoint[], deadline: ZeroLossDeadline): MiniCurve | null {
  if (deadline.kind === 'none_in_horizon') return null
  const deadlineAt = curve.findIndex((point) => point.confirm_on === deadline.last_day)
  const stepAt = deadlineAt + 1
  if (deadlineAt < 0 || stepAt >= curve.length) return null
  const next = curve[stepAt].additional_loss
  if (next.value <= 0 && next.high <= 0) return null
  const rise = next.value > 0 ? `+${formatMoney(next.value)}` : `최대 +${formatMoney(next.high)}`
  const window = curve.slice(0, Math.min(curve.length, stepAt + 1 + tailDays(stepAt)))
  const useHigh = window.every((point) => point.additional_loss.value === 0)
  const points = window.map((point) => ({
    day: point.confirm_on,
    loss: useHigh ? point.additional_loss.high : point.additional_loss.value,
  }))
  return { points, deadlineAt, stepAt, rise, max: Math.max(...points.map((p) => p.loss)) }
}

/** 계단 그림의 SVG 경로(그날 값이 그날부터 이어짐 — 곡선 탭과 같은 계단). 폭·높이는 viewBox 단위, 위아래 여백 pad. */
export function stepPath(mini: MiniCurve, width: number, height: number, pad = 4): string {
  const last = Math.max(1, mini.points.length - 1)
  const x = (i: number) => +((i / last) * width).toFixed(2)
  const y = (v: number) => +(height - pad - (mini.max > 0 ? (v / mini.max) * (height - 2 * pad) : 0)).toFixed(2)
  let d = `M 0 ${y(mini.points[0].loss)}`
  for (let i = 1; i < mini.points.length; i++) d += ` H ${x(i)} V ${y(mini.points[i].loss)}`
  return d
}

/** 점 i의 가로 자리(%, 0~100). */
export function xPercent(mini: MiniCurve, i: number): number {
  return (i / Math.max(1, mini.points.length - 1)) * 100
}
