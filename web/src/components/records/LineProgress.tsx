// 결재선 진행(docs/records.md(기록·결재) 14절): 파트장 → 팀장 → 본부장 — 승인한 단계(사람·전결) · 지금 단계 · 남은 단계.
// 결재 띠와 결재함 줄이 같이 쓴다. 상태는 아이콘 + 글자(색만으로 가르지 않음).
import { Check, ChevronRight } from 'lucide-react'
import { Fragment } from 'react'
import type { ApprovalStep, StepSign } from '@/api/client'
import { lineNodes } from '@/lib/approval'
import { cn } from '@/lib/utils'

interface Props {
  steps: readonly ApprovalStep[]
  /** 지금 단계(1부터). */
  current: number
  signed: readonly StepSign[]
  className?: string
  /** 'step' = 결재 띠의 큰 단계 칩(지금 단계는 채운 칩), 기본 = 결재함 줄의 한 줄 글. */
  variant?: 'inline' | 'step'
}

/**
 * 단계 칩: 승인 = 성공 색 테두리 + 체크, 지금 = 채운 주색, 남은 = 흐린 테두리(색 + 아이콘·글자).
 * 결재 띠('step')는 큰 칩, 결재함 줄('inline')은 같은 모양의 작은 칩 — 두 화면이 같은 진행 표시로 읽히게.
 */
const STEP = {
  step: { chip: 'h-9 gap-1 px-2.5 text-base', icon: 'size-4', gap: 'gap-x-1.5 gap-y-1' },
  inline: { chip: 'h-7 gap-1 px-2 text-sm', icon: 'size-3.5', gap: 'gap-x-1 gap-y-1' },
} as const

export function LineProgress({ steps, current, signed, className, variant = 'inline' }: Props) {
  const nodes = lineNodes(steps, current, signed)
  const size = STEP[variant]
  const chip = `inline-flex items-center rounded-sm border whitespace-nowrap ${size.chip}`
  return (
    <span className={cn('inline-flex flex-wrap items-center', size.gap, className)} data-testid="line-progress">
      {/* span의 aria-label은 읽히지 않아 화면 읽기용 글로 단계 위치를 먼저 알린다 */}
      <span className="sr-only">
        결재선 {current}/{steps.length}단계:{' '}
      </span>
      {nodes.map((node, index) => (
        <Fragment key={node.step}>
          {index > 0 && <ChevronRight aria-hidden className={cn(size.icon, 'text-foreground-secondary')} />}
          {node.state === 'done' ? (
            <span className={cn(chip, 'border-success/50 font-medium text-success')} data-step-state="done">
              <Check aria-hidden className={size.icon} />
              {node.label}
              {/* 칩이 flex라 앞 공백이 사라져 '파트장이파트장'으로 붙지 않게 사이를 여백으로 */}
              {node.by && <span className="text-foreground-secondary">{node.by}</span>}
            </span>
          ) : node.state === 'now' ? (
            <span className={cn(chip, 'border-primary bg-primary font-semibold text-primary-foreground')} data-step-state="now">
              {node.label} 차례
            </span>
          ) : (
            <span className={cn(chip, 'border-border text-foreground-secondary')} data-step-state="next">
              {node.label}
            </span>
          )}
        </Fragment>
      ))}
    </span>
  )
}
