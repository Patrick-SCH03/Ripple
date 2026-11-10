import { describe, expect, it } from 'vitest'
import config from '../../../../generator/config.yaml?raw'
import { SHIP, bottomAt, deckAt, halfBreadth, pieceContains, sectionOf, stemX, thicknessAt, zRange, type Piece } from './hull'
import {
  ADJACENCY,
  BLOCK_LAYOUT,
  CARGO_AFT,
  CARGO_FWD,
  CONTEXT_LABELS,
  DB,
  HOPPER,
  JOINT,
  JOINTS,
  SIDE,
  VIEWS,
  contextPieces,
  jointOf,
  superstructurePieces,
  tankAft,
} from './layout'

/** generator/config.yaml의 blocks 줄(`- {code: B31P, zone: ZCT, name: …, …}`)과 adjacency 줄(`- [B31P, B31S]`). */
function configBlocks(): { code: string; zone: string; name: string }[] {
  return [...config.matchAll(/^\s*- \{code: (\w+), zone: (\w+), name: ([^,]+),/gm)].map((m) => ({
    code: m[1],
    zone: m[2],
    name: m[3].trim(),
  }))
}

function configAdjacency(): string[] {
  const section = config.slice(config.indexOf('adjacency:'), config.indexOf('activities:'))
  return [...section.matchAll(/- \[(\w+), (\w+)\]/g)].map((m) => [m[1], m[2]].sort().join('-')).sort()
}

const block = (code: string) => {
  const found = BLOCK_LAYOUT.find((b) => b.code === code)
  if (!found) throw new Error(code)
  return found
}
const inBlock = (code: string, p: readonly [number, number, number]) => block(code).pieces.some((piece) => pieceContains(piece, p))

// 격자 겹침 검사는 혼자 2초 안팎이지만, 로컬 CI처럼 다른 검사와 같이 돌면 기본 5초를 넘을 수 있다
const GRID_TIMEOUT = 30_000

describe('배치 표 = 합성 지도 설정', () => {
  it('블록 코드·구역·이름이 generator/config.yaml과 같다', () => {
    const blocks = configBlocks()
    expect(blocks).toHaveLength(14)
    expect(BLOCK_LAYOUT.map((b) => ({ code: b.code, zone: b.zone, name: b.name })).sort((a, b) => a.code.localeCompare(b.code))).toEqual(
      blocks.sort((a, b) => a.code.localeCompare(b.code)),
    )
  })

  it('블록 이음이 adjacency와 같다', () => {
    expect(ADJACENCY.map((pair) => [...pair].sort().join('-')).sort()).toEqual(configAdjacency())
  })
})

type Entity = { id: string; pieces: Piece[] }

function entities(): Entity[] {
  return [
    ...BLOCK_LAYOUT.map((b) => ({ id: b.code, pieces: b.pieces })),
    ...contextPieces().map((piece, i) => ({ id: `context-${i}`, pieces: [piece] })),
    ...superstructurePieces().map((piece, i) => ({ id: `super-${i}`, pieces: [piece] })),
  ]
}

/** 격자 점마다 그 점을 품은 블록·맥락 조각 수를 세어 둘 이상인 곳(겹침)을 찾는다. */
function overlaps(range: { x: [number, number, number]; y: [number, number, number]; z: [number, number, number] }) {
  const all = entities()
  const found = new Set<string>()
  const counts = new Map<string, number>()
  for (let x = range.x[0]; x < range.x[1]; x += range.x[2]) {
    const near = all.filter((e) => e.pieces.some((p) => x > p.x[0] && x < p.x[1]))
    for (let y = range.y[0]; y < range.y[1]; y += range.y[2]) {
      for (let z = range.z[0]; z < range.z[1]; z += range.z[2]) {
        const inside = near.filter((e) => e.pieces.some((p) => pieceContains(p, [x, y, z]))).map((e) => e.id)
        for (const id of inside) counts.set(id, (counts.get(id) ?? 0) + 1)
        if (inside.length > 1) found.add(inside.sort().join('+'))
      }
    }
  }
  return { found: [...found], counts }
}

describe('블록이 서로 겹치지 않는다', () => {
  it('No.3 COT(이중저·선측·종격벽·횡격벽·갑판): 촘촘한 격자', () => {
    const { found, counts } = overlaps({ x: [142.07, 178, 0.37], y: [0.03, 24, 0.29], z: [-24.9, 25, 0.31] })
    expect(found).toEqual([])
    for (const code of ['B31P', 'B31S', 'S31P', 'S31S', 'L31C', 'T31C', 'D31C']) expect(counts.get(code) ?? 0).toBeGreaterThan(20)
  }, GRID_TIMEOUT)

  it('배 전체(선미·기관실·펌프룸·선수·상부 구조): 성긴 격자', () => {
    const { found, counts } = overlaps({ x: [-5.93, 270, 0.61], y: [0.07, 47, 0.37], z: [-24.9, 25, 0.53] })
    expect(found).toEqual([])
    for (const b of BLOCK_LAYOUT) expect(counts.get(b.code) ?? 0, b.code).toBeGreaterThan(5)
  }, GRID_TIMEOUT)

  it('선미·선수 블록 둘레: 촘촘한 격자', () => {
    expect(overlaps({ x: [-5.93, 50, 0.29], y: [0.07, 24, 0.23], z: [-24.9, 25, 0.41] }).found).toEqual([])
    expect(overlaps({ x: [236.1, 270, 0.27], y: [0.07, 27, 0.21], z: [-24.9, 25, 0.37] }).found).toEqual([])
  }, GRID_TIMEOUT)

  it('블록은 선체 안에 있다(러더·보스 상자 빼고)', () => {
    for (const b of BLOCK_LAYOUT) {
      for (const piece of b.pieces.filter((p) => !p.box)) {
        for (const f of [0.1, 0.5, 0.9]) {
          const x = piece.x[0] + (piece.x[1] - piece.x[0]) * f
          const section = sectionOf(piece, x, 8)
          if (section.empty) continue
          for (const row of section.rows) {
            expect(Math.abs(row.left)).toBeLessThanOrEqual(halfBreadth(x, row.y) + 1e-6)
            expect(Math.abs(row.right)).toBeLessThanOrEqual(halfBreadth(x, row.y) + 1e-6)
            expect(row.left).toBeLessThanOrEqual(row.right)
          }
        }
      }
    }
  })

  it('라벨 자리는 블록마다 다르고 맥락 이름표도 겹치지 않는다', () => {
    const keys = [...BLOCK_LAYOUT.map((b) => b.label.join(',')), ...CONTEXT_LABELS.map((l) => l.at.join(','))]
    expect(new Set(keys).size).toBe(keys.length)
  })
})

describe('블록이 빈틈 없이 맞물린다', () => {
  /** 선체 안 격자 점 중 기대한 블록에 들지 않는 점의 비율(경계에서 0.12m 안쪽은 건너뜀). */
  function missRate(region: { x: [number, number]; y: [number, number] }, expected: (p: [number, number, number]) => string | null) {
    let total = 0
    let miss = 0
    for (let x = region.x[0] + 0.21; x < region.x[1] - 0.12; x += 0.53) {
      for (let y = region.y[0] + 0.17; y < region.y[1] - 0.12; y += 0.31) {
        const hb = halfBreadth(x, y)
        for (let z = -hb + 0.13; z < hb - 0.12; z += 0.47) {
          const code = expected([x, y, z])
          if (!code) continue
          total += 1
          if (!inBlock(code, [x, y, z])) miss += 1
        }
      }
    }
    return { total, rate: total ? miss / total : 1 }
  }

  it('No.3 COT 외곽 구조(이중저·이중선측·호퍼·갑판·종격벽·횡격벽)는 블록으로 다 덮인다', () => {
    const x0 = tankAft(3)
    const near = (v: number, edge: number) => Math.abs(v - edge) < 0.12
    const { total, rate } = missRate({ x: [x0, x0 + 32], y: [0, SHIP.depth] }, ([x, y, z]) => {
      const hb = halfBreadth(x, y)
      const t = SIDE + HOPPER.w * Math.min(1, Math.max(0, 1 - (y - DB) / HOPPER.h))
      if (near(y, DB) || near(y, SHIP.depth - 1.5) || near(Math.abs(z), hb - t) || near(z, 0) || near(Math.abs(z), 0.45) || near(x, x0 + 1.5))
        return null
      if (y < DB) return z < 0 ? 'B31P' : 'B31S'
      if (y > SHIP.depth - 1.5) return 'D31C'
      if (Math.abs(z) > hb - t) return z < 0 ? 'S31P' : 'S31S'
      if (x < x0 + 1.5) return 'T31C'
      if (Math.abs(z) < 0.45) return 'L31C'
      return null // 화물 공간
    })
    expect(total).toBeGreaterThan(2000)
    expect(rate).toBe(0)
  })

  it('기관실 이중저·선미·펌프룸·선수 평형수탱크·구상선수는 그 구획을 다 덮는다', () => {
    const cases: [string, { x: [number, number]; y: [number, number] }][] = [
      ['E11C', { x: [12, 42], y: [0, 3] }],
      ['P11C', { x: [42, CARGO_AFT], y: [0, SHIP.depth] }],
      ['A11C', { x: [SHIP.aftEnd, 12], y: [0, SHIP.transomLow] }],
      ['F21C', { x: [244, 256], y: [0, SHIP.depth] }],
      ['F11C', { x: [256, SHIP.fwdEnd], y: [0, 12] }],
    ]
    for (const [code, region] of cases) {
      const { total, rate } = missRate(region, () => code)
      expect(total, code).toBeGreaterThan(50)
      expect(rate, code).toBe(0)
    }
  })

  it('맞닿은 이웃 블록마다 이음면이 있고, 이음면 양쪽이 두 블록 안이다', () => {
    const touching = ADJACENCY.filter(([a, b]) => jointOf(a, b))
    expect(touching).toHaveLength(ADJACENCY.length - 1)
    expect(jointOf('P11C', 'T31C')).toBeUndefined() // 펌프룸과 No.3 횡격벽은 배치 표에서 떨어져 있다(화면은 낮은 호)
    const mid = (r: readonly [number, number]) => (r[0] + r[1]) / 2
    const span = (r: readonly [number, number], step: number) => {
      const out: number[] = []
      for (let v = r[0] + 0.2; v < r[1] - 0.1; v += step) out.push(v)
      return out
    }
    for (const joint of JOINTS) {
      const [a, b] = joint.pair
      const axis = { x: 0, y: 1, z: 2 }[joint.axis]
      let total = 0
      let hit = 0
      for (const piece of joint.pieces) {
        const xs = joint.axis === 'x' ? [mid(piece.x)] : span(piece.x, 0.9)
        const ys = joint.axis === 'y' ? [mid(piece.y)] : span(piece.y, 0.33)
        for (const x of xs) {
          for (const y of ys) {
            const range = zRange(piece, x, y)
            if (!range) continue
            const zs = joint.axis === 'z' ? [mid(range)] : span([Math.max(range[0], -40), Math.min(range[1], 40)], 0.37)
            for (const z of zs) {
              const plus: [number, number, number] = [x, y, z]
              const minus: [number, number, number] = [x, y, z]
              plus[axis] += JOINT + 0.05
              minus[axis] -= JOINT + 0.05
              total += 1
              if ((inBlock(a, plus) && inBlock(b, minus)) || (inBlock(b, plus) && inBlock(a, minus))) hit += 1
            }
          }
        }
      }
      // 이음면 가장자리(외판·호퍼 안쪽 끝)에서는 위아래 0.2m 사이에 선체 폭이 달라 한쪽이 비껴 나간다 — 특히 스케그 쪽
      // 기관실 앞뒤는 위로 갈수록 빠르게 넓어진다. 그래서 전부가 아니라 대부분(80%)을 본다.
      expect(total, joint.pair.join('-')).toBeGreaterThan(10)
      expect(hit / total, joint.pair.join('-')).toBeGreaterThan(0.8)
    }
  })
})

describe('선형(공개 대표 치수에 맞춘 가상 선형)', () => {
  it('주요 치수: 전장 274 · 수선간장 264 · 폭 48 · 형깊이 23 · 흘수 17', () => {
    expect(SHIP.fwdEnd - SHIP.aftEnd).toBe(274)
    expect(SHIP.lbp).toBe(264)
    expect(2 * SHIP.halfBreadth).toBe(48)
    expect(SHIP.depth).toBe(23)
    expect(SHIP.draft).toBe(17)
    // 선수재는 흘수선에서 FP, 구상선수가 가장 앞
    expect(stemX(SHIP.draft)).toBe(SHIP.lbp)
    let front = 0
    for (let y = 0; y <= deckAt(260); y += 0.1) for (let x = 250; x <= 270; x += 0.05) if (halfBreadth(x, y) > 0) front = Math.max(front, x)
    expect(front).toBeGreaterThan(SHIP.fwdEnd - 0.2)
  })

  it('구획 비율: 이중저·이중선측 2~3m, 화물탱크 6쌍 × 32m, 충돌격벽은 FP 뒤 0.05L~0.08L', () => {
    expect(DB).toBeGreaterThanOrEqual(2)
    expect(DB).toBeLessThanOrEqual(3)
    expect(SIDE).toBeGreaterThanOrEqual(2)
    expect(SIDE).toBeLessThanOrEqual(3)
    expect(CARGO_FWD - CARGO_AFT).toBe(6 * 32)
    const collision = SHIP.lbp - 244
    expect(collision).toBeGreaterThanOrEqual(0.05 * SHIP.lbp)
    expect(collision).toBeLessThanOrEqual(0.08 * SHIP.lbp)
    expect(thicknessAt({ x: [0, 1], y: [0, 1], t: SIDE, hopper: HOPPER }, DB)).toBe(SIDE + HOPPER.w)
    expect(thicknessAt({ x: [0, 1], y: [0, 1], t: SIDE, hopper: HOPPER }, DB + HOPPER.h)).toBe(SIDE)
  })

  it('평행 중앙부는 반폭 24 · 형깊이 23 · 빌지 원호, No.3 COT는 그 안', () => {
    expect(halfBreadth(150, 10)).toBe(SHIP.halfBreadth)
    expect(halfBreadth(150, 0.2)).toBeLessThan(SHIP.halfBreadth - 1)
    expect(deckAt(150)).toBe(SHIP.depth)
    expect(halfBreadth(150, SHIP.depth + 0.1)).toBe(0)
    expect(SHIP.runEnd).toBeLessThan(tankAft(3))
    expect(SHIP.entrance).toBeGreaterThan(tankAft(3) + 32)
  })

  it('선수·선미로 갈수록 오므라들고 위쪽이 아래쪽보다 넓다(플레어·V자 선미)', () => {
    for (const x of [20, 40, 230, 250]) {
      expect(halfBreadth(x, 4)).toBeLessThan(SHIP.halfBreadth)
      expect(halfBreadth(x, 4)).toBeLessThan(halfBreadth(x, 20))
    }
    expect(halfBreadth(240, 10)).toBeGreaterThan(halfBreadth(255, 10))
    // 트랜섬은 선체 폭의 약 74%
    expect(halfBreadth(SHIP.aftEnd + 0.01, SHIP.depth - 0.01) / SHIP.halfBreadth).toBeCloseTo(0.74, 1)
  })

  it('구상선수는 선수재 앞으로 튀어나오고, 프로펠러 자리는 비어 있고, 선수루는 높다', () => {
    expect(halfBreadth(266, 6)).toBeGreaterThan(1)
    expect(halfBreadth(266, 15)).toBe(0)
    expect(halfBreadth(5, 6)).toBe(0) // 프로펠러 원판 자리
    expect(bottomAt(5)).toBeGreaterThan(5 + 4.2) // 카운터가 프로펠러 날개 끝 위
    expect(halfBreadth(3, 18)).toBeGreaterThan(5)
    expect(deckAt(250)).toBe(SHIP.forecastle)
  })

  it('선체 단면은 껍질을 나눈 높이 구간마다 한 덩어리다(로프트가 끊기지 않게)', () => {
    const bands: [number, number][] = [
      [0, 12],
      [12, SHIP.draft],
      [SHIP.draft, SHIP.forecastle + 1],
    ]
    for (let x = SHIP.aftEnd; x <= SHIP.fwdEnd; x += 0.25) {
      for (const [lo, hi] of bands) {
        let runs = 0
        let inside = false
        for (let y = lo; y <= Math.min(hi, deckAt(x)); y += 0.05) {
          const now = halfBreadth(x, y) > 0.02
          if (now && !inside) runs += 1
          inside = now
        }
        expect(runs, `x ${x} y ${lo}~${hi}`).toBeLessThanOrEqual(1)
      }
    }
  })

  it('시점 상자는 배 안의 범위', () => {
    for (const view of VIEWS) {
      expect(view.box[0][0]).toBeLessThan(view.box[1][0])
      expect(view.box[0][0]).toBeGreaterThanOrEqual(SHIP.aftEnd - 2)
      expect(view.box[1][0]).toBeLessThanOrEqual(SHIP.fwdEnd + 2)
    }
  })
})
