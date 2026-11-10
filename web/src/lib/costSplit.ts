// 비용 구분(계약 1.35.0, docs/engine.md(비용·일정) 4-12): 판단 요약 첫 줄의 추가 공수 · 추가 재료비 카드, 비용 탭의 공수 ·
// 재료비 두 묶음과 소계, 검토서·요약 복사의 같은 값. 숫자는 엔진의 구분별 합(cost_split)과 줄의 구분·공수(MH) 그대로 —
// 금액 ÷ 임률로 공수를 거꾸로 구하지 않는다. 구분이 없는 옛 기록(1.34.0까지)은 null을 돌려 이전처럼 총변경비용 하나로 보인다.
import type { AnalysisResult, CostItem, CostKind, CostLine, CostSplit } from '@/api/client'
import { formatMoney, formatRange, formatWon } from './money'
import { orderedItems } from './ordered'

/** 구분 이름(엑셀 ripple/ingest/out_labels.py COST_KIND와 같은 말 — tests/checks/cost_split.py가 대조). */
export const COST_KIND_NAMES: Record<CostKind, string> = { labor: '공수', material: '재료비', damages: '지체상금' }

/** 세부 구분 이름(엑셀 out_labels.py COST_ITEM과 같은 말). */
export const COST_ITEM_NAMES: Record<CostItem, string> = {
  rework: '재작업',
  new_work: '신규 작업',
  onboard: '선상 설치',
  after_paint: '도장 뒤 작업',
  weld: '용접',
  machining: '가공',
  drawing: '도면',
  material_diff: '자재 차이',
  stock: '재고 전용',
  po_change: '발주 변경·취소',
  reorder: '새 발주 할증',
  transfer: '잉여 자재 전용',
  liquidated_damages: '지체상금',
}

/** 재료비 중 '구매' 묶음(계약 PURCHASE_ITEMS와 같음): 발주 변경·취소 · 새 규격 발주 할증 · 잉여 자재 전용 취급비. */
export const PURCHASE_ITEMS: ReadonlySet<CostItem> = new Set<CostItem>(['po_change', 'reorder', 'transfer'])

/** 공수 카드의 작업 구분 한 줄 순서(재작업 → … → 도면). */
const WORK_ORDER: readonly CostItem[] = ['rework', 'new_work', 'onboard', 'after_paint', 'weld', 'machining', 'drawing']

/** 재료비 카드의 구매 속 이름(짧게): 발주 변경 · 새 발주 · 잉여 전용. */
const PURCHASE_SHORT: Partial<Record<CostItem, string>> = {
  po_change: '발주 변경',
  reorder: '새 발주',
  transfer: '잉여 전용',
}

/** 세 자리 쉼표(로캘에 기대지 않음). */
function grouped(n: number): string {
  return String(Math.trunc(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

/**
 * 공수(MH) 첫 화면 표기(서버 ripple/brief/text.py hours_text와 같음): 100 이상은 정수(천 단위 쉼표), 그 아래는 소수 첫째
 * 자리(끝 .0은 지움). 806.861 → '807', 21.265 → '21.3', 16 → '16'.
 */
export function formatHours(hours: number): string {
  if (hours >= 100) return grouped(Math.round(hours))
  return (Math.round(hours * 10) / 10).toFixed(1).replace(/\.0$/, '')
}

/** 공수 범위: '243~1,661 MH'. 최소 = 최대면 null. */
export function hoursRange(low: number, high: number): string | null {
  return low === high ? null : `${formatHours(low)}~${formatHours(high)} MH`
}

/** 금액이 0이 아닌 줄(0원 줄은 '실제 있는 것'으로 세지 않는다 — 전량 전용한 발주 변경 등). */
function nonZero(line: CostLine): boolean {
  return line.amount.low !== 0 || line.amount.high !== 0
}

/** 결과에 구분이 있나(1.35.0 이후 분석). */
function hasSplit(result: AnalysisResult): result is AnalysisResult & { cost_split: CostSplit } {
  return result.cost_split != null
}

/** 공수 줄의 작업 구분(실제 있는 것만, 정해진 순서): ['재작업', '가공', '용접', '도면']. */
export function laborWorks(lines: readonly CostLine[]): string[] {
  const seen = new Set(lines.filter((l) => l.kind === 'labor' && nonZero(l)).map((l) => l.item))
  return WORK_ORDER.filter((item) => seen.has(item)).map((item) => COST_ITEM_NAMES[item])
}

/** 재료비 카드 둘째 줄: '자재 차이 63만원 · 구매 264만원(발주 변경 · 새 발주)'(있는 묶음만). 없으면 null. */
export function materialParts(result: AnalysisResult & { cost_split: CostSplit }): string | null {
  const lines = result.cost_lines.filter((l) => l.kind === 'material' && nonZero(l))
  const diff = lines.some((l) => !PURCHASE_ITEMS.has(l.item as CostItem))
  const bought = [...new Set(lines.filter((l) => PURCHASE_ITEMS.has(l.item as CostItem)).map((l) => l.item as CostItem))]
  const { material_diff: materialDiff, purchase } = result.cost_split
  const parts: string[] = []
  if (diff) parts.push(`자재 차이 ${formatMoney(materialDiff.value)}`)
  if (bought.length > 0) {
    const names = (['po_change', 'reorder', 'transfer'] as const).filter((i) => bought.includes(i)).map((i) => PURCHASE_SHORT[i])
    parts.push(`구매 ${formatMoney(purchase.value)}(${names.join(' · ')})`)
  }
  return parts.length > 0 ? parts.join(' · ') : null
}

export interface LaborHead {
  /** 큰 숫자 '807 MH'. */
  hours: string
  /** 작은 글 '≈ 4,007만원'. */
  money: string
  /** 공수 범위 '243~1,661 MH'(없으면 null). */
  range: string | null
  /** 작업 구분 '재작업 · 가공 · 용접 · 도면'. */
  works: string
}

export interface MaterialHead {
  /** 큰 숫자 '327만원'(음수는 '절감 …'). */
  value: string
  /** 범위 '267만~405만원'(없으면 null). */
  range: string | null
  /** '자재 차이 63만원 · 구매 264만원(발주 변경 · 새 발주)'. */
  parts: string | null
  /** '이미 발주 1건 · 자재 확보 1'(발주가 나간 품목이 없으면 null). */
  ordered: string | null
  /** 경고 한 줄 '발주 단계 판단 불가 n건'. */
  caution: string | null
}

export interface CostHead {
  /** null = 공수 줄 없음 → '추가 공수 없음' 한 줄. */
  labor: LaborHead | null
  /** null = 재료비 줄·이미 발주된 품목 없음 → '추가 재료비 없음' 한 줄. */
  material: MaterialHead | null
  /** 아래 작은 한 줄: 총변경비용과 범위, 두 금액(+ 지체상금)의 합이라는 것. */
  total: { value: string; range: string | null; sum: string }
}

/** 판단 요약 첫 줄(DESIGN.md 2절): 추가 공수 · 추가 재료비 두 카드와 총변경비용 한 줄. 구분이 없는 옛 결과는 null. */
export function costHead(result: AnalysisResult): CostHead | null {
  if (!hasSplit(result)) return null
  const split = result.cost_split
  const laborLines = result.cost_lines.filter((l) => l.kind === 'labor' && nonZero(l))
  const labor: LaborHead | null =
    laborLines.length === 0
      ? null
      : {
          hours: `${formatHours(split.labor_hours.value)} MH`,
          money: `≈ ${formatMoney(split.labor.value)}`,
          range: hoursRange(split.labor_hours.low, split.labor_hours.high),
          works: laborWorks(result.cost_lines).join(' · '),
        }
  const items = orderedItems(result)
  const materialLines = result.cost_lines.filter((l) => l.kind === 'material' && nonZero(l))
  const hasOrdered = items !== null && (items.ordered > 0 || items.unknown > 0)
  const material: MaterialHead | null =
    materialLines.length === 0 && !hasOrdered
      ? null
      : {
          value: formatMoney(split.material.value),
          range: split.material.low === split.material.high ? null : formatRange(split.material.low, split.material.high),
          parts: materialParts(result),
          ordered:
            items && items.ordered > 0
              ? [`이미 발주 ${items.ordered}건`, ...items.stages.map((s) => `${s.label} ${s.count}`)].join(' · ')
              : null,
          caution: items && items.unknown > 0 ? `발주 단계 판단 불가 ${items.unknown}건` : null,
        }
  const { total } = result
  const damages = split.damages.low !== 0 || split.damages.high !== 0
  return {
    labor,
    material,
    total: {
      value: formatMoney(total.value),
      range: total.low === total.high ? null : formatRange(total.low, total.high),
      sum: damages ? '공수 + 재료비 + 지체상금' : '공수 + 재료비',
    },
  }
}

/** 요약 복사·결정 도우미 한 줄: '추가 공수 807 MH · 재료비 327만원'(서버 ripple/brief/text.py split_text와 같은 글). */
export function splitLine(result: AnalysisResult): string | null {
  if (!hasSplit(result)) return null
  const split = result.cost_split
  return `추가 공수 ${formatHours(split.labor_hours.value)} MH · 재료비 ${formatMoney(split.material.value)}`
}

/** 비용 탭·검토서의 묶음(공수 · 재료비(자재 차이 · 구매) · 지체상금). 소계는 엔진 구분별 합 그대로. */
export interface CostPart {
  key: 'labor' | 'material_diff' | 'purchase' | 'damages'
  title: string
  lines: CostLine[]
}

export interface CostSection {
  kind: CostKind
  title: string
  subtotal: { value: number; low: number; high: number }
  /** 공수 묶음만: 추가 공수(MH). */
  hours?: { value: number; low: number; high: number }
  /** 공수·지체상금은 한 묶음, 재료비는 자재 차이 · 구매(있는 것만). */
  parts: CostPart[]
}

/**
 * 금액 큰 순으로 정렬된 줄 → 묶음. 공수(소계 = 공수 금액, MH) → 재료비(소계 = 재료비, 안에 자재 차이 · 구매 소계) →
 * 지체상금(있을 때만). 줄이 없는 묶음은 뺀다. 구분이 없는 옛 결과는 null.
 */
export function costSections(result: AnalysisResult, sorted: readonly CostLine[]): CostSection[] | null {
  if (!hasSplit(result)) return null
  const split = result.cost_split
  const of = (keep: (l: CostLine) => boolean) => sorted.filter(keep)
  const labor = of((l) => l.kind === 'labor')
  const diff = of((l) => l.kind === 'material' && !PURCHASE_ITEMS.has(l.item as CostItem))
  const bought = of((l) => l.kind === 'material' && PURCHASE_ITEMS.has(l.item as CostItem))
  const damages = of((l) => l.kind === 'damages')
  const sections: CostSection[] = []
  if (labor.length > 0) {
    sections.push({
      kind: 'labor',
      title: '공수',
      subtotal: split.labor,
      hours: split.labor_hours,
      parts: [{ key: 'labor', title: '공수', lines: labor }],
    })
  }
  if (diff.length + bought.length > 0) {
    sections.push({
      kind: 'material',
      title: '재료비',
      subtotal: split.material,
      parts: [
        ...(diff.length > 0 ? [{ key: 'material_diff' as const, title: '자재 차이', lines: diff }] : []),
        ...(bought.length > 0 ? [{ key: 'purchase' as const, title: '구매', lines: bought }] : []),
      ],
    })
  }
  if (damages.length > 0) {
    sections.push({
      kind: 'damages',
      title: '지체상금',
      subtotal: split.damages,
      parts: [{ key: 'damages', title: '지체상금', lines: damages }],
    })
  }
  return sections
}

/** 재료비 묶음 안 소계: 자재 차이·구매는 엔진 값(material_diff·purchase). */
export function partSubtotal(split: CostSplit, key: CostPart['key']): { value: number; low: number; high: number } {
  if (key === 'material_diff') return split.material_diff
  if (key === 'purchase') return split.purchase
  if (key === 'damages') return split.damages
  return split.labor
}

/** 묶은 줄('테이퍼 가공 8건')의 짧은 근거: 모두 공수 줄이면 줄 공수의 합(MH). */
export function groupMeta(lines: readonly CostLine[]): string | null {
  const hours = lines.map((line) => line.hours?.value).filter((h): h is number => h != null)
  if (hours.length === 0 || hours.length !== lines.length) return null
  return `${formatHours(hours.reduce((sum, h) => sum + h, 0))} MH`
}

/** 재작업 줄의 작업반(줄 이름 '… — ○○ 작업반 추가 공비' · '… — 직영', 엑셀 수행 주체 칸과 같은 규칙). 없으면 null. */
export function crewOf(line: CostLine): string | null {
  const at = line.label.lastIndexOf(' — ')
  if (at < 0) return null
  const tail = line.label.slice(at + 3)
  if (tail.endsWith(' 추가 공비')) return tail.slice(0, -' 추가 공비'.length)
  return tail === '직영' ? '직영' : null
}

/** 재작업 줄 이름 끝의 수행 주체 조각('직영' · '○○ 작업반 추가 공비'). 없으면 null. */
function performerTail(line: CostLine): string | null {
  const at = line.label.lastIndexOf(' — ')
  return at < 0 || crewOf(line) === null ? null : line.label.slice(at + 3)
}

/**
 * 비용 탭·검토서 줄 이름: 재작업 줄은 수행 주체 조각을 떼고('B31P … 블록 재작업') 그 조각은 줄 근거(lineMeta)에 둔다 —
 * 같은 말이 이름과 근거에 두 번 나오지 않게.
 */
export function lineLabel(line: CostLine): string {
  const tail = performerTail(line)
  return tail === null ? line.label : line.label.slice(0, line.label.length - tail.length - 3)
}

/** 엔진 qty_text와 같은 수량 글: 소수 셋째 자리까지, 끝 0 지움, 천 단위 쉼표. */
function qtyText(qty: number): string {
  const [whole, frac = ''] = qty.toFixed(3).split('.')
  const tail = frac.replace(/0+$/, '')
  return `${grouped(Number(whole))}${tail ? `.${tail}` : ''}`
}

/** 계산식 속 수량 뒤의 단위(엔진 계산식은 수량을 '3.53t'처럼 단위와 붙여 쓴다). 못 찾으면 ''. */
function unitIn(line: CostLine, qty: number): string {
  const text = qtyText(qty)
  const at = line.formula.indexOf(text)
  if (at < 0) return ''
  const unit = /^([A-Za-z가-힣]+)/.exec(line.formula.slice(at + text.length))
  return unit ? unit[1] : ''
}

function num(value: unknown): number | null {
  return typeof value === 'number' ? value : null
}

/**
 * 비용 탭 줄의 짧은 근거(펼치지 않아도 보이는 것): 공수 줄 'n MH · 직영'(작업반 몫은 '○○ 작업반 추가 공비'),
 * 재료비 줄 '수량 3.53t · 단가 1,240,000원/t'(규격 변경의 자재비 차이는 '수량 3→3.53t'). 값은 줄의 공수·입력값
 * 그대로(새 계산 없음 — 발주 변경의 수량은 엔진 계산식과 같은 '영향 수량 − 전용 수량').
 */
export function lineMeta(line: CostLine): string | null {
  if (line.kind === 'labor' && line.hours) {
    const tail = performerTail(line)
    return [`${formatHours(line.hours.value)} MH`, ...(tail ? [tail] : [])].join(' · ')
  }
  if (line.kind !== 'material') return null
  const { inputs } = line
  if (line.item === 'reorder') {
    const bought = num(inputs.bought_value)
    return bought === null ? null : `신규 구매 자재 ${formatMoney(Math.round(bought))} × 할증률`
  }
  const qty = num(inputs.new_qty) ?? num(inputs.qty)
  if (qty === null) return null
  const shown = line.item === 'po_change' ? qty - (num(inputs.moved_qty) ?? 0) : qty
  const unit = unitIn(line, shown)
  const price = num(inputs.new_unit_price) ?? num(inputs.unit_price)
  const before = num(inputs.new_qty) !== null ? num(inputs.qty) : null
  const head = `수량 ${before !== null && before !== shown ? `${qtyText(before)}→` : ''}${qtyText(shown)}${unit}`
  return price === null ? head : `${head} · 단가 ${formatWon(Math.round(price))}${unit ? `/${unit}` : ''}`
}
