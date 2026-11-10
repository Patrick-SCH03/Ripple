// 검토서의 절 하나: 번호 붙은 제목(굵은 아래 선) + 본문. 제목 바로 뒤에서 쪽을 나누지 않는다(report.css).
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function Section({
  title,
  number,
  children,
  testId,
  className,
}: {
  title: string
  /** 절 번호(1부터). 없으면 번호 없이. */
  number?: number
  children: ReactNode
  testId?: string
  className?: string
}) {
  return (
    <section className={cn('report-section mt-5', className)} data-testid={testId}>
      <h2 className="report-h2 mb-2 border-b-2 border-foreground pb-0.5 text-base font-bold">
        {number !== undefined && <span className="mr-1.5 tabular-nums">{number}.</span>}
        {title}
      </h2>
      {children}
    </section>
  )
}
