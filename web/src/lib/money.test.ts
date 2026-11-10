import { describe, expect, it } from 'vitest'
import { formatAxis, formatMoney, formatRange, formatWon } from './money'

describe('금액 표기', () => {
  it('원 단위는 세 자리 쉼표, 음수는 빼기 기호', () => {
    expect(formatWon(2984205)).toBe('2,984,205원')
    expect(formatWon(0)).toBe('0원')
    expect(formatWon(-12000)).toBe('−12,000원')
  })

  it('첫 화면은 만원 반올림, 1만원 미만은 원 그대로', () => {
    expect(formatMoney(2984205)).toBe('298만원')
    expect(formatMoney(2985000)).toBe('299만원')
    expect(formatMoney(8500)).toBe('8,500원')
    expect(formatMoney(0)).toBe('0원')
    expect(formatMoney(10_000)).toBe('1만원')
  })

  it('1억 이상은 억과 만원으로 나눠 씀(만원이 0이면 억만)', () => {
    expect(formatMoney(224214705)).toBe('2억 2,421만원')
    expect(formatMoney(200_000_000)).toBe('2억원')
    expect(formatMoney(99_995_000)).toBe('1억원')
    expect(formatMoney(1_234_567_890_000)).toBe('12,345억 6,789만원')
  })

  it('음수는 절감', () => {
    expect(formatMoney(-1189320)).toBe('절감 119만원')
    expect(formatMoney(-500)).toBe('절감 500원')
  })

  it('범위는 앞 끝 단위를 줄이고, 1만원 미만·음수 끝은 끝마다 단위', () => {
    expect(formatRange(664313, 7893318)).toBe('66만~789만원')
    expect(formatRange(144_000_000, 360_000_000)).toBe('1억 4,400만~3억 6,000만원')
    expect(formatRange(8500, 120_000)).toBe('8,500원~12만원')
    expect(formatRange(-120_000, 7893318)).toBe('−12만원~789만원')
    expect(formatRange(0, 0)).toBe('0원~0원')
  })

  it('축 눈금은 짧게', () => {
    expect(formatAxis(0)).toBe('0')
    expect(formatAxis(9000)).toBe('0.9만')
    expect(formatAxis(2984205)).toBe('298만')
    expect(formatAxis(224214705)).toBe('2.2억')
    expect(formatAxis(200_000_000)).toBe('2억')
    expect(formatAxis(-1189320)).toBe('−119만')
  })
})
