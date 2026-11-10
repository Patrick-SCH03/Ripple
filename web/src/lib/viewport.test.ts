import { describe, expect, it } from 'vitest'
import { isCompact, layoutOf, layoutOfQueries, MODE_MIN_WIDTH } from './viewport'

/** CSS 폭(소수 가능)에 대한 min-width 쿼리 결과 흉내 — 브라우저처럼 소수 폭 그대로 비교한다. */
const cssWidth = (width: number) => (query: string) => width >= Number(/min-width: (\d+)px/.exec(query)![1])

describe('layoutOfQueries(쿼리 결과로 정하는 모드)', () => {
  it('정수 폭에서는 layoutOf와 같음', () => {
    for (let width = 0; width <= 2000; width += 1) expect(layoutOfQueries(cssWidth(width))).toBe(layoutOf(width))
  })

  it('확대 110%의 소수 폭(1023.6px)은 쿼리대로 태블릿 — innerWidth 반올림(1024)으로 데스크톱이 되지 않음', () => {
    expect(layoutOfQueries(cssWidth(1023.6))).toBe('tablet')
    expect(layoutOf(Math.round(1023.6))).toBe('desktop') // 옛 방식(정수 폭)이 어긋나던 경우
    expect(layoutOfQueries(cssWidth(1439.5))).toBe('desktop')
    expect(layoutOfQueries(cssWidth(767.8))).toBe('phone')
  })
})

describe('layoutOf', () => {
  it('경계값(DESIGN.md 7절)', () => {
    expect(layoutOf(1440)).toBe('wide')
    expect(layoutOf(1439)).toBe('desktop')
    expect(layoutOf(1024)).toBe('desktop')
    expect(layoutOf(1023)).toBe('tablet')
    expect(layoutOf(768)).toBe('tablet')
    expect(layoutOf(767)).toBe('phone')
    expect(layoutOf(375)).toBe('phone')
    expect(layoutOf(0)).toBe('phone')
  })

  it('폭이 넓어지면 모드가 좁은 쪽으로 돌아가지 않음(단조)', () => {
    const order = ['phone', 'tablet', 'desktop', 'wide']
    let previous = 0
    for (let width = 0; width <= 2560; width += 1) {
      const rank = order.indexOf(layoutOf(width))
      expect(rank).toBeGreaterThanOrEqual(previous)
      previous = rank
    }
  })

  it('좁은 모드는 태블릿·휴대전화', () => {
    expect([MODE_MIN_WIDTH.wide, MODE_MIN_WIDTH.desktop, 900, 500].map((w) => isCompact(layoutOf(w)))).toEqual([
      false,
      false,
      true,
      true,
    ])
  })
})
