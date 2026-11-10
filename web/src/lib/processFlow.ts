// 일정 탭의 공정 흐름(엔진 0.10.0, docs/engine.md(비용·일정) 6-1): 늦어지는 블록마다 블록 공정 일곱(소조립 → … → PE →
// 탑재)과 늘어난 일수, 그 뒤 구역 출구 → (후행 의장·선체도장 — 공정도 표시용, 계산하지 않음) → 진수 → 시운전 → 인도 이정표.
// 숫자는 결과의 schedule 필드(공정별 늘어난 일수·구역 출구·인도) 그대로이고, 여기서는 공정 ID를 블록·공정으로 나눠
// 순서대로 늘어놓기만 한다. 진수·시운전은 일정 망에 들지 않아(인도는 경계 조건) 늘어난 일수가 없다.
import type { AnalysisResult } from '@/api/client'
import { ACTIVITY_NAMES, codeOf, zoneName } from './labels'

/** 블록 공정 순서(엔진 BLOCK_ACTIVITY_ORDER, 1.32.0 PE 포함). */
export const BLOCK_PROCESS_ORDER = [
  'sub_assembly',
  'panel',
  'assembly',
  'pre_outfitting',
  'pre_painting',
  'pre_erection',
  'erection',
] as const

export interface FlowStep {
  kind: string
  name: string
  /** 늘어난 일수(0 = 그대로). 계산하지 않는 이정표는 null. */
  days: number | null
}

export interface BlockFlow {
  /** 블록 코드(호선 뺀 것, 예: B31P). */
  block: string
  steps: FlowStep[]
}

export interface ProcessFlow {
  /** 늦어지는 공정이 있는 블록(탑재 지연 큰 순 → 가장 크게 늘어난 공정 순 → 블록 코드 순). */
  blocks: BlockFlow[]
  /** 블록 공정으로 읽지 못한 늦어지는 공정(엑셀로 가져온 지도의 다른 ID 꼴 등) — 표로 따로 보인다. */
  others: { id: string; days: number }[]
  /** 구역 출구(가장 늦는 곳) → 진수 → 시운전 → 인도. 인도는 계산하지 못했으면 days null + unknown. */
  milestones: { exit: { zone: string | null; days: number }; delivery: { days: number | null } }
}

const BLOCK_KINDS = new Set<string>(BLOCK_PROCESS_ORDER)

/** 'S-001:B31P:pre_erection' → ['S-001:B31P', 'pre_erection']. 블록 공정 꼴이 아니면 null. */
function splitId(id: string): [string, string] | null {
  const at = id.lastIndexOf(':')
  if (at <= 0) return null
  const [block, kind] = [id.slice(0, at), id.slice(at + 1)]
  return BLOCK_KINDS.has(kind) && block.includes(':') ? [block, kind] : null
}

export function processFlow(result: Pick<AnalysisResult, 'schedule'>): ProcessFlow {
  const { schedule } = result
  const exitIds = new Set(schedule.zone_exits.map((exit) => exit.exit_activity_id))
  const byBlock = new Map<string, Map<string, number>>()
  const others: { id: string; days: number }[] = []
  for (const [id, days] of Object.entries(schedule.added_days_by_activity ?? {})) {
    if (days <= 0 || exitIds.has(id)) continue
    const parts = splitId(id)
    if (!parts) {
      others.push({ id, days })
      continue
    }
    const [block, kind] = parts
    byBlock.set(block, (byBlock.get(block) ?? new Map()).set(kind, days))
  }
  const blocks = [...byBlock.entries()]
    .map(([block, days]) => ({
      block,
      erection: days.get('erection') ?? 0,
      most: Math.max(...days.values()),
      steps: BLOCK_PROCESS_ORDER.map((kind) => ({ kind, name: ACTIVITY_NAMES[kind], days: days.get(kind) ?? 0 })),
    }))
    .sort((a, b) => b.erection - a.erection || b.most - a.most || a.block.localeCompare(b.block))
    .map(({ block, steps }) => ({ block: codeOf(block), steps }))
  const worst = schedule.zone_exits.find((exit) => exit.delay_days === schedule.max_exit_delay_days)
  const late = schedule.max_exit_delay_days > 0 && worst !== undefined
  return {
    blocks,
    others: others.sort((a, b) => b.days - a.days || a.id.localeCompare(b.id)),
    milestones: {
      exit: { zone: late ? zoneName(worst) : null, days: late ? schedule.max_exit_delay_days : 0 },
      delivery: { days: schedule.delivery ? schedule.delivery.added_delay_days : null },
    },
  }
}

/** 늘어난 일수 글: '+9일' · '그대로'. */
export function stepDays(days: number | null): string {
  if (days === null) return ''
  return days > 0 ? `+${days}일` : '그대로'
}

/** 공정 흐름 칸의 뜻(화면은 일정 탭 'ⓘ 계산 기준', DESIGN.md 6절 일정 탭). */
export const FLOW_BASIS =
  '후행 의장·선체도장: 표시용(일정 계산 제외) · 진수·시운전·인도: 이정표 · 인도 지연 = 구역 출구 → 인도 여유로 계산'
