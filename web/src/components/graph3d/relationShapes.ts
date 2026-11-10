// 관계 화살표·용접 이음면 도형(three 객체 — 계산은 relations.ts 순수 함수, 그리기는 ShipRelations).
import { type BufferGeometry, Quaternion, Vector3 } from 'three'
import { blockShapes, jointGeometry } from './geometry'
import { SHIP } from './hull'
import { jointOf } from './layout'
import { type BlockLink, arcControl, arrowDirection, bezierAt } from './relations'

const UP = new Vector3(0, 1, 0)
/** 이름표를 곡선 꼭대기보다 조금 위에(곡선을 가리지 않게, m). */
const LABEL_RISE = 4

export interface ArrowShape {
  link: BlockLink
  from: Vector3
  control: Vector3
  to: Vector3
  /** 곡선 가운데 조금 위(이름표 자리). */
  mid: Vector3
  /** 화살촉 회전(원뿔 +y → 끝 방향). */
  turn: Quaternion
}

/** 블록 위 끝점: 블록 가운데의 x·z, 블록 윗면 높이(선체 위로 넘어가는 곡선이 블록 속에서 시작하지 않게). */
function topOf(code: string): Vector3 | null {
  const shape = blockShapes().get(code)
  const box = shape?.geometry.boundingBox
  if (!shape || !box) return null
  return new Vector3(shape.center.x, box.max.y, shape.center.z)
}

/** 화살표 도형(곡선 세 점 · 가운데 · 화살촉 방향). 배치 표에 없는 블록은 뺀다. */
export function arrowShapes(links: readonly BlockLink[]): ArrowShape[] {
  return links.flatMap((link) => {
    const from = topOf(link.from)
    const to = topOf(link.to)
    if (!from || !to) return []
    const a = from.toArray()
    const b = to.toArray()
    const c = arcControl(a, b, SHIP.depth)
    const turn = new Quaternion().setFromUnitVectors(UP, new Vector3(...arrowDirection(c, b)))
    const mid = new Vector3(...bezierAt(a, c, b, 0.5))
    mid.y += LABEL_RISE
    return [{ link, from, control: new Vector3(...c), to, mid, turn }]
  })
}

const seamCache = new Map<string, { geometry: BufferGeometry; center: Vector3 }>()

/** 이음면 도형과 가운데(한 번만 만든다 — 3D를 다시 열어도 그대로). 맞닿지 않는 쌍은 null. */
export function seamShape(a: string, b: string): { geometry: BufferGeometry; center: Vector3 } | null {
  const key = a < b ? `${a}|${b}` : `${b}|${a}`
  const cached = seamCache.get(key)
  if (cached) return cached
  const joint = jointOf(a, b)
  if (!joint) return null
  const geometry = jointGeometry(joint)
  geometry.computeBoundingBox()
  const center = geometry.boundingBox ? geometry.boundingBox.getCenter(new Vector3()) : new Vector3()
  const made = { geometry, center }
  seamCache.set(key, made)
  return made
}
