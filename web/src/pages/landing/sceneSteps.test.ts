import { describe, expect, it } from 'vitest'
import { SCENE_STEPS, SCENE_ZOOM, SHIP_POINTS, STEP_FLOW, sceneFlags, stageAt, zoomTo, zoomed } from './sceneSteps'

describe('첫 화면 흐름 장면', () => {
  it('붙는 자리에 닿기 전은 첫 단계, 끝까지 내리면 마지막 단계, 단계마다 같은 길이', () => {
    // 창 900, 위 막대 64 → 붙는 높이 836, 길 높이 836 + 5 × 400
    const height = 836 + 2000
    expect(stageAt(300, height, 900, 64)).toBe(0)
    expect(stageAt(64, height, 900, 64)).toBe(0)
    expect(stageAt(64 - 399, height, 900, 64)).toBe(0)
    expect(stageAt(64 - 401, height, 900, 64)).toBe(1)
    expect(stageAt(64 - 1201, height, 900, 64)).toBe(3)
    expect(stageAt(64 - 2000, height, 900, 64)).toBe(4)
    expect(stageAt(-99999, height, 900, 64)).toBe(4)
    expect(stageAt(0, 500, 900, 64)).toBe(SCENE_STEPS.length - 1)
  })

  it('뒤 단계는 앞 단계에서 켠 것을 그대로 둔다', () => {
    expect(sceneFlags(0)).toEqual({ zoom: false, blocks: false, numbers: false, report: false })
    expect(sceneFlags(2)).toEqual({ zoom: true, blocks: true, numbers: false, report: false })
    expect(sceneFlags(4)).toEqual({ zoom: true, blocks: true, numbers: true, report: true })
  })

  it('단계마다 흐름 띠 칸이 하나 이상 강조되고, 다섯 칸이 모두 한 번은 강조됨', () => {
    const seen = new Set(SCENE_STEPS.flatMap((step) => STEP_FLOW[step]))
    expect([...seen].sort()).toEqual(['approval', 'change', 'cost', 'deadline', 'scope'])
  })

  it('확대는 그림 밖을 보이지 않고, 확대 뒤 B31P·L31C·물결 자리는 판 안', () => {
    expect(SCENE_ZOOM.x).toBeLessThanOrEqual(0)
    expect(SCENE_ZOOM.x).toBeGreaterThanOrEqual(1 - SCENE_ZOOM.scale)
    expect(SCENE_ZOOM.y).toBeLessThanOrEqual(0)
    expect(SCENE_ZOOM.y).toBeGreaterThanOrEqual(1 - SCENE_ZOOM.scale)
    for (const point of Object.values(SHIP_POINTS)) {
      const at = zoomed(point)
      expect(at.x).toBeGreaterThan(0.05)
      expect(at.x).toBeLessThan(0.95)
      expect(at.y).toBeGreaterThan(0.05)
      expect(at.y).toBeLessThan(0.95)
    }
    expect(zoomTo({ x: 0, y: 0 }, 2)).toEqual({ scale: 2, x: 0, y: 0 })
    expect(zoomTo({ x: 1, y: 1 }, 2)).toEqual({ scale: 2, x: -1, y: -1 })
  })
})
