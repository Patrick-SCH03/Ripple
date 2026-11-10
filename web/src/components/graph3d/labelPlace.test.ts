import { describe, expect, it } from 'vitest'
import { type LabelInput, placeLabels } from './labelPlace'

const label = (key: string, x: number, y: number, priority: number, extra: Partial<LabelInput> = {}): LabelInput => ({
  key,
  x,
  y,
  w: 60,
  h: 20,
  priority,
  depth: 0,
  movable: true,
  pinned: false,
  ...extra,
})

function boxesOverlap(a: { x: number; y: number }, b: { x: number; y: number }, w = 60, h = 20) {
  return Math.abs(a.x - b.x) * 2 < w + w && Math.abs(a.y - b.y) * 2 < h + h
}

describe('라벨 자리', () => {
  it('겹치지 않으면 제자리', () => {
    const spots = placeLabels([label('a', 100, 100, 10), label('b', 300, 100, 5)], 800, 600)
    expect(spots.get('a')).toEqual({ x: 100, y: 100, visible: true })
    expect(spots.get('b')).toEqual({ x: 300, y: 100, visible: true })
  })

  it('겹치면 우선순위 높은 쪽이 제자리, 낮은 쪽은 비켜 놓는다(보이는 라벨끼리 겹치지 않음)', () => {
    const inputs = [label('low', 105, 102, 5), label('high', 100, 100, 50), label('mid', 98, 104, 20)]
    const spots = placeLabels(inputs, 800, 600)
    expect(spots.get('high')).toEqual({ x: 100, y: 100, visible: true })
    const shown = [...spots.values()].filter((s) => s.visible)
    expect(shown).toHaveLength(3)
    for (let i = 0; i < shown.length; i += 1) for (let j = i + 1; j < shown.length; j += 1) expect(boxesOverlap(shown[i], shown[j])).toBe(false)
  })

  it('자리가 없으면 숨기고, 고정 라벨(고른 블록)은 그래도 보인다', () => {
    const crowd = Array.from({ length: 30 }, (_, i) => label(`l${i}`, 40, 15, 1))
    const spots = placeLabels([label('top', 40, 15, 100), ...crowd, label('pin', 40, 15, 0, { pinned: true })], 120, 60)
    expect(spots.get('top')?.visible).toBe(true)
    expect(spots.get('pin')?.visible).toBe(true)
    expect([...spots.values()].filter((s) => !s.visible).length).toBeGreaterThan(20)
  })

  it('맥락 이름표는 옮기지 않고 숨긴다, 화면 밖 기준점은 숨긴다', () => {
    const spots = placeLabels([label('block', 100, 100, 50), label('ctx', 102, 100, 0, { movable: false }), label('out', -50, 100, 40)], 800, 600)
    expect(spots.get('ctx')?.visible).toBe(false)
    expect(spots.get('out')?.visible).toBe(false)
  })

  it('비켜 놓은 자리는 화면 밖으로 나가지 않는다', () => {
    const spots = placeLabels([label('a', 30, 10, 10), label('b', 30, 10, 5)], 400, 300)
    const b = spots.get('b')
    expect(b?.visible).toBe(true)
    expect((b?.y ?? 0) - 10).toBeGreaterThanOrEqual(0)
    expect((b?.x ?? 0) - 30).toBeGreaterThanOrEqual(0)
  })
})
