// 시점 계산(순수 함수, camera.test.ts): 정한 방향에서 상자 전체가 화면에 들어오는 카메라 자리.
// camera-controls의 fitToBox는 가장 가까운 축 방향으로 돌려 버려 비스듬한 시점을 쓸 수 없어 직접 계산한다.
import { BLOCK_LAYOUT, type ShipView, VIEWS, ZONE_VIEW } from './layout'

type Vec = [number, number, number]

const sub = (a: Vec, b: Vec): Vec => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const dot = (a: Vec, b: Vec) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const cross = (a: Vec, b: Vec): Vec => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
const unit = (a: Vec): Vec => {
  const n = Math.hypot(...a) || 1
  return [a[0] / n, a[1] / n, a[2] / n]
}

/** 구면 좌표(camera-controls: θ = y축 둘레 방위, 0이면 +z, φ = +y에서 잰 극각) → 대상에서 카메라 쪽 단위 벡터. */
export function directionOf(azimuth: number, polar: number): Vec {
  return [Math.sin(polar) * Math.sin(azimuth), Math.cos(polar), Math.sin(polar) * Math.cos(azimuth)]
}

export interface LookAt {
  position: Vec
  target: Vec
}

/**
 * 상자의 여덟 꼭짓점이 모두 시야(세로 fov, 가로는 aspect로)에 들어오는 가장 가까운 거리. padding = 여유 배율(1.1이면 10%).
 */
export function fitView(view: Pick<ShipView, 'box' | 'azimuth' | 'polar'>, fovDeg: number, aspect: number, padding = 1.08): LookAt {
  const [min, max] = view.box
  const target: Vec = [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2]
  const back = directionOf(view.azimuth, view.polar)
  const forward: Vec = [-back[0], -back[1], -back[2]]
  const right = unit(cross(forward, [0, 1, 0]))
  const up = cross(right, forward)
  const tanV = Math.tan(((fovDeg * Math.PI) / 180) / 2)
  const tanH = tanV * Math.max(0.1, aspect)
  let distance = 1
  for (const x of [min[0], max[0]]) {
    for (const y of [min[1], max[1]]) {
      for (const z of [min[2], max[2]]) {
        const d = sub([x, y, z], target)
        // 카메라 = 대상 − forward × 거리 → 꼭짓점의 깊이 = 거리 + d·forward
        const depth = dot(d, forward)
        distance = Math.max(
          distance,
          (Math.abs(dot(d, right)) * padding) / tanH - depth,
          (Math.abs(dot(d, up)) * padding) / tanV - depth,
        )
      }
    }
  }
  return { position: [target[0] + back[0] * distance, target[1] + back[1] * distance, target[2] + back[2] * distance], target }
}

/** 휠 확대의 가장 가까운 거리(m): 블록 하나(약 20~30m)가 화면을 채우는 정도 — 더 다가가 선체 안으로 파고들지 않게. */
export const MIN_DISTANCE = 25
/** 휠 축소 상한 = 전체 시점 맞춤 거리 × 이 배율 — 배가 화면 가운데 작게 남고 밖으로 사라지지 않게. */
export const MAX_DISTANCE_FACTOR = 1.6

/** 휠 확대·축소 거리 범위(m): 화면 비율마다 전체 시점 맞춤 거리를 기준으로 상한을 잡는다(세로로 긴 휴대폰 전체 화면도 전체 시점이 상한 안). */
export function zoomLimits(fovDeg: number, aspect: number): { min: number; max: number } {
  const whole = VIEWS.find((view) => view.name === 'whole') ?? VIEWS[0]
  if (!whole) return { min: MIN_DISTANCE, max: MIN_DISTANCE * 40 }
  const { position, target } = fitView(whole, fovDeg, aspect)
  const distance = Math.hypot(...sub(position, target))
  return { min: MIN_DISTANCE, max: Math.max(MIN_DISTANCE * 4, Math.ceil(distance * MAX_DISTANCE_FACTOR)) }
}

/** 목록에서 고른 블록으로 날아갈 때 상자에 더하는 여유(m) — 이웃 블록이 조금 보여 배 안 어디인지 알 수 있게. */
export const BLOCK_MARGIN = 6

/**
 * 블록 하나에 맞추는 시점: 그 블록 구역의 시점(화물창·선미·선수)과 같은 높이각, 방위는 블록이 있는 현측(코드 끝 P = 좌현,
 * S = 우현, 가운데 C는 지금 보던 쪽 mirror)에서. 상자 = 블록 도형 상자 + 사방 BLOCK_MARGIN. 배치 표에 없으면 null.
 */
export function blockView(
  code: string,
  bounds: readonly [Vec, Vec],
  mirror: boolean,
): Pick<ShipView, 'box' | 'azimuth' | 'polar'> | null {
  const place = BLOCK_LAYOUT.find((block) => block.code === code)
  const zone = place && VIEWS.find((view) => view.name === ZONE_VIEW[place.zone])
  if (!place || !zone) return null
  const port = code.endsWith('P') ? true : code.endsWith('S') ? false : mirror
  const [min, max] = bounds
  const m = BLOCK_MARGIN
  return {
    box: [
      [min[0] - m, min[1] - m / 2, min[2] - m],
      [max[0] + m, max[1] + m / 2, max[2] + m],
    ],
    azimuth: port ? Math.PI - zone.azimuth : zone.azimuth,
    polar: zone.polar,
  }
}
