// 열 확인 상태 배지: 아이콘 + 글자(자동 · 확인 · 선택 필요 · 단위 선택 필요 · 다른 열과 겹침 · 고침).
import { CircleAlert, CircleCheck, PencilLine, TriangleAlert, type LucideIcon } from 'lucide-react'
import type { ColumnStatus } from '@/lib/mapping'
import { cn } from '@/lib/utils'

const LOOK: Record<ColumnStatus, { icon: LucideIcon; label: string; tone: string }> = {
  auto: { icon: CircleCheck, label: '자동', tone: 'border-success/40 text-success' },
  confirm: { icon: CircleAlert, label: '확인', tone: 'border-primary/40 text-primary' },
  choose: { icon: TriangleAlert, label: '선택 필요', tone: 'border-warning/40 text-warning' },
  unit: { icon: TriangleAlert, label: '단위 선택 필요', tone: 'border-warning/40 text-warning' },
  clash: { icon: TriangleAlert, label: '다른 열과 겹침', tone: 'border-danger/40 text-danger' },
  done: { icon: PencilLine, label: '고침', tone: 'border-primary/40 text-primary' },
}

export function StatusBadge({ status, label }: { status: ColumnStatus; label?: string }) {
  const { icon: Icon, label: text, tone } = LOOK[status]
  return (
    <span
      className={cn(
        'inline-flex h-6 w-fit shrink-0 items-center gap-1 justify-self-start rounded-sm border bg-surface px-1.5 text-xs font-medium whitespace-nowrap sm:justify-self-end',
        tone,
      )}
    >
      <Icon aria-hidden className="size-3" />
      {label ?? text}
    </span>
  )
}
