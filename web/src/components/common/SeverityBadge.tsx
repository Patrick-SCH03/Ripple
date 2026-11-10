// 심각도 배지: 아이콘 + 글자로 전한다(색만으로 전하지 않는다, DESIGN.md 3절).
import { CircleAlert, CircleDot, Info, TriangleAlert, type LucideIcon } from 'lucide-react'
import type { Severity } from '@/api/client'
import { SEVERITY_NAMES } from '@/lib/labels'
import { cn } from '@/lib/utils'

const LOOK: Record<Severity, { icon: LucideIcon; tone: string }> = {
  high: { icon: TriangleAlert, tone: 'border-danger/35 bg-danger/8 text-danger' },
  medium: { icon: CircleAlert, tone: 'border-warning/35 bg-warning/8 text-warning' },
  low: { icon: CircleDot, tone: 'border-primary/35 bg-primary/8 text-primary' },
  info: { icon: Info, tone: 'border-border bg-muted text-foreground-secondary' },
}

export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  const { icon: Icon, tone } = LOOK[severity]
  return (
    <span
      className={cn(
        'inline-flex h-6 shrink-0 items-center gap-1 rounded-sm border px-1.5 text-xs font-medium whitespace-nowrap',
        tone,
        className,
      )}
    >
      <Icon aria-hidden className="size-3" />
      {SEVERITY_NAMES[severity]}
    </span>
  )
}
