// 결재 상태 칩(DESIGN.md 13절): 글자 + 색 테두리. 판정 배지(VerdictBadge)와 같은 높이·바탕 규칙. 목록 줄은 StateText(작은 글자).
import type { EcnState } from '@/api/client'
import { STATE_LABEL, STATE_TONE, type StateTone } from '@/lib/records'
import { cn } from '@/lib/utils'

const TONE: Record<StateTone, string> = {
  muted: 'border-border text-foreground-secondary',
  primary: 'border-primary/40 bg-[color-mix(in_oklab,var(--primary)_8%,var(--surface))] text-primary',
  success: 'border-success/40 bg-[color-mix(in_oklab,var(--success)_8%,var(--surface))] text-success',
  warning: 'border-warning/40 bg-[color-mix(in_oklab,var(--warning)_8%,var(--surface))] text-warning',
  danger: 'border-danger/40 bg-[color-mix(in_oklab,var(--danger)_8%,var(--surface))] text-danger',
}

const TEXT_TONE: Record<StateTone, string> = {
  muted: 'text-foreground-secondary',
  primary: 'text-primary',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
}

/** 목록 줄의 결재 상태: 테두리 없는 작은 글자(판정 칩과 칩 두 개가 나란히 붙지 않게, DESIGN.md 6절). */
export function StateText({ state }: { state: EcnState }) {
  return (
    <span data-state={state} className={cn('shrink-0 font-medium', TEXT_TONE[STATE_TONE[state]])}>
      {STATE_LABEL[state]}
    </span>
  )
}

export function StateChip({ state, size = 'sm' }: { state: EcnState; size?: 'sm' | 'md' }) {
  return (
    <span
      data-state={state}
      className={cn(
        'inline-flex shrink-0 items-center rounded-sm border whitespace-nowrap',
        size === 'md' ? 'h-7 px-2 text-sm font-semibold' : 'h-6 px-1.5 text-xs font-medium',
        TONE[STATE_TONE[state]],
      )}
    >
      {STATE_LABEL[state]}
    </span>
  )
}
