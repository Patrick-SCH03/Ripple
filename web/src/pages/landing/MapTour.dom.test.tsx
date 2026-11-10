// @vitest-environment jsdom
// 영향 지도 둘러보기 배치(DOM): CSS lg 쿼리 결과를 따른다 — 창 폭 숫자(innerWidth)와 어긋나도, 창 크기를 바꿔 쿼리 결과가
// 바뀌면 그때마다 글 | 고정 그림 ↔ 단계마다 그림으로 바뀐다.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { LG_QUERY } from './media'
import { MapTour } from './MapTour'
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let lg = false
const listeners = new Set<() => void>()
const original = window.matchMedia

beforeEach(() => {
  lg = false
  listeners.clear()
  window.matchMedia = ((query: string) => ({
    media: query,
    get matches() {
      return query === LG_QUERY ? lg : false
    },
    addEventListener: (_: string, fn: () => void) => query === LG_QUERY && listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  })) as unknown as typeof window.matchMedia
})

const mounted: Root[] = []
afterEach(() => {
  for (const root of mounted.splice(0)) act(() => root.unmount())
  document.body.innerHTML = ''
  window.matchMedia = original
})

/** 창 크기를 바꿔 lg 쿼리 결과가 바뀐 것처럼(브라우저는 이때만 알린다). */
function resize(next: boolean) {
  lg = next
  act(() => listeners.forEach((fn) => fn()))
}

async function mount() {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  mounted.push(root)
  await act(async () => root.render(<MapTour />))
  return {
    steps: () => container.querySelectorAll('[data-step]').length,
    figures: () => container.querySelectorAll('figure').length,
  }
}

describe('MapTour 배치', () => {
  it('innerWidth가 1024여도 CSS lg가 아니면 단계마다 그림(브라우저 확대 110%의 1023.6px)', async () => {
    expect(window.innerWidth).toBe(1024)
    const tour = await mount()
    expect(tour.steps()).toBe(0)
    expect(tour.figures()).toBe(7)
  })

  it('창을 넓혀 lg가 되면 글 | 고정 그림, 다시 좁히면 단계마다 그림', async () => {
    const tour = await mount()
    resize(true)
    expect(tour.steps()).toBe(7)
    expect(tour.figures()).toBe(1)
    resize(false)
    expect(tour.steps()).toBe(0)
    expect(tour.figures()).toBe(7)
  })

  it('넓게 연 뒤 좁히면 따라온다(처음 값에 묶이지 않음)', async () => {
    lg = true
    const tour = await mount()
    expect(tour.figures()).toBe(1)
    resize(false)
    expect(tour.figures()).toBe(7)
  })

  it('고정 그림은 붙는 자리(.rp-pin) 안 상자이고 가로세로비(--rp-box 16:10)를 넘겨 높이로도 폭을 묶는다', async () => {
    lg = true
    await mount()
    const figure = document.querySelector<HTMLElement>('.rp-pin figure.rp-viewer')!
    expect(Number(figure.style.getPropertyValue('--rp-box'))).toBeCloseTo(16 / 10)
    resize(false)
    expect(document.querySelector('.rp-pin')).toBeNull()
  })
})
