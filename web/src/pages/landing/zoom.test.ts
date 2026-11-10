import { describe, expect, it } from 'vitest'
import {
  APPROVAL_MARKS,
  APPROVAL_SHOT,
  COST_MARKS,
  COST_SHOT,
  CURVE_MARKS,
  CURVE_SHOT,
  MAP_SHOT,
  OPTIONS_MARKS,
  OPTIONS_SHOT,
  REPORT_MARKS,
  REPORT_SHOT,
  SHIP_MARKS,
  SHIP_SHOT,
  SUMMARY_MARKS,
  SUMMARY_SHOT,
  mapFocus,
  union,
  type Rect,
} from './captures'
import { SHOWCASE } from './example'
import { mapSteps } from './mapSteps'
import { focusView } from './zoom'

const BOX = 16 / 10
const inside = (r: Rect, size: { width: number; height: number }) =>
  r.x >= 0 && r.y >= 0 && r.x + r.w <= size.width && r.y + r.h <= size.height

describe('고정 화면 확대(focusView)', () => {
  it('전체 보기: 넓은 그림은 상자 폭 가득, 위아래 같은 여백, 확대·이동 없음', () => {
    const view = focusView(MAP_SHOT, BOX, null)
    expect(view).toMatchObject({ scale: 1, x: 0, y: 0, focus: null })
    expect(view.image.width).toBe(1)
    expect(view.image.top).toBeCloseTo((1 - view.image.height) / 2)
  })

  it('세로로 긴 그림은 상자 높이 가득, 좌우 같은 여백', () => {
    const view = focusView({ width: 400, height: 840 }, BOX, null)
    expect(view.image.height).toBe(1)
    expect(view.image.left).toBeCloseTo((1 - view.image.width) / 2)
  })

  it('영향 지도 단계마다: 확대는 1~3.2배, 강조 자리는 확대 뒤에도 상자 안, 상자 밖으로 밀지 않음', () => {
    for (const step of mapSteps(SHOWCASE)) {
      const focus = mapFocus(step.key)
      expect(focus, step.key).not.toBeNull()
      const view = focusView(MAP_SHOT, BOX, focus)
      expect(view.scale).toBeGreaterThanOrEqual(1)
      expect(view.scale).toBeLessThanOrEqual(3.2)
      expect(view.x).toBeLessThanOrEqual(0)
      expect(view.x).toBeGreaterThanOrEqual(1 - view.scale - 1e-9)
      expect(view.y).toBeLessThanOrEqual(0)
      expect(view.y).toBeGreaterThanOrEqual(1 - view.scale - 1e-9)
      const area = view.focus!
      const left = view.scale * area.left + view.x
      const top = view.scale * area.top + view.y
      expect(left, step.key).toBeGreaterThanOrEqual(-1e-9)
      expect(top, step.key).toBeGreaterThanOrEqual(-1e-9)
      expect(left + view.scale * area.width, step.key).toBeLessThanOrEqual(1 + 1e-9)
      expect(top + view.scale * area.height, step.key).toBeLessThanOrEqual(1 + 1e-9)
    }
  })

  it('휴대폰 상자(4:3, 상한 4.5배)에서도 강조 자리는 상자 안', () => {
    for (const step of mapSteps(SHOWCASE)) {
      const view = focusView(MAP_SHOT, 4 / 3, mapFocus(step.key), { maxZoom: 4.5 })
      expect(view.scale).toBeLessThanOrEqual(4.5)
      const area = view.focus!
      const left = view.scale * area.left + view.x
      const top = view.scale * area.top + view.y
      expect(left, step.key).toBeGreaterThanOrEqual(-1e-9)
      expect(top, step.key).toBeGreaterThanOrEqual(-1e-9)
      expect(left + view.scale * area.width, step.key).toBeLessThanOrEqual(1 + 1e-9)
      expect(top + view.scale * area.height, step.key).toBeLessThanOrEqual(1 + 1e-9)
    }
  })

  it('작은 자리는 더 크게 확대한다(카드 하나 > 공정 줄 전체)', () => {
    const block = focusView(MAP_SHOT, BOX, mapFocus('block'))
    const chain = focusView(MAP_SHOT, BOX, mapFocus('erection'))
    expect(block.scale).toBeGreaterThan(chain.scale)
  })
})

describe('그림 위 강조 자리(captures)', () => {
  it('강조 자리는 모두 그림 안', () => {
    for (const r of Object.values(SUMMARY_MARKS)) expect(inside(r, SUMMARY_SHOT)).toBe(true)
    for (const r of Object.values(COST_MARKS)) expect(inside(r, COST_SHOT)).toBe(true)
    for (const r of Object.values(SHIP_MARKS)) expect(inside(r, SHIP_SHOT)).toBe(true)
    for (const r of Object.values(REPORT_MARKS)) expect(inside(r, REPORT_SHOT)).toBe(true)
    for (const r of Object.values(CURVE_MARKS)) expect(inside(r, CURVE_SHOT)).toBe(true)
    for (const r of Object.values(OPTIONS_MARKS)) expect(inside(r, OPTIONS_SHOT)).toBe(true)
    for (const r of Object.values(APPROVAL_MARKS)) expect(inside(r, APPROVAL_SHOT)).toBe(true)
    for (const step of mapSteps(SHOWCASE)) expect(inside(mapFocus(step.key)!, MAP_SHOT), step.key).toBe(true)
  })

  it('union: 여러 사각형을 감싸고 여백만큼 넓힌다', () => {
    expect(union([{ x: 10, y: 20, w: 5, h: 5 }, { x: 30, y: 0, w: 10, h: 10 }], 2)).toEqual({ x: 8, y: -2, w: 34, h: 29 })
  })
})
