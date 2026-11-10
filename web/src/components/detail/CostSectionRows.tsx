// 비용 탭의 묶음 줄(계약 1.35.0, DESIGN.md 6절): 공수 · 재료비(자재 차이 · 구매) · 지체상금 머리 줄과 소계. 소계는 엔진
// 구분별 합(cost_split) 그대로다. 금액 칸·판단 불가 표시도 여기 두고 비용 줄(CostTable)이 같이 쓴다.
import { CircleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import type { AnalysisResult } from '@/api/client'
import type { CostRow } from '@/lib/costGroups'
import { groupLines } from '@/lib/costGroups'
import { formatHours, hoursRange, partSubtotal, type CostSection } from '@/lib/costSplit'
import { formatMoney, formatRange } from '@/lib/money'
import { cn } from '@/lib/utils'

export function AmountCell({ value, low, high, strong }: { value: number; low: number; high: number; strong?: boolean }) {
  return (
    <span className="shrink-0 text-right tabular-nums">
      <span className={cn('block', strong ? 'font-semibold' : 'font-medium')}>{formatMoney(value)}</span>
      {low !== high && <span className="block text-sm font-normal text-foreground-secondary">{formatRange(low, high)}</span>}
    </span>
  )
}

export function UnknownBadge() {
  return (
    <span className="inline-flex h-6 shrink-0 items-center gap-1 rounded-sm border border-warning/40 bg-warning/8 px-1.5 text-xs font-medium text-warning">
      <CircleAlert aria-hidden className="size-3" />
      판단 불가
    </span>
  )
}

/** 묶음 머리 줄: 이름 · (공수면 MH와 범위) · 소계. 재료비는 그 아래 자재 차이 · 구매 소계 줄, 그 아래 줄들. */
export function SectionRows({
  section,
  result,
  renderRow,
}: {
  section: CostSection
  result: AnalysisResult
  renderRow: (row: CostRow) => ReactNode
}) {
  const split = result.cost_split
  const hours = section.hours
  const range = hours ? hoursRange(hours.low, hours.high) : null
  const nested = section.kind === 'material'
  return (
    <>
      <li data-cost-section={section.kind} className="flex items-center gap-3 bg-muted px-3 py-2 text-base">
        <span className="min-w-0 flex-1 pl-7">
          <span className="font-semibold">{section.title}</span>
          {hours && (
            <span className="ml-2 text-sm text-foreground-secondary tabular-nums">
              {formatHours(hours.value)} MH{range ? ` (${range})` : ''}
            </span>
          )}
        </span>
        <AmountCell value={section.subtotal.value} low={section.subtotal.low} high={section.subtotal.high} strong />
      </li>
      {section.parts.map((part) => {
        const subtotal = split ? partSubtotal(split, part.key) : null
        return (
          <PartRows key={part.key} title={nested ? part.title : null} subtotal={subtotal}>
            {groupLines(part.lines).map(renderRow)}
          </PartRows>
        )
      })}
    </>
  )
}

/** 재료비 안 묶음(자재 차이 · 구매): 작은 머리 줄 + 소계, 그 아래 줄들. title이 없으면 줄만. */
function PartRows({
  title,
  subtotal,
  children,
}: {
  title: string | null
  subtotal: { value: number; low: number; high: number } | null
  children: ReactNode
}) {
  return (
    <>
      {title && (
        <li data-cost-part={title} className="flex items-center gap-3 px-3 py-1.5 text-sm text-foreground-secondary">
          <span className="min-w-0 flex-1 pl-7 font-medium">{title}</span>
          {subtotal && <span className="shrink-0 tabular-nums">{formatMoney(subtotal.value)}</span>}
        </li>
      )}
      {children}
    </>
  )
}
