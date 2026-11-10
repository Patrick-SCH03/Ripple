// 칸 머리: 제목(15px) · 건수 · 오른쪽 동작. 세 칸이 같은 높이(44px)를 쓴다.
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface Props {
  title: string
  count?: number
  actions?: ReactNode
  className?: string
}

export function PaneHeader({ title, count, actions, className }: Props) {
  return (
    <div className={cn('flex h-11 shrink-0 items-center gap-2 border-b border-border px-4', className)}>
      {/* 좁은 칸(1024px 목록 · 큰 글자)에서 제목·건수가 글자 단위로 접히지 않게 한 줄로 — 줄어드는 것은 오른쪽 동작 */}
      <h2 className="shrink-0 text-md font-semibold whitespace-nowrap">{title}</h2>
      {count !== undefined && (
        <span className="shrink-0 text-sm whitespace-nowrap text-foreground-secondary tabular-nums">{count}건</span>
      )}
      {actions && <div className="ml-auto flex min-w-0 items-center gap-1">{actions}</div>}
    </div>
  )
}
