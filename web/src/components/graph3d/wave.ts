// 3D 물결 전파(순수 함수, wave.test.ts가 검사): 바꾸는 부재가 있는 블록에서 시작해 영향이 번진 순서대로 블록이 차례로 밝아지고,
// 순서가 다른 이웃 블록 사이 이음면에 점선이 흐른다. 2D 영향 지도의 단계별 나타나기·흐르는 점선과 같은 뜻이다.
//
// 순서 근거(지어내지 않는다):
// - 결과에 근거 경로(impacts[].path)가 있으면 블록 홉 순서(relations.ts — 바꾸는 블록 0, 경로를 따라 블록이 바뀔 때마다 +1,
//   영향마다 가장 작은 값 = '1차·2차' 칩과 같은 값). 홉이 없는 블록은 2D와 같은 단계(lib/ripple layersOf, 구성 엔터티 중
//   가장 작은 값)로 그 뒤에. 비어 있는 단계는 당겨 0, 1, 2…로 붙인다.
// - 경로가 없으면 보수적 규칙: 바꾸는 부재(attrs.role) 블록 → 배치 표 이음(ADJACENCY)으로 가까운 순 → 이음으로 닿지 않는
//   나머지. 바꾸는 부재 블록도 없으면 모든 영향 블록이 함께 한 번 밝아진다(순서를 말하지 않는다).
import type { ImpactView } from '@/api/client'
import { layersOf } from '@/lib/ripple'
import type { BlockState } from './blocks'
import { relationPlan } from './relations'

/** 물결 시간(초). 단계 간격은 2D 단계별 나타나기(STEP_MS 520ms)와 비슷하게. */
export const WAVE = {
  /** 단계 하나가 다음 단계보다 앞서는 시간. */
  step: 0.5,
  /** 밝아지는 시간. */
  rise: 0.3,
  /** 다시 어두워지는 시간. */
  fade: 1.2,
  /** 한 바퀴가 끝나고 다음 물결까지 쉬는 시간. */
  rest: 6,
  /** 시작 블록에서 퍼지는 고리의 시간. */
  ring: 1.8,
  /** 처음 그린 뒤 첫 물결까지 기다리는 시간(장면이 자리 잡은 뒤에). */
  delay: 0.6,
} as const

/** 목록에서 고른 블록의 짧은 강조 맥동(초). */
export const FLASH_SECONDS = 1.4

export interface WaveFlow {
  /** 먼저 밝아지는 블록 코드. */
  from: string
  to: string
}

export interface WavePlan {
  /** 블록 코드 → 단계(0부터). 영향 블록(영향 단계가 있거나 바꾸는 부재를 품은 블록)만 들어 있다. */
  steps: Map<string, number>
  /** 물결이 시작하는 블록(단계 0). */
  origins: string[]
  /** 단계가 다른 이웃 블록 쌍(이음면 흐름, 앞 단계 → 뒤 단계). */
  flows: WaveFlow[]
  /** 순서 근거: 결과의 경로·대상 부재(path) · 배치 표 이음(adjacency) · 순서 없음(none). */
  basis: 'path' | 'adjacency' | 'none'
  /** 한 바퀴 시간(초) · 다음 물결까지(초). */
  duration: number
  period: number
}

/** 값의 빈 단계를 당겨 0, 1, 2…로(같은 값은 같은 단계). */
function compress(raw: ReadonlyMap<string, number>): Map<string, number> {
  const ranks = new Map([...new Set(raw.values())].sort((a, b) => a - b).map((value, i) => [value, i]))
  return new Map([...raw].map(([code, value]) => [code, ranks.get(value) ?? 0]))
}

/** 이음으로 잰 거리(origins에서). 닿지 않으면 들어 있지 않다. */
function hops(origins: readonly string[], adjacency: readonly (readonly [string, string])[]): Map<string, number> {
  const distance = new Map(origins.map((code) => [code, 0]))
  const queue = [...origins]
  while (queue.length > 0) {
    const code = queue.shift() as string
    for (const [a, b] of adjacency) {
      const next = a === code ? b : b === code ? a : null
      if (next && !distance.has(next)) {
        distance.set(next, (distance.get(code) ?? 0) + 1)
        queue.push(next)
      }
    }
  }
  return distance
}

export function wavePlan(
  report: ImpactView,
  placed: ReadonlyMap<string, BlockState>,
  adjacency: readonly (readonly [string, string])[],
  blockHops: ReadonlyMap<string, number> = relationPlan(report, placed).hops,
): WavePlan {
  const lit = [...placed.values()].filter((state) => state.severity !== null || state.target)
  const ordered = report.impacts.some((impact) => impact.path.length > 0)
  const raw = new Map<string, number>()
  let basis: WavePlan['basis'] = 'none'
  if (lit.length > 0 && ordered) {
    basis = 'path'
    // 블록 홉 순서(바꾸는 블록 0 → 1차 → 2차 …, relations.ts). 홉이 없는 블록은 지도 단계로 그 뒤에
    const layers = layersOf(report)
    for (const state of lit) {
      const hop = blockHops.get(state.code)
      raw.set(state.code, hop ?? 1000 + Math.min(...state.members.map((id) => layers.get(id) ?? Infinity)))
    }
  } else if (lit.some((state) => state.target)) {
    basis = 'adjacency'
    const distance = hops(lit.filter((state) => state.target).map((state) => state.code), adjacency)
    const far = Math.max(0, ...lit.map((state) => distance.get(state.code) ?? 0)) + 1
    for (const state of lit) raw.set(state.code, distance.get(state.code) ?? far)
  } else {
    for (const state of lit) raw.set(state.code, 0)
  }
  // 구성원이 없거나(바꾸는 부재 표시만) 단계를 못 구한 블록은 맨 끝 단계로
  const known = [...raw.values()].filter(Number.isFinite)
  const tail = known.length ? Math.max(...known) + 1 : 0
  for (const [code, value] of raw) if (!Number.isFinite(value)) raw.set(code, tail)
  const steps = compress(raw)
  const flows: WaveFlow[] = []
  for (const [a, b] of adjacency) {
    const sa = steps.get(a)
    const sb = steps.get(b)
    if (sa === undefined || sb === undefined || sa === sb) continue
    flows.push(sa < sb ? { from: a, to: b } : { from: b, to: a })
  }
  const last = Math.max(0, ...steps.values())
  const duration = steps.size ? Math.max(last * WAVE.step + WAVE.rise + WAVE.fade, WAVE.ring) : 0
  return {
    steps,
    origins: [...steps].filter(([, step]) => step === 0).map(([code]) => code).sort(),
    flows,
    basis,
    duration,
    period: duration + WAVE.rest,
  }
}

/** 물결 시작에서 지난 시간(초, 반복 주기 안) — 시작 전이면 음수. */
export function wavePhase(elapsed: number, period: number): number {
  if (elapsed < 0 || period <= 0) return elapsed
  return elapsed % period
}

/** 단계 step 블록의 물결 밝기(0~1): 차례가 오면 부드럽게 밝아졌다가 천천히 어두워진다. */
export function waveGlow(step: number, phase: number): number {
  const t = phase - step * WAVE.step
  if (t <= 0) return 0
  if (t < WAVE.rise) {
    const x = t / WAVE.rise
    return x * x * (3 - 2 * x)
  }
  const fade = (t - WAVE.rise) / WAVE.fade
  return fade >= 1 ? 0 : (1 - fade) * (1 - fade)
}

/** 시작 블록에서 퍼지는 고리: 반지름 배율(0~1)과 불투명도(0~1). 끝났으면 null. */
export function ringAt(phase: number): { scale: number; opacity: number } | null {
  if (phase < 0 || phase > WAVE.ring) return null
  const x = phase / WAVE.ring
  const scale = 1 - (1 - x) * (1 - x)
  return { scale, opacity: (1 - x) * Math.min(1, x * 6) }
}

/** 움직임 시계(초, performance.now 기준). 블록·고리가 프레임마다 같은 값을 읽는다. */
export interface MotionClock {
  /** 첫 물결 시작 시각(이후 plan.period마다 반복). */
  waveStart: number
  /** 마지막 강조 맥동 시작 시각(없으면 -Infinity). */
  flashStart: number
}

export const seconds = () => performance.now() / 1000

/** 지금 물결 한 바퀴(또는 강조 맥동) 안인가 — 이때만 초당 30장으로 그린다. */
export function busy(clock: MotionClock, plan: Pick<WavePlan, 'steps' | 'duration' | 'period'>, now: number): boolean {
  const phase = wavePhase(now - clock.waveStart, plan.period)
  const waving = plan.steps.size > 0 && phase >= 0 && phase <= plan.duration
  return waving || (now >= clock.flashStart && now - clock.flashStart <= FLASH_SECONDS)
}

/** 고른 블록 강조 맥동(0~1): 한 번 부드럽게 밝아졌다 돌아온다(깜빡임 없음). */
export function flashGlow(elapsed: number): number {
  if (elapsed < 0 || elapsed > FLASH_SECONDS) return 0
  return (1 - Math.cos((elapsed / FLASH_SECONDS) * 2 * Math.PI)) / 2
}
