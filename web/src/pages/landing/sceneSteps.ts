// 첫 화면 흐름 장면(DESIGN.md 12절)의 순수 계산: 스크롤 위치 → 단계, 단계 → 켜는 것·흐름 띠 강조, 3D 배치 그림의 확대 자리와
// 확대 뒤 이름표·물결 자리. 화면(HeroScene.tsx)은 이 값만 쓰고, 검사(sceneSteps.test.ts)가 경계와 자리를 본다.
import type { FlowKey } from './content'

/** 장면 단계: 배 전체 → No.3 화물창 확대 → B31P·L31C 이름표와 물결 → 판단 요약 숫자 → 결재·A4 검토서. */
export const SCENE_STEPS = ['ship', 'zoom', 'blocks', 'numbers', 'report'] as const
export type SceneStep = (typeof SCENE_STEPS)[number]

/** 단계마다 흐름 띠에서 강조할 칸(번호 배지 없이 칸 바탕·밑줄로). */
export const STEP_FLOW: Record<SceneStep, FlowKey[]> = {
  ship: ['change'],
  zoom: ['scope'],
  blocks: ['scope'],
  numbers: ['cost', 'deadline'],
  report: ['approval'],
}

/** 그 단계까지 켜진 것(뒤 단계는 앞 단계의 것을 그대로 둔다). */
export function sceneFlags(step: number): { zoom: boolean; blocks: boolean; numbers: boolean; report: boolean } {
  return { zoom: step >= 1, blocks: step >= 2, numbers: step >= 3, report: step >= 4 }
}

/**
 * 붙어 있는 장면의 단계. top = 장면 길(track) 위쪽의 화면 위치(px), height = 길 높이, viewport = 창 높이, pin = 붙는 자리(위 막대
 * 높이). 길이 붙는 자리에 닿기 전은 0, 끝까지 내리면 마지막 단계. 단계마다 같은 길이의 스크롤을 쓴다.
 */
export function stageAt(top: number, height: number, viewport: number, pin: number, steps = SCENE_STEPS.length): number {
  const span = height - (viewport - pin)
  if (span <= 0) return steps - 1
  const progress = Math.min(1, Math.max(0, (pin - top) / span))
  return Math.min(steps - 1, Math.floor(progress * steps))
}

/** 3D 배치 전체 시점 그림(ship-whole, 1000×500) 안의 자리(그림 크기 비율 0~1, 찍은 그림에서 잰 값). */
export const SHIP_POINTS = {
  /** No.3 화물창 영향 블록 둘(B31P·L31C) 가운데 — 확대 중심. */
  hold: { x: 0.45, y: 0.62 },
  /** B31P 이름표 가운데. */
  b31p: { x: 0.482, y: 0.752 },
  /** L31C 이름표 가운데. */
  l31c: { x: 0.289, y: 0.616 },
  /** 두 블록 덩어리 가운데 — 물결 고리 중심. */
  wave: { x: 0.43, y: 0.66 },
} as const

export interface Zoom {
  scale: number
  /** transform-origin 0 0에서 translate(%) — 그림 크기 비율. */
  x: number
  y: number
}

/** 중심점이 가운데 오게 확대하되 그림 밖이 보이지 않게 이동을 묶는다. */
export function zoomTo(center: { x: number; y: number }, scale: number): Zoom {
  const clamp = (t: number) => Math.min(0, Math.max(1 - scale, t))
  return { scale, x: clamp(0.5 - scale * center.x), y: clamp(0.5 - scale * center.y) }
}

export const SCENE_ZOOM = zoomTo(SHIP_POINTS.hold, 1.8)

/** 확대 뒤 그림 위 자리(판 크기 비율 0~1). */
export function zoomed(point: { x: number; y: number }, zoom: Zoom = SCENE_ZOOM): { x: number; y: number } {
  return { x: zoom.scale * point.x + zoom.x, y: zoom.scale * point.y + zoom.y }
}

/** CSS transform(transform-origin 0 0). */
export function zoomTransform(zoom: Zoom = SCENE_ZOOM): string {
  return `translate(${(zoom.x * 100).toFixed(2)}%, ${(zoom.y * 100).toFixed(2)}%) scale(${zoom.scale})`
}
