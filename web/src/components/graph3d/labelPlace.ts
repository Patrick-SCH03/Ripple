// 라벨 자리 정하기(순수 함수, labelPlace.test.ts): 화면에 옮긴 라벨 상자들이 겹치지 않게.
// 우선순위 높은 라벨부터 제자리 → 위 → 아래 → 오른쪽 → 왼쪽 → 대각선 순으로 비어 있는 자리를 찾고, 없으면 숨긴다.
// 고정 라벨(고른 블록·초점 있는 라벨)은 자리가 없어도 제자리에 남긴다. 맥락 이름표(movable false)는 옮기지 않는다.

/** 라벨 DOM(라벨 겹과 장면이 함께 쓴다): 키 → 라벨 요소, 블록 코드 → 라벨 끈. */
export interface LabelElements {
  labels: Map<string, HTMLElement>
  leaders: Map<string, SVGLineElement>
}

export function createLabelElements(): LabelElements {
  return { labels: new Map(), leaders: new Map() }
}

export interface LabelInput {
  key: string
  /** 기준점(화면 px) — 라벨 가운데. */
  x: number
  y: number
  w: number
  h: number
  priority: number
  /** 카메라에서 깊이(같은 우선순위면 가까운 쪽 먼저). */
  depth: number
  movable: boolean
  pinned: boolean
}

export interface LabelSpot {
  x: number
  y: number
  visible: boolean
}

interface Rect {
  x: number
  y: number
  w: number
  h: number
}

const GAP = 4

const overlaps = (a: Rect, b: Rect) => Math.abs(a.x - b.x) * 2 < a.w + b.w + GAP && Math.abs(a.y - b.y) * 2 < a.h + b.h + GAP

/** 라벨마다 자리(가운데)와 보일지. width·height = 화면 크기(밖으로 나가는 자리는 고르지 않는다, 기준점이 밖이면 숨김). */
export function placeLabels(labels: readonly LabelInput[], width: number, height: number): Map<string, LabelSpot> {
  const order = [...labels].sort((a, b) => b.priority - a.priority || a.depth - b.depth || (a.key < b.key ? -1 : 1))
  const shown: Rect[] = []
  const out = new Map<string, LabelSpot>()
  const inside = (r: Rect) => r.x - r.w / 2 >= 0 && r.x + r.w / 2 <= width && r.y - r.h / 2 >= 0 && r.y + r.h / 2 <= height
  for (const label of order) {
    const { x, y, w, h } = label
    if (x < 0 || x > width || y < 0 || y > height) {
      out.set(label.key, { x, y, visible: label.pinned })
      if (label.pinned) shown.push({ x, y, w, h })
      continue
    }
    const dx = w / 2 + GAP + 10
    const dy = h + GAP
    const offsets: [number, number][] = label.movable
      ? [
          [0, 0],
          [0, -dy],
          [0, dy],
          [dx, 0],
          [-dx, 0],
          [dx, -dy],
          [-dx, -dy],
          [dx, dy],
          [-dx, dy],
          [0, -2 * dy],
          [0, 2 * dy],
        ]
      : [[0, 0]]
    const spot = offsets
      .map(([ox, oy]) => ({ x: x + ox, y: y + oy, w, h }))
      .find((rect) => (rect.x === x && rect.y === y ? true : inside(rect)) && !shown.some((box) => overlaps(box, rect)))
    if (spot) {
      shown.push(spot)
      out.set(label.key, { x: spot.x, y: spot.y, visible: true })
    } else if (label.pinned) {
      shown.push({ x, y, w, h })
      out.set(label.key, { x, y, visible: true })
    } else out.set(label.key, { x, y, visible: false })
  }
  return out
}
