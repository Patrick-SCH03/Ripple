// 조각(선체 안 ∩ 상자) → three 도형: x 단면(hull.ts sectionOf)을 이어 붙인 로프트. 면은 바깥에서 반시계 방향.
// 법선은 꺾인 모서리(35° 넘게)만 날카롭게, 곡면은 매끈하게(toCreasedNormals).
import { Box3, BufferGeometry, CylinderGeometry, Float32BufferAttribute, SphereGeometry, Vector3 } from 'three'
import { mergeGeometries, toCreasedNormals } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import { type Piece, SHIP, bottomAt, deckAt, halfBreadth, sectionOf } from './hull'
import { BLOCK_LAYOUT, type BlockPlace, type Joint } from './layout'

/** 블록 사이 이음매(m): 블록마다 이만큼 안쪽으로 줄여 경계가 보이게. */
const SEAM = 0.14
const CREASE = (35 * Math.PI) / 180

interface LoftOptions {
  /** 단면 사이 간격(m). */
  step?: number
  /** 단면 행 수. */
  rows?: number
  gap?: number
  /** 앞뒤 끝 마구리 면(열린 껍질이면 false). */
  caps?: boolean
  /** 윗면·아랫면(높이로 나눈 껍질을 이을 때 맞닿는 쪽은 false). */
  top?: boolean
  bottom?: boolean
}

/**
 * 로프트 단면 자리: 곡면(선수·선미)은 step 간격, 단면이 같은 평행 중앙부는 최대 4m 간격(삼각형 수를 줄여 내장 그래픽에서도
 * 가볍게). 평행 중앙부 경계에는 꼭 단면을 둔다.
 */
function stationsBetween(x0: number, x1: number, step: number): number[] {
  const out: number[] = []
  const coarse = Math.max(step, 4)
  let x = x0
  while (x < x1 - 1e-6) {
    out.push(x)
    const flat = x >= SHIP.runEnd && x < SHIP.entrance
    let next = x + (flat ? coarse : step)
    // 평행 중앙부 경계를 건너뛰지 않게
    for (const edge of [SHIP.runEnd, SHIP.entrance]) if (x < edge - 1e-6 && next > edge) next = edge
    x = Math.min(next, x1)
  }
  out.push(x1)
  return out
}

function loftGeometry(piece: Piece, options: LoftOptions = {}): BufferGeometry {
  const { step = 1, rows = 24, gap = SEAM, caps = true, top = true, bottom = true } = options
  if (piece.shape === 'rudder') return rudderGeometry(piece, gap)
  if (piece.shape === 'boss') return bossGeometry(piece, gap)
  const x0 = piece.x[0] + gap
  const x1 = piece.x[1] - gap
  const xs = piece.box ? [x0, x1] : stationsBetween(x0, x1, step)
  const count = xs.length - 1
  const n = piece.box ? 1 : rows
  const stations = xs.map((x) => sectionOf(piece, x, n, gap))
  // 조각이 없는 단면(구상선수 코 앞·카운터 뒤)은 가장 가까운 단면의 가운데 한 점(x도 그 단면)으로 모은다 — 끝이 뾰족하게
  // 닫히고, 빈 단면이 이어져도 앞뒤로 가는 띠가 생기지 않는다
  const filled = stations.map((section, j) => {
    if (!section.empty) return section
    let k = -1
    for (let d = 1; d < stations.length && k < 0; d += 1) {
      if (j - d >= 0 && !stations[j - d].empty) k = j - d
      else if (j + d < stations.length && !stations[j + d].empty) k = j + d
    }
    if (k < 0) return section
    const near = stations[k].rows
    const y = (near[0].y + near[near.length - 1].y) / 2
    const z = near.reduce((sum, row) => sum + (row.left + row.right) / 2, 0) / near.length
    return { ...section, x: stations[k].x, rows: section.rows.map(() => ({ y, left: z, right: z })) }
  })
  const width = n + 1
  const positions: number[] = []
  for (const section of filled) {
    for (const row of section.rows) positions.push(section.x, row.y, row.left, section.x, row.y, row.right)
  }
  const L = (j: number, k: number) => (j * width + k) * 2
  const R = (j: number, k: number) => L(j, k) + 1
  const index: number[] = []
  const quad = (a: number, b: number, c: number, d: number) => index.push(a, b, d, a, d, c)
  for (let j = 0; j < count; j += 1) {
    for (let k = 0; k < width - 1; k += 1) {
      quad(R(j, k), R(j + 1, k), R(j, k + 1), R(j + 1, k + 1)) // 우현 쪽 면(+z)
      quad(L(j, k), L(j, k + 1), L(j + 1, k), L(j + 1, k + 1)) // 좌현 쪽 면(−z)
    }
    if (bottom) quad(L(j, 0), L(j + 1, 0), R(j, 0), R(j + 1, 0)) // 아랫면(−y)
    if (top) quad(L(j, width - 1), R(j, width - 1), L(j + 1, width - 1), R(j + 1, width - 1)) // 윗면(+y)
  }
  if (caps) {
    for (let k = 0; k < width - 1; k += 1) {
      quad(L(0, k), R(0, k), L(0, k + 1), R(0, k + 1)) // 뒤 끝(−x)
      quad(L(count, k), L(count, k + 1), R(count, k), R(count, k + 1)) // 앞 끝(+x)
    }
  }
  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new Float32BufferAttribute(positions, 3))
  geometry.setIndex(index)
  return geometry
}

/** 러더: 대칭 날개 단면(NACA 4자리식, 두께비 18%)을 아래 → 위로 이은 것. 아래쪽 코드가 10% 짧다. */
function rudderGeometry(piece: Piece, gap: number): BufferGeometry {
  const [xTe, xLe] = [piece.x[0] + gap, piece.x[1] - gap]
  const [y0, y1] = [piece.y[0] + gap, piece.y[1] - gap]
  const half = Math.min(Math.abs((piece.z ?? [-1, 1])[0]), Math.abs((piece.z ?? [-1, 1])[1])) - gap
  const samples = 18
  const ring = (y: number, scale: number) => {
    const chord = (xLe - xTe) * scale
    const points: [number, number, number][] = []
    for (let i = 0; i <= samples; i += 1) {
      const u = (1 - Math.cos((Math.PI * i) / samples)) / 2
      const t = 5 * 0.18 * (0.2969 * Math.sqrt(u) - 0.126 * u - 0.3516 * u ** 2 + 0.2843 * u ** 3 - 0.1036 * u ** 4)
      points.push([xLe - u * chord, y, Math.min(half, t * chord)])
    }
    // 위 → 아래 둘레(우현 앞 → 뒤, 좌현 뒤 → 앞)
    return [...points, ...points.slice(1, -1).reverse().map(([x, yy, z]) => [x, yy, -z] as [number, number, number])]
  }
  const levels = [ring(y0, 0.9), ring(y1, 1)]
  const m = levels[0].length
  const positions = levels.flatMap((level) => level.flat())
  const index: number[] = []
  for (let i = 0; i < m; i += 1) {
    const a = i
    const b = (i + 1) % m
    index.push(a, m + b, b, a, m + a, m + b)
  }
  // 위·아래 마구리(가운데 점 부채꼴)
  const base = positions.length / 3
  positions.push((xLe + xTe) / 2, y0, 0, (xLe + xTe) / 2, y1, 0)
  for (let i = 0; i < m; i += 1) {
    const b = (i + 1) % m
    index.push(base, i, b, base + 1, m + b, m + i)
  }
  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new Float32BufferAttribute(positions, 3))
  geometry.setIndex(index)
  return geometry
}

/** 프로펠러 축 보스: 선미재(굵게) → 프로펠러 허브(가늘게) 원뿔대. */
function bossGeometry(piece: Piece, gap: number): BufferGeometry {
  const [x0, x1] = [piece.x[0] + gap, piece.x[1] - gap]
  const cy = (piece.y[0] + piece.y[1]) / 2
  const r = (piece.y[1] - piece.y[0]) / 2 - gap
  const geometry = new CylinderGeometry(r, r * 0.7, x1 - x0, 28, 1)
  geometry.rotateZ(-Math.PI / 2)
  geometry.translate((x0 + x1) / 2, cy, 0)
  return geometry
}

/** 여러 조각을 한 도형으로(블록 하나 = 메시 하나, 맥락 선체 = 메시 하나). */
export function piecesGeometry(pieces: readonly Piece[], options?: LoftOptions): BufferGeometry {
  const parts = pieces.map((piece) => {
    const part = loftGeometry(piece, options)
    return part.index ? part.toNonIndexed() : part
  })
  for (const part of parts) {
    for (const name of Object.keys(part.attributes)) if (name !== 'position') part.deleteAttribute(name)
  }
  const merged = parts.length === 1 ? parts[0] : (mergeGeometries(parts) ?? parts[0])
  const smooth = toCreasedNormals(merged, CREASE)
  smooth.computeBoundingBox()
  smooth.computeBoundingSphere()
  return smooth
}

/** 선체 외판(반투명 껍질)을 흘수선 아래·위로 나눠서(아래는 조금 짙게 — 흘수선 띠). */
export function hullSkin(): { below: BufferGeometry; above: BufferGeometry } {
  const { aftEnd, fwdEnd, draft, forecastle } = SHIP
  const x: [number, number] = [aftEnd, fwdEnd]
  const shell = (y: readonly [number, number], rows: number, top: boolean, bottom: boolean) =>
    loftGeometry({ x, y }, { step: 0.6, rows, gap: 0, caps: true, top, bottom })
  const below = [shell([0, 12], 26, false, true), shell([12, draft], 12, false, false)].map((part) => part.toNonIndexed())
  const above = shell([draft, forecastle + 1], 18, true, false)
  const lower = toCreasedNormals(mergeGeometries(below) ?? below[0], CREASE)
  const upper = toCreasedNormals(above, CREASE)
  return { below: lower, above: upper }
}

/** 선체 단면 윤곽(선도의 늑골선처럼): 좌현 갑판 끝 → 빌지 → 용골(또는 카운터) → 우현 갑판 끝. */
export function frameLine(x: number, samples = 48): Vector3[] {
  const top = deckAt(x)
  const low = bottomAt(x)
  const right: Vector3[] = []
  for (let k = 0; k <= samples; k += 1) {
    const y = low + ((top - low) * k) / samples
    const hb = halfBreadth(x, y)
    if (hb > 0) right.push(new Vector3(x, y, hb))
  }
  const left = [...right].reverse().map((p) => new Vector3(p.x, p.y, -p.z))
  return [...left, ...right]
}

/** 갑판 끝선(현측선) 한쪽: 선미 → 선수. */
export function sheerLine(side: 1 | -1, step = 1): Vector3[] {
  const points: Vector3[] = []
  for (let x = SHIP.aftEnd; x <= SHIP.fwdEnd; x += step) {
    const y = deckAt(x) - 0.01
    const hb = halfBreadth(x, y)
    if (hb > 0) points.push(new Vector3(x, y, side * hb))
  }
  return points
}

/** 흘수선(설계 흘수 높이의 수선면 둘레, 닫힌 고리): 우현 선미 → 선수 → 좌현 → 선미. */
export function waterLine(step = 0.75): Vector3[] {
  const y = SHIP.draft
  const right: Vector3[] = []
  for (let x = SHIP.aftEnd; x <= SHIP.fwdEnd; x += step) {
    const hb = halfBreadth(x, y)
    if (hb > 0) right.push(new Vector3(x, y, hb + 0.02))
  }
  const left = [...right].reverse().map((p) => new Vector3(p.x, p.y, -p.z))
  return [...right, ...left, right[0]]
}

/** 프로펠러(맥락): 허브 + 날개 넷(피치만큼 비틀린 납작한 타원). 지름 8.4 · 축 높이 5 · x 5. */
export function propellerGeometry(): BufferGeometry {
  const parts: BufferGeometry[] = []
  const hub = new SphereGeometry(1, 20, 14)
  hub.scale(0.9, 0.95, 0.95)
  parts.push(hub)
  for (let i = 0; i < 4; i += 1) {
    const blade = new SphereGeometry(1, 18, 12)
    blade.scale(0.16, 1.7, 0.75)
    blade.rotateY(0.55) // 피치
    blade.translate(0, 2.5, 0)
    blade.rotateX((i * Math.PI) / 2 + 0.35)
    parts.push(blade)
  }
  const merged = mergeGeometries(parts.map((part) => part.toNonIndexed())) ?? parts[0]
  merged.translate(5, 5, 0)
  merged.computeVertexNormals()
  return merged
}

/** 블록 도형과 가운데(라벨 끈의 끝점). */
function blockGeometry(place: BlockPlace): { geometry: BufferGeometry; center: Vector3 } {
  const geometry = piecesGeometry(place.pieces, { step: 0.5, rows: 24 })
  return { geometry, center: (geometry.boundingBox ?? new Box3()).getCenter(new Vector3()) }
}

let shapes: Map<string, { geometry: BufferGeometry; center: Vector3 }> | null = null

/** 블록 도형 전부(한 번만 만든다 — 3D를 다시 열어도 다시 계산하지 않음). */
export function blockShapes(): Map<string, { geometry: BufferGeometry; center: Vector3 }> {
  shapes ??= new Map(BLOCK_LAYOUT.map((place) => [place.code, blockGeometry(place)]))
  return shapes
}

/** 이음면 도형(얇은 판) — 블록 이음매만큼 줄이지 않는다. */
export function jointGeometry(joint: Joint): BufferGeometry {
  return piecesGeometry(joint.pieces, { step: 1, rows: 8, gap: 0 })
}
