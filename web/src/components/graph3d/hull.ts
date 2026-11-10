// 가상 선형(합성 호선 S-001, 수에즈막스 원유운반선): 해석식으로 만든 선체 모양(순수 함수, layout.test.ts가 검사).
// 공개된 수에즈막스급 대표 주요 치수에 맞춘 가상 배치이고 실제 도면이 아니다. 출처가 확실하지 않은 값은 범위 가운데의 둥근 값.
// 좌표(m): x = 선미 → 선수(AP 0, FP 264), y = 기선에서 위로, z = 우현(+)·좌현(−).
//
// - 주요 치수: 전장 274(트랜섬 x −5 ~ 구상선수 앞끝 x 269) · 수선간장 264 · 폭 48 · 형깊이 23 · 설계 흘수 17.
// - 평행 중앙부 x 62~205(수선간장의 약 54%): 반폭 24 · 빌지 반지름 2.5.
// - 선미(x < 62): 아래쪽부터 오므라져 스케그로. 선미재(x 9) 뒤는 프로펠러·러더 자리로 비고, 그 위 카운터가 트랜섬(아랫면 y 16)까지
//   올라간다. 트랜섬 반폭은 선체 반폭의 약 74%.
// - 선수(x > 205): 위쪽은 플레어로 통통하게, 아래쪽은 가늘게 선수재까지. 선수재는 흘수선에서 FP, 위로 앞으로 기운다.
//   구상선수(앞끝 x 269, 중심 높이 6, 아래 4.8 · 위 6.5 · 폭 6.8)는 몸체와 부드럽게 이어 붙인다.
// - 설계 흘수 17에 흘수선(geometry.ts waterLine)을 긋고, 외판 껍질은 흘수선 아래를 조금 짙게 그린다.
// - 선수루: x 240부터 갑판이 3m 높다(26).

export const SHIP = {
  aftEnd: -5,
  fwdEnd: 269,
  lbp: 264,
  halfBreadth: 24,
  depth: 23,
  draft: 17,
  bilge: 2.5,
  forecastle: 26,
  forecastleAft: 240,
  /** 평행 중앙부 뒤 끝 · 앞 끝. */
  runEnd: 62,
  entrance: 205,
  /** 선미재(스케그 뒤 끝) · 그 뒤 카운터 아랫면 높이(선미재 → 트랜섬). */
  sternPost: 9,
  counterLow: 10.5,
  transomLow: 16,
} as const

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
const smooth = (t: number) => {
  const u = clamp(t, 0, 1)
  return u * u * (3 - 2 * u)
}

/** 갑판 높이: 선수루(x 240부터 2.5m 사이에 3m 올라감) 앞은 26m, 그 밖은 형깊이. */
export function deckAt(x: number): number {
  return SHIP.depth + (SHIP.forecastle - SHIP.depth) * smooth((x - SHIP.forecastleAft) / 2.5)
}

/** 선체 아래 끝: 선미재 앞은 기선(0), 뒤는 카운터(선미재 10.5 → 트랜섬 16으로 올라감). */
export function bottomAt(x: number): number {
  const { sternPost, counterLow, transomLow, aftEnd } = SHIP
  if (x >= sternPost) return 0
  return counterLow + ((sternPost - x) / (sternPost - aftEnd)) * (transomLow - counterLow)
}

/** 선수재 위치: 흘수선(17)에서 FP(264), 위로는 앞으로 기울고, 12 아래는 포어풋으로 뒤로 휜다(기선에서 x 약 252). */
export function stemX(y: number): number {
  if (y >= 12) return SHIP.lbp + (y - SHIP.draft) * 0.3
  const s = 12 - y
  return SHIP.lbp - 1.5 - 0.3 * s - 0.05 * s * s
}

/** 평행 중앙부 단면의 반폭(빌지 원호). */
function midWidth(y: number): number {
  const { halfBreadth: b, bilge: r } = SHIP
  if (y >= r) return b
  return b - r + Math.sqrt(Math.max(0, r * r - (r - y) ** 2))
}

/** 선미 몸체 반폭: 바닥 반폭이 x 14에서 0으로, 갑판 반폭은 트랜섬에서 74%로. 아래 → 위로 섞는 높이는 뒤로 갈수록 높다. */
function aftWidth(x: number, y: number): number {
  const { runEnd, aftEnd, sternPost, halfBreadth: b } = SHIP
  if (x >= runEnd) return Infinity
  const deckW = b * (1 - 0.26 * smooth((runEnd - x) / (runEnd - aftEnd)) ** 1.4)
  const keelW = b * clamp(1 - (runEnd - x) / (runEnd - 14), 0, 1) ** 1.3
  const t = smooth((runEnd - x) / (runEnd - sternPost))
  const reach = 3 + 19 * t
  const h = clamp(y / reach, 0, 1)
  // 중앙부 쪽은 U자(빌지가 둥근 단면), 선미재 쪽은 V자(프로펠러 위로 갈수록 넓어지는 단면)
  const blend = (1 - t) * (1 - (1 - h) ** 1.6) + t * h
  const width = keelW + (deckW - keelW) * blend
  // 스케그(중심선 판, 프로펠러 축 아래·앞): 반 두께 0.9
  if (x >= sternPost && x < 34 && y < 10) return Math.max(width, 0.9 * (1 - smooth((x - 26) / 8)) + 0.05)
  return width
}

/** 선수 몸체 비율(1 = 중앙부 반폭, 0 = 선수재 앞). 위쪽일수록 늦게 오므라든다(플레어). */
function bowFactor(x: number, y: number): number {
  const start = SHIP.entrance
  const end = stemX(y)
  if (x <= start) return 1
  if (x >= end) return 0
  const f = (x - start) / (end - start)
  const up = clamp(y / SHIP.depth, 0, 1)
  return (1 - f ** (1.8 + 1.6 * up)) ** (0.8 - 0.15 * up)
}

/**
 * 구상선수 반폭: 앞쪽 13m는 타원체 코, 그 뒤는 단면 일정(몸체 안으로 들어가 보이지 않음). 윗쪽 반지름을 크게 잡아 위 끝이
 * 포어풋(선수재 아래)과 겹치게 한다 — 단면마다 선체가 한 덩어리로 이어져 로프트가 끊기지 않는다.
 */
function bulbWidth(x: number, y: number): number {
  const nose = SHIP.fwdEnd
  const length = 13
  const below = 4.8
  const above = 6.5
  const rh = 3.4
  const cy = 6
  if (x > nose || x < 236) return 0
  const u = Math.max(0, (x - (nose - length)) / length)
  const s = Math.sqrt(Math.max(0, 1 - u * u))
  const rv = (y > cy ? above : below) * s
  const dy = (y - cy) / (rv || 1e-9)
  return Math.abs(dy) < 1 ? rh * s * Math.sqrt(1 - dy * dy) : 0
}

/** 부드러운 최댓값(구상선수와 몸체 이음 — 모서리 대신 필릿). 둘 중 하나가 0이면 보통 최댓값. */
function smoothMax(a: number, b: number, k: number): number {
  if (a <= 0 || b <= 0) return Math.max(a, b)
  const h = clamp(0.5 + (0.5 * (b - a)) / k, 0, 1)
  return a + (b - a) * h + k * h * (1 - h)
}

/** 선체 안쪽의 반폭(x, y에서 |z| ≤ 반폭이면 선체 안). 선체 밖이면 0. */
export function halfBreadth(x: number, y: number): number {
  if (x < SHIP.aftEnd || x > SHIP.fwdEnd || y < 0 || y > deckAt(x)) return 0
  const body = y < bottomAt(x) ? 0 : Math.min(midWidth(y), aftWidth(x, y)) * bowFactor(x, y)
  return smoothMax(body, bulbWidth(x, y), 1.2)
}

/** 조각: 선체 안 ∩ 상자. mode는 z 범위를 고르는 방법(외판에서 두께 t만큼 = 선측, 외판에서 t 안쪽 = 횡격벽·플랫). */
export interface Piece {
  x: readonly [number, number]
  y: readonly [number, number]
  z?: readonly [number, number]
  mode?: 'full' | 'port' | 'stbd' | 'inner'
  t?: number
  /** 호퍼(이중선측 아래 경사판): y0에서 위로 h 사이에 두께가 w(아래 끝)에서 0까지 더해진다. */
  hopper?: { y0: number; h: number; w: number }
  /** 선체와 상관없는 상자(러더·상부 구조). */
  box?: boolean
  /** 상자 안에 그릴 모양(러더 날개 · 프로펠러 축 보스). 겹침 검사는 상자로 한다. */
  shape?: 'rudder' | 'boss'
}

/** 조각의 y 높이에서 외판 두께(호퍼 포함). */
export function thicknessAt(piece: Piece, y: number): number {
  const base = piece.t ?? 0
  const hopper = piece.hopper
  if (!hopper) return base
  return base + hopper.w * clamp(1 - (y - hopper.y0) / hopper.h, 0, 1)
}

/** 조각의 (x, y) 단면에서 z 범위. 비어 있으면 null. */
export function zRange(piece: Piece, x: number, y: number): [number, number] | null {
  const [z0, z1] = piece.z ?? [-Infinity, Infinity]
  if (piece.box) return [z0, z1]
  const hb = halfBreadth(x, y)
  if (hb <= 0) return null
  const t = thicknessAt(piece, y)
  // 선측 띠는 중심선을 넘지 않는다(선미 스케그처럼 반폭이 두께보다 좁은 곳에서 좌·우 띠가 겹치지 않게)
  const range: [number, number] =
    piece.mode === 'port'
      ? [-hb, Math.min(-hb + t, 0)]
      : piece.mode === 'stbd'
        ? [Math.max(hb - t, 0), hb]
        : piece.mode === 'inner'
          ? [-hb + t, hb - t]
          : [-hb, hb]
  const lo = Math.max(range[0], z0)
  const hi = Math.min(range[1], z1)
  return lo < hi ? [lo, hi] : null
}

/** 점이 조각 안에 있나(경계는 밖으로 — 맞닿은 블록끼리 겹침 검사가 경계에서 걸리지 않게). */
export function pieceContains(piece: Piece, [x, y, z]: readonly [number, number, number]): boolean {
  if (!(x > piece.x[0] && x < piece.x[1] && y > piece.y[0] && y < piece.y[1])) return false
  const range = zRange(piece, x, y)
  return range !== null && z > range[0] && z < range[1]
}

/** 단면 하나: 아래 → 위 행마다 왼쪽·오른쪽 z. empty면 그 x에 조각이 없다. */
export interface Section {
  x: number
  empty: boolean
  rows: { y: number; left: number; right: number }[]
}

/**
 * 조각의 x 단면을 rows+1개 행으로. 행 높이는 그 단면에서 조각이 실제로 있는 범위(아래·위 끝)에 맞춘다 — 갑판·트랜섬·카운터
 * 높이가 단면마다 달라도 윗면·아랫면이 그 높이를 따른다. gap만큼 안쪽으로 줄여 블록 사이 이음매를 보인다.
 */
export function sectionOf(piece: Piece, x: number, rows: number, gap = 0): Section {
  const y0 = piece.y[0] + gap
  const y1 = Math.min(piece.y[1], piece.box ? piece.y[1] : deckAt(x)) - gap
  let low = Infinity
  let high = -Infinity
  const scan = Math.max(0.02, Math.min(0.1, (y1 - y0) / 40))
  for (let y = y0; y <= y1 + 1e-9; y += scan) {
    const at = Math.min(y, y1)
    const range = zRange(piece, x, at)
    if (range && range[1] - range[0] > 2 * gap) {
      low = Math.min(low, at)
      high = Math.max(high, at)
    }
  }
  const [cz0, cz1] = piece.z ?? [0, 0]
  const center = clamp(0, Number.isFinite(cz0) ? cz0 : -1e6, Number.isFinite(cz1) ? cz1 : 1e6)
  const empty = !Number.isFinite(low) || high - low < 1e-6
  const out: Section = { x, empty, rows: [] }
  for (let k = 0; k <= rows; k += 1) {
    const y = empty ? y0 : low + ((high - low) * k) / rows
    const range = empty ? null : zRange(piece, x, y)
    if (range && range[1] - range[0] > 2 * gap) out.rows.push({ y, left: range[0] + gap, right: range[1] - gap })
    else out.rows.push({ y, left: center, right: center })
  }
  return out
}
