// 비용 줄 펼침(DESIGN.md 6절 비용 탭): 발생 사유 · 계산 · 가정과 범위 · 늦어지면 · 일정 · 보류 권고 · 비중 · 근거.
// 숫자와 문장은 모두 분석 결과 필드(CostLine.reason·factors·outlook, schedule, timing.holds, graph)에서 오고,
// 여기서는 단위 표기·날짜 계산·고르기만 한다.
import type { AnalysisResult, CostFactor, CostLine, HoldAdvice, ParamStatus } from '@/api/client'
import { nodeFor } from './assistant'
import { addDays } from './format'
import { ACTIVITY_NAMES, BLOCK_SHAPE_NAMES } from './labels'
import { formatMoney, formatRange, formatWon } from './money'

export const FACTOR_STATUS_NAMES: Record<ParamStatus, string> = {
  evidence: '근거 있음',
  mentor: '현업 확인',
  assumption: '가정',
}

const RATIO = '비율'
const MONEY_UNITS = new Set(['원/시간', '원/t', '원/일'])
/** 블록 공정 순서(엔진 BLOCK_ACTIVITY_ORDER와 같음, 1.32.0 PE 포함). */
const BLOCK_ACTIVITIES = ['sub_assembly', 'panel', 'assembly', 'pre_outfitting', 'pre_painting', 'pre_erection', 'erection']

/** 소수 셋째 자리까지, 끝 0 없이, 정수부 세 자리 쉼표(로캘에 기대지 않음). */
function plain(n: number): string {
  const [int, frac] = String(Number(n.toFixed(3))).split('.')
  const sign = int.startsWith('-') ? '−' : ''
  const digits = int.replace('-', '').replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${sign}${digits}${frac ? `.${frac}` : ''}`
}

/** 가정값 숫자 하나(단위 없이)와 붙일 단위: 비율은 %, 원 단위는 원 그대로, 그 밖은 받은 단위. */
function factorParts(value: number, unit: string): { number: string; suffix: string } {
  if (unit === RATIO) return { number: plain(value * 100), suffix: '%' }
  if (MONEY_UNITS.has(unit)) return { number: formatWon(value).replace(/원$/, ''), suffix: unit }
  return { number: plain(value), suffix: unit }
}

/** 가정값의 대표값("30시간/t", "80%", "50,000원/시간")과 범위("19~46시간/t", 최소 = 최대면 null). */
export function factorText(factor: Pick<CostFactor, 'value' | 'low' | 'high' | 'unit'>): {
  value: string
  range: string | null
} {
  const { number, suffix } = factorParts(factor.value, factor.unit)
  if (factor.low === factor.high) return { value: `${number}${suffix}`, range: null }
  const low = factorParts(factor.low, factor.unit).number
  const high = factorParts(factor.high, factor.unit).number
  return { value: `${number}${suffix}`, range: `${low}~${high}${suffix}` }
}

/** 배수·계수 표기: 소수 둘째 자리까지, 끝 0은 지우되 한 자리는 남김(2 → '2.0', 1.344 → '1.34', 0.75 → '0.75'). */
export function multipleText(n: number): string {
  return n.toFixed(2).replace(/0$/, '')
}

export interface ReworkFactors {
  /** 재작업 배수(확정일 단계): '2.0', 단계 이름(가정값 이름표 괄호 안). */
  multiplier: { value: string; stage: string | null } | null
  /** 블록 난이도 계수(1.32.0): 값 · 1보다 큰 계수만 '곡블록 1.3' 꼴 · 상한을 적용했으면 상한. */
  difficulty: { value: string; parts: string[]; cap: string | null } | null
}

/**
 * 블록 재작업 줄의 배수와 난이도 계수(DESIGN.md 6절 비용 탭, 명세 4-4): 둘을 곱한 값 하나('배수 2.7배')로 읽히지 않게
 * 따로 낸다. 배수는 가정값(rework_multiplier.*)의 대표값, 난이도는 줄의 difficulty 그대로. 둘 다 없으면 null.
 */
export function reworkFactors(line: Pick<CostLine, 'factors' | 'difficulty'>): ReworkFactors | null {
  const factor = line.factors.find((f) => f.keys.some((key) => key.startsWith('rework_multiplier.')))
  const d = line.difficulty
  if (!factor && !d) return null
  const parts = d
    ? [
        ...(d.shape_factor > 1 ? [`${BLOCK_SHAPE_NAMES[d.shape ?? ''] ?? '형상'} ${multipleText(d.shape_factor)}`] : []),
        ...(d.outfit_factor > 1 ? [`의장 밀도 ${multipleText(d.outfit_factor)}`] : []),
        ...(d.electric_factor > 1 ? [`전장품 ${multipleText(d.electric_factor)}`] : []),
      ]
    : []
  return {
    multiplier: factor
      ? { value: multipleText(factor.value), stage: /\(([^()]+)\)$/.exec(factor.label)?.[1] ?? null }
      : null,
    difficulty: d ? { value: multipleText(d.value), parts, cap: d.capped ? multipleText(d.cap) : null } : null,
  }
}

/** 한 줄 글: '배수 2.0(선행도장) · 난이도 1.34(곡블록 1.3 × 의장 밀도 1.02 × 전장품 1.01)'. */
export function reworkFactorText(factors: ReworkFactors): string {
  const { multiplier, difficulty } = factors
  const pieces = [
    multiplier ? `배수 ${multiplier.value}${multiplier.stage ? `(${multiplier.stage})` : ''}` : null,
    difficulty
      ? `난이도 ${difficulty.value}${difficulty.parts.length > 0 ? `(${difficulty.parts.join(' × ')})` : ''}` +
        (difficulty.cap ? ` · 상한 ${difficulty.cap} 적용` : '')
      : null,
  ]
  return pieces.filter(Boolean).join(' · ')
}

/** 늦어지면: 확정이 늦어질 때 이 줄이 어떻게 되는지 문장(날짜는 근거 펼침 표기 YYYY-MM-DD). 결과에 없으면 []. */
export function outlookSentences(line: Pick<CostLine, 'amount' | 'outlook'>): string[] {
  const outlook = line.outlook
  if (!outlook) return []
  if (outlook.kind === 'unchecked') return ['확정일 뒤 탐색 기간 없음 · 늦어질 때 미계산']
  if (outlook.kind === 'steady') {
    return outlook.checked_until ? [`${outlook.checked_until}까지 늦게 확정해도 금액 그대로`] : []
  }
  const on = outlook.on
  if (!on) return []
  const keep = `${addDays(on, -1)}까지 확정 시 지금 금액 그대로`
  if (outlook.kind === 'removed') return [keep, `${on}부터 확정 시 이 항목 없어짐`]
  const amount = outlook.amount
  if (!amount) return [keep]
  const note = outlook.note ? `(${outlook.note})` : ''
  const delta = amount.value - line.amount.value
  if (delta === 0) return [keep, `${on}부터 금액 범위 ${formatRange(amount.low, amount.high)}${note}`]
  const way = delta > 0 ? '늘어남' : '줄어듦'
  return [keep, `${on}부터 ${formatMoney(amount.value)} · ${formatMoney(Math.abs(delta))} ${way}${note}`]
}

/** 블록 재작업 줄: 그 블록 공정의 늘어난 일수(공정 순, 설계변경 전체 기준). 블록이 아니면 []. */
export function blockDelays(
  line: Pick<CostLine, 'entity_id'>,
  addedDays: Readonly<Record<string, number>>,
): { name: string; days: number }[] {
  const prefix = `${line.entity_id}:`
  return BLOCK_ACTIVITIES.flatMap((kind) => {
    const days = addedDays[`${prefix}${kind}`] ?? 0
    return days > 0 ? [{ name: ACTIVITY_NAMES[kind] ?? kind, days }] : []
  })
}

/** 이 줄에 붙일 보류 권고: 권고 품목을 가리키는 줄 중 금액 순으로 첫 줄에만(같은 발주를 줄마다 되풀이하지 않게). */
export function holdFor(
  line: Pick<CostLine, 'line_id' | 'entity_id'>,
  sorted: readonly Pick<CostLine, 'line_id' | 'entity_id'>[],
  holds: readonly HoldAdvice[],
): HoldAdvice | null {
  const advice = holds.find((hold) => hold.line_ids.includes(line.entity_id))
  if (!advice) return null
  const first = sorted.find((other) => advice.line_ids.includes(other.entity_id))
  return first?.line_id === line.line_id ? advice : null
}

/** 보류 권고 한 문장. */
export function holdSentence(advice: HoldAdvice): string {
  return (
    `발주 ${advice.po_id}: ${advice.hold_until}까지(최대 ${advice.max_hold_days}일) 보류하면 설계변경 전체 비용이` +
    ` 최대 ${formatMoney(advice.avoided.value)} 줄어듦(탐색 기간 중 차이가 가장 큰 날 기준)` +
    " · 할 일 '보류 적용'으로 다시 계산 가능"
  )
}

/** 비중: 비용 항목(절감 제외) 합계 대비 %, 절감 줄은 따로 알림. 0원이면 null. */
export function shareText(line: Pick<CostLine, 'amount'>, lines: readonly Pick<CostLine, 'amount'>[]): string | null {
  const value = line.amount.value
  if (value < 0) return '절감 항목(총변경비용에서 뺌)'
  if (value === 0) return null
  const positive = lines.reduce((sum, other) => sum + Math.max(0, other.amount.value), 0)
  if (positive <= 0) return null
  const percent = (value / positive) * 100
  return `비용 항목(절감 제외) 합계의 ${percent < 1 ? '1% 미만' : `${Math.round(percent)}%`}`
}

/** '영향 지도에서 근거 보기'로 열 엔터티: 영향 지도에 있는 이 줄의 엔터티, 지체상금(호선)은 그 호선의 인도 지연 공정. */
export function evidenceTarget(
  line: Pick<CostLine, 'entity_id'>,
  result: Pick<AnalysisResult, 'graph' | 'impacts'>,
): string | null {
  const delay = result.impacts.find(
    (impact) => impact.impact_type === 'delivery_delay' && impact.ship_id === line.entity_id,
  )
  const delayNode = delay ? nodeFor(delay.entity_id, result.graph.nodes) : null
  return delayNode ?? nodeFor(line.entity_id, result.graph.nodes)
}
