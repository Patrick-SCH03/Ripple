// 판정 배지: 아이콘 + 글자(DESIGN.md 3절: 승인 가능 = success, 검토 필요 = warning, 경고 = danger).
import { CircleAlert, CircleCheck, TriangleAlert, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import type { VerdictLevel } from '@/api/client'
import { VERDICT_NAMES } from '@/lib/labels'
import { cn } from '@/lib/utils'

// 바탕은 판정 색 8%를 표면색에 섞은 불투명 색: 고른 줄(회색)·마우스 올린 줄 위에서도 글자 대비가 같다(4.5:1 이상)
const LOOK: Record<VerdictLevel, { icon: LucideIcon; tone: string }> = {
  approve: {
    icon: CircleCheck,
    tone: 'border-success/40 bg-[color-mix(in_oklab,var(--success)_8%,var(--surface))] text-success',
  },
  review: {
    icon: CircleAlert,
    tone: 'border-warning/40 bg-[color-mix(in_oklab,var(--warning)_8%,var(--surface))] text-warning',
  },
  warn: {
    icon: TriangleAlert,
    tone: 'border-danger/40 bg-[color-mix(in_oklab,var(--danger)_8%,var(--surface))] text-danger',
  },
}

/** size: md = 판정 머리·결재(15px), sm = 목록 줄(배지 14px, DESIGN.md 4절). */
export function VerdictBadge({
  level,
  size = 'md',
  className,
}: {
  level: VerdictLevel
  size?: 'sm' | 'md'
  className?: string
}) {
  const { icon: Icon, tone } = LOOK[level]
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center rounded-sm border whitespace-nowrap',
        size === 'md' ? 'h-7 gap-1.5 px-2 text-sm font-semibold' : 'h-6 gap-1 px-1.5 text-xs font-medium',
        tone,
        className,
      )}
    >
      <Icon aria-hidden className={size === 'md' ? 'size-4' : 'size-3'} />
      {VERDICT_NAMES[level]}
    </span>
  )
}

// 판정 띠(상세 머리, DESIGN.md 6절): 판정 색 바탕 한 덩어리 — 큰 아이콘·판정 이름 + 짧은 이유(서버의 명사형 조각) 1~3개.
// 판정이 머리에서 가장 먼저 눈에 띄게.
const BAND: Record<VerdictLevel, string> = {
  approve: 'border-success/45 bg-[color-mix(in_oklab,var(--success)_9%,var(--surface))]',
  review: 'border-warning/45 bg-[color-mix(in_oklab,var(--warning)_10%,var(--surface))]',
  warn: 'border-danger/45 bg-[color-mix(in_oklab,var(--danger)_9%,var(--surface))]',
}
const BAND_TEXT: Record<VerdictLevel, string> = { approve: 'text-success', review: 'text-warning', warn: 'text-danger' }

export function VerdictBand({
  level,
  reasons,
  info,
  className,
}: {
  level: VerdictLevel
  reasons: readonly string[]
  /** 판정 이름 옆 ⓘ. */
  info?: ReactNode
  className?: string
}) {
  const { icon: Icon } = LOOK[level]
  return (
    <section
      aria-label="판정"
      data-verdict={level}
      className={cn('flex min-w-0 items-start gap-3 rounded-md border border-l-4 px-3 py-2.5', BAND[level], className)}
    >
      <Icon aria-hidden className={cn('mt-0.5 size-6 shrink-0', BAND_TEXT[level])} />
      <div className="min-w-0 flex-1">
        <p className={cn('flex items-center gap-1 text-lg font-bold', BAND_TEXT[level])}>
          {VERDICT_NAMES[level]}
          {info}
        </p>
        {reasons.length > 0 && (
          <ul aria-label="판정 이유" className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-base font-medium text-foreground [&>li:not(:last-child)]:after:ml-2 [&>li:not(:last-child)]:after:text-foreground-secondary [&>li:not(:last-child)]:after:content-['·']">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}