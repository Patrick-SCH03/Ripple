// 소개 화면 예시: example.json(엔진이 만든 값, scripts/export_showcase.py — 검사가 지금 엔진 결과와 같은지 본다)을
// 그림 카드·판정 상자 문구로 바꾼다. 숫자는 모두 JSON에서 온다(DESIGN.md 10절: 결과에 없는 지표를 만들지 않음).
import type { CostItem } from '@/api/client'
import { COST_ITEM_NAMES, formatHours } from '@/lib/costSplit'
import { addDays, daysBetween, formatDay } from '@/lib/format'
import { BLOCK_STAGE_NAMES, IMPACT_NAMES, PART_KIND_NAMES, PO_STATUS_NAMES, VERDICT_NAMES } from '@/lib/labels'
import { formatMoney, formatRange } from '@/lib/money'
import { formatDelta } from '@/lib/weightChange'
import data from './example.json'

export interface ShowcaseNode {
  key: string
  parent: string | null
  relation: string
  entity_type: string
  impacts: string[]
  severity: 'low' | 'medium' | 'high' | 'info'
  count: number
  amount: number
  name?: string
  full_name?: string
  stage?: string | null
  kinds?: Record<string, number>
}

export interface Showcase {
  source: string
  ecn_id: string
  title: string
  as_of: string
  change: { op: string; block: string; block_name: string; part_count: number; from_mm: number | null; to_mm: number | null; amount: number }
  verdict: { level: string; reasons: string[] }
  total: { value: number; low: number; high: number }
  deadline: string | null
  impact_count: number
  cost_line_count: number
  zone_exit: { name: string; delay_days: number } | null
  /** 결정 기한에 확정할 때 구역 출구 예상 최대 지연(곡선 값). */
  deadline_exit_days: number | null
  /** 결정 기한 다음 날 확정하면 생기는 추가손실(곡선 대표값) — 결재함 '미루면'·결정 기한 카드 '다음 날부터'와 같은 값. */
  delay: { on: string; loss: number } | null
  /** 그날 가장 크게 바뀌는 비용 줄 하나(이유: 블록 단계 변화 등). 금액은 줄 하나의 증가분이라 총 추가손실(delay)과 다르다. */
  step_up: { on: string; entity_id: string; before: number; after: number; note: string | null } | null
  /** 추가손실 곡선의 마지막 날(탐색 기간 끝). */
  horizon_end: string | null
  nodes: ShowcaseNode[]
  /** 판단 요약 첫 줄(계약 1.35.0): 추가 공수 · 추가 재료비 — 결과 cost_split과 줄의 구분 그대로(scripts/export_showcase.py). */
  cost: ShowcaseCost
  /** 블록별 강재 중량 변화 합계(t). 바뀌는 부재가 없으면 null. */
  weight: { before_t: number; after_t: number; delta_t: number; blocks: number; counted: number } | null
}

interface Range {
  value: number
  low: number
  high: number
}

export interface ShowcaseCost {
  labor_hours: Range
  labor: Range
  /** 공수 줄의 작업 구분(정해진 순서, 금액이 있는 것만). */
  works: CostItem[]
  material: Range
  /** 자재 차이·구매 묶음 금액(그 묶음 줄이 없으면 null). */
  material_diff: number | null
  purchase: number | null
  purchases: CostItem[]
  damages: number
  /** 확정일에 이미 발주가 나간 품목 수. */
  ordered: number
}

export const SHOWCASE = data as Showcase

/**
 * 예시의 날짜를 다른 날로 옮긴다. 합성 시연 세계는 날짜를 옮겨도 금액·일수가 같아(생성기 이동 불변,
 * docs/operations.md(서비스) 6절) 그날의 업무 화면과 같은 달력이 된다. 금액·일수·노드는 그대로다.
 */
export function onDay(showcase: Showcase, today: string): Showcase {
  const shift = daysBetween(showcase.as_of, today)
  if (!shift) return showcase
  const move = (day: string) => addDays(day, shift)
  return {
    ...showcase,
    as_of: today,
    deadline: showcase.deadline === null ? null : move(showcase.deadline),
    delay: showcase.delay === null ? null : { ...showcase.delay, on: move(showcase.delay.on) },
    step_up: showcase.step_up === null ? null : { ...showcase.step_up, on: move(showcase.step_up.on) },
    horizon_end: showcase.horizon_end === null ? null : move(showcase.horizon_end),
  }
}

/**
 * 예시 기준일: 소개 화면의 실제 업무 화면 그림(public/landing)을 찍은 날(그날의 업무상 오늘). 움직이는 그림·문구도 이 날로
 * 고정해 그림 속 날짜(결정 기한 11월 11일(수) 등)와 어긋나지 않게 한다 — 그림을 다시 찍으면 함께 바꾼다(docs/operations.md 소개 단락,
 * 검사 captures.test.ts가 그림 속 값과 이 날로 옮긴 예시를 대조).
 */
export const SHOWCASE_DAY = '2026-11-04'

/** 소개 화면이 보이는 예시: 날짜만 예시 기준일로 옮긴 것. */
export const SHOWCASE_TODAY = onDay(SHOWCASE, SHOWCASE_DAY)

const BLOCK_STAGES = BLOCK_STAGE_NAMES
const PO_STATUSES = PO_STATUS_NAMES

/** 블록 공정 단계 이름('선행의장'). 모르는 값은 그대로. */
export function blockStageName(stage: string): string {
  return BLOCK_STAGES[stage] ?? stage
}
const RELATION_VERB: Record<string, string> = { butt_weld: '맞대기 용접한', fillet_weld: '필릿 용접한' }
// 그림의 첫 고리 순서: 이야기 순서(부재 → 블록 → 발주 → 도면)
const ORDER = ['taper', 'weld_recheck', 'rework', 'po_change', 'drawing_revision']

export interface NodeText {
  /** 무엇이(옅은 첫 줄). */
  subject: string
  /** 어떻게 되나(굵은 둘째 줄). */
  action: string
  amount: string
}

/** 부재 종류: 많은 것부터("보강재·브라켓"). */
function kinds(node: ShowcaseNode): string {
  return Object.entries(node.kinds ?? {})
    .sort(([a, x], [b, y]) => y - x || a.localeCompare(b))
    .map(([kind]) => PART_KIND_NAMES[kind] ?? kind)
    .join('·')
}

export function nodeText(node: ShowcaseNode): NodeText {
  const amount = formatMoney(node.amount)
  if (node.entity_type === 'part') {
    const verb = RELATION_VERB[node.relation] ?? '이어진'
    return { subject: `${verb} ${kinds(node)} ${node.count}개`, action: IMPACT_NAMES[node.impacts[0] as never] ?? node.impacts[0], amount }
  }
  if (node.entity_type === 'block') {
    const stage = node.stage ? ` · ${blockStageName(node.stage)} 중` : ''
    return { subject: `${node.name} 블록${stage}`, action: '블록 재작업', amount }
  }
  if (node.entity_type === 'po_line') {
    const status = node.stage ? ` · ${PO_STATUSES[node.stage] ?? node.stage} 단계` : ''
    const both = node.impacts.includes('po_change') && node.impacts.includes('reorder')
    return { subject: `발주 ${node.name}${status}`, action: both ? '발주 변경·재발주' : IMPACT_NAMES.po_change, amount }
  }
  if (node.entity_type === 'drawing') return { subject: `도면 ${node.name}`, action: '도면 개정', amount }
  return { subject: node.name ?? node.key, action: node.impacts.join(', '), amount }
}

function rank(node: ShowcaseNode): number {
  const at = ORDER.findIndex((impact) => node.impacts.includes(impact))
  return at < 0 ? ORDER.length : at
}

/** 첫 고리(바뀐 부재에서 바로 번진 곳)와 그 카드를 거쳐 번진 두 번째 고리. */
export function rings(nodes: ShowcaseNode[]): { first: ShowcaseNode[]; second: ShowcaseNode[] } {
  const first = nodes.filter((n) => n.parent === null).sort((a, b) => rank(a) - rank(b))
  const order = new Map(first.map((n, i) => [n.key, i]))
  const second = nodes
    .filter((n) => n.parent !== null)
    .sort((a, b) => (order.get(a.parent ?? '') ?? 0) - (order.get(b.parent ?? '') ?? 0) || rank(a) - rank(b))
  return { first, second }
}

export function changeText(showcase: Showcase): { subject: string; action: string } {
  const { change } = showcase
  const thickness = change.op === 'thickness' && change.from_mm !== null && change.to_mm !== null
  return {
    subject: `설계변경 ${showcase.ecn_id}`,
    action: thickness
      ? `${change.block} 판 ${change.part_count}장 두께 ${change.from_mm}→${change.to_mm}mm`
      : showcase.title,
  }
}

export interface LaterText {
  /** 결정 기한 다음 날("11월 5일(목)") — 그날부터 확정하면 추가손실이 생긴다. */
  on: string
  /** 그날 확정할 때의 총 추가손실(곡선 대표값, "1,867만원") — 결재함 '미루면'·결정 기한 카드 '다음 날부터'와 같은 값. */
  amount: string
  /** 그날 가장 크게 바뀌는 비용 줄의 이름("B31P 블록 재작업"), 모르면 null. */
  cause: string | null
  /** 그 줄의 단계 변화("선행의장 → 선행도장"), 없으면 null. */
  note: string | null
}

/** 결정 기한 다음 날의 추가손실(delay)과 그 이유 줄(step_up)을 조각으로. 값이 없으면 null. */
export function laterText(showcase: Showcase): LaterText | null {
  const { delay, step_up: step } = showcase
  if (!delay) return null
  const node = step ? showcase.nodes.find((n) => n.key === step.entity_id) : undefined
  return {
    on: formatDay(delay.on),
    amount: formatMoney(delay.loss),
    cause: node ? nodeText(node).action.replace('블록 재작업', `${node.name} 블록 재작업`) : null,
    note: step?.note ? step.note.replace('단계 ', '') : null,
  }
}

/** 이유 괄호("(B31P 블록 재작업, 선행의장 → 선행도장)"), 이유가 없으면 빈 글. */
export function laterWhy(later: LaterText): string {
  const parts = [later.cause, later.note].filter((part) => part !== null)
  return parts.length ? `(${parts.join(', ')})` : ''
}

export interface VerdictText {
  level: string
  label: string
  reasons: string[]
  total: string
  range: string
  /** 기준일("10월 20일(화)"). */
  asOf: string
  deadline: string | null
  dDay: string | null
  exit: string | null
  /** 결정 기한 다음 날부터 늘어나는 금액 한 문장(제품 결정 기한 카드 '다음 날부터 x 늘어남'과 같은 값). */
  later: string | null
}

export function verdictText(showcase: Showcase): VerdictText {
  const { total, deadline, as_of: asOf, zone_exit: exit } = showcase
  const left = deadline ? daysBetween(asOf, deadline) : null
  const later = laterText(showcase)
  return {
    level: showcase.verdict.level,
    label: VERDICT_NAMES[showcase.verdict.level] ?? showcase.verdict.level,
    reasons: showcase.verdict.reasons,
    total: formatMoney(total.value),
    range: formatRange(total.low, total.high),
    asOf: formatDay(asOf),
    deadline: deadline ? formatDay(deadline) : null,
    dDay: left === null ? null : left === 0 ? '오늘' : `D-${left}`,
    exit: exit ? `${exit.name} ${exit.delay_days}일` : null,
    later: later ? `${later.on}부터 확정하면 ${later.amount} 늘어납니다${laterWhy(later)}` : null,
  }
}

/**
 * 문제 절 제목 두 줄: 작은 변경 하나(예시) → 엔진이 찾은 영향 수(부재·블록·발주·도면, 공정 일정 영향 제외 —
 * example.json impact_count). 두께 변경이면 '판 3장 두께 변경 하나에', 그 밖의 변경이면 '설계변경 한 건에'.
 */
export function problemTitle(showcase: Showcase): [string, string] {
  const { change } = showcase
  const lead = change.op === 'thickness' ? `판 ${change.part_count}장 두께 변경 하나에` : '설계변경 한 건에'
  return [lead, `영향 ${showcase.impact_count}건`]
}

/** 판단 요약 첫 줄을 소개 화면 글로(업무 화면 판단 요약과 같은 포맷 — lib/costSplit). */
export interface CostText {
  /** '807 MH'. */
  hours: string
  /** 공수 금액 '4,007만원'. */
  laborMoney: string
  /** '재작업 · 용접 · 가공 · 도면'. */
  works: string
  /** 추가 재료비 '327만원'. */
  material: string
  /** '자재 차이 63만원 · 구매 264만원'(있는 묶음만). */
  materialParts: string
  /** 확정일에 이미 발주된 품목 수(0이면 null). */
  ordered: number | null
  /** 총변경비용 '4,334만원'. */
  total: string
}

export function costText(showcase: Showcase): CostText {
  const { cost } = showcase
  const parts = [
    cost.material_diff === null ? null : `자재 차이 ${formatMoney(cost.material_diff)}`,
    cost.purchase === null ? null : `구매 ${formatMoney(cost.purchase)}`,
  ].filter((part) => part !== null)
  return {
    hours: `${formatHours(cost.labor_hours.value)} MH`,
    laborMoney: formatMoney(cost.labor.value),
    works: cost.works.map((item) => COST_ITEM_NAMES[item]).join(' · '),
    material: formatMoney(cost.material.value),
    materialParts: parts.join(' · '),
    ordered: cost.ordered > 0 ? cost.ordered : null,
    total: formatMoney(showcase.total.value),
  }
}

/** 중량 변화 합계('+0.69t'). 바뀌는 부재가 없으면 null. */
export function weightText(showcase: Showcase): string | null {
  return showcase.weight ? formatDelta(showcase.weight.delta_t) : null
}

/** 결정 기한에 확정할 때 구역 출구 지연이 어떻게 되나(기준일 → 결정 기한, 일). */
export interface ExitDays {
  asOf: number
  atDeadline: number
}

/** 출구 지연 변화: 기준일 값(zone_exit, 없으면 0)과 결정 기한 값(deadline_exit_days, 곡선 값). 결정 기한 값이 없으면 null. */
export function deadlineExit(showcase: Showcase): ExitDays | null {
  if (showcase.deadline_exit_days === null) return null
  return { asOf: showcase.zone_exit?.delay_days ?? 0, atDeadline: showcase.deadline_exit_days }
}

